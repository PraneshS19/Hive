from datetime import datetime

from app.db.base import Base, get_utc_now
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class ReviewRun(Base):
    """
    Persisted execution & evaluation run tracking Qwen execution, Gemma review,
    and bounded revision cycles.
    """
    __tablename__ = "review_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False, default="MARKET_ANALYSIS")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, default="RELIANCE")
    task_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="INITIALIZED")  # INITIALIZED, EXECUTING, VALIDATING, REVIEWING, REVISING, COMPLETED, FAILED
    executor_model: Mapped[str] = mapped_column(String(50), nullable=False)
    reviewer_model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(30), default="v1.0")
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=True)

    executor_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    reviewer_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)

    executor_output_json: Mapped[str] = mapped_column(Text, default="{}")
    reviewer_output_json: Mapped[str] = mapped_column(Text, default="{}")
    objective_checks_json: Mapped[str] = mapped_column(Text, default="{}")

    review_verdict: Mapped[str] = mapped_column(String(20), default="PENDING")  # PASS, FLAG, REVISE, ERROR, PENDING
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewStepEvent(Base):
    """
    Observable step event within an agent execution / evaluation workflow.
    """
    __tablename__ = "review_step_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    step_name: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")  # RUNNING, COMPLETED, FAILED, SKIPPED
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class ReviewToolEvent(Base):
    """
    Observable tool execution event distinguishing model-selected from policy-selected invocations.
    """
    __tablename__ = "review_tool_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    selection_source: Mapped[str] = mapped_column(String(20), default="policy")  # 'model' or 'policy'
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="SUCCESS")  # SUCCESS, ERROR, TIMEOUT
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class ReviewFinding(Base):
    """
    Individual finding produced by Gemma reviewer or deterministic verification check.
    """
    __tablename__ = "review_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    criterion_id: Mapped[str] = mapped_column(String(50), nullable=False)  # task_completion, evidence_grounding, etc.
    severity: Mapped[str] = mapped_column(String(20), default="INFO")  # INFO, WARNING, CRITICAL
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class ImprovementProposalRecord(Base):
    """
    Continuous improvement proposal generated from failure analysis,
    awaiting evaluation and explicit human promotion.
    """
    __tablename__ = "improvement_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    failure_category: Mapped[str] = mapped_column(String(50), nullable=False)
    supporting_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    root_cause_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_change_json: Mapped[str] = mapped_column(Text, default="{}")
    affected_configuration: Mapped[str] = mapped_column(String(100), nullable=False)
    expected_benefit: Mapped[str] = mapped_column(Text, nullable=False)
    regression_risks: Mapped[str] = mapped_column(Text, nullable=False)
    benchmark_case_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="PENDING_APPROVAL")  # PENDING_APPROVAL, APPROVED, REJECTED, PROMOTED, ROLLED_BACK
    baseline_version: Mapped[str] = mapped_column(String(30), default="v1.0")
    candidate_version: Mapped[str] = mapped_column(String(30), default="v1.1")
    benchmark_results_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class PromptVersionRecord(Base):
    """
    Versioned prompt template and active configuration record.
    """
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_tag: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=0)
    parent_version: Mapped[str] = mapped_column(String(30), nullable=True)
    benchmark_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class ReviewEvidenceRecord(Base):
    """Exact model evidence packet and its original checksum."""

    __tablename__ = "review_evidence"

    run_id: Mapped[str] = mapped_column(ForeignKey("review_runs.run_id"), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class PromptAuditEvent(Base):
    """Local operator decisions written in the same transaction as the change."""

    __tablename__ = "prompt_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("improvement_proposals.proposal_id"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    prior_version: Mapped[str | None] = mapped_column(String(64))
    target_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class BenchmarkTrialRecord(Base):
    """History of paired benchmark attempts, including incomplete trials."""

    __tablename__ = "benchmark_trials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("improvement_proposals.proposal_id"), index=True)
    artifacts_json: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
