from app.execution.paper_proposals import PaperProposalService, paper_proposal_service


def test_proposal_creation_10pct_limit(db):
    # Starting equity: 1,000,000 cash, 0 positions.
    # 10% limit = 100,000 max single order.
    proposal = paper_proposal_service.create_proposal_from_analysis(
        run_id="RUN_TEST_1",
        symbol="RELIANCE",
        side="BUY",
        price=1200.0,
        reason="Momentum breakout on verified earnings",
        target_allocation_pct=8.0 # 8% = ~80,000
    )

    assert proposal["status"] == "PENDING_CONFIRMATION"
    assert proposal["risk_check_passed"] is True
    assert proposal["estimated_notional"] <= 100000.0
    assert proposal["requested_qty"] > 0

def test_proposal_rejection_when_exceeding_10pct_limit(db):
    service = PaperProposalService()
    # Request an allocation of 20%, which would violate 10% limit if not capped.
    # The service automatically caps requested qty to max_order_val (10%).
    # Let's verify that even if target_allocation is huge, it is strictly capped at or below 10%.
    proposal = service.create_proposal_from_analysis(
        run_id="RUN_TEST_OVERSIZED",
        symbol="TCS",
        side="BUY",
        price=2500.0,
        reason="Aggressive allocation attempt",
        target_allocation_pct=25.0
    )

    assert proposal["estimated_notional"] <= 100000.0

def test_proposal_expiration(db):
    # Starting equity: 1,000,000 cash, 0 positions.

    # Create proposal with -1 minute expiry
    proposal = paper_proposal_service.create_proposal_from_analysis(
        run_id="RUN_TEST_EXPIRED",
        symbol="INFY",
        side="BUY",
        price=1100.0,
        reason="Test expired proposal",
        expiry_minutes=-5
    )

    # Attempting to confirm an expired proposal should fail
    result = paper_proposal_service.confirm_and_execute_proposal(proposal["proposal_id"])
    assert result["success"] is False
    assert "expired" in result["error"].lower()

def test_proposal_confirmation_and_execution(db, monkeypatch):
    from app.execution import paper_broker as broker_module

    monkeypatch.setattr(broker_module, "is_market_session_active", lambda: (True, "TEST_FIXTURE"))
    monkeypatch.setattr(broker_module.dhan_live_feed, "get_quote", lambda symbol: {
        "symbol": symbol, "price": 700.0, "freshness_status": "LIVE",
    })

    # Create valid proposal
    proposal = paper_proposal_service.create_proposal_from_analysis(
        run_id="RUN_TEST_EXEC",
        symbol="HDFCBANK",
        side="BUY",
        price=700.0,
        reason="High quality banking breakout",
        target_allocation_pct=5.0
    )

    prop_id = proposal["proposal_id"]

    # Confirm execution
    exec_result = paper_proposal_service.confirm_and_execute_proposal(prop_id)
    assert exec_result["success"] is True
    assert exec_result["status"] == "EXECUTED"
    assert exec_result["fill_price"] > 0
    assert exec_result["fee"] > 0

    # Duplicate confirmation must be blocked
    dup_result = paper_proposal_service.confirm_and_execute_proposal(prop_id)
    assert dup_result["success"] is False
    assert "duplicate" in dup_result["error"].lower() or "already" in dup_result["error"].lower()

def test_proposal_api_endpoints(client, db):
    # Test GET /api/v1/proposals
    res = client.get("/api/v1/proposals")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

    # Test reject endpoint with nonexistent proposal
    rej = client.post("/api/v1/proposals/confirm", json={"proposal_id": "NON_EXISTENT"})
    assert rej.status_code in (400, 404)
