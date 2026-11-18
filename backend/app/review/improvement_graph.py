import json
from difflib import unified_diff
from typing import Any, TypedDict
from uuid import uuid4

from app.core.config import settings
from app.core.logging import logger
from app.db.models import ImprovementProposalRecord, ReviewRun
from app.db.models.review import ReviewEvidenceRecord
from app.db.session import SessionLocal
from app.review.model_client import review_model_client
from app.review.prompts import (
    FAILURE_ANALYSIS_SYSTEM_PROMPT,
    compute_prompt_hash,
)
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session


class ContinuousImprovementState(TypedDict):
    proposal_id: str
    sample_size: int
    sample_sufficient: bool
    evaluations: list[dict[str, Any]]
    failure_categories: dict[str, int]
    total_failures: int
    proposal_type: str
    findings: list[dict[str, Any]]
    representative_traces: list[dict[str, Any]]
    root_cause_hypothesis: str
    hypothesis_source: str
    proposed_change: dict[str, Any]
    proposal: dict[str, Any] | None
    baseline_benchmark: dict[str, Any] | None
    candidate_benchmark: dict[str, Any] | None
    benchmark_comparison: dict[str, Any] | None
    status: str
    error_message: str | None


# -------------------------------------------------------------------------
# Node 1: load_recent_evaluations
# -------------------------------------------------------------------------
def load_recent_evaluations(state: ContinuousImprovementState) -> dict[str, Any]:
    db: Session = SessionLocal()
    try:
        runs = db.query(ReviewRun).join(ReviewEvidenceRecord).filter(
            ReviewRun.status.in_(("COMPLETED", "PARTIAL")),
        ).order_by(ReviewRun.created_at.desc()).limit(30).all()
        eval_list = []
        for r in runs:
            rev_out = json.loads(r.reviewer_output_json) if r.reviewer_output_json else {}
            eval_list.append({
                "run_id": r.run_id,
                "symbol": r.symbol,
                "verdict": r.review_verdict,
                "score": r.overall_score,
                "executor_output": json.loads(r.executor_output_json) if r.executor_output_json else {},
                "reviewer_output": rev_out,
                "objective_checks": json.loads(r.objective_checks_json) if r.objective_checks_json else {},
                "findings": rev_out.get("findings", [])
            })

        logger.info(f"Loaded {len(eval_list)} recent review evaluations for failure aggregation.")
        return {
            "evaluations": eval_list,
            "sample_size": len(eval_list),
            "status": "EVALUATIONS_LOADED"
        }
    finally:
        db.close()


# -------------------------------------------------------------------------
# Node 2: check_sample_sufficiency
# -------------------------------------------------------------------------
def check_sample_sufficiency(state: ContinuousImprovementState) -> dict[str, Any]:
    sample_size = state.get("sample_size", 0)
    min_thresh = getattr(settings, "MIN_EVAL_SAMPLE_THRESHOLD", 3)
    sufficient = sample_size >= min_thresh

    if not sufficient:
        msg = f"Insufficient evaluation data: {sample_size} runs recorded (minimum {min_thresh} required)."
        logger.info(f"Sample sufficiency gate: {msg}")
        return {
            "sample_sufficient": False,
            "status": "INSUFFICIENT_DATA",
            "error_message": msg
        }

    return {
        "sample_sufficient": True,
        "status": "SAMPLE_SUFFICIENT"
    }


