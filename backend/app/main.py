from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import HiveError
from app.core.logging import logger
from app.db import session
from app.db.init_db import init_db
from app.review.operations import mark_interrupted_runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and seed default records
    logger.info("Initializing HIVE database and baseline data...")
    init_db(seed_historical=True)
    with session.SessionLocal() as db:
        mark_interrupted_runs(db, "Research was interrupted by a backend restart. Recorded evidence remains available.")

    # Start active market feed if configured and enabled
    try:
        from app.market.dhan_adapter import dhan_live_feed
        dhan_live_feed.start()
    except (ImportError, RuntimeError, OSError) as e:
        logger.warning(f"Could not automatically start market feed at startup: {e}")

    logger.info("HIVE backend startup complete.")
    yield
    # Shutdown
    logger.info("HIVE backend shutting down.")
    try:
        from app.market.dhan_adapter import dhan_live_feed
        dhan_live_feed.stop()
    except (ImportError, RuntimeError, OSError):
        pass


app = FastAPI(
    title=settings.APP_NAME,
    description="HIVE — AI-Assisted Intelligence for Smarter Financial Decisions. Paper trading only.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
origins = settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [settings.CORS_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom exception handler for HIVE application errors
@app.exception_handler(HiveError)
async def hive_exception_handler(request: Request, exc: HiveError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "error_code": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )


# Include API v1 router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {
        "app": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "version": "1.0.0",
        "api_docs": "/docs",
        "status": "online",
        "note": "Simulation and educational paper-trading environment only.",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
