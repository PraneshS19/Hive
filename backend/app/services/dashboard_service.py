import json
from typing import Any

from app.db.models import AgentRun, ScenarioRecord
from app.market.dhan_adapter import dhan_live_feed
from app.portfolio.service import portfolio_service
from app.schemas.agents import AgentRoleCard
from sqlalchemy import func, select
from sqlalchemy.orm import Session

SPECIALIST_ROLES = (
    "Market Analyst", "Sentiment Analyst", "Quantitative Alpha",
    "Macro Strategist", "Institutional Risk", "Portfolio Manager",
)


def specialist_cards(db: Session) -> list[AgentRoleCard]:
    ranked = select(
        AgentRun.id,
        func.row_number().over(
            partition_by=AgentRun.role, order_by=(AgentRun.created_at.desc(), AgentRun.id.desc()),
        ).label("rank"),
    ).where(AgentRun.role.in_(SPECIALIST_ROLES)).subquery()
    records = db.scalars(select(AgentRun).join(ranked, ranked.c.id == AgentRun.id).where(ranked.c.rank == 1))
    latest = {record.role: record for record in records}
    cards = []
    for role in SPECIALIST_ROLES:
        record = latest.get(role)
        if record is None:
            cards.append(AgentRoleCard(
                name=role, status="Idle", value="", text="No recorded execution.",
                execution_mode="idle", provider=None, model=None,
            ))
            continue
        try:
            metadata = json.loads(record.output_json or "{}")
            if not isinstance(metadata, dict):
                metadata = {}
        except json.JSONDecodeError:
            metadata = {}
        cards.append(AgentRoleCard(
            name=role, status="Complete" if record.status == "COMPLETED" else record.status,
            value=record.value, text=record.summary, execution_mode=record.execution_mode,
            provider=metadata.get("provider"), model=metadata.get("model"),
            latency_ms=metadata.get("latency_ms"),
        ))
    return cards


class DashboardService:
    def get_summary(self, db: Session) -> dict[str, Any]:
        # 1. Authoritative portfolio metrics & history
        port = portfolio_service.get_portfolio_summary(db)

        # 2. Watchlist strictly from authoritative Dhan live feed
        quotes = dhan_live_feed.get_watchlist()

        agents = [card.model_dump() for card in specialist_cards(db)]

        # 4. Recent activity from scenarios
        scenarios = db.query(ScenarioRecord).order_by(ScenarioRecord.created_at.desc()).limit(5).all()
        activity = []
        for s in scenarios:
            activity.append({
                "id": s.id,
                "type": s.scenario_type,
                "severity": s.severity,
                "headline": s.headline,
                "time": s.created_at.strftime("%H:%M"),
                "outcome": s.outcome,
                "target_symbol": s.target_symbol,
                "created_at": s.created_at,
            })

        return {
            "metrics": port["metrics"],
            "equity_curve": port["history"],
            "watchlist": quotes,
            "agents": agents,
            "recent_activity": activity,
            "running": False,
        }


dashboard_service = DashboardService()
