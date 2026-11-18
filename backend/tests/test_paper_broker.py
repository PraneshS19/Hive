import pytest
from app.db.models import Account, LedgerEntry, Position
from app.execution.paper_broker import paper_broker


@pytest.fixture(autouse=True)
def mock_market_open_for_broker_math(monkeypatch):
    import app.execution.paper_broker as pb
    monkeypatch.setattr(pb, "is_market_session_active", lambda dt=None: (True, "Simulated market session active"))
    monkeypatch.setattr(pb.dhan_live_feed, "get_quote", lambda symbol: {
        "symbol": symbol, "price": 1211.70, "freshness_status": "LIVE",
    })


def test_successful_buy_execution_and_ledger(db):
    acc_before = db.query(Account).first()
    cash_before = acc_before.cash_balance

    pos_before = db.query(Position).filter(Position.symbol == "RELIANCE").first()
    qty_before = pos_before.quantity if pos_before else 0

    res = paper_broker.submit_and_process_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=50,
        price=1211.70,
        auto_execute=True
    )

    assert res["outcome"] in ("APPROVED", "RESIZED")
    assert res["executed"] > 0

    acc_after = db.query(Account).first()
    assert acc_after.cash_balance < cash_before

    pos_after = db.query(Position).filter(Position.symbol == "RELIANCE").first()
    assert pos_after is not None
    assert pos_after.quantity == qty_before + res["executed"]

    # Verify ledger entries
    ledger_entries = db.query(LedgerEntry).all()
    assert len(ledger_entries) >= 2


def test_rejected_order_leaves_portfolio_unchanged(db):
    acc_before = db.query(Account).first()
    cash_before = acc_before.cash_balance

    res = paper_broker.submit_and_process_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=50,
        price=1211.70,
        scenario_type="UNVERIFIED_RUMOR",
        auto_execute=True
    )

    assert res["outcome"] == "REJECTED"
    assert res["executed"] == 0

    acc_after = db.query(Account).first()
    assert acc_after.cash_balance == cash_before  # Cash unchanged!


def test_buy_slippage_and_fee_accounting(db):
    """
    Verifies that buying applies 0.05% slippage, 0.1% fee, updates position average entry
    to the fill price, and reconciles cash exactly.
    """
    from app.core.config import settings
    acc = db.query(Account).first()
    acc.cash_balance = 1000000.0
    db.query(Position).delete()
    db.commit()

    base_price = 1211.70
    expected_fill_price = round(base_price * (1.0 + settings.SLIPPAGE_PCT / 100.0), 2)  # 1212.31
    qty = 82

    expected_notional = round(qty * expected_fill_price, 2)  # 99409.42
    expected_fee = round(expected_notional * (settings.COMMISSION_PCT / 100.0), 2)  # 99.41
    expected_outflow = round(expected_notional + expected_fee, 2)  # 99508.83

    res = paper_broker.submit_and_process_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=qty,
        price=base_price,
        auto_execute=True
    )

    assert res["outcome"] == "APPROVED"
    assert res["executed"] == qty
    assert res["price"] == expected_fill_price
    assert res["fee"] == expected_fee

    acc_after = db.query(Account).first()
    assert round(acc_after.cash_balance, 2) == round(1000000.0 - expected_outflow, 2)

    pos = db.query(Position).filter(Position.symbol == "RELIANCE").first()
    assert pos is not None
    assert pos.quantity == qty
    assert pos.average_entry == expected_fill_price


def test_sell_slippage_and_realized_cash(db):
    """
    Verifies selling applies 0.05% downward slippage and deducts 0.1% fee on proceeds.
    """
    from app.core.config import settings
    acc = db.query(Account).first()
    acc.cash_balance = 500000.0
    db.query(Position).delete()
    pos = Position(account_id=acc.id, symbol="RELIANCE", quantity=100, average_entry=1200.00)
    db.add(pos)
    db.commit()

    base_price = 1211.70
    expected_fill_price = round(base_price * (1.0 - settings.SLIPPAGE_PCT / 100.0), 2)  # 1211.09
    sell_qty = 50

    expected_notional = round(sell_qty * expected_fill_price, 2)  # 60554.50
    expected_fee = round(expected_notional * (settings.COMMISSION_PCT / 100.0), 2)  # 60.55
    expected_inflow = round(expected_notional - expected_fee, 2)  # 60493.95

    res = paper_broker.submit_and_process_order(
        db=db,
        symbol="RELIANCE",
        side="SELL",
        requested_qty=sell_qty,
        price=base_price,
        auto_execute=True
    )

    assert res["outcome"] == "APPROVED"
    assert res["executed"] == sell_qty
    assert res["price"] == expected_fill_price
    assert res["fee"] == expected_fee

    acc_after = db.query(Account).first()
    assert round(acc_after.cash_balance, 2) == round(500000.0 + expected_inflow, 2)

    pos_after = db.query(Position).filter(Position.symbol == "RELIANCE").first()
    assert pos_after.quantity == 50


