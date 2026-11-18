import json

from app.api.dependencies import get_db
from app.core.security import require_operator
from app.db.models import RiskConfig, RiskDecision
from app.schemas.risk import RiskConfigResponse, RiskConfigUpdate, RiskDecisionResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/risk/config", response_model=RiskConfigResponse)
def get_risk_config(db: Session = Depends(get_db)):
    cfg = db.query(RiskConfig).first()
    if not cfg:
        cfg = RiskConfig()
        db.add(cfg)
        db.commit()

    return RiskConfigResponse(
        fee=cfg.fee_pct,
        maxOrder=cfg.max_order_pct,
        maxAllocation=cfg.max_allocation_pct,
        drawdown=cfg.drawdown_halt_pct,
        auto_execute=cfg.auto_execute,
        updated_at=cfg.updated_at,
    )


@router.put("/risk/config", response_model=RiskConfigResponse, dependencies=[Depends(require_operator)])
def update_risk_config(payload: RiskConfigUpdate, db: Session = Depends(get_db)):
    cfg = db.query(RiskConfig).first()
    if not cfg:
        cfg = RiskConfig()
        db.add(cfg)

    # Validate logical coherence between per-order and per-asset limits
    target_max_order = payload.max_order_pct if payload.max_order_pct is not None else cfg.max_order_pct
    target_max_alloc = payload.max_allocation_pct if payload.max_allocation_pct is not None else cfg.max_allocation_pct
    if target_max_order > target_max_alloc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid risk configuration: max single-order limit ({target_max_order}%) cannot exceed max asset allocation limit ({target_max_alloc}%)."
        )

    if payload.fee_pct is not None:
        cfg.fee_pct = payload.fee_pct
    if payload.max_order_pct is not None:
        cfg.max_order_pct = payload.max_order_pct
    if payload.max_allocation_pct is not None:
        cfg.max_allocation_pct = payload.max_allocation_pct
    if payload.drawdown_halt_pct is not None:
        cfg.drawdown_halt_pct = payload.drawdown_halt_pct
    if payload.auto_execute is not None:
        cfg.auto_execute = payload.auto_execute

    db.commit()
    db.refresh(cfg)

    return RiskConfigResponse(
        fee=cfg.fee_pct,
        maxOrder=cfg.max_order_pct,
        maxAllocation=cfg.max_allocation_pct,
        drawdown=cfg.drawdown_halt_pct,
        auto_execute=cfg.auto_execute,
        updated_at=cfg.updated_at,
    )


@router.get("/risk/decisions", response_model=list[RiskDecisionResponse])
def get_risk_decisions(db: Session = Depends(get_db)):
    decisions = db.query(RiskDecision).order_by(RiskDecision.timestamp.desc()).limit(20).all()
    results = []
    for d in decisions:
        try:
            rules = json.loads(d.rule_results_json)
        except (TypeError, ValueError):
            rules = []
        results.append(RiskDecisionResponse(
            id=d.id,
            order_id=d.order_id,
            outcome=d.outcome,
            reason=d.reason,
            evaluated_qty=d.evaluated_qty,
            approved_qty=d.approved_qty,
            rule_results=rules,
            timestamp=d.timestamp,
        ))
    return results
