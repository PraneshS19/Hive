import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.agents.orchestrator import agent_orchestrator
from app.core.config import settings
from app.db.models import DecisionPipelineRun, ScenarioRecord
from app.execution.paper_broker import paper_broker
from app.market.scenarios import calculate_scenario_effect
from app.portfolio.service import portfolio_service
from sqlalchemy.orm import Session


class DecisionPipelineEngine:
    """
    Reasoned decision pipeline state machine.
    Sequences:
    Stage 1: Market Data
    Stage 2: Specialist Analysis
    Stage 3: Portfolio Proposal
    Stage 4: Risk Gate
    Stage 5: Simulated Execution
    """

    async def execute_pipeline(
        self,
        db: Session,
        symbol: str = "RELIANCE",
        scenario_type: str | None = None,
        severity: float = 60.0,
        auto_execute: bool = True
    ) -> dict[str, Any]:
        run_id = f"DEC_{uuid.uuid4().hex[:10]}"
        symbol = symbol.upper()
        now = datetime.now(UTC)

        # 1. Authoritative market quote strictly from live feed
        scenario_id = None
        headline = None
        from app.market.dhan_adapter import dhan_live_feed
        quote = dhan_live_feed.get_quote(symbol)
        if not quote or quote.get("price") is None:
            provider_name = getattr(settings, "MARKET_DATA_PROVIDER", "0xramm_yahoo_rest")
            raise ValueError(
                f"Live analysis unavailable for '{symbol}': no verified live market observation received from provider ({provider_name}). "
                f"SYNQ is operating in LIVE_ONLY mode. Live analysis requires an active live feed session."
            )
        current_price = quote["price"]

        if scenario_type:
            _, _, headline = calculate_scenario_effect(scenario_type, severity, current_price)
            scenario_rec = ScenarioRecord(
                scenario_type=scenario_type,
                name=f"{scenario_type} Replay",
                headline=headline,
                severity=severity,
                target_symbol=symbol,
                status="COMPLETED",
                outcome="APPROVED",
                created_at=now
            )
            db.add(scenario_rec)
            db.flush()
            scenario_id = scenario_rec.id

        stages: list[dict[str, Any]] = []

        # Stage 1: Market Data
        live_ticks = dhan_live_feed.get_live_ticks(symbol)
        if len(live_ticks) >= 20:
            import numpy as np
            indicators = {
                "symbol": symbol,
                "status": "CALCULATED_FROM_LIVE_SESSION",
                "observations_count": len(live_ticks),
                "sma_20": round(float(np.mean(live_ticks[-20:])), 2),
                "sma_50": round(float(np.mean(live_ticks[-50:])), 2) if len(live_ticks) >= 50 else None,
            }
        else:
            indicators = {
                "symbol": symbol,
                "status": "WARMING_UP",
                "observations_count": len(live_ticks),
                "required_observations": 20,
                "sma_20": None,
                "sma_50": None,
            }
        stages.append({
            "name": "Market Data",
            "state": "done",
            "summary": f"Live quotes and indicators computed for {symbol} (₹{current_price:,.2f}).",
            "details": indicators,
        })

        # Stage 2: Specialist Analysis
        agent_res = await agent_orchestrator.run_multi_agent_analysis(
            db=db,
            symbol=symbol,
            pipeline_run_id=run_id,
            scenario_type=scenario_type,
            headline=headline,
            severity=severity
        )
        stages.append({
            "name": "Specialist Analysis",
            "state": "done",
            "summary": (
                f"Multi-Agent Committee: Market ({agent_res['market_analyst']['value']}), "
                f"Sentiment ({agent_res['sentiment_analyst']['value']}), "
                f"Quant Alpha ({agent_res['quant_analyst']['value']}), "
                f"Macro ({agent_res['macro_analyst']['value']}), "
                f"Risk ({agent_res['risk_officer']['value']})."
            ),
            "details": {
                "market": agent_res["market_analyst"],
                "sentiment": agent_res["sentiment_analyst"],
                "quant": agent_res["quant_analyst"],
                "macro": agent_res["macro_analyst"],
                "risk": agent_res["risk_officer"],
            }
        })

        # Stage 3: Portfolio Proposal
        proposal = agent_res["portfolio_manager"]
        action = proposal["action"]
        requested_qty = proposal["target_quantity"]
        stages.append({
            "name": "Portfolio Proposal",
            "state": "done",
            "summary": proposal["summary"],
            "details": proposal,
        })

        # Check database risk config for auto_execute policy
        from app.db.models import RiskConfig
        risk_cfg = db.query(RiskConfig).first()
        effective_auto_execute = auto_execute
        if risk_cfg is not None and not risk_cfg.auto_execute:
            effective_auto_execute = False

        # Stage 4: Risk Gate
        # Independent validation before execution
        broker_res = paper_broker.submit_and_process_order(
            db=db,
            symbol=symbol,
            side=action if action != "HOLD" else "BUY",
            requested_qty=requested_qty if action != "HOLD" else 1,
            price=current_price,
            scenario_type=scenario_type,
            auto_execute=effective_auto_execute and (action != "HOLD"),
            reason=f"Pipeline {run_id} execution"
        )

        risk_outcome = broker_res["outcome"]
        risk_passed = risk_outcome in ("APPROVED", "RESIZED")

        stages.append({
            "name": "Risk Gate",
            "state": "done" if risk_passed else "bad",
            "summary": broker_res["reason"],
            "details": broker_res["risk_decision"],
        })

        # Update scenario record outcome
        if scenario_id:
            s_rec = db.query(ScenarioRecord).filter(ScenarioRecord.id == scenario_id).first()
            if s_rec:
                s_rec.outcome = risk_outcome
                db.flush()

        # Stage 5: Simulated Execution
        if not risk_passed:
            stages.append({
                "name": "Simulated Execution",
                "state": "bad",
                "summary": "Execution blocked: risk gate rejected proposal.",
                "details": {"status": "BLOCKED", "order_id": broker_res["order_id"]},
            })
            pipeline_status = "rejected"
        elif action == "HOLD":
            stages.append({
                "name": "Simulated Execution",
                "state": "idle",
                "summary": "No order executed: portfolio hold recommended.",
                "details": {"status": "HOLD"},
            })
            pipeline_status = "completed"
        elif scenario_type:
            stages.append({
                "name": "Simulated Execution",
                "state": "simulated",
                "summary": f"Simulated Scenario Replay ({scenario_type}): Order #{broker_res['order_id']} staged as SIMULATED_SCENARIO. Real portfolio cash and holdings remain isolated and untouched.",
                "details": {"order_id": broker_res["order_id"], "status": "SIMULATED_SCENARIO", "is_simulated": True},
            })
            pipeline_status = "completed"
        elif effective_auto_execute and broker_res.get("executed", 0) > 0:
            stages.append({
                "name": "Simulated Execution",
                "state": "done",
                "summary": f"Executed {broker_res['executed']} units {action} {symbol} @ ₹{current_price:,.2f} via PaperBrokerService.",
                "details": {"order_id": broker_res["order_id"], "execution_id": broker_res["execution_id"]},
            })
            pipeline_status = "completed"
        else:
            stages.append({
                "name": "Simulated Execution",
                "state": "idle",
                "summary": f"Order #{broker_res['order_id']} staged as PROPOSAL awaiting manual human confirmation.",
                "details": {"order_id": broker_res["order_id"], "status": "PROPOSAL"},
            })
            pipeline_status = "completed"

        # Record equity snapshot after pipeline execution
        portfolio_service.record_snapshot(db)

        # Persist decision pipeline run
        pipeline_rec = DecisionPipelineRun(
            id=run_id,
            scenario_id=scenario_id,
            symbol=symbol,
            status=pipeline_status,
            current_stage=stages[-1]["name"],
            stages_json=json.dumps(stages),
            summary=proposal["summary"],
            created_at=now,
            completed_at=datetime.now(UTC)
        )
        db.add(pipeline_rec)
        db.commit()

        return {
            "run_id": run_id,
            "symbol": symbol,
            "scenario_id": scenario_id,
            "status": pipeline_status,
            "current_stage": stages[-1]["name"],
            "stages": stages,
            "proposal": proposal,
            "risk_decision": broker_res["risk_decision"],
            "execution_result": broker_res,
            "execution_mode": agent_res["portfolio_manager"]["execution_mode"],
            "created_at": now,
            "completed_at": datetime.now(UTC)
        }


decision_pipeline = DecisionPipelineEngine()