# -------------------------------------------------------------------------
# Node 3: aggregate_failures & select representative traces
# -------------------------------------------------------------------------
def aggregate_failures(state: ContinuousImprovementState) -> dict[str, Any]:
    evals = state.get("evaluations", [])
    categories: dict[str, int] = {
        "EVIDENCE_UNGROUNDED": 0,
        "SCHEMA_DRIFT": 0,
        "QUANTITATIVE_MISALIGNMENT": 0,
        "UNVERIFIED_RUMOR_EXPOSURE": 0,
        "LATENCY_SPIKE": 0
    }
    representative_traces = []
    all_findings = []

    for ev in evals:
        obj = ev.get("objective_checks", {})
        verdict = ev.get("verdict")
        score = ev.get("score", 100.0)
        findings = ev.get("findings") or ev.get("reviewer_output", {}).get("findings", [])

        is_flagged_or_revise = verdict in ("FLAG", "REVISE", "ERROR") or score < 80.0

        if not obj.get("schema_valid", True):
            categories["SCHEMA_DRIFT"] += 1
        if not obj.get("evidence_refs_exist", True):
            categories["EVIDENCE_UNGROUNDED"] += 1
        if not obj.get("quantitative_consistency", True):
            categories["QUANTITATIVE_MISALIGNMENT"] += 1
        if obj.get("prompt_injection_detected", False) or ("rumor" in str(ev).lower() and verdict == "FLAG"):
            categories["UNVERIFIED_RUMOR_EXPOSURE"] += 1

        if is_flagged_or_revise and len(representative_traces) < 3:
            representative_traces.append({
                "run_id": ev["run_id"],
                "symbol": ev["symbol"],
                "verdict": verdict,
                "score": score,
                "summary": ev.get("executor_output", {}).get("summary", "")[:120],
                "failures": obj.get("failure_reasons", [])
            })

        for f in findings:
            all_findings.append({
                "run_id": ev["run_id"],
                "symbol": ev["symbol"],
                "criterion_id": f.get("criterion_id"),
                "severity": f.get("severity"),
                "title": f.get("title"),
                "description": f.get("description"),
                "recommendation": f.get("recommendation")
            })

    total_observed_failures = sum(categories.values())
    is_proactive_refinement = (total_observed_failures == 0)

    # When no failures occurred, use analyzed runs as reference baselines
    if is_proactive_refinement and not representative_traces and evals:
        for ev in evals[:3]:
            f_titles = [f.get("title") for f in ev.get("findings", []) if f.get("title")]
            representative_traces.append({
                "run_id": ev["run_id"],
                "symbol": ev["symbol"],
                "verdict": ev.get("verdict"),
                "score": ev.get("score"),
                "summary": ev.get("executor_output", {}).get("summary", "")[:120],
                "failures": [],
                "findings": f_titles
            })

    return {
        "failure_categories": categories,
        "total_failures": total_observed_failures,
        "proposal_type": "PROACTIVE_REFINEMENT" if is_proactive_refinement else "FAILURE_REMEDIATION",
        "findings": all_findings,
        "representative_traces": representative_traces,
        "status": "FAILURES_AGGREGATED"
    }


# -------------------------------------------------------------------------
# Node 4: ask_gemma_for_root_cause_hypotheses
# -------------------------------------------------------------------------
async def ask_gemma_for_root_cause_hypotheses(state: ContinuousImprovementState) -> dict[str, Any]:
    categories = state.get("failure_categories", {})
    traces = state.get("representative_traces", [])
    findings = state.get("findings", [])
    total_failures = state.get("total_failures", sum(categories.values()))
    prop_type = state.get("proposal_type", "FAILURE_REMEDIATION")

    if total_failures == 0 or prop_type == "PROACTIVE_REFINEMENT":
        top_failure = "NONE_OBSERVED (PROACTIVE_REFINEMENT)"
        user_prompt = (
            f"Evaluation Baseline: 0 failures observed across all {len(traces)} analyzed runs (100% objective check pass rate).\n"
            f"Reviewer Context & Findings: {json.dumps(findings, indent=2)}\n"
            f"Analyzed Baseline Traces: {json.dumps(traces, indent=2)}\n\n"
            "All evaluated runs passed deterministic objective checks with zero recorded failures. "
            "Propose a proactive prompt refinement hypothesis to further enhance evidence grounding and disclosures.\n"
            'Respond with a JSON object: {"root_cause_hypothesis": "...", "primary_category": "PROACTIVE_REFINEMENT"}'
        )
        fallback_hypothesis = (
            "All evaluated runs passed deterministic objective checks with zero recorded failures. "
            "Proactive prompt refinement reinforces explicit missing-input disclosure and comprehensive evidence cross-referencing."
        )
    else:
        top_failure = max(categories.items(), key=lambda x: x[1])[0] if categories else "SCHEMA_DRIFT"
        user_prompt = (
            f"Aggregated Failure Counts: {json.dumps(categories)}\n"
            f"Top Failure Category: {top_failure}\n"
            f"Representative Traces: {json.dumps(traces, indent=2)}\n\n"
            "Explain the probable root cause of these agent weaknesses and propose a testable prompt/guidance hypothesis.\n"
            'Respond with a JSON object: {"root_cause_hypothesis": "...", "primary_category": "' + top_failure + '"}'
        )
        fallback_hypothesis = f"Executor prompts lack explicit emphasis on {top_failure.lower().replace('_', ' ')} and mandatory evidence tagging."

    parsed, telemetry = await review_model_client.generate_structured(
        model_name=review_model_client.reviewer_model,
        system_prompt=FAILURE_ANALYSIS_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
        num_predict=300
    )

    observed_hypothesis = parsed.get("root_cause_hypothesis") if parsed else None
    has_model_hypothesis = isinstance(observed_hypothesis, str) and bool(observed_hypothesis.strip())
    hypothesis = observed_hypothesis if has_model_hypothesis else fallback_hypothesis

    return {
        "root_cause_hypothesis": hypothesis,
        "hypothesis_source": telemetry.get("execution_mode") if has_model_hypothesis else "DETERMINISTIC_HYPOTHESIS",
        "status": "HYPOTHESIS_FORMULATED"
    }


