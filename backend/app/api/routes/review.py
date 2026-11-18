import json
from asyncio import CancelledError
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

from app.api.dependencies import get_db
from app.core.config import settings
from app.core.logging import logger
from app.core.security import require_operator
from app.db.models import (
    ImprovementProposalRecord,
    PromptVersionRecord,
    ReviewFinding,
    ReviewRun,
    ReviewStepEvent,
    ReviewToolEvent,
)
from app.db.models.review import BenchmarkTrialRecord, PromptAuditEvent
from app.market.evidence_verifier import evidence_verifier
from app.review.benchmark import benchmark_suite
from app.review.execution_graph import execution_review_graph
from app.review.improvement_graph import continuous_improvement_graph
from app.review.model_client import review_model_client
from app.review.operations import mark_interrupted_runs, single_operation
from app.review.prompts import (
    EXECUTOR_SYSTEM_PROMPT_V1,
    compute_prompt_hash,
)
from app.review.schemas import (
    EvaluationAnalyticsSummary,
    EvidenceVerificationResponse,
    PointInTimeReplayRequest,
    PointInTimeReplayResponse,
    PromptVersionResponse,
    RunDetailResponse,
    RunSummaryResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

router = APIRouter()


def _compute_run_objective_pass_pct(checks: dict[str, Any]) -> float | None:
    if not checks:
        return None
    failures = checks.get("failure_reasons", [])
    core_checks = [
        checks.get("schema_valid", False),
        checks.get("required_fields_present", False),
        checks.get("evidence_refs_exist", False),
        checks.get("quantitative_consistency", True),
        checks.get("risk_policy_compliant", True),
        not checks.get("prompt_injection_detected", False),
    ]
    if core_checks:
        return round((sum(1 for c in core_checks if c) / len(core_checks)) * 100.0, 1)
    return 100.0 if not failures else 0.0


@router.get("/model-status")
async def get_model_status():
    """
    Truthful readiness of local Ollama server and configured Qwen/Gemma models.
    """
    return await review_model_client.get_model_status()


class AgentRunRequest(BaseModel):
    symbol: str = Field(default="RELIANCE", pattern=r"^[A-Za-z0-9][A-Za-z0-9&.-]{0,19}$")
    task_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    acceptance_criteria: str = Field(default="Cite available evidence, reconcile indicators and identify risks.", min_length=1, max_length=2000)
    task_type: str = Field(default="MARKET_ANALYSIS", min_length=1, max_length=50)
    replay_cutoff: datetime | None = None
    replay_dataset_id: str | None = Field(default=None, max_length=64)


@router.post("/agent-runs", response_model=RunSummaryResponse)
async def create_agent_run(
    payload: AgentRunRequest,
    db: Session = Depends(get_db)
):
    """
    Execute a full LangGraph run:
    Evidence Preparation -> Qwen Execution -> Trace Persistence -> Objective Checks -> Gemma Review -> Evaluation
    """
    symbol = payload.symbol.upper()
    task_prompt = payload.task_prompt or f"Analyze the available market and volatility evidence for {symbol}."
    acceptance_criteria = payload.acceptance_criteria
    replay_cutoff = payload.replay_cutoff
    if replay_cutoff is not None and replay_cutoff.utcoffset() is None:
        raise HTTPException(422, "Historical research cutoff must specify a timezone.")
    task_type = "HISTORICAL_REPLAY" if replay_cutoff is not None else payload.task_type
    run_id = f"RUN_{uuid4().hex}"

    initial_state = {
        "run_id": run_id,
        "task_type": task_type,
        "replay_cutoff": replay_cutoff.isoformat() if replay_cutoff else None,
        "replay_dataset_id": payload.replay_dataset_id,
        "symbol": symbol,
        "task_prompt": task_prompt,
        "acceptance_criteria": acceptance_criteria,
        "status": "INITIALIZED",
        "evidence_packet": {},
        "tool_results": [],
        "executor_output": None,
        "executor_telemetry": {},
        "objective_checks": {},
        "reviewer_output": None,
        "reviewer_telemetry": {},
        "review_verdict": "PENDING",
        "overall_score": 0.0,
        "revision_count": 0,
        "max_revisions": settings.HIVE_MAX_REVISION_ATTEMPTS,
        "step_events": [],
        "findings": [],
        "error_message": None
    }

    request_key = sha256(payload.model_copy(update={
        "symbol": symbol,
        "replay_cutoff": replay_cutoff.astimezone(UTC) if replay_cutoff else None,
    }).model_dump_json().encode()).hexdigest()
    with single_operation("research request", request_key):
        try:
            await execution_review_graph.ainvoke(initial_state)
        except CancelledError:
            db.rollback()
            mark_interrupted_runs(db, "Research was interrupted before it completed.", run_id)
            raise
        except Exception:
            logger.exception(f"Research run {run_id} failed")
            db.rollback()
            mark_interrupted_runs(db, "Research execution failed. See the local application log.", run_id)
            raise HTTPException(status_code=500, detail=f"Research execution failed for {run_id}.")

    r = db.query(ReviewRun).filter(ReviewRun.run_id == run_id).first()
    if not r:
        raise HTTPException(status_code=500, detail="Failed to locate persisted run record.")

    checks = json.loads(r.objective_checks_json) if r.objective_checks_json else {}
    f_count = db.query(func.count(ReviewFinding.id)).filter(ReviewFinding.run_id == r.run_id).scalar() or 0

    return RunSummaryResponse(
        run_id=r.run_id,
        task_type=r.task_type,
        symbol=r.symbol,
        status=r.status,
        executor_model=r.executor_model,
        reviewer_model=r.reviewer_model,
        review_verdict=r.review_verdict,
        overall_score=r.overall_score,
        revision_count=r.revision_count,
        total_latency_ms=r.total_latency_ms,
        executor_latency_ms=r.executor_latency_ms,
        reviewer_latency_ms=r.reviewer_latency_ms,
        objective_pass_pct=_compute_run_objective_pass_pct(checks),
        objective_checks=checks,
        findings_count=f_count,
        error_message=r.error_message,
        created_at=r.created_at.isoformat() if r.created_at else "",
        completed_at=r.completed_at.isoformat() if r.completed_at else None
    )


@router.get("/agent-runs", response_model=list[RunSummaryResponse])
def list_agent_runs(
    symbol: str | None = None,
    verdict: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    List recorded execution/review runs with optional symbol and verdict filters.
    """
    q = db.query(ReviewRun)
    if symbol:
        q = q.filter(ReviewRun.symbol == symbol.upper())
    if verdict:
        q = q.filter(ReviewRun.review_verdict == verdict.upper())

    records = q.order_by(ReviewRun.created_at.desc()).limit(limit).all()
    run_ids = [r.run_id for r in records]
    finding_counts = {}
    if run_ids:
        counts = db.query(ReviewFinding.run_id, func.count(ReviewFinding.id)).filter(
            ReviewFinding.run_id.in_(run_ids)
        ).group_by(ReviewFinding.run_id).all()
        finding_counts = {cid: cnt for cid, cnt in counts}

    results = []
    for r in records:
        checks = json.loads(r.objective_checks_json) if r.objective_checks_json else {}
        results.append(RunSummaryResponse(
            run_id=r.run_id,
            task_type=r.task_type,
            symbol=r.symbol,
            status=r.status,
            executor_model=r.executor_model,
            reviewer_model=r.reviewer_model,
            review_verdict=r.review_verdict,
            overall_score=r.overall_score,
            revision_count=r.revision_count,
            total_latency_ms=r.total_latency_ms,
            executor_latency_ms=r.executor_latency_ms,
            reviewer_latency_ms=r.reviewer_latency_ms,
            objective_pass_pct=_compute_run_objective_pass_pct(checks),
            objective_checks=checks,
            findings_count=finding_counts.get(r.run_id, 0),
            error_message=r.error_message,
            created_at=r.created_at.isoformat() if r.created_at else "",
            completed_at=r.completed_at.isoformat() if r.completed_at else None
        ))
    return results


@router.get("/agent-runs/{run_id}", response_model=RunDetailResponse)
def get_agent_run_detail(
    run_id: str,
    db: Session = Depends(get_db)
):
    """
    Retrieve full execution trace, actual tool calls, reviewer rubric criteria, and findings.
    """
    r = db.query(ReviewRun).filter(ReviewRun.run_id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    step_events = db.query(ReviewStepEvent).filter(ReviewStepEvent.run_id == run_id).order_by(ReviewStepEvent.id.asc()).all()
    tool_events = db.query(ReviewToolEvent).filter(ReviewToolEvent.run_id == run_id).order_by(ReviewToolEvent.id.asc()).all()
    findings = db.query(ReviewFinding).filter(ReviewFinding.run_id == run_id).order_by(ReviewFinding.id.asc()).all()

    return RunDetailResponse(
        run_id=r.run_id,
        task_type=r.task_type,
        symbol=r.symbol,
        task_prompt=r.task_prompt,
        acceptance_criteria=r.acceptance_criteria,
        status=r.status,
        executor_model=r.executor_model,
        reviewer_model=r.reviewer_model,
        prompt_version=r.prompt_version,
        prompt_hash=r.prompt_hash,
        executor_output=json.loads(r.executor_output_json) if r.executor_output_json else {},
        reviewer_output=json.loads(r.reviewer_output_json) if r.reviewer_output_json else {},
        objective_checks=json.loads(r.objective_checks_json) if r.objective_checks_json else {},
        review_verdict=r.review_verdict,
        overall_score=r.overall_score,
        revision_count=r.revision_count,
        step_events=[{"step": se.step_name, "status": se.status, "duration_ms": se.duration_ms, "details": json.loads(se.details_json) if se.details_json else {}, "time": se.timestamp.isoformat()} for se in step_events],
        tool_events=[{"tool": te.tool_name, "source": te.selection_source, "input": json.loads(te.input_json) if te.input_json else {}, "output": json.loads(te.output_json) if te.output_json else {}, "duration_ms": te.duration_ms, "status": te.status} for te in tool_events],
        findings=[{"criterion": f.criterion_id, "severity": f.severity, "title": f.title, "description": f.description, "recommendation": f.recommendation} for f in findings],
        executor_latency_ms=r.executor_latency_ms,
        reviewer_latency_ms=r.reviewer_latency_ms,
        total_latency_ms=r.total_latency_ms,
        error_message=r.error_message,
        created_at=r.created_at.isoformat() if r.created_at else "",
        completed_at=r.completed_at.isoformat() if r.completed_at else None
    )


@router.get("/agent-runs/{run_id}/events")
def get_run_step_events(run_id: str, db: Session = Depends(get_db)):
    """
    Expose chronological workflow step events for live telemetry monitoring.
    """
    events = db.query(ReviewStepEvent).filter(ReviewStepEvent.run_id == run_id).order_by(ReviewStepEvent.id.asc()).all()
    return [
        {
            "id": e.id,
            "step_name": e.step_name,
            "status": e.status,
            "duration_ms": e.duration_ms,
            "details": json.loads(e.details_json) if e.details_json else {},
            "timestamp": e.timestamp.isoformat()
        }
        for e in events
    ]


@router.get("/agent-evaluations/summary", response_model=EvaluationAnalyticsSummary)
def get_evaluation_analytics_summary(db: Session = Depends(get_db)):
    """
    Compute real aggregated metrics: completion rates, schema validity %,
    PASS/FLAG/REVISE distribution, latency percentiles, and failure categories.
    """
    runs = db.query(ReviewRun).all()
    total = len(runs)
    if total == 0:
        return EvaluationAnalyticsSummary(
            total_runs=0,
            sample_sufficient_for_improvement=False,
            sample_size=0,
            min_threshold=settings.MIN_EVAL_SAMPLE_THRESHOLD
        )

    completed = sum(1 for r in runs if r.status == "COMPLETED")
    failed = sum(1 for r in runs if r.status == "FAILED")
    passes = sum(1 for r in runs if r.review_verdict == "PASS")
    flags = sum(1 for r in runs if r.review_verdict == "FLAG")
    revises = sum(1 for r in runs if r.review_verdict == "REVISE")
    errors = sum(1 for r in runs if r.review_verdict == "ERROR")

    scores = [r.overall_score for r in runs if r.overall_score > 0]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    latencies = [r.total_latency_ms for r in runs if r.total_latency_ms > 0]
    avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    p95_lat = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

    # Schema validity and grounding rates
    valid_schemas = 0
    grounded = 0
    categories = {
        "EVIDENCE_UNGROUNDED": 0,
        "SCHEMA_DRIFT": 0,
        "QUANTITATIVE_MISALIGNMENT": 0,
        "UNVERIFIED_RUMOR_EXPOSURE": 0,
        "LATENCY_SPIKE": 0
    }

    for r in runs:
        try:
            checks = json.loads(r.objective_checks_json) if r.objective_checks_json else {}
            if checks.get("schema_valid", False):
                valid_schemas += 1
            else:
                categories["SCHEMA_DRIFT"] += 1

            if checks.get("evidence_refs_exist", False):
                grounded += 1
            else:
                categories["EVIDENCE_UNGROUNDED"] += 1

            if not checks.get("quantitative_consistency", True):
                categories["QUANTITATIVE_MISALIGNMENT"] += 1

            if r.total_latency_ms > 45000:
                categories["LATENCY_SPIKE"] += 1
        except (TypeError, ValueError, KeyError, AttributeError):
            pass

    revisions = sum(1 for r in runs if r.revision_count > 0)
    rev_freq = round((revisions / total) * 100, 1) if total > 0 else 0.0

    active_rec = db.query(PromptVersionRecord).filter(
        PromptVersionRecord.role == "EXECUTOR",
        PromptVersionRecord.is_active == 1
    ).order_by(PromptVersionRecord.id.desc()).first()
    active_prompt_ver = active_rec.version_tag if active_rec else "v1.0"
    active_prompt_hash = active_rec.prompt_hash if (active_rec and active_rec.prompt_hash) else compute_prompt_hash(EXECUTOR_SYSTEM_PROMPT_V1)
    active_source = "PERSISTED_DATABASE" if active_rec else "RUNTIME_FALLBACK"

    total_findings = db.query(func.count(ReviewFinding.id)).scalar() or 0

    return EvaluationAnalyticsSummary(
        total_runs=total,
        completed_runs=completed,
        failed_runs=failed,
        pass_count=passes,
        flag_count=flags,
        revise_count=revises,
        error_count=errors,
        pass_rate_pct=round((passes / total) * 100, 1) if total > 0 else 0.0,
        schema_validity_pct=round((valid_schemas / total) * 100, 1) if total > 0 else 0.0,
        evidence_grounding_pct=round((grounded / total) * 100, 1) if total > 0 else 0.0,
        average_score=avg_score,
        average_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        revision_frequency_pct=rev_freq,
        failure_categories=categories,
        active_prompt_version=active_prompt_ver,
        active_prompt_hash=active_prompt_hash,
        active_prompt_source=active_source,
        sample_sufficient_for_improvement=total >= settings.MIN_EVAL_SAMPLE_THRESHOLD,
        sample_size=total,
        min_threshold=settings.MIN_EVAL_SAMPLE_THRESHOLD,
        total_findings_count=total_findings
    )


@router.post("/improvement-proposals/generate")
async def generate_improvement_proposal_endpoint(db: Session = Depends(get_db)):
    """
    Trigger the LangGraph Continuous Improvement workflow:
    Aggregate Failures -> Gemma Root Cause Hypotheses -> Improvement Proposal -> Benchmark Execution
    """
    initial_state = {
        "proposal_id": "",
        "sample_size": 0,
        "sample_sufficient": False,
        "evaluations": [],
        "failure_categories": {},
        "representative_traces": [],
        "root_cause_hypothesis": "",
        "proposed_change": {},
        "proposal": None,
        "baseline_benchmark": None,
        "candidate_benchmark": None,
        "benchmark_comparison": None,
        "status": "INITIALIZED",
        "error_message": None
    }

    with single_operation("proposal generation", "queue"):
        try:
            final_state = await continuous_improvement_graph.ainvoke(initial_state)
        except Exception as error:
            logger.exception("Continuous improvement graph failed")
            raise HTTPException(500, "Proposal generation failed. See the local application log.") from error

    if not final_state.get("sample_sufficient", False):
        raise HTTPException(
            status_code=400,
            detail=final_state.get("error_message", "Insufficient evaluation data to generate reliable proposal.")
        )

    prop = final_state.get("proposal")
    return prop


def proposal_response(proposal: ImprovementProposalRecord) -> dict[str, Any]:
    artifacts = json.loads(proposal.benchmark_results_json or "{}")
    baseline = {case["case_id"]: case for case in artifacts.get("baseline", {}).get("case_results", [])}
    candidate = artifacts.get("candidate", {}).get("case_results", [])
    return {
        "proposal_id": proposal.proposal_id,
        "title": proposal.title,
        "failure_category": proposal.failure_category,
        "supporting_run_ids": json.loads(proposal.supporting_run_ids_json or "[]"),
        "root_cause_hypothesis": proposal.root_cause_hypothesis,
        "proposed_change": json.loads(proposal.proposed_change_json or "{}"),
        "affected_configuration": proposal.affected_configuration,
        "expected_benefit": proposal.expected_benefit,
        "regression_risks": proposal.regression_risks,
        "status": proposal.status,
        "baseline_version": proposal.baseline_version,
        "candidate_version": proposal.candidate_version,
        "benchmark_comparison": artifacts.get("comparison", {}),
        "paired_cases": [{
            "case_id": case["case_id"],
            "baseline_score": baseline[case["case_id"]]["score"],
            "baseline_measured": baseline[case["case_id"]]["actual_execution"],
            "candidate_score": case["score"],
            "candidate_measured": case["actual_execution"],
            "candidate_safety_violation": case.get("safety_violation", False),
        } for case in candidate if case["case_id"] in baseline],
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }


@router.get("/improvement-proposals")
def list_improvement_proposals(db: Session = Depends(get_db)):
    proposals = db.query(ImprovementProposalRecord).order_by(ImprovementProposalRecord.created_at.desc()).all()
    return [proposal_response(proposal) for proposal in proposals]


@router.get("/improvement-proposals/{proposal_id}")
def get_proposal_detail(proposal_id: str, db: Session = Depends(get_db)):
    return proposal_response(get_proposal(db, proposal_id))


class OperatorDecision(BaseModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


def get_proposal(db: Session, proposal_id: str) -> ImprovementProposalRecord:
    proposal = db.query(ImprovementProposalRecord).filter_by(proposal_id=proposal_id).first()
    if proposal is None:
        raise HTTPException(404, "Proposal not found.")
    return proposal


def executor_version(db: Session, version: str) -> PromptVersionRecord:
    record = db.query(PromptVersionRecord).filter_by(role="EXECUTOR", version_tag=version).first()
    if not record or not record.prompt_hash or compute_prompt_hash(record.system_prompt) != record.prompt_hash:
        raise HTTPException(409, "Stored prompt version is missing or failed integrity verification.")
    return record


def begin_operator_action(db: Session) -> None:
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def record_decision(db: Session, proposal, action: str, actor: str, reason: str, prior: str, target: str):
    db.add(PromptAuditEvent(
        proposal_id=proposal.proposal_id, action=action, actor=actor, reason=reason.strip(),
        prior_version=prior, target_version=target,
    ))
    proposal.updated_at = datetime.now(UTC)
    db.commit()
    return {"success": True, "proposal_id": proposal.proposal_id, "status": proposal.status}


def validate_promotion(db: Session, proposal):
    baseline = executor_version(db, proposal.baseline_version)
    change = json.loads(proposal.proposed_change_json)
    artifacts = json.loads(proposal.benchmark_results_json or "{}")
    base_trial, cand_trial = artifacts.get("baseline"), artifacts.get("candidate")
    supporting_run_ids = json.loads(proposal.supporting_run_ids_json or "[]")
    if any(
        not evidence_verifier.verify_original_run_evidence(run_id, db).get("content_hash_verified")
        for run_id in supporting_run_ids
    ):
        raise HTTPException(409, "Supporting run evidence is missing or failed integrity verification.")
    if (
        not baseline.is_active or not base_trial or not cand_trial
        or not change.get("updated_system_prompt")
        or base_trial.get("model_name") != review_model_client.executor_model
        or base_trial.get("version_tag") != baseline.version_tag
        or cand_trial.get("version_tag") != proposal.candidate_version
        or base_trial.get("system_prompt_sha256") != baseline.prompt_hash
        or cand_trial.get("system_prompt_sha256") != compute_prompt_hash(change["updated_system_prompt"])
        or benchmark_suite.compare_benchmarks(base_trial, cand_trial)["decision"] != "PROMOTION_READY"
    ):
        raise HTTPException(409, "Current prompt and complete paired benchmark artifacts are required.")
    return baseline, change["updated_system_prompt"]


@router.post("/improvement-proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, payload: OperatorDecision, actor: str = Depends(require_operator), db: Session = Depends(get_db)):
    begin_operator_action(db)
    proposal = get_proposal(db, proposal_id)
    if proposal.status != "ELIGIBLE":
        raise HTTPException(409, "Only eligible proposals can be approved.")
    validate_promotion(db, proposal)
    proposal.status = "APPROVED"
    return record_decision(db, proposal, "APPROVED", actor, payload.reason, proposal.baseline_version, proposal.candidate_version)


@router.post("/improvement-proposals/{proposal_id}/activate")
def activate_proposal(proposal_id: str, payload: OperatorDecision, actor: str = Depends(require_operator), db: Session = Depends(get_db)):
    begin_operator_action(db)
    proposal = get_proposal(db, proposal_id)
    if proposal.status != "APPROVED":
        raise HTTPException(409, "Approval is required before activation.")
    baseline, candidate_prompt = validate_promotion(db, proposal)
    if db.query(PromptVersionRecord).filter_by(version_tag=proposal.candidate_version).first():
        raise HTTPException(409, "Candidate version already exists.")
    candidate_hash = compute_prompt_hash(candidate_prompt)
    baseline.is_active = 0
    db.add(PromptVersionRecord(
        version_tag=proposal.candidate_version, role="EXECUTOR", prompt_hash=candidate_hash,
        system_prompt=candidate_prompt, user_template=baseline.user_template, is_active=1,
        parent_version=baseline.version_tag,
        benchmark_score=json.loads(proposal.benchmark_results_json)["candidate"]["average_score"],
    ))
    proposal.status = "ACTIVE"
    return record_decision(db, proposal, "ACTIVE", actor, payload.reason, baseline.version_tag, proposal.candidate_version)


@router.post("/improvement-proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, payload: OperatorDecision, actor: str = Depends(require_operator), db: Session = Depends(get_db)):
    begin_operator_action(db)
    proposal = get_proposal(db, proposal_id)
    if proposal.status not in ("DRAFT", "BENCHMARKED", "ELIGIBLE", "APPROVED", "PENDING_APPROVAL"):
        raise HTTPException(409, "This proposal cannot be rejected in its current state.")
    proposal.status = "REJECTED"
    return record_decision(db, proposal, "REJECTED", actor, payload.reason, proposal.baseline_version, proposal.candidate_version)


@router.post("/improvement-proposals/{proposal_id}/rollback")
def rollback_proposal(proposal_id: str, payload: OperatorDecision, actor: str = Depends(require_operator), db: Session = Depends(get_db)):
    begin_operator_action(db)
    proposal = get_proposal(db, proposal_id)
    if proposal.status not in ("ACTIVE", "PROMOTED"):
        raise HTTPException(409, "Only an active proposal can be rolled back.")
    baseline = executor_version(db, proposal.baseline_version)
    candidate = executor_version(db, proposal.candidate_version)
    if candidate.is_active != 1 or baseline.is_active:
        raise HTTPException(409, "The recorded candidate is no longer the active prompt.")
    candidate.is_active = 0
    baseline.is_active = 1
    proposal.status = "ROLLED_BACK"
    return record_decision(db, proposal, "ROLLED_BACK", actor, payload.reason, candidate.version_tag, baseline.version_tag)


@router.get("/improvement-proposals/{proposal_id}/audit")
def prompt_audit_history(proposal_id: str, db: Session = Depends(get_db)):
    get_proposal(db, proposal_id)
    events = db.query(PromptAuditEvent).filter_by(proposal_id=proposal_id).order_by(PromptAuditEvent.id).all()
    return [{
        "action": event.action, "actor": event.actor, "reason": event.reason,
        "prior_version": event.prior_version, "target_version": event.target_version,
        "created_at": event.created_at,
    } for event in events]


@router.get("/prompt-versions", response_model=list[PromptVersionResponse])
def get_prompt_versions(role: str | None = "EXECUTOR", db: Session = Depends(get_db)):
    """
    Expose all registered prompt versions and active status for auditing and UI tracking.
    """
    from app.review.prompt_lifecycle import init_prompt_versions
    init_prompt_versions(db)

    query = db.query(PromptVersionRecord)
    if role:
        query = query.filter(PromptVersionRecord.role == role)
    records = query.order_by(PromptVersionRecord.id.asc()).all()
    measured_versions = {
        version for (version,) in db.query(PromptAuditEvent.target_version).filter_by(action="ACTIVE")
    }
    return [
        PromptVersionResponse(
            id=r.id,
            version_tag=r.version_tag,
            role=r.role,
            prompt_hash=r.prompt_hash or compute_prompt_hash(r.system_prompt),
            is_active=r.is_active,
            parent_version=r.parent_version,
            benchmark_score=r.benchmark_score if r.version_tag in measured_versions else None,
            created_at=r.created_at.isoformat() if r.created_at else ""
        )
        for r in records
    ]


@router.get("/prompt-versions/active")
def get_active_prompt_version(db: Session = Depends(get_db)):
    """
    Expose the currently active prompt version, cryptographic hash, and source (persisted DB vs runtime fallback).
    """
    from app.review.prompt_lifecycle import get_active_executor_prompt_info
    info = get_active_executor_prompt_info(db)
    measured = db.query(PromptAuditEvent.id).filter_by(action="ACTIVE", target_version=info["version_tag"]).first()
    return {**info, "benchmark_score": info["benchmark_score"] if measured else None}


@router.post("/improvement-proposals/{proposal_id}/benchmark")
async def run_proposal_benchmark(
    proposal_id: str,
    mode: str = Query("real_llm", pattern=r"^(auto|real_llm)$"),
    db: Session = Depends(get_db),
):
    with single_operation("proposal benchmark", proposal_id):
        proposal = get_proposal(db, proposal_id)
        if proposal.status not in ("DRAFT", "BENCHMARKED", "PENDING_APPROVAL"):
            raise HTTPException(409, "This proposal cannot be benchmarked in its current state.")
        baseline = executor_version(db, proposal.baseline_version)
        candidate = json.loads(proposal.proposed_change_json).get("updated_system_prompt")
        if not baseline.is_active or not candidate or candidate == baseline.system_prompt:
            raise HTTPException(409, "The active baseline and a distinct candidate are required.")
        base_prompt, base_version, candidate_version = baseline.system_prompt, baseline.version_tag, proposal.candidate_version
        previous_status, previous_results = proposal.status, proposal.benchmark_results_json
        db.rollback()

        health = await review_model_client.get_model_status()
        if not health["executor_installed"]:
            detail = " ".join([health["status_message"], *health["pull_commands"]])
            raise HTTPException(503, detail)
        baseline_result = await benchmark_suite.run_llm_benchmark(base_prompt, version_tag=base_version)
        candidate_result = await benchmark_suite.run_llm_benchmark(candidate, version_tag=candidate_version)
        comparison = benchmark_suite.compare_benchmarks(baseline_result, candidate_result)
        trial_id = str(uuid4())
        artifacts = {"trial_id": trial_id, "baseline": baseline_result, "candidate": candidate_result, "comparison": comparison}

        begin_operator_action(db)
        proposal = get_proposal(db, proposal_id)
        if proposal.status != previous_status or proposal.benchmark_results_json != previous_results:
            raise HTTPException(409, "Proposal changed while benchmarking.")
        proposal.benchmark_results_json = json.dumps(artifacts)
        db.add(BenchmarkTrialRecord(
            id=trial_id, proposal_id=proposal.proposal_id, artifacts_json=proposal.benchmark_results_json,
        ))
        proposal.status = {
            "PROMOTION_READY": "ELIGIBLE", "REJECT": "REJECTED",
        }.get(comparison["decision"], "BENCHMARKED")
        proposal.updated_at = datetime.now(UTC)
        db.commit()
        return {"proposal_id": proposal_id, **artifacts}


@router.get("/improvement-proposals/{proposal_id}/benchmarks")
def benchmark_history(proposal_id: str, db: Session = Depends(get_db)):
    get_proposal(db, proposal_id)
    trials = db.query(BenchmarkTrialRecord).filter_by(proposal_id=proposal_id).order_by(
        BenchmarkTrialRecord.recorded_at.desc()
    ).limit(20).all()
    return [json.loads(trial.artifacts_json) for trial in trials]


@router.get("/runs/{run_id}/evidence-verification", response_model=EvidenceVerificationResponse)
@router.get("/agent-runs/{run_id}/evidence-verification", response_model=EvidenceVerificationResponse)
def verify_run_evidence(run_id: str, db: Session = Depends(get_db)):
    """
    Verify the integrity, checksum provenance, and cited tags of an original recorded AI decision.
    Validates deterministic rules without re-running the agent or overwriting historical outputs.
    """
    res = evidence_verifier.verify_original_run_evidence(run_id, db)
    if res["audit_verdict"] == "RUN_NOT_FOUND":
        raise HTTPException(404, "Run not found.")
    return res


@router.post("/point-in-time-replay", response_model=PointInTimeReplayResponse)
def point_in_time_replay(payload: PointInTimeReplayRequest, db: Session = Depends(get_db)):
    """
    Perform point-in-time historical replay strictly excluding any data observed after cutoff T.
    """
    cutoff_str = payload.cutoff_datetime.strip()
    try:
        if len(cutoff_str) == 10 and "-" in cutoff_str:
            cutoff_dt = datetime.strptime(cutoff_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=UTC)
        else:
            cutoff_dt = datetime.fromisoformat(cutoff_str)
            if cutoff_dt.tzinfo is None:
                cutoff_dt = cutoff_dt.replace(tzinfo=UTC)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid cutoff_datetime format: {e!s}. Use YYYY-MM-DD or ISO 8601.")

    res = evidence_verifier.point_in_time_evidence_replay(
        symbol=payload.symbol,
        cutoff_datetime=cutoff_dt,
        db=db,
        dataset_id=payload.dataset_id
    )
    return res
