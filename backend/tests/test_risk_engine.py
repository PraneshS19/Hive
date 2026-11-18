from app.risk.engine import risk_engine


def test_unverified_rumor_rejected_by_risk_gate(db):
    res = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=100,
        price=1211.70,
        scenario_type="UNVERIFIED_RUMOR"
    )
    assert res["outcome"] == "REJECTED"
    assert "unverified headline" in res["reason"].lower()
    assert res["approved_qty"] == 0


def test_oversized_order_resized_to_10_percent(db):
    # Total equity is 1,000,000. 10% order limit = 100,000.
    # INFY price is ~1160.35.
    # Requesting 200 units (~₹232,070) exceeds 10% limit (₹100,000) and will be resized!
    res = risk_engine.evaluate_order(
        db=db,
        symbol="INFY",
        side="BUY",
        requested_qty=200,
        price=1160.35,
    )
    assert res["outcome"] == "RESIZED"
    assert res["approved_qty"] < 200
    assert res["approved_qty"] * 1160.35 <= 101000.0  # ~10% limit


def test_short_selling_prohibited(db):
    # With 0 existing position, attempting to sell should fail.
    res = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="SELL",
        requested_qty=10,
        price=1211.70,
    )
    assert res["outcome"] == "REJECTED"
    assert "short selling" in res["reason"].lower()


def test_cash_insufficiency_rejected(db):
    # Requesting order that exceeds cash should be rejected
    from app.db.models import Account
    acc = db.query(Account).first()
    acc.cash_balance = 500.0
    db.commit()

    res = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=100,
        price=1211.70,
    )
    assert res["outcome"] == "REJECTED"
    assert "insufficient cash" in res["reason"].lower()


def test_exact_10_percent_single_order_limit_boundary(db):
    """
    Empirically verifies the authoritative 10% single-order limit at exact boundaries.
    With ₹1,000,000 equity, the maximum single-order notional is ₹100,000.
    At RELIANCE price ₹1,211.70 with 0.05% BUY slippage, fill price is ₹1,212.31:
    - 82 shares * ₹1,212.31 = ₹99,409.42 (<= ₹100,000) -> APPROVED
    - 83 shares * ₹1,212.31 = ₹100,621.73 (> ₹100,000) -> RESIZED to 82
    - 150 shares -> RESIZED to 82
    """
    from app.db.models import Account, Position
    acc = db.query(Account).first()
    acc.cash_balance = 1000000.0
    db.query(Position).delete()
    db.commit()

    # 1. Below limit (50 shares)
    res_50 = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=50,
        price=1211.70,
    )
    assert res_50["outcome"] == "APPROVED"
    assert res_50["approved_qty"] == 50
    assert res_50["fill_price"] == 1212.31
    assert 50 * res_50["fill_price"] <= 100000.0

    # 2. At boundary limit (82 shares)
    res_82 = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=82,
        price=1211.70,
    )
    assert res_82["outcome"] == "APPROVED"
    assert res_82["approved_qty"] == 82
    assert res_82["fill_price"] == 1212.31
    assert 82 * res_82["fill_price"] <= 100000.0
    assert 82 * res_82["fill_price"] == 99409.42

    # 3. Exceeding boundary by 1 share (83 shares)
    res_83 = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=83,
        price=1211.70,
    )
    assert res_83["outcome"] == "RESIZED"
    assert res_83["approved_qty"] == 82
    assert res_83["approved_qty"] * res_83["fill_price"] <= 100000.0

    # 4. Large order (150 shares)
    res_150 = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=150,
        price=1211.70,
    )
    assert res_150["outcome"] == "RESIZED"
    assert res_150["approved_qty"] == 82
    assert res_150["approved_qty"] * res_150["fill_price"] <= 100000.0


def test_llm_recommendation_cannot_bypass_risk_limit(db):
    """
    Verifies that even if an LLM recommendation instructs an aggressive allocation of 120 units,
    the deterministic risk gate independently enforces the 10% equity ceiling.
    """
    from app.db.models import Account, Position
    acc = db.query(Account).first()
    acc.cash_balance = 1000000.0
    db.query(Position).delete()
    db.commit()

    res = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=120,
        price=1211.70,
    )
    assert res["outcome"] == "RESIZED"
    assert res["approved_qty"] == 82
    assert res["approved_qty"] * res["fill_price"] <= 100000.0


def test_drawdown_circuit_breaker_threshold_boundaries(db):
    """
    Empirically verifies the 10.0% drawdown circuit breaker at exact boundaries:
    1. Below threshold (9.9% drawdown): BUY orders permitted.
    2. At threshold (10.0% drawdown): BUY orders strictly blocked.
    3. Above threshold (10.1% drawdown): BUY orders strictly blocked.
    4. Under drawdown halt (15.0% drawdown): Risk-off SELL orders remain strictly permitted.
    """
    from app.db.models import Account, Position
    acc = db.query(Account).first()
    acc.starting_cash = 1000000.0
    db.query(Position).delete()

    # 1. Just below threshold: Drawdown = 9.9% (Equity = 901,000.0)
    acc.cash_balance = 901000.0
    db.commit()

    res_below = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=10,
        price=1200.0
    )
    assert res_below["outcome"] == "APPROVED"
    assert res_below["approved_qty"] == 10

    # 2. Exactly at threshold: Drawdown = 10.0% (Equity = 900,000.0)
    acc.cash_balance = 900000.0
    db.commit()

    res_at = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=10,
        price=1200.0
    )
    assert res_at["outcome"] == "REJECTED"
    assert "exceeds safety threshold (10.0%)" in res_at["reason"]
    assert "new buy orders halted" in res_at["reason"].lower()
    assert res_at["approved_qty"] == 0

    # 3. Above threshold: Drawdown = 10.1% (Equity = 899,000.0)
    acc.cash_balance = 899000.0
    db.commit()

    res_above = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=10,
        price=1200.0
    )
    assert res_above["outcome"] == "REJECTED"
    assert "exceeds safety threshold (10.0%)" in res_above["reason"]
    assert res_above["approved_qty"] == 0

    # 4. Under deep drawdown (15.0%), risk-off liquidation (SELL) is permitted
    acc.cash_balance = 850000.0
    pos = Position(
        account_id=acc.id,
        symbol="RELIANCE",
        quantity=50,
        average_entry=1200.0
    )
    db.add(pos)
    db.commit()

    res_sell = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="SELL",
        requested_qty=50,
        price=1200.0
    )
    assert res_sell["outcome"] == "APPROVED"
    assert res_sell["approved_qty"] == 50
    # Rule 6 explicitly verified risk-off liquidation permission
    r6 = next((r for r in res_sell["rule_results"] if "drawdown halt" in r["rule_name"].lower()), None)
    assert r6 is not None
    assert r6["passed"] is True
    assert "liquidations permitted" in r6["description"].lower()