# -------------------------------------------------------------------------
# Node 5: generate_improvement_proposal
# -------------------------------------------------------------------------
async def generate_improvement_proposal(state: ContinuousImprovementState) -> dict[str, Any]:
    hypothesis = state.get("root_cause_hypothesis", "")
    categories = state.get("failure_categories", {})
    total_failures = state.get("total_failures", sum(categories.values()))
    prop_type = state.get("proposal_type", "FAILURE_REMEDIATION")
    prop_id = f"PROP_{uuid4().hex}"
    from app.review.prompt_lifecycle import get_active_executor_prompt_info
    with SessionLocal() as db:
        baseline = get_active_executor_prompt_info(db)
    baseline_prompt = baseline["system_prompt"]

    if total_failures == 0 or prop_type == "PROACTIVE_REFINEMENT":
        top_failure = "NONE_OBSERVED (PROACTIVE_REFINEMENT)"
        title = "Proactive Guardrail Refinement: Evidence Grounding & Gap Disclosure"
        proposed_system_prompt_delta = (
            baseline_prompt +
            "\nCRITICAL EMPHASIS: Strictly cite all relevant evidence tags (EV_PRICE, EV_IND, EV_MACRO, EV_NEWS) in 'evidence_refs'. "
            "Explicitly list any missing or unverified items in 'missing_inputs' and 'uncertainties'."
        )
        expected_benefit = (
            "Hypothesis: improve citation checks and missing-input disclosure in paired trials."
        )
    else:
        top_failure = max(categories.items(), key=lambda x: x[1])[0] if categories else "EVIDENCE_UNGROUNDED"
        title = f"Prompt Guardrail Optimization for {top_failure.replace('_', ' ').title()}"
        proposed_system_prompt_delta = (
            baseline_prompt +
            f"\nCRITICAL EMPHASIS: Always verify {top_failure.replace('_', ' ').lower()}. "
            "Strictly cite all relevant evidence tags (EV_PRICE, EV_IND, EV_MACRO, EV_NEWS) in 'evidence_refs'. "
            "Explicitly list any missing or unverified items in 'missing_inputs'."
        )
        expected_benefit = f"Hypothesis: reduce {top_failure.lower()} errors in paired trials."

    proposal = {
        "proposal_id": prop_id,
        "title": title,
        "failure_category": top_failure,
        "proposal_type": prop_type,
        "total_failures_observed": total_failures,
        "supporting_run_ids": [t.get("run_id") for t in state.get("representative_traces", []) if t.get("run_id")],
        "root_cause_hypothesis": hypothesis,
        "proposed_change": {
            "component": "EXECUTOR_SYSTEM_PROMPT",
            "modified_prompt_section": f"Mandate for {'proactive evidence grounding and gap disclosure' if total_failures == 0 else top_failure}.",
            "updated_system_prompt": proposed_system_prompt_delta,
            "baseline_prompt_hash": baseline["prompt_hash"],
            "candidate_prompt_hash": compute_prompt_hash(proposed_system_prompt_delta),
            "prompt_diff": "\n".join(unified_diff(
                baseline_prompt.splitlines(), proposed_system_prompt_delta.splitlines(),
                fromfile=baseline["version_tag"], tofile="candidate", lineterm="",
            )),
            "hypothesis_source": state.get("hypothesis_source"),
            "target_temperature": 0.1
        },
        "affected_configuration": "HEDGELAB_EXECUTOR_SYSTEM_PROMPT",
        "expected_benefit": expected_benefit,
        "regression_risks": "Minimal; preserves quantitative indicator alignment and risk gate boundaries.",
        "benchmark_case_ids": ["BM_01_NORMAL_MOMENTUM", "BM_02_MISSING_INDICATOR", "BM_03_UNVERIFIED_RUMOR", "BM_08_PORTFOLIO_CONCENTRATION_LIMIT"],
        "status": "DRAFT",
        "baseline_version": baseline["version_tag"],
        "candidate_version": f"v-{uuid4().hex[:24]}"
    }

    return {
        "proposal_id": prop_id,
        "proposal": proposal,
        "proposed_change": proposal["proposed_change"],
        "status": "PROPOSAL_GENERATED"
    }


