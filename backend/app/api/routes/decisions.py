import json

from app.api.dependencies import get_db
from app.db.models import DecisionPipelineRun
from app.decisions.pipeline import decision_pipeline
from app.schemas.decisions import DecisionPipelineResponse, DecisionPipelineRunRequest
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

router = APIRouter()


@router.post("/decisions/run", response_model=DecisionPipelineResponse)
async def run_decision_pipeline(payload: DecisionPipelineRunRequest, db: Session = Depends(get_db)):
    """Run full Reasoned decision pipeline with persisted stages and auditable states."""
    res = await decision_pipeline.execute_pipeline(
        db=db,
        symbol=payload.symbol,
        scenario_type=payload.scenario_type,
        severity=payload.severity if payload.severity else 60.0,
        auto_execute=payload.auto_execute if payload.auto_execute is not None else True
    )
    return res


def _extract_execution_mode(stages: list) -> str:
    for s in stages:
        if s.get("name") == "Portfolio Proposal" and isinstance(s.get("details"), dict) and s["details"].get("execution_mode"):
            return s["details"]["execution_mode"]
        if s.get("name") == "Specialist Analysis" and isinstance(s.get("details"), dict):
            for agent_data in s["details"].values():
                if isinstance(agent_data, dict) and agent_data.get("execution_mode"):
                    return agent_data["execution_mode"]
    return "deterministic_fallback"


@router.get("/decisions", response_model=list[DecisionPipelineResponse])
@router.get("/decisions/history", response_model=list[DecisionPipelineResponse])
def get_decisions(db: Session = Depends(get_db)):
    runs = db.query(DecisionPipelineRun).order_by(DecisionPipelineRun.created_at.desc()).limit(10).all()
    results = []
    for r in runs:
        try:
            stages = json.loads(r.stages_json)
        except (TypeError, ValueError):
            stages = []
        exec_mode = _extract_execution_mode(stages)
        results.append(DecisionPipelineResponse(
            run_id=r.id,
            symbol=r.symbol,
            scenario_id=r.scenario_id,
            status=r.status,
            current_stage=r.current_stage,
            stages=stages,
            proposal=None,
            risk_decision=None,
            execution_result=None,
            execution_mode=exec_mode,
            created_at=r.created_at,
            completed_at=r.completed_at
        ))
    return results


@router.get("/decisions/{run_id}", response_model=DecisionPipelineResponse)
def get_decision_by_id(run_id: str, db: Session = Depends(get_db)):
    r = db.query(DecisionPipelineRun).filter(DecisionPipelineRun.id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Pipeline run not found.")
    try:
        stages = json.loads(r.stages_json)
    except (TypeError, ValueError):
        stages = []
    exec_mode = _extract_execution_mode(stages)
    return DecisionPipelineResponse(
        run_id=r.id,
        symbol=r.symbol,
        scenario_id=r.scenario_id,
        status=r.status,
        current_stage=r.current_stage,
        stages=stages,
        proposal=None,
        risk_decision=None,
        execution_result=None,
        execution_mode=exec_mode,
        created_at=r.created_at,
        completed_at=r.completed_at
    )
