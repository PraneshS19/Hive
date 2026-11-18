from app.api.routes import (
    agents,
    backtests,
    config_route,
    dashboard,
    datasets,
    decisions,
    dhan,
    health,
    market_data,
    orders,
    portfolio,
    proposals,
    review,
    risk,
    scenarios,
    stream,
)
from app.api.routes import (
    settings as settings_route,
)
from fastapi import APIRouter

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health"])
api_router.include_router(config_route.router, tags=["Config"])
api_router.include_router(dashboard.router, tags=["Dashboard"])
api_router.include_router(market_data.router, tags=["Market Data"])
api_router.include_router(scenarios.router, tags=["Scenarios"])
api_router.include_router(agents.router, tags=["Agents"])
api_router.include_router(decisions.router, tags=["Decisions"])
api_router.include_router(portfolio.router, tags=["Portfolio"])
api_router.include_router(risk.router, tags=["Risk"])
api_router.include_router(orders.router, tags=["Orders"])
api_router.include_router(backtests.router, tags=["Backtesting"])
api_router.include_router(datasets.router, tags=["Historical Datasets"])
api_router.include_router(settings_route.router, tags=["Settings"])
api_router.include_router(stream.router, tags=["Streaming"])
api_router.include_router(review.router, tags=["AI Review & Improvement"])
api_router.include_router(review.router, prefix="/review", tags=["AI Review & Improvement (Prefixed)"])
api_router.include_router(dhan.router, prefix="/dhan", tags=["DhanHQ Live Feed"])
api_router.include_router(proposals.router, tags=["Paper Trade Proposals"])
