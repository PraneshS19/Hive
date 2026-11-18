from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ResearchOrderProposal(BaseModel):
    quantity: int = Field(gt=0, strict=True)
    price: float = Field(gt=0, allow_inf_nan=False)
    symbol: str | None = None


class ExecutorOutput(BaseModel):
    """
    Structured response contract emitted by Qwen execution agent.
    """
    run_id: str = Field(description="Unique run execution identifier")
    task_status: str = Field(default="COMPLETED", description="'COMPLETED', 'PARTIAL', or 'FAILED'")
    summary: str = Field(description="High-level analytical summary")
    observations: list[str] = Field(default_factory=list, description="Core analytical observations")
    evidence_refs: list[str] = Field(default_factory=list, description="List of evidence/source IDs referenced")
    quantitative_interpretation: str = Field(default="", description="Interpretation of technical and volatility indicators")
    bull_case: str = Field(default="", description="Bullish scenario arguments")
    bear_case: str = Field(default="", description="Bearish scenario arguments")
    key_risks: list[str] = Field(default_factory=list, description="Identified tail or operational risks")
    uncertainties: list[str] = Field(default_factory=list, description="Acknowledged data gaps or uncertainties")
    missing_inputs: list[str] = Field(default_factory=list, description="Explicitly missing or partial inputs")
    recommendation_type: str = Field(default="NEUTRAL", description="Action recommendation: BUY, HOLD, REDUCE, AVOID, NEUTRAL")
    order_proposal: ResearchOrderProposal | None = None
    completion_notes: str = Field(default="", description="Operational notes on task completion")

    @field_validator("bull_case", "bear_case", "quantitative_interpretation", "summary", mode="before")
    @classmethod
    def coerce_list_to_str(cls, v):
        if isinstance(v, list):
            return "; ".join(str(item) for item in v)
        return str(v) if v is not None else ""


class CriterionFinding(BaseModel):
    criterion_id: str
    severity: str = "INFO"  # 'INFO', 'WARNING', 'CRITICAL'
    title: str
    description: str
    evidence_refs: list[str] = Field(default_factory=list)
    recommendation: str = ""


class CriterionScore(BaseModel):
    criterion_id: str
    score: float | None = None  # 0.0 to 10.0, or None if not applicable
    status: str = "PASS"  # 'PASS', 'FLAG', 'FAIL', 'NOT_APPLICABLE'
    weight: float = 1.0
    evaluation_notes: str = ""
    findings: list[CriterionFinding] = Field(default_factory=list)


class ReviewerResult(BaseModel):
    """
    Structured review contract emitted by Gemma independent reviewer.
    """
    run_id: str
    review_status: Literal["PASS", "FLAG", "REVISE", "ERROR"]  # 'PASS', 'FLAG', 'REVISE', 'ERROR'
    overall_score: float = Field(ge=0, le=100, allow_inf_nan=False)
    criteria: dict[str, CriterionScore] = Field(default_factory=dict)
    findings: list[CriterionFinding] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    revision_instructions: str | None = None
    unavailable_checks: list[str] = Field(default_factory=list)
    reviewer_model: str = "gemma-3-4b"
    rubric_version: str = "v1.0"


class ObjectiveChecks(BaseModel):
    """
    Deterministic Python validation checks executed independently of LLM opinions.
    """
    schema_valid: bool = False
    required_fields_present: bool = False
    evidence_refs_exist: bool = False
    quantitative_consistency: bool = False
    risk_policy_compliant: bool = True
    missing_data_disclosed: bool = False
    prompt_injection_detected: bool = False
    unverified_rumor_blocked: bool = False
    measured_metrics: dict[str, Any] = Field(default_factory=dict)
    failure_reasons: list[str] = Field(default_factory=list)


class ImprovementProposal(BaseModel):
    """
    Continuous improvement proposal for targeted prompt / configuration optimization.
    """
    proposal_id: str
    title: str
    failure_category: str  # EVIDENCE_UNGROUNDED, SCHEMA_DRIFT, QUANTITATIVE_MISALIGNMENT, etc.
    supporting_run_ids: list[str] = Field(default_factory=list)
    root_cause_hypothesis: str
    proposed_change: dict[str, Any] = Field(default_factory=dict)
    affected_configuration: str
    expected_benefit: str
    regression_risks: str
    benchmark_case_ids: list[str] = Field(default_factory=list)
    status: str = "PENDING_APPROVAL"  # PENDING_APPROVAL, APPROVED, REJECTED, PROMOTED, ROLLED_BACK
    baseline_version: str = "v1.0"
    candidate_version: str = "v1.1"
    benchmark_comparison: dict[str, Any] | None = None