def test_duplicate_proposal_confirmation_rejected(db, monkeypatch):
    """
    Verifies that attempting to confirm an order a second time raises an OrderExecutionError.
    """
    import pytest
    from app.core.errors import OrderExecutionError
    acc = db.query(Account).first()
    acc.cash_balance = 1000000.0
    db.query(Position).delete()
    db.commit()

    from app.execution import paper_broker as broker_module

    monkeypatch.setattr(broker_module, "is_market_session_active", lambda: (True, "TEST_FIXTURE"))
    monkeypatch.setattr(broker_module.dhan_live_feed, "get_quote", lambda symbol: {
        "symbol": symbol, "price": 1211.7, "freshness_status": "LIVE",
    })

    # Stage order proposal without auto_execute
    res = paper_broker.submit_and_process_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=50,
        price=1211.70,
        auto_execute=False
    )
    assert res["status"] == "PROPOSAL"
    order_id = res["order_id"]

    # First confirmation execution succeeds
    exec_res = paper_broker.execute_staged_proposal(db, order_id)
    assert exec_res["status"] in ("APPROVED", "RESIZED")
    assert exec_res["executed"] == 50

    # Second confirmation attempt MUST raise OrderExecutionError
    with pytest.raises(OrderExecutionError) as exc_info:
        paper_broker.execute_staged_proposal(db, order_id)

    assert "duplicate execution rejected" in str(exc_info.value).lower() or "not 'proposal'" in str(exc_info.value).lower()

def test_open_market_without_quote_keeps_order_unfilled(db, monkeypatch):
    from app.market.dhan_adapter import dhan_live_feed

    monkeypatch.setattr(dhan_live_feed, "get_quote", lambda symbol: None)
    account = db.query(Account).first()
    cash_before = account.cash_balance
    ledger_before = db.query(LedgerEntry).count()

    result = paper_broker.submit_and_process_order(db, "RELIANCE", "BUY", 1, 100.0)

    assert result["status"] == "PROPOSAL"
    assert result["executed"] == 0
    assert account.cash_balance == cash_before
    assert db.query(LedgerEntry).count() == ledger_before


def test_paper_fill_retry_rejection_and_file_restart(tmp_path, monkeypatch):
    import app.db.init_db as initialization
    import app.db.session as database
    import app.execution.paper_broker as broker
    from app.main import app
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{(tmp_path / 'paper.sqlite3').as_posix()}")
    sessions = sessionmaker(bind=engine, autoflush=False)
    for module in (initialization, database):
        monkeypatch.setattr(module, "engine", engine)
        monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(broker, "is_market_session_active", lambda: (True, "TEST_FIXTURE"))
    monkeypatch.setattr(broker.dhan_live_feed, "get_quote", lambda symbol: {
        "symbol": symbol, "price": 100.0, "freshness_status": "LIVE",
    })
    order = {"symbol": "RELIANCE", "side": "BUY", "requested": 10, "price": 1.0}
    key = {"Idempotency-Key": "restart-buy"}
    try:
        with TestClient(app) as client:
            start_cash = client.get("/api/v1/portfolio").json()["cash"]
            result = client.post("/api/v1/orders", json=order, headers=key)
            assert result.status_code == 200, result.text
            fill = result.json()
            assert fill["price"] == 100.05 and fill["executed"] == 10
            before_reject = client.get("/api/v1/portfolio").json()
            ledger = client.get("/api/v1/ledger").json()
            rejected = client.post(
                "/api/v1/orders", json={**order, "side": "SELL", "requested": 11},
                headers={"Idempotency-Key": "restart-reject"},
            ).json()
            assert rejected["status"] == "REJECTED"
            assert client.get("/api/v1/portfolio").json()["cash"] == before_reject["cash"]
            assert client.get("/api/v1/portfolio").json()["positions"] == before_reject["positions"]
            assert client.get("/api/v1/ledger").json() == ledger
            assert before_reject["cash"] == round(start_cash - (fill["price"] * 10 + fill["fee"]), 2)

        engine.dispose()
        with TestClient(app) as client:
            replay = client.post("/api/v1/orders", json=order, headers=key)
            assert replay.status_code == 200, replay.text
            assert replay.json()["id"] == fill["id"]
            assert len(client.get("/api/v1/executions").json()) == 1
            assert client.get("/api/v1/portfolio").json()["cash"] == before_reject["cash"]
    finally:
        engine.dispose()


def test_rest_response_timestamp_alone_cannot_authorize_fill(monkeypatch):
    from datetime import UTC, datetime

    import app.execution.paper_broker as broker

    quote = {"source": "0XRAMM_REST_V3", "price": 100, "freshness_status": "LIVE",
             "provider_timestamp": datetime.now(UTC).isoformat()}
    monkeypatch.setattr(broker.dhan_live_feed, "get_quote", lambda symbol: quote)
    assert broker.executable_quote_price("RELIANCE") is None
    quote["market_timestamp"] = datetime.now(UTC).isoformat()
    assert broker.executable_quote_price("RELIANCE") == 100
