import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any, TypedDict

import pandas as pd
from app.core.config import settings
from app.core.logging import logger
from app.db.models import (
    Candle,
    Quote,
    ReviewFinding,
    ReviewRun,
    ReviewStepEvent,
    ReviewToolEvent,
)
from app.db.models.review import ReviewEvidenceRecord
from app.db.session import SessionLocal
from app.market.indicators import compute_all_indicators
from app.review.model_client import review_model_client
from app.review.objective_checks import run_deterministic_objective_checks
from app.review.prompts import (
    EXECUTOR_SYSTEM_PROMPT_V1,
    EXECUTOR_USER_PROMPT_TEMPLATE_V1,
    REVIEWER_SYSTEM_PROMPT_V1,
    REVIEWER_USER_PROMPT_TEMPLATE_V1,
    compute_prompt_hash,
)
from app.review.schemas import ExecutorOutput, ReviewerResult
from app.review.tools import tool_registry
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session


class ReviewExecutionState(TypedDict):
    run_id: str
    task_type: str
    symbol: str
    task_prompt: str
    acceptance_criteria: str
    status: str
    evidence_packet: dict[str, Any]
    tool_results: list[dict[str, Any]]
    executor_output: dict[str, Any] | None
    executor_telemetry: dict[str, Any]
    objective_checks: dict[str, Any]
    reviewer_output: dict[str, Any] | None
    reviewer_telemetry: dict[str, Any]
    review_verdict: str
    overall_score: float
    revision_count: int
    max_revisions: int
    step_events: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    error_message: str | None
    prompt_version: str
    prompt_hash: str
    executor_system_prompt: str
    replay_cutoff: str
    replay_dataset_id: str | None


def log_step(state: ReviewExecutionState, step_name: str, status: str, duration_ms: float, details: dict[str, Any]):
    state["step_events"].append({
        "step_name": step_name,
        "status": status,
        "duration_ms": duration_ms,
        "details": details,
        "timestamp": datetime.now(UTC).isoformat()
    })


