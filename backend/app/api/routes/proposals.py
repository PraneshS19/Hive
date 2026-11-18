"""
SYNQ — Risk-Gated Paper-Trade Proposals & Evidence Snapshot Endpoints
Provides explicit human confirmation workflows, revalidation checks,
and access to immutable evidence packets.
"""

from typing import Any

from app.execution.paper_proposals import paper_proposal_service
from app.market.evidence_snapshot import evidence_snapshot_service
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class CreateProposalPayload(BaseModel):
    run_id: str
    symbol: str
    side: str
    price: float
    reason: str
    event_id: str | None = None
    snapshot_id: str | None = None
    target_allocation_pct: float = 8.0


@router.get("/proposals")
def list_paper_proposals(
    status: str | None = None,
    limit: int = Query(default=30, ge=1, le=100)
):
    """
    List paper-trading proposals with active status and expiration dates.
    """
    return paper_proposal_service.list_proposals(status=status, limit=limit)


@router.post("/proposals")
def create_paper_proposal(payload: CreateProposalPayload):
    """
    Create a new paper-trade proposal from an analysis run.
    """
    return paper_proposal_service.create_proposal_from_analysis(
        run_id=payload.run_id,
        symbol=payload.symbol,
        side=payload.side,
        price=payload.price,
        reason=payload.reason,
        event_id=payload.event_id,
        snapshot_id=payload.snapshot_id,
        target_allocation_pct=payload.target_allocation_pct
    )


@router.post("/proposals/{proposal_id}/confirm")
def confirm_paper_proposal(proposal_id: str):
    """
    Explicit human confirmation: revalidates current cash, limits, and expiration,
    then executes order in the simulated local paper broker.
    """
    res = paper_proposal_service.confirm_and_execute_proposal(proposal_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Proposal confirmation failed."))
    return res


@router.post("/proposals/{proposal_id}/reject")
def reject_paper_proposal(proposal_id: str, payload: dict[str, Any] | None = None):
    """
    Explicit operator rejection of a pending proposal.
    """
    reason = payload.get("reason", "Operator rejected proposal") if payload else "Operator rejected proposal"
    res = paper_proposal_service.reject_proposal(proposal_id, reason=reason)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Proposal rejection failed."))
    return res


@router.get("/snapshots/{snapshot_id}")
def get_evidence_snapshot(snapshot_id: str):
    """
    Retrieve an immutable frozen evidence snapshot by ID.
    """
    snap = evidence_snapshot_service.get_snapshot(snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail=f"Evidence snapshot '{snapshot_id}' not found.")
    return snap