class RunSummaryResponse(BaseModel):
    run_id: str
    task_type: str
    symbol: str
    status: str
    executor_model: str
    reviewer_model: str
    review_verdict: str
    overall_score: float
    revision_count: int
    total_latency_ms: float
    executor_latency_ms: float | None = 0.0
    reviewer_latency_ms: float | None = 0.0
    objective_pass_pct: float | None = None
    objective_checks: dict[str, Any] | None = None
    findings_count: int | None = 0
    error_message: str | None = None
    created_at: str
    completed_at: str | None = None


class RunDetailResponse(BaseModel):
    run_id: str
    task_type: str
    symbol: str
    task_prompt: str
    acceptance_criteria: str
    status: str
    executor_model: str
    reviewer_model: str
    prompt_version: str
    prompt_hash: str | None = None
    executor_output: dict[str, Any]
    reviewer_output: dict[str, Any]
    objective_checks: dict[str, Any]
    review_verdict: str
    overall_score: float
    revision_count: int
    step_events: list[dict[str, Any]]
    tool_events: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    executor_latency_ms: float
    reviewer_latency_ms: float
    total_latency_ms: float
    error_message: str | None = None
    created_at: str
    completed_at: str | None = None


class EvaluationAnalyticsSummary(BaseModel):
    total_runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    pass_count: int = 0
    flag_count: int = 0
    revise_count: int = 0
    error_count: int = 0
    pass_rate_pct: float = 0.0
    schema_validity_pct: float = 0.0
    evidence_grounding_pct: float = 0.0
    average_score: float = 0.0
    average_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    revision_frequency_pct: float = 0.0
    failure_categories: dict[str, int] = Field(default_factory=dict)
    active_prompt_version: str = "v1.0"
    active_prompt_hash: str | None = None
    active_prompt_source: str | None = "PERSISTED_DATABASE"
    sample_sufficient_for_improvement: bool = False
    sample_size: int = 0
    min_threshold: int = 3
    total_findings_count: int = 0


class PromptVersionResponse(BaseModel):
    id: int
    version_tag: str
    role: str
    prompt_hash: str | None = None
    is_active: int
    parent_version: str | None = None
    benchmark_score: float | None = None
    created_at: str


class EvidenceVerificationResponse(BaseModel):
    run_id: str
    symbol: str
    decision_timestamp: str | datetime | None = None
    audit_verdict: str
    audit_description: str
    content_hash_verified: bool
    stored_sha256: str | None = None
    computed_sha256: str | None = None
    prompt_hash: str | None = None
    snapshot_id: str | None = None
    source_timestamp: str | datetime | None = None
    ingestion_timestamp: str | datetime | None = None
    cited_references: list[dict[str, Any]] = Field(default_factory=list)
    original_agent_output_preserved: bool = True
    re_run_agent: bool = False
    reproducibility_status: str = "DETERMINISTIC_RULES_REPRODUCIBLE"
    audit_executed_at: str


class PointInTimeReplayRequest(BaseModel):
    symbol: str = Field(default="RELIANCE")
    cutoff_datetime: str = Field(description="ISO 8601 or YYYY-MM-DD timestamp cutoff T")
    dataset_id: str | None = Field(default=None, description="Optional registered dataset ID")


class PointInTimeReplayResponse(BaseModel):
    replay_id: str
    symbol: str
    cutoff_timestamp: str | None = None
    status: str | None = None
    error: str | None = None
    is_replay: bool = True
    mode: str = "HISTORICAL_EVIDENCE_REPLAY"
    audit_label: str | None = None
    reconstruction_type: str | None = None
    latest_observed_bar: dict[str, Any] | None = None
    historical_indicators: dict[str, Any] | None = None
    evidence_snapshot: dict[str, Any] | None = None
    lookahead_prevention_verified: bool = True
    future_bars_excluded_count: int = 0
    provenance: str | None = None
    notes: str | None = None
