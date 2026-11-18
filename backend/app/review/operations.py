"""Bound in-process work and reconcile interrupted research on single-worker startup."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.db.models import ReviewRun
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

_active: set[tuple[str, str]] = set()
_in_flight = ("INITIALIZED", "RUNNING", "EXECUTING", "EXECUTED", "VALIDATING", "REVIEWING", "REVISING")


@contextmanager
def single_operation(kind: str, key: str) -> Iterator[None]:
    operation = (kind, key)
    if operation in _active:
        raise HTTPException(409, f"This {kind} is already running. Check its status before retrying.")
    _active.add(operation)
    try:
        yield
    finally:
        _active.discard(operation)


def mark_interrupted_runs(db: Session, reason: str, run_id: str | None = None) -> None:
    statement = update(ReviewRun).where(
        ReviewRun.status.in_(_in_flight), ReviewRun.completed_at.is_(None),
    )
    if run_id is not None:
        statement = statement.where(ReviewRun.run_id == run_id)
    db.execute(statement.values(
        status="FAILED", review_verdict="ERROR", error_message=reason, completed_at=datetime.now(UTC),
    ))
    db.commit()
