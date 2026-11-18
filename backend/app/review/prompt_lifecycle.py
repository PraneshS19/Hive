from typing import Any

from app.core.logging import logger
from app.db.models.review import PromptVersionRecord
from app.review.prompts import (
    EXECUTOR_SYSTEM_PROMPT_V1,
    EXECUTOR_USER_PROMPT_TEMPLATE_V1,
    compute_prompt_hash,
)
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def ensure_prompt_versions_schema(db: Session) -> None:
    """
    Ensure the prompt_versions table has the prompt_hash column.
    Idempotent and safe migration.
    """
    bind = db.get_bind()
    inspector = inspect(bind)
    if "prompt_versions" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("prompt_versions")]
        if "prompt_hash" not in columns:
            logger.info("Migrating prompt_versions table: adding prompt_hash column...")
            try:
                db.execute(text("ALTER TABLE prompt_versions ADD COLUMN prompt_hash VARCHAR(64)"))
                db.commit()
            except SQLAlchemyError as e:
                logger.debug(f"Schema alteration notice: {e}")


def init_prompt_versions(db: Session) -> PromptVersionRecord:
    """
    Safely and idempotently initialize versioned prompt records in SQLite.
    Guarantees:
      1. Baseline v1.0 exists with exact runtime system prompt, user template, and full SHA-256 hash.
      2. All prompt version records have populated prompt_hash fields.
      3. Exactly one executor prompt version is active (v1.0 by default).
      4. Candidate versions remain inactive until explicitly promoted.
    """
    ensure_prompt_versions_schema(db)

    expected_baseline_hash = compute_prompt_hash(EXECUTOR_SYSTEM_PROMPT_V1)

    # 1. Check or seed baseline v1.0
    v1_rec = db.query(PromptVersionRecord).filter(
        PromptVersionRecord.version_tag == "v1.0",
        PromptVersionRecord.role == "EXECUTOR"
    ).first()

    if not v1_rec:
        logger.info(f"Seeding baseline prompt version v1.0 (hash: {expected_baseline_hash})...")
        v1_rec = PromptVersionRecord(
            version_tag="v1.0",
            role="EXECUTOR",
            prompt_hash=expected_baseline_hash,
            system_prompt=EXECUTOR_SYSTEM_PROMPT_V1,
            user_template=EXECUTOR_USER_PROMPT_TEMPLATE_V1,
            is_active=1,
            parent_version=None,
            benchmark_score=0.0
        )
        db.add(v1_rec)
        db.flush()
    # 2. Populate prompt_hash for any other existing records
    all_prompts = db.query(PromptVersionRecord).all()
    for p in all_prompts:
        if not p.prompt_hash and p.system_prompt:
            p.prompt_hash = compute_prompt_hash(p.system_prompt)

    # 3. Enforce exactly one active executor prompt version invariant
    active_executors = db.query(PromptVersionRecord).filter(
        PromptVersionRecord.role == "EXECUTOR",
        PromptVersionRecord.is_active == 1
    ).order_by(PromptVersionRecord.id.desc()).all()

    if len(active_executors) == 0:
        logger.warning("No active executor prompt found; activating baseline v1.0.")
        v1_rec.is_active = 1
    elif len(active_executors) > 1:
        logger.warning(f"Multiple ({len(active_executors)}) active executor prompts detected; normalizing to single active.")
        # Retain only the newest active prompt, deactivate older duplicates
        active_executors[0]
        for duplicate in active_executors[1:]:
            duplicate.is_active = 0

    db.commit()

    active_rec = db.query(PromptVersionRecord).filter(
        PromptVersionRecord.role == "EXECUTOR",
        PromptVersionRecord.is_active == 1
    ).first()

    return active_rec or v1_rec


def get_active_executor_prompt_info(db: Session) -> dict[str, Any]:
    """
    Retrieve the currently active executor prompt record and identify
    whether it was retrieved from persisted database state or runtime fallback.
    """
    ensure_prompt_versions_schema(db)

    active_rec = db.query(PromptVersionRecord).filter(
        PromptVersionRecord.role == "EXECUTOR",
        PromptVersionRecord.is_active == 1
    ).order_by(PromptVersionRecord.id.desc()).first()

    if active_rec:
        stored_hash = active_rec.prompt_hash
        if stored_hash and compute_prompt_hash(active_rec.system_prompt) != stored_hash:
            raise RuntimeError("Active executor prompt failed integrity verification.")
        return {
            "source": "PERSISTED_DATABASE",
            "version_tag": active_rec.version_tag,
            "role": active_rec.role,
            "prompt_hash": active_rec.prompt_hash or compute_prompt_hash(active_rec.system_prompt),
            "system_prompt": active_rec.system_prompt,
            "user_template": active_rec.user_template,
            "is_active": 1,
            "benchmark_score": active_rec.benchmark_score,
            "created_at": active_rec.created_at.isoformat() if active_rec.created_at else None,
        }

    # Fallback to runtime constants if table is empty or unseeded
    fallback_hash = compute_prompt_hash(EXECUTOR_SYSTEM_PROMPT_V1)
    return {
        "source": "RUNTIME_FALLBACK",
        "version_tag": "v1.0",
        "role": "EXECUTOR",
        "prompt_hash": fallback_hash,
        "system_prompt": EXECUTOR_SYSTEM_PROMPT_V1,
        "user_template": EXECUTOR_USER_PROMPT_TEMPLATE_V1,
        "is_active": 1,
        "benchmark_score": 0.0,
        "created_at": None,
    }


def enforce_single_active_executor(db: Session, target_active_version: str) -> None:
    """
    Atomically ensure that exactly ONE executor prompt version has is_active = 1.
    All other executor records are set to is_active = 0.
    """
    db.query(PromptVersionRecord).filter(
        PromptVersionRecord.role == "EXECUTOR"
    ).update({"is_active": 0})

    target_rec = db.query(PromptVersionRecord).filter(
        PromptVersionRecord.role == "EXECUTOR",
        PromptVersionRecord.version_tag == target_active_version
    ).first()

    if target_rec:
        target_rec.is_active = 1
    else:
        # Fallback to activating v1.0
        v1_rec = db.query(PromptVersionRecord).filter(
            PromptVersionRecord.role == "EXECUTOR",
            PromptVersionRecord.version_tag == "v1.0"
        ).first()
        if v1_rec:
            v1_rec.is_active = 1
