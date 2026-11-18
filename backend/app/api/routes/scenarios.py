
from app.api.dependencies import get_db
from app.db.models import ScenarioRecord
from app.decisions.pipeline import decision_pipeline
from app.market.engine import market_engine
from app.schemas.scenarios import ScenarioInjectRequest, ScenarioResponse, ScenarioRunResult
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/scenarios", response_model=list[ScenarioResponse])
def get_scenarios(db: Session = Depends(get_db)):
    records = db.query(ScenarioRecord).order_by(ScenarioRecord.created_at.desc()).all()
    results = []
    for r in records:
        results.append({
            "id": r.id,
            "type": r.scenario_type,
            "severity": r.severity,
            "headline": r.headline,
            "time": r.created_at.strftime("%H:%M"),
            "outcome": r.outcome,
            "target_symbol": r.target_symbol,
            "created_at": r.created_at,
        })
    return results


@router.post("/scenarios/inject", response_model=ScenarioRunResult)
async def inject_scenario(payload: ScenarioInjectRequest, db: Session = Depends(get_db)):
    """
    Inject a simulated shock scenario (CRASH, RALLY, MISLEADING_NEWS, LIQUIDITY_SHOCK)
    and pass it through the decision pipeline and Risk Gate.
    """
    res = await decision_pipeline.execute_pipeline(
        db=db,
        symbol=payload.symbol,
        scenario_type=payload.scenario,
        severity=payload.severity,
        auto_execute=True
    )

    exec_res = res.get("execution_result", {})
    quote = market_engine.get_quote(db, payload.symbol)
    actual_price = quote["price"] if quote else exec_res.get("price", 0.0)
    return ScenarioRunResult(
        scenario_id=res.get("scenario_id") or 1,
        scenario_type=payload.scenario,
        symbol=payload.symbol,
        severity=payload.severity,
        prior_price=actual_price,
        new_price=actual_price,
        price_change_pct=0.0,
        headline=res.get("proposal", {}).get("rationale", ""),
        status="COMPLETED",
        outcome=exec_res.get("outcome", "APPROVED"),
        order_id=exec_res.get("order_id"),
        order_status=exec_res.get("status"),
        reason=exec_res.get("reason", ""),
        time=exec_res.get("time", "12:00"),
        is_simulated=True,
        simulation_label="SIMULATED SCENARIO · ISOLATED FROM LIVE DATA"
    )


@router.post("/scenarios/{scenario_id}/run", response_model=ScenarioRunResult)
async def run_scenario_by_id(scenario_id: int, db: Session = Depends(get_db)):
    s = db.query(ScenarioRecord).filter(ScenarioRecord.id == scenario_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Scenario record not found.")

    res = await decision_pipeline.execute_pipeline(
        db=db,
        symbol=s.target_symbol,
        scenario_type=s.scenario_type,
        severity=s.severity,
        auto_execute=True
    )
    exec_res = res.get("execution_result", {})
    quote = market_engine.get_quote(db, s.target_symbol)
    actual_price = quote["price"] if quote else exec_res.get("price", 0.0)
    return ScenarioRunResult(
        scenario_id=s.id,
        scenario_type=s.scenario_type,
        symbol=s.target_symbol,
        severity=s.severity,
        prior_price=actual_price,
        new_price=actual_price,
        price_change_pct=0.0,
        headline=s.headline,
        status="COMPLETED",
        outcome=exec_res.get("outcome", "APPROVED"),
        order_id=exec_res.get("order_id"),
        order_status=exec_res.get("status"),
        reason=exec_res.get("reason", ""),
        time=exec_res.get("time", "12:00"),
        is_simulated=True,
        simulation_label="SIMULATED SCENARIO · ISOLATED FROM LIVE DATA"
    )
