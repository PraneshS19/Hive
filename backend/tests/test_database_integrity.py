from datetime import timedelta

import pytest
from app.core.errors import OrderExecutionError
from app.db.base import Base, enforce_sqlite_foreign_keys
from app.db.init_db import init_db
from app.db.models import Account, Execution, LedgerEntry, Order, RiskDecision
from app.execution import paper_broker as broker
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_sqlite_enforces_foreign_keys_on_new_connections(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'hive.db').as_posix()}")
    enforce_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    engine.dispose()
    with Session(engine) as db:
        assert db.scalar(text("PRAGMA foreign_keys")) == 1
        db.add(RiskDecision(order_id=91, outcome="REJECTED", evaluated_qty=1, approved_qty=0))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_new_order_keeps_orphaned_decisions_detached(tmp_path):
    url = f"sqlite:///{(tmp_path / 'previous.db').as_posix()}"
    # Reproduce historical data written before the application enforced the constraint.
    legacy = create_engine(url)
    Base.metadata.create_all(legacy)
    with Session(legacy) as db:
        db.add(RiskDecision(order_id=17, outcome="REJECTED", evaluated_qty=1, approved_qty=0))
        db.commit()
    legacy.dispose()

    current = create_engine(url)
    enforce_sqlite_foreign_keys(current)
    with Session(current) as db:
        init_db(db)
        original = db.execute(text("PRAGMA foreign_key_check")).all()
        assert original == [("risk_decisions", 1, "orders", 0)]
        result = broker.paper_broker.submit_and_process_order(db, "RELIANCE", "BUY", 1, 100.0, auto_execute=False)
        assert result["order_id"] == 18
        assert db.get(RiskDecision, 1).order_id == 17
        assert db.execute(text("PRAGMA foreign_key_check")).all() == original
    current.dispose()


def test_confirmation_ignores_decisions_older_than_order(db, monkeypatch):
    monkeypatch.setattr(broker, "is_market_session_active", lambda: (True, "TEST_FIXTURE"))
    monkeypatch.setattr(broker, "executable_quote_price", lambda _symbol: 100.0)
    result = broker.paper_broker.submit_and_process_order(db, "RELIANCE", "BUY", 3, 100.0, auto_execute=False)
    order = db.get(Order, result["order_id"])
    db.add(RiskDecision(
        id=-1, order_id=order.id, outcome="APPROVED", evaluated_qty=1, approved_qty=1,
        timestamp=order.created_at - timedelta(days=1),
    ))
    db.commit()
    assert broker.paper_broker.execute_staged_proposal(db, order.id)["executed"] == 3
    assert db.execute(text("PRAGMA foreign_key_check")).all() == []


def test_confirmation_without_linked_approval_cannot_settle(db):
    result = broker.paper_broker.submit_and_process_order(db, "RELIANCE", "BUY", 3, 100.0, auto_execute=False)
    db.query(RiskDecision).delete()
    db.commit()
    with pytest.raises(OrderExecutionError, match="no applicable approving risk decision"):
        broker.paper_broker.execute_staged_proposal(db, result["order_id"])
    db.rollback()
    assert db.get(Order, result["order_id"]).executed == 0
    assert db.query(Execution).count() == 0


def test_unknown_order_symbol_cannot_create_orphans(client, db):
    cash_before = db.query(Account).one().cash_balance
    ledger_before = db.query(LedgerEntry).count()
    response = client.post("/api/v1/orders", headers={"Idempotency-Key": "unknown-symbol-test"}, json={
        "symbol": "NOTLISTED", "side": "BUY", "requested": 1, "price": 100.0, "auto_execute": False,
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown instrument."
    assert db.query(Order).count() == db.query(RiskDecision).count() == 0
    assert db.query(Account).one().cash_balance == cash_before
    assert db.query(LedgerEntry).count() == ledger_before
    assert db.execute(text("PRAGMA foreign_key_check")).all() == []