# -------------------------------------------------------------------------
# Node 1: initialize_run
# -------------------------------------------------------------------------
def initialize_run(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    run_id = state.get("run_id") or f"RUN_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    logger.info(f"Initializing LangGraph review run: {run_id}")

    events = state.get("step_events", [])
    events.append({
        "step_name": "initialize_run",
        "status": "COMPLETED",
        "duration_ms": round((time.time() - t0) * 1000, 1),
        "details": {"run_id": run_id, "symbol": state.get("symbol")},
        "timestamp": datetime.now(UTC).isoformat()
    })

    from app.review.prompt_lifecycle import get_active_executor_prompt_info
    with SessionLocal.begin() as db:
        active = get_active_executor_prompt_info(db)
        db.add(ReviewRun(
            run_id=run_id, task_type=state["task_type"], symbol=state["symbol"],
            task_prompt=state["task_prompt"], acceptance_criteria=state["acceptance_criteria"],
            executor_model=review_model_client.executor_model,
            reviewer_model=review_model_client.reviewer_model,
            prompt_version=active["version_tag"], prompt_hash=active["prompt_hash"],
            status="RUNNING",
        ))

    return {
        "run_id": run_id,
        "status": "INITIALIZED",
        "step_events": events,
        "prompt_version": active["version_tag"],
        "prompt_hash": active["prompt_hash"],
        "executor_system_prompt": active["system_prompt"],
        "revision_count": 0,
        "max_revisions": settings.HIVE_MAX_REVISION_ATTEMPTS
    }


# -------------------------------------------------------------------------
# Node 2: validate_task_and_permissions
# -------------------------------------------------------------------------
def validate_task_and_permissions(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    symbol = state.get("symbol", "RELIANCE").upper()
    valid_symbols = {"RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "NIFTY50"}

    if symbol not in valid_symbols:
        err = f"Symbol '{symbol}' is not in verified NSE symbols: {valid_symbols}"
        log_step(state, "validate_task_and_permissions", "FAILED", round((time.time() - t0) * 1000, 1), {"error": err})
        return {"status": "FAILED", "error_message": err}

    log_step(state, "validate_task_and_permissions", "COMPLETED", round((time.time() - t0) * 1000, 1), {"symbol": symbol, "valid": True})
    return {"status": "TASK_VALIDATED"}


# -------------------------------------------------------------------------
# Node 3: collect_or_load_evidence
# -------------------------------------------------------------------------
def collect_or_load_evidence(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    symbol = state.get("symbol", "RELIANCE").upper()
    db: Session = SessionLocal()
    try:
        if state.get("replay_cutoff"):
            from app.market.evidence_verifier import evidence_verifier

            replay = evidence_verifier.point_in_time_evidence_replay(
                symbol, datetime.fromisoformat(state["replay_cutoff"]), db, state.get("replay_dataset_id"),
            )
            if replay.get("status") == "FAILED_NO_DATA":
                return {"status": "FAILED", "error_message": replay["error"]}
            bar = replay["latest_observed_bar"]
            provenance = {
                "source": replay["evidence_snapshot"]["source"],
                "cutoff": replay["cutoff_timestamp"],
                "availability_policy": replay["availability_policy_metadata"],
            }
            return {
                "status": "PACKET_READY",
                "evidence_packet": {
                    "EV_PRICE": {
                        "evidence_id": "EV_PRICE", "symbol": symbol, "price": bar["close"],
                        "source_timestamp": bar["timestamp"],
                        "available_at": replay["latest_bar_availability_timestamp"],
                        "provenance": provenance,
                    },
                    "EV_IND": {
                        "evidence_id": "EV_IND", "indicators": replay["historical_indicators"],
                        "provenance": provenance,
                    },
                },
            }

        from app.market.dhan_adapter import dhan_live_feed
        live_q = dhan_live_feed.get_quote(symbol)

        if live_q and live_q.get("price") is not None:
            quote_dict = {
                "symbol": live_q["symbol"],
                "price": live_q["price"],
                "previous": live_q.get("previous"),
                "change": live_q.get("change"),
                "change_pct": live_q.get("change_pct"),
                "volume": live_q.get("volume"),
                "evidence_id": "EV_PRICE",
                "source_timestamp": live_q.get("source_timestamp") or live_q.get("observation_timestamp"),
                "freshness_status": live_q.get("freshness_status"),
                "provenance": live_q.get("provenance", f"DhanHQ-py live tick ({live_q.get('security_id', '')})")
            }
        else:
            allow_hist = getattr(settings, "ALLOW_HISTORICAL_MARKET_FALLBACK", False)
            q = db.query(Quote).filter(Quote.symbol == symbol).first() if allow_hist else None
            if q:
                quote_dict = {
                    "symbol": q.symbol,
                    "price": q.price,
                    "change": q.change,
                    "change_pct": q.change_pct,
                    "volume": q.volume,
                    "evidence_id": "EV_PRICE",
                    "source_timestamp": q.observation_timestamp.isoformat() if q.observation_timestamp else None,
                    "freshness_status": "HISTORICAL",
                    "provenance": q.source
                }
            else:
                quote_dict = {
                    "symbol": symbol,
                    "price": None,
                    "evidence_id": "EV_PRICE",
                    "provenance": "Awaiting active DhanHQ-py market tick (LIVE_ONLY mode)"
                }

        candles = []
        if settings.ALLOW_HISTORICAL_MARKET_FALLBACK:
            candles = db.query(Candle).filter(
                Candle.symbol == symbol, Candle.is_synthetic.is_(False),
                Candle.timestamp <= datetime.now(UTC),
            ).order_by(Candle.timestamp.desc()).limit(252).all()
            candles.reverse()

        if candles:
            candle_list = [
                {"close": c.close, "high": c.high, "low": c.low, "volume": c.volume, "timestamp": c.timestamp.isoformat()}
                for c in candles
            ]
        else:
            candle_list = []

        log_step(state, "collect_or_load_evidence", "COMPLETED", round((time.time() - t0) * 1000, 1), {
            "candle_count": len(candle_list),
            "price": quote_dict.get("price")
        })

        return {
            "status": "EVIDENCE_COLLECTED",
            "evidence_packet": {
                "EV_PRICE": quote_dict,
                "candle_data": candle_list
            }
        }
    finally:
        db.close()


# -------------------------------------------------------------------------
# Node 4: validate_evidence
# -------------------------------------------------------------------------
def validate_evidence(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    packet = state.get("evidence_packet", {})
    candle_data = packet.get("candle_data", [])

    quote = packet.get("EV_PRICE") or {}
    if not quote.get("price") and not candle_data:
        err = "No usable market quote or eligible historical bars are available."
        log_step(state, "validate_evidence", "FAILED", round((time.time() - t0) * 1000, 1), {"error": err})
        return {"status": "FAILED", "error_message": err}

    log_step(state, "validate_evidence", "COMPLETED", round((time.time() - t0) * 1000, 1), {"bars_validated": len(candle_data)})
    return {"status": "EVIDENCE_VALIDATED"}


# -------------------------------------------------------------------------
# Node 5: compute_deterministic_metrics
# -------------------------------------------------------------------------
def compute_deterministic_metrics(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    packet = state.get("evidence_packet", {})
    candle_data = packet.get("candle_data", [])

    candle_df = pd.DataFrame(candle_data) if candle_data else pd.DataFrame(columns=["close"])
    indicators = compute_all_indicators(candle_df)
    packet["EV_IND"] = {
        "evidence_id": "EV_IND",
        "indicators": indicators,
        "provenance": "Deterministic NumPy/pandas quantitative calculation (daily log return std * sqrt(252))"
    }
    log_step(state, "compute_deterministic_metrics", "COMPLETED", round((time.time() - t0) * 1000, 1), {
        "sma_20": indicators.get("sma_20"),
        "rsi_14": indicators.get("rsi_14"),
        "annualized_volatility": indicators.get("volatility")
    })
    return {"evidence_packet": packet, "status": "METRICS_COMPUTED"}


# -------------------------------------------------------------------------
# Node 6: build_evidence_packet & execute allowlisted tools
# -------------------------------------------------------------------------
def build_evidence_packet(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    symbol = state.get("symbol", "RELIANCE")
    packet = state.get("evidence_packet", {})

    # Load announcements through the read-only allowlist.
    db: Session = SessionLocal()
    try:
        tool_res = tool_registry.execute_tool(
            db=db,
            tool_name="get_corporate_announcements",
            params={"symbol": symbol},
            selection_source="policy"
        )
        announcements = tool_res.result.get("announcements", [])
        if announcements and tool_res.status == "SUCCESS":
            packet["EV_NEWS"] = {
                "evidence_id": "EV_NEWS",
                "announcements": announcements,
                "provenance": "Corporate announcement tool results",
            }

        tool_events = state.get("tool_results", [])
        tool_events.append(tool_res.model_dump())

        log_step(state, "build_evidence_packet", "COMPLETED", round((time.time() - t0) * 1000, 1), {
            "evidence_keys": list(packet.keys()),
            "tools_called": len(tool_events)
        })

        return {
            "evidence_packet": packet,
            "tool_results": tool_events,
            "status": "PACKET_READY"
        }
    finally:
        db.close()


# -------------------------------------------------------------------------
# Node 7: execute_with_qwen
# -------------------------------------------------------------------------
async def execute_with_qwen(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    run_id = state.get("run_id")
    symbol = state.get("symbol")
    task_prompt = state.get("task_prompt")
    criteria = state.get("acceptance_criteria")
    evidence = state.get("evidence_packet", {})
    tools = state.get("tool_results", [])

    active_prompt_version = state["prompt_version"]
    active_prompt_hash = state["prompt_hash"]
    active_system_prompt = state["executor_system_prompt"]

    # Format user prompt
    evidence_clean = {k: v for k, v in evidence.items() if k != "candle_data"}
    user_prompt = EXECUTOR_USER_PROMPT_TEMPLATE_V1.format(
        run_id=run_id,
        symbol=symbol,
        task_prompt=task_prompt,
        acceptance_criteria=criteria,
        evidence_packet_json=json.dumps(evidence_clean, indent=2, default=str),
        tool_results_json=json.dumps(tools, indent=2)
    )

    archived = json.dumps(
        evidence_clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str,
    )
    with SessionLocal.begin() as db:
        db.add(ReviewEvidenceRecord(
            run_id=run_id, payload_json=archived, sha256=hashlib.sha256(archived.encode()).hexdigest(),
        ))

    parsed_output, telemetry = await review_model_client.generate_structured(
        model_name=review_model_client.executor_model,
        system_prompt=active_system_prompt,
        user_prompt=user_prompt,
        schema_model=ExecutorOutput,
        temperature=0.1,
        num_predict=900
    )

    duration_ms = round((time.time() - t0) * 1000, 1)
    log_step(state, "execute_with_qwen", "COMPLETED" if parsed_output else "FAILED", duration_ms, {
        "error": telemetry.get("error"),
        "model": telemetry.get("model"),
        "mode": telemetry.get("execution_mode"),
        "model_digest": telemetry.get("model_digest"),
        "latency_ms": telemetry.get("latency_ms"),
        "prompt_version": active_prompt_version
    })

    return {
        "executor_output": parsed_output,
        "executor_telemetry": telemetry,
        "prompt_version": active_prompt_version,
        "prompt_hash": active_prompt_hash,
        "executor_system_prompt": active_system_prompt,
        "status": "EXECUTED" if parsed_output else "FAILED",
        "error_message": telemetry.get("error") if not parsed_output else None,
    }


# -------------------------------------------------------------------------
# Node 8: validate_executor_output
# -------------------------------------------------------------------------
def validate_executor_output(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    out = state.get("executor_output")
    is_valid = out is not None and isinstance(out, dict) and "run_id" in out and "summary" in out

    log_step(state, "validate_executor_output", "COMPLETED" if is_valid else "FAILED", round((time.time() - t0) * 1000, 1), {
        "valid": is_valid
    })
    return {"status": "OUTPUT_VALIDATED"}


# -------------------------------------------------------------------------
# Node 9: persist_execution_trace
# -------------------------------------------------------------------------
def persist_execution_trace(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    run_id = state.get("run_id")
    db: Session = SessionLocal()
    try:
        active_version = state.get("prompt_version", "v1.0")
        active_hash = state.get("prompt_hash") or compute_prompt_hash(EXECUTOR_SYSTEM_PROMPT_V1)
        run_rec = db.query(ReviewRun).filter(ReviewRun.run_id == run_id).first()
        if not run_rec:
            run_rec = ReviewRun(
                run_id=run_id,
                task_type=state.get("task_type", "MARKET_ANALYSIS"),
                symbol=state.get("symbol", "RELIANCE"),
                task_prompt=state.get("task_prompt", ""),
                acceptance_criteria=state.get("acceptance_criteria", ""),
                status="EXECUTED",
                executor_model=state.get("executor_telemetry", {}).get("model", settings.HIVE_EXECUTOR_MODEL),
                reviewer_model=settings.HIVE_REVIEWER_MODEL,
                prompt_version=active_version,
                prompt_hash=active_hash,
                executor_latency_ms=state.get("executor_telemetry", {}).get("latency_ms", 0.0),
                executor_output_json=json.dumps(state.get("executor_output") or {})
            )
            db.add(run_rec)
        else:
            run_rec.executor_output_json = json.dumps(state.get("executor_output") or {})
            run_rec.executor_latency_ms = state.get("executor_telemetry", {}).get("latency_ms", 0.0)
            run_rec.prompt_version = active_version
            run_rec.prompt_hash = active_hash
            run_rec.status = "EXECUTED"

        # Persist tool events
        for te in state.get("tool_results", []):
            tool_rec = ReviewToolEvent(
                run_id=run_id,
                tool_name=te.get("tool_name", "unknown"),
                selection_source=te.get("selection_source", "policy"),
                input_json=json.dumps(te.get("parameters", {})),
                output_json=json.dumps(te.get("result", {})),
                duration_ms=te.get("duration_ms", 0.0),
                status=te.get("status", "SUCCESS")
            )
            db.add(tool_rec)

        db.commit()
        log_step(state, "persist_execution_trace", "COMPLETED", round((time.time() - t0) * 1000, 1), {"persisted": True})
        return {"status": "TRACE_PERSISTED"}
    finally:
        db.close()


# -------------------------------------------------------------------------
# Node 10: run_objective_checks
# -------------------------------------------------------------------------
def run_objective_checks(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    packet = state.get("evidence_packet", {})
    output = state.get("executor_output")
    tools = state.get("tool_results", [])
    latency = state.get("executor_telemetry", {}).get("latency_ms", 0.0)

    checks = run_deterministic_objective_checks(
        task_prompt=state.get("task_prompt", ""),
        acceptance_criteria=state.get("acceptance_criteria", ""),
        evidence_packet=packet,
        executor_output=output,
        tool_results=tools,
        latency_ms=latency
    )

    log_step(state, "run_objective_checks", "COMPLETED", round((time.time() - t0) * 1000, 1), {
        "schema_valid": checks.schema_valid,
        "grounded": checks.evidence_refs_exist,
        "failures": checks.failure_reasons
    })

    return {
        "objective_checks": checks.model_dump(),
        "status": "OBJECTIVE_CHECKS_COMPLETED"
    }


# -------------------------------------------------------------------------
# Node 11: review_with_gemma
# -------------------------------------------------------------------------
async def review_with_gemma(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    run_id = state.get("run_id")
    task_prompt = state.get("task_prompt")
    criteria = state.get("acceptance_criteria")
    evidence = state.get("evidence_packet", {})
    tools = state.get("tool_results", [])
    obj_checks = state.get("objective_checks", {})
    output = state.get("executor_output")

    if not output:
        log_step(state, "review_with_gemma", "SKIPPED", 0.0, {"reason": "No executor output"})
        return {"review_verdict": "UNAVAILABLE", "reviewer_output": None}

    evidence_clean = {k: v for k, v in evidence.items() if k != "candle_data"}
    user_prompt = REVIEWER_USER_PROMPT_TEMPLATE_V1.format(
        run_id=run_id,
        task_prompt=task_prompt,
        acceptance_criteria=criteria,
        evidence_packet_json=json.dumps(evidence_clean, indent=2, default=str),
        tool_results_json=json.dumps(tools, indent=2),
        objective_checks_json=json.dumps(obj_checks, indent=2),
        executor_output_json=json.dumps(output, indent=2)
    )

    parsed_review, telemetry = await review_model_client.generate_structured(
        model_name=review_model_client.reviewer_model,
        system_prompt=REVIEWER_SYSTEM_PROMPT_V1,
        user_prompt=user_prompt,
        schema_model=ReviewerResult,
        temperature=0.1,
        num_predict=900
    )

    if not parsed_review:
        error = telemetry.get("error") or "Reviewer returned no validated response"
        log_step(state, "review_with_gemma", "FAILED", round((time.time() - t0) * 1000, 1), {
            "error": error, "mode": telemetry.get("execution_mode"),
        })
        return {
            "reviewer_telemetry": telemetry,
            "reviewer_output": None,
            "review_verdict": "UNAVAILABLE",
            "error_message": error,
        }

    duration_ms = round((time.time() - t0) * 1000, 1)
    log_step(state, "review_with_gemma", "COMPLETED", duration_ms, {
        "reviewer_model": telemetry.get("model"),
        "mode": telemetry.get("execution_mode"),
        "model_digest": telemetry.get("model_digest"),
        "verdict": parsed_review.get("review_status"),
        "score": parsed_review.get("overall_score")
    })

    return {
        "reviewer_output": parsed_review,
        "reviewer_telemetry": telemetry,
        "review_verdict": parsed_review.get("review_status", "PASS"),
        "overall_score": parsed_review.get("overall_score", 85.0),
        "findings": parsed_review.get("findings", []),
        "status": "REVIEWED"
    }


# -------------------------------------------------------------------------
# Node 12: combine_evaluation_results
# -------------------------------------------------------------------------
def combine_evaluation_results(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    obj_checks = state.get("objective_checks", {})
    review_out = state.get("reviewer_output") or {}

    verdict = review_out.get("review_status", "UNAVAILABLE")
    if state.get("executor_output") and (
        obj_checks.get("prompt_injection_detected") or not obj_checks.get("risk_policy_compliant")
    ):
        verdict = "ERROR"
    elif verdict == "PASS" and obj_checks.get("failure_reasons"):
        verdict = "FLAG"

    log_step(state, "combine_evaluation_results", "COMPLETED", round((time.time() - t0) * 1000, 1), {
        "final_verdict": verdict,
        "overall_score": review_out.get("overall_score")
    })

    return {
        "review_verdict": verdict,
        "status": "EVALUATED"
    }


# -------------------------------------------------------------------------
# Conditional router
# -------------------------------------------------------------------------
def route_review_decision(state: ReviewExecutionState) -> str:
    verdict = state.get("review_verdict", "PASS")
    rev_count = state.get("revision_count", 0)
    max_rev = state.get("max_revisions", 1)

    if verdict == "REVISE" and rev_count < max_rev:
        logger.info(f"Routing to bounded revision (attempt {rev_count + 1}/{max_rev})")
        return "revise_with_qwen"
    return "persist_final_evaluation"


# -------------------------------------------------------------------------
# Node 13: revise_with_qwen (bounded revision loop)
# -------------------------------------------------------------------------
async def revise_with_qwen(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    run_id = state.get("run_id")
    rev_count = state.get("revision_count", 0) + 1
    review_out = state.get("reviewer_output") or {}
    instructions = review_out.get("revision_instructions", "Address findings and provide fully validated JSON.")
    pre_revision_output = state.get("executor_output")

    active_system_prompt = state["executor_system_prompt"]

    revision_prompt = (
        f"REVISION REQUEST FOR RUN {run_id} (Attempt {rev_count}):\n"
        f"Previous output: {json.dumps(pre_revision_output)}\n"
        f"Evidence: {json.dumps({k: v for k, v in state['evidence_packet'].items() if k != 'candle_data'})}\n"
        f"Independent Reviewer Findings: {json.dumps(review_out.get('findings', []), indent=2)}\n"
        f"Specific Revision Instructions: {instructions}\n\n"
        "Re-submit the complete corrected assessment conforming strictly to the JSON schema."
    )

    parsed_output, telemetry = await review_model_client.generate_structured(
        model_name=review_model_client.executor_model,
        system_prompt=active_system_prompt,
        user_prompt=revision_prompt,
        schema_model=ExecutorOutput,
        temperature=0.1,
        num_predict=900
    )

    if not parsed_output:
        log_step(state, "revise_with_qwen", "FAILED", round((time.time() - t0) * 1000, 1), {
            "error": telemetry.get("error"),
        })
        return {"revision_count": rev_count, "status": "REVISION_FAILED"}

    duration_ms = round((time.time() - t0) * 1000, 1)
    log_step(state, "revise_with_qwen", "COMPLETED", duration_ms, {
        "attempt": rev_count,
        "latency_ms": telemetry.get("latency_ms"),
        "pre_revision_output": pre_revision_output
    })

    return {
        "executor_output": parsed_output,
        "revision_count": rev_count,
        "status": "REVISED"
    }


# -------------------------------------------------------------------------
# Node 14: revalidate_revision
# -------------------------------------------------------------------------
def revalidate_revision(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    packet = state.get("evidence_packet", {})
    output = state.get("executor_output")
    tools = state.get("tool_results", [])
    latency = state.get("executor_telemetry", {}).get("latency_ms", 0.0)

    checks = run_deterministic_objective_checks(
        task_prompt=state.get("task_prompt", ""),
        acceptance_criteria=state.get("acceptance_criteria", ""),
        evidence_packet=packet,
        executor_output=output,
        tool_results=tools,
        latency_ms=latency
    )

    if state.get("status") == "REVISION_FAILED":
        verdict = "REVISE"
    elif checks.prompt_injection_detected:
        verdict = "ERROR"
    elif not checks.schema_valid or not checks.required_fields_present:
        verdict = "REVISE"
    elif not checks.risk_policy_compliant:
        verdict = "ERROR"
    elif not checks.evidence_refs_exist or not checks.quantitative_consistency:
        verdict = "FLAG"
    else:
        verdict = "REVISE"

    log_step(state, "revalidate_revision", "COMPLETED", round((time.time() - t0) * 1000, 1), {
        "post_revision_verdict": verdict,
        "failures": checks.failure_reasons
    })

    return {
        "objective_checks": checks.model_dump(),
        "review_verdict": verdict,
        "status": "REVALIDATED"
    }


# -------------------------------------------------------------------------
# Node 15: persist_final_evaluation
# -------------------------------------------------------------------------
def persist_final_evaluation(state: ReviewExecutionState) -> dict[str, Any]:
    t0 = time.time()
    run_id = state.get("run_id")
    db: Session = SessionLocal()
    try:
        terminal_status = "FAILED"
        run_rec = db.query(ReviewRun).filter(ReviewRun.run_id == run_id).first()
        if run_rec:
            terminal_status = (
                "FAILED" if not state.get("executor_output")
                else "PARTIAL" if not state.get("reviewer_output")
                else "COMPLETED"
            )
            run_rec.status = terminal_status
            run_rec.error_message = state.get("error_message")
            run_rec.review_verdict = (state.get("review_verdict", "UNAVAILABLE") if terminal_status != "FAILED" else "ERROR")
            run_rec.overall_score = state.get("overall_score", 85.0)
            run_rec.revision_count = state.get("revision_count", 0)
            run_rec.executor_output_json = json.dumps(state.get("executor_output") or {})
            run_rec.reviewer_output_json = json.dumps(state.get("reviewer_output") or {})
            run_rec.objective_checks_json = json.dumps(state.get("objective_checks", {}))
            run_rec.reviewer_latency_ms = state.get("reviewer_telemetry", {}).get("latency_ms", 0.0)
            run_rec.total_latency_ms = run_rec.executor_latency_ms + run_rec.reviewer_latency_ms
            run_rec.completed_at = datetime.now(UTC)

        # Persist findings
        seen_findings = set()
        for f in state.get("findings", []):
            fingerprint = (f.get("criterion_id"), f.get("title"), f.get("description"))
            if fingerprint in seen_findings:
                continue
            seen_findings.add(fingerprint)
            finding_rec = ReviewFinding(
                run_id=run_id,
                criterion_id=f.get("criterion_id", "general"),
                severity=f.get("severity", "INFO"),
                title=f.get("title", "Review Finding"),
                description=f.get("description", ""),
                evidence_refs_json=json.dumps(f.get("evidence_refs", [])),
                recommendation=f.get("recommendation", "")
            )
            db.add(finding_rec)

        # Persist step events
        for se in state.get("step_events", []):
            se_rec = ReviewStepEvent(
                run_id=run_id,
                step_name=se.get("step_name", "step"),
                status=se.get("status", "COMPLETED"),
                duration_ms=se.get("duration_ms", 0.0),
                details_json=json.dumps(se.get("details", {}))
            )
            db.add(se_rec)

        db.commit()
        log_step(state, "persist_final_evaluation", "COMPLETED", round((time.time() - t0) * 1000, 1), {"terminal_state": terminal_status})
        return {"status": terminal_status}
    finally:
        db.close()


# -------------------------------------------------------------------------
# Compile LangGraph Workflow
# -------------------------------------------------------------------------
def create_execution_review_graph():
    builder = StateGraph(ReviewExecutionState)

    builder.add_node("initialize_run", initialize_run)
    builder.add_node("validate_task_and_permissions", validate_task_and_permissions)
    builder.add_node("collect_or_load_evidence", collect_or_load_evidence)
    builder.add_node("validate_evidence", validate_evidence)
    builder.add_node("compute_deterministic_metrics", compute_deterministic_metrics)
    builder.add_node("build_evidence_packet", build_evidence_packet)
    builder.add_node("execute_with_qwen", execute_with_qwen)
    builder.add_node("validate_executor_output", validate_executor_output)
    builder.add_node("persist_execution_trace", persist_execution_trace)
    builder.add_node("run_objective_checks", run_objective_checks)
    builder.add_node("review_with_gemma", review_with_gemma)
    builder.add_node("combine_evaluation_results", combine_evaluation_results)
    builder.add_node("revise_with_qwen", revise_with_qwen)
    builder.add_node("revalidate_revision", revalidate_revision)
    builder.add_node("persist_final_evaluation", persist_final_evaluation)

    # Linear execution up to evaluation
    builder.add_edge(START, "initialize_run")
    builder.add_edge("initialize_run", "validate_task_and_permissions")
    builder.add_conditional_edges(
        "validate_task_and_permissions",
        lambda state: "persist_final_evaluation" if state["status"] == "FAILED" else "collect_or_load_evidence",
        ["persist_final_evaluation", "collect_or_load_evidence"],
    )
    def route_evidence(state: ReviewExecutionState) -> str:
        if state["status"] == "FAILED":
            return "persist_final_evaluation"
        return "execute_with_qwen" if state.get("replay_cutoff") else "validate_evidence"

    builder.add_conditional_edges("collect_or_load_evidence", route_evidence, [
        "persist_final_evaluation", "execute_with_qwen", "validate_evidence",
    ])
    builder.add_conditional_edges(
        "validate_evidence",
        lambda state: "persist_final_evaluation" if state["status"] == "FAILED" else "compute_deterministic_metrics",
        ["persist_final_evaluation", "compute_deterministic_metrics"],
    )
    builder.add_edge("compute_deterministic_metrics", "build_evidence_packet")
    builder.add_edge("build_evidence_packet", "execute_with_qwen")
    builder.add_edge("execute_with_qwen", "validate_executor_output")
    builder.add_edge("validate_executor_output", "persist_execution_trace")
    builder.add_edge("persist_execution_trace", "run_objective_checks")
    builder.add_edge("run_objective_checks", "review_with_gemma")
    builder.add_edge("review_with_gemma", "combine_evaluation_results")

    # Conditional branching for bounded revision
    builder.add_conditional_edges(
        "combine_evaluation_results",
        route_review_decision,
        {
            "revise_with_qwen": "revise_with_qwen",
            "persist_final_evaluation": "persist_final_evaluation"
        }
    )

    builder.add_edge("revise_with_qwen", "revalidate_revision")
    builder.add_edge("revalidate_revision", "persist_final_evaluation")
    builder.add_edge("persist_final_evaluation", END)

    return builder.compile()


execution_review_graph = create_execution_review_graph()
