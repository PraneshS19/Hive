import asyncio
import json
from unittest.mock import AsyncMock

import httpx
from app.core.config import settings
from app.db.models import ImprovementProposalRecord
from app.db.models.review import ReviewEvidenceRecord
from app.review.model_client import ReviewModelClient, review_model_client

API = "/api/v1"


def test_model_availability_requires_exact_installed_tag(monkeypatch):
    async def tags(request, **kwargs):
        assert request.endswith("/api/tags")
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen3.5:4b-similar"}, {"name": review_model_client.reviewer_model}]},
            request=httpx.Request("GET", request),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(side_effect=tags))
    chat = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "post", chat)
    client = ReviewModelClient()
    client.enabled = True
    info = asyncio.run(client.get_model_status())
    assert info["pull_commands"] == ["ollama pull qwen3.5:4b"]
    output, telemetry = asyncio.run(client.generate_structured(client.executor_model, "Research", "Check"))
    assert output is None
    assert telemetry["execution_mode"] == "unavailable"
    chat.assert_not_called()


def test_missing_models_persist_honest_status_and_review_checks(client, db, monkeypatch):
    from app.review import execution_graph

    packet = {"EV_PRICE": {"price": 100.0}, "EV_IND": {"indicators": {"rsi_14": 60.0}}}
    def replay(_symbol, cutoff, _db, _dataset_id):
        return {
            "latest_observed_bar": {"timestamp": cutoff.isoformat(), "close": packet["EV_PRICE"]["price"]},
            "latest_bar_availability_timestamp": cutoff.isoformat(),
            "historical_indicators": packet["EV_IND"]["indicators"],
            "cutoff_timestamp": cutoff.isoformat(),
            "availability_policy_metadata": {},
            "evidence_snapshot": {"source": "TEST_FIXTURE"},
        }

    from app.market.evidence_verifier import evidence_verifier
    monkeypatch.setattr(evidence_verifier, "point_in_time_evidence_replay", replay)
    call = AsyncMock(return_value=(None, {"error": "TEST_MOCK offline", "execution_mode": "unavailable"}))
    monkeypatch.setattr(execution_graph.review_model_client, "generate_structured", call)
    request = {"symbol": "RELIANCE", "replay_cutoff": "2025-03-01T14:30:00+00:00"}
    response = client.post(f"{API}/agent-runs", json=request)
    assert response.status_code == 200, response.text
    failed = response.json()
    assert failed["status"] == "FAILED"
    assert failed["error_message"] == "TEST_MOCK offline"
    assert not failed["objective_checks"]["schema_valid"]
    assert call.await_count == 1

    output = {
        "run_id": "fixture", "task_status": "COMPLETED", "summary": "Fixture review input",
        "observations": ["Observed price"], "evidence_refs": ["EV_PRICE"],
        "quantitative_interpretation": "RSI is 60", "bull_case": "Potential upside",
        "bear_case": "Potential downside", "key_risks": ["Market risk"], "recommendation_type": "HOLD",
    }
    call.reset_mock()
    call.side_effect = [
        (output, {"execution_mode": "TEST_MOCK"}),
        (None, {"error": "TEST_MOCK reviewer offline", "execution_mode": "unavailable"}),
    ]
    response = client.post(f"{API}/agent-runs", json=request)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "PARTIAL"
    assert run["review_verdict"] == "UNAVAILABLE"
    assert run["objective_checks"]["schema_valid"]
    assert call.await_args_list[0].kwargs["model_name"] == review_model_client.executor_model
    assert call.await_args_list[1].kwargs["model_name"] == review_model_client.reviewer_model
    record = db.get(ReviewEvidenceRecord, run["run_id"])
    assert json.loads(record.payload_json)["EV_PRICE"]["price"] == 100
    evidence = f"{API}/agent-runs/{run['run_id']}/evidence-verification"
    assert client.get(evidence).json()["audit_verdict"] == "FULLY_AUDITABLE"
    record.payload_json = record.payload_json.replace("100.0", "999.0")
    db.commit()
    assert client.get(evidence).json()["content_hash_verified"] is False