# -------------------------------------------------------------------------
# Node 6: validate_proposal_scope (Safety Guardrail!)
# -------------------------------------------------------------------------
def validate_proposal_scope(state: ContinuousImprovementState) -> dict[str, Any]:
    """
    CRITICAL FINANCIAL SAFETY CHECK:
    Model-generated proposals CANNOT weaken financial safety rules,
    cannot touch max order sizes (10%), asset allocations (25%),
    drawdown halts (15%), or brokerage execution formulas.
    """
    prop = state.get("proposal", {})
    prop_change = prop.get("proposed_change", {})
    change_text = json.dumps(prop_change).lower()

    forbidden_keywords = [
        "bypass risk", "disable risk", "increase max_order", "increase allocation",
        "allow short", "real broker", "skip fee", "remove limit"
    ]

    for kw in forbidden_keywords:
        if kw in change_text:
            err = f"Security Policy Violation: Proposal attempted forbidden modification: '{kw}'."
            logger.error(err)
            prop["status"] = "REJECTED"
            return {"status": "REJECTED", "error_message": err}

    return {"status": "PROPOSAL_VALIDATED"}


# -------------------------------------------------------------------------
# Node 8: persist_pending_proposal
# -------------------------------------------------------------------------
def persist_pending_proposal(state: ContinuousImprovementState) -> dict[str, Any]:
    prop = state.get("proposal", {})
    if not prop:
        return {"status": "NO_PROPOSAL"}

    db: Session = SessionLocal()
    try:
        rec = db.query(ImprovementProposalRecord).filter(
            ImprovementProposalRecord.proposal_id == prop.get("proposal_id")
        ).first()

        if not rec:
            rec = ImprovementProposalRecord(
                proposal_id=prop.get("proposal_id"),
                title=prop.get("title"),
                failure_category=prop.get("failure_category"),
                supporting_run_ids_json=json.dumps(prop.get("supporting_run_ids", [])),
                root_cause_hypothesis=prop.get("root_cause_hypothesis"),
                proposed_change_json=json.dumps(prop.get("proposed_change", {})),
                affected_configuration=prop.get("affected_configuration"),
                expected_benefit=prop.get("expected_benefit"),
                regression_risks=prop.get("regression_risks"),
                benchmark_case_ids_json=json.dumps(prop.get("benchmark_case_ids", [])),
                status=prop.get("status", "PENDING_APPROVAL"),
                baseline_version=prop.get("baseline_version", "v1.0"),
                candidate_version=prop.get("candidate_version", "v1.1"),
                benchmark_results_json=json.dumps(prop.get("benchmark_comparison", {}))
            )
            db.add(rec)
        else:
            rec.benchmark_results_json = json.dumps(prop.get("benchmark_comparison", {}))

        db.commit()
        logger.info(f"Persisted improvement proposal: {prop.get('proposal_id')}")
        return {"status": "PROPOSAL_PERSISTED"}
    finally:
        db.close()


# -------------------------------------------------------------------------
# Router
# -------------------------------------------------------------------------
def route_improvement_workflow(state: ContinuousImprovementState) -> str:
    if not state.get("sample_sufficient", False):
        return END
    return "aggregate_failures"


# -------------------------------------------------------------------------
# Compile Continuous Improvement Graph
# -------------------------------------------------------------------------
def create_continuous_improvement_graph():
    builder = StateGraph(ContinuousImprovementState)

    builder.add_node("load_recent_evaluations", load_recent_evaluations)
    builder.add_node("check_sample_sufficiency", check_sample_sufficiency)
    builder.add_node("aggregate_failures", aggregate_failures)
    builder.add_node("ask_gemma_for_root_cause_hypotheses", ask_gemma_for_root_cause_hypotheses)
    builder.add_node("generate_improvement_proposal", generate_improvement_proposal)
    builder.add_node("validate_proposal_scope", validate_proposal_scope)
    builder.add_node("persist_pending_proposal", persist_pending_proposal)

    builder.add_edge(START, "load_recent_evaluations")
    builder.add_edge("load_recent_evaluations", "check_sample_sufficiency")

    builder.add_conditional_edges(
        "check_sample_sufficiency",
        route_improvement_workflow,
        {
            "aggregate_failures": "aggregate_failures",
            END: END
        }
    )

    builder.add_edge("aggregate_failures", "ask_gemma_for_root_cause_hypotheses")
    builder.add_edge("ask_gemma_for_root_cause_hypotheses", "generate_improvement_proposal")
    builder.add_edge("generate_improvement_proposal", "validate_proposal_scope")
    builder.add_edge("validate_proposal_scope", "persist_pending_proposal")
    builder.add_edge("persist_pending_proposal", END)

    return builder.compile()


continuous_improvement_graph = create_continuous_improvement_graph()
