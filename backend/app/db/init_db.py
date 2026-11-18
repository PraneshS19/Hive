import os

from app.core.config import settings
from app.core.logging import logger
from app.db.base import Base
from app.db.models import (
    Account,
    AgentRun,
    Asset,
    DecisionPipelineRun,
    EquitySnapshot,
    EvidenceSnapshotRecord,
    Execution,
    LedgerEntry,
    MarketEventRecord,
    Order,
    PaperTradeProposal,
    Position,
    Quote,
    RiskConfig,
    RiskDecision,
    ScenarioRecord,
)
from app.db.models.order import OrderSubmission
from app.db.session import SessionLocal, engine
from app.market.dhan_adapter import INITIAL_INSTRUMENT_CATALOG
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

HISTORICAL_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "historical")


def init_db(db: Session | None = None, seed_historical: bool = False) -> None:
    """
    Initialize database schema and seed reference instrument metadata and primary account.
    In LIVE_ONLY mode: strictly zero historical candle imports or fake/stale quote seedings.
    """
    bind_engine = db.get_bind() if db is not None else engine
    inspector = inspect(bind_engine)
    if "candles" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("candles")]
        if "dataset_id" not in columns:
            with bind_engine.connect() as conn:
                conn.execute(text("ALTER TABLE candles ADD COLUMN dataset_id VARCHAR(64)"))
                conn.commit()
    if "prompt_versions" in inspector.get_table_names():
        p_columns = [col["name"] for col in inspector.get_columns("prompt_versions")]
        if "prompt_hash" not in p_columns:
            with bind_engine.connect() as conn:
                conn.execute(text("ALTER TABLE prompt_versions ADD COLUMN prompt_hash VARCHAR(64)"))
                conn.commit()
    if "quotes" in inspector.get_table_names():
        q_columns = [col["name"] for col in inspector.get_columns("quotes")]
        with bind_engine.connect() as conn:
            if "price_type" not in q_columns:
                conn.execute(text("ALTER TABLE quotes ADD COLUMN price_type VARCHAR(50) DEFAULT 'LAST_OBSERVED_PRICE'"))
            if "observation_timestamp" not in q_columns:
                conn.execute(text("ALTER TABLE quotes ADD COLUMN observation_timestamp DATETIME"))
            if "source" not in q_columns:
                conn.execute(text("ALTER TABLE quotes ADD COLUMN source VARCHAR(80) DEFAULT '0XRAMM_REST_V3'"))
            if "freshness_status" not in q_columns:
                conn.execute(text("ALTER TABLE quotes ADD COLUMN freshness_status VARCHAR(50) DEFAULT 'MARKET_CLOSED'"))
            if "market_status" not in q_columns:
                conn.execute(text("ALTER TABLE quotes ADD COLUMN market_status VARCHAR(30) DEFAULT 'CLOSED'"))
            conn.commit()

    Base.metadata.create_all(bind=bind_engine)

    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        # 2. Register static instrument metadata from the authoritative 30 NSE catalog
        # Reference metadata only (symbol, name, sector, currency) — NOT market prices
        for item in INITIAL_INSTRUMENT_CATALOG:
            sym = item["symbol"]
            asset = db.query(Asset).filter(Asset.symbol == sym).first()
            if not asset:
                asset = Asset(
                    symbol=sym,
                    name=item["name"],
                    sector=item.get("type", "EQUITY"),
                    currency="INR",
                    is_active=True,
                )
                db.add(asset)
        db.flush()

        # 3. HISTORICAL_RESEARCH Data Store Initialization:
        # Seed verified historical datasets for Backtest Studio if explicitly requested and not already registered.
        # Strictly separated from LIVE mode: does NOT write to Quote store or live tick cache.
        if seed_historical:
            from app.db.seed_historical import seed_verified_historical_datasets
            try:
                seed_verified_historical_datasets(db)
            except (TypeError, ValueError, OSError, RuntimeError, SQLAlchemyError) as seed_err:
                logger.warning(f"Historical dataset seeding notice: {seed_err}")

        # In LIVE_ONLY mode: authoritative live quote cache remains clean of historical backfills
        db.query(Quote).delete()
        db.commit()

        # 4. Primary Simulation Account
        account = db.query(Account).first()
        if not account:
            account = Account(
                name="Primary Simulation Account",
                starting_cash=settings.INITIAL_EQUITY,
                cash_balance=settings.INITIAL_EQUITY,
                currency="INR",
            )
            db.add(account)
            db.flush()

            ledger = LedgerEntry(
                account_id=account.id,
                transaction_type="DEPOSIT",
                amount=settings.INITIAL_EQUITY,
                balance_after=settings.INITIAL_EQUITY,
                description="Initial virtual capital funding for simulation",
                reference_id="SEED_INIT",
            )
            db.add(ledger)

        # 5. Risk Configuration
        risk_cfg = db.query(RiskConfig).first()
        if not risk_cfg:
            risk_cfg = RiskConfig(
                fee_pct=settings.TRANSACTION_FEE_PCT,
                max_order_pct=settings.MAX_ORDER_PCT,
                max_allocation_pct=settings.MAX_ALLOCATION_PCT,
                drawdown_halt_pct=settings.MAX_DRAWDOWN_PCT,
                auto_execute=settings.AUTO_EXECUTE,
            )
            db.add(risk_cfg)

        db.commit()

        # 6. Versioned Prompt Lifecycle Initialization
        from app.review.prompt_lifecycle import init_prompt_versions
        init_prompt_versions(db)

        logger.info("HIVE database initialization complete.")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        if close_session:
            db.close()


def reset_simulation(db: Session) -> None:
    """
    Reset paper trading state back to clean baseline:
    Zero holdings, zero orders, zero proposals, ₹10,00,000 cash balance.
    Preserves verified historical datasets for Backtest Studio and PIT Replay.
    """
    db.query(OrderSubmission).delete()
    db.query(RiskDecision).delete()
    db.query(Execution).delete()
    db.query(Order).delete()
    db.query(DecisionPipelineRun).delete()
    db.query(AgentRun).delete()
    db.query(ScenarioRecord).delete()
    db.query(Position).delete()
    db.query(EquitySnapshot).delete()
    db.query(PaperTradeProposal).delete()
    db.query(MarketEventRecord).delete()
    db.query(EvidenceSnapshotRecord).delete()
    db.query(Quote).delete()

    account = db.query(Account).first()
    if account:
        account.cash_balance = settings.INITIAL_EQUITY
        account.starting_cash = settings.INITIAL_EQUITY

        # Clean ledger except for initial funding
        db.query(LedgerEntry).filter(LedgerEntry.account_id == account.id).delete()
        ledger = LedgerEntry(
            account_id=account.id,
            transaction_type="DEPOSIT",
            amount=settings.INITIAL_EQUITY,
            balance_after=settings.INITIAL_EQUITY,
            description="Initial virtual capital funding for simulation",
            reference_id="SEED_INIT",
        )
        db.add(ledger)

    # Restore authoritative risk limits to clean defaults (10% single-order limit)
    risk_cfg = db.query(RiskConfig).first()
    if risk_cfg:
        risk_cfg.fee_pct = settings.TRANSACTION_FEE_PCT
        risk_cfg.max_order_pct = settings.MAX_ORDER_PCT
        risk_cfg.max_allocation_pct = settings.MAX_ALLOCATION_PCT
        risk_cfg.drawdown_halt_pct = settings.MAX_DRAWDOWN_PCT
        risk_cfg.auto_execute = settings.AUTO_EXECUTE

    db.commit()
    logger.info("Simulation successfully reset to baseline clean state with zero holdings and live-only enforcement.")