def test_promotion_is_authenticated_and_requires_measured_artifacts(client, db, monkeypatch):
    monkeypatch.setattr(settings, "HIVE_OPERATOR_TOKEN", "test-only-operator")
    proposal = ImprovementProposalRecord(
        proposal_id="test-gate", title="Test proposal", failure_category="TEST",
        root_cause_hypothesis="Test", affected_configuration="EXECUTOR_SYSTEM_PROMPT",
        expected_benefit="Test", regression_risks="Test",
        proposed_change_json=json.dumps({"updated_system_prompt": "candidate"}),
        status="ELIGIBLE", baseline_version="v1.0", candidate_version="v-test",
        benchmark_results_json=json.dumps({"decision": "PROMOTION_READY", "safety_violations": 0}),
    )
    db.add(proposal)
    db.commit()
    url = f"{API}/improvement-proposals/test-gate"
    body = {"reason": "Explicit test approval"}
    headers = {"X-Hive-Operator-Token": "test-only-operator"}
    assert client.post(f"{url}/approve", json=body).status_code == 403
    assert client.post(f"{url}/activate", json=body, headers=headers).status_code == 409
    assert client.post(f"{url}/approve", json=body, headers=headers).status_code == 409
    assert client.get(f"{url}/audit").json() == []


def test_manual_paper_order_is_idempotent_and_rejects_changed_retry(client, db):
    body = {"symbol": "RELIANCE", "side": "BUY", "requested": 1, "price": 100.0, "auto_execute": False}
    headers = {"Idempotency-Key": "test-order-idempotency"}
    first = client.post(f"{API}/orders", json=body, headers=headers)
    assert first.status_code == 200, first.text
    second = client.post(f"{API}/orders", json=body, headers=headers)
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert client.post(f"{API}/orders", json={**body, "requested": 2}, headers=headers).status_code == 409


def test_one_share_cannot_exceed_the_order_limit(db):
    from app.risk.engine import risk_engine

    result = risk_engine.evaluate_order(db, "RELIANCE", "BUY", 1, 200_000.0)
    assert result["outcome"] == "REJECTED"
    assert result["approved_qty"] == 0


def test_research_can_report_disregarded_untrusted_instruction():
    from app.review.objective_checks import run_deterministic_objective_checks

    checks = run_deterministic_objective_checks(
        "Summarize the supplied evidence",
        "Cite usable evidence",
        {"EV_NEWS": {"announcements": [{"verified": False}]}},
        {
            "run_id": "TEST_QUOTED_WARNING",
            "summary": "The announcement is unverified and should be disregarded.",
            "observations": ["The label 'SYSTEM PROMPT OVERRIDE' was disregarded."],
            "evidence_refs": ["EV_NEWS"],
            "recommendation_type": "NEUTRAL",
        },
        [],
        0.0,
    )
    assert checks.measured_metrics["untrusted_instruction_mentioned"]
    assert not checks.prompt_injection_detected
    assert checks.risk_policy_compliant


def test_empty_specialist_cards_do_not_imply_model_activity(client):
    cards = client.get(f"{API}/agents/cards").json()
    summary = client.get(f"{API}/dashboard/summary").json()
    assert cards == summary["agents"]
    assert len(cards) == 6
    assert all(card["status"] == "Idle" and card["model"] is None for card in cards)


def test_risk_mutations_require_authority_and_respect_hard_caps(operator_client):
    endpoint = f"{API}/risk/config"
    denied = operator_client.put(endpoint, json={"max_order_pct": 5}, headers={"X-Hive-Operator-Token": ""})
    assert denied.status_code == 403
    assert operator_client.put(endpoint, json={"max_order_pct": 11}).status_code == 422
    assert operator_client.put(endpoint, json={"max_allocation_pct": 26}).status_code == 422
    assert operator_client.put(endpoint, json={"drawdown_halt_pct": 11}).status_code == 422
    assert operator_client.get(endpoint).json()["maxOrder"] == 10


def test_csv_preview_and_upload_enforce_processing_cap(client, monkeypatch):
    from app.api.routes import datasets

    monkeypatch.setattr(datasets, "MAX_CSV_BYTES", 32)
    content = "Date,Open,High,Low,Close,Volume\n2026-10-16,1,2,1,2,100"
    assert client.post(
        f"{API}/datasets/preview-csv", json={"csv_text": content, "symbol": "RELIANCE"},
    ).status_code == 413
    assert client.post(
        f"{API}/datasets/preview-csv-file",
        files={"file": ("fixture.csv", content, "text/csv")},
    ).status_code == 413
