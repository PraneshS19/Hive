import asyncio
import hashlib
import json

import pytest
from app.api.routes import review
from app.db.models import ImprovementProposalRecord, ReviewRun
from app.db.models.review import BenchmarkTrialRecord, ReviewEvidenceRecord
from app.main import app
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _run(run_id, status):
    return ReviewRun(
        run_id=run_id, status=status, task_prompt="Audit research", acceptance_criteria="Cite evidence",
        executor_model="executor-fixture", reviewer_model="reviewer-fixture",
    )


def test_startup_marks_interrupted_runs_without_rewriting_evidence(db):
    payload = '{"prices":[]}'
    digest = hashlib.sha256(payload.encode()).hexdigest()
    db.add_all([_run("unfinished", "EXECUTED"), _run("finished", "COMPLETED")])
    db.flush()
    db.add(ReviewEvidenceRecord(run_id="unfinished", payload_json=payload, sha256=digest))
    db.commit()
    with TestClient(app) as client:
        response = client.get("/api/v1/agent-runs")
        assert response.status_code == 200
        records = {row["run_id"]: row for row in response.json()}
        assert records["unfinished"]["status"] == "FAILED"
        assert "backend restart" in records["unfinished"]["error_message"]
        assert records["finished"]["status"] == "COMPLETED"
    evidence = db.get(ReviewEvidenceRecord, "unfinished")
    assert (evidence.payload_json, evidence.sha256) == (payload, digest)


def test_same_inflight_research_is_rejected_and_cancellation_is_persisted(db, monkeypatch):
    async def scenario():
        started = asyncio.Event()

        async def blocked_graph(state):
            db.add(_run(state["run_id"], "RUNNING"))
            db.commit()
            started.set()
            await asyncio.Future()

        monkeypatch.setattr(review.execution_review_graph, "ainvoke", blocked_graph)
        request = review.AgentRunRequest(symbol="RELIANCE")
        task = asyncio.create_task(review.create_agent_run(request, db))
        await asyncio.wait_for(started.wait(), timeout=5)
        with pytest.raises(HTTPException) as duplicate:
            await review.create_agent_run(review.AgentRunRequest(symbol="reliance"), db)
        assert duplicate.value.status_code == 409
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        record = db.query(ReviewRun).one()
        assert record.status == "FAILED" and record.completed_at
        assert "interrupted" in record.error_message

    asyncio.run(scenario())


def test_interrupted_benchmark_preserves_previous_trial_and_releases_guard(db, monkeypatch):
    artifacts = json.dumps({"trial_id": "previous"})
    db.add(ImprovementProposalRecord(
        proposal_id="benchmark-1", title="Compare", failure_category="TEST", root_cause_hypothesis="Test",
        proposed_change_json=json.dumps({"updated_system_prompt": "Distinct fixture"}),
        affected_configuration="prompts", expected_benefit="Test", regression_risks="Fixture",
        status="BENCHMARKED", baseline_version="v1.0", candidate_version="v1.1", benchmark_results_json=artifacts,
    ))
    db.flush()
    db.add(BenchmarkTrialRecord(id="previous", proposal_id="benchmark-1", artifacts_json=artifacts))
    db.commit()

    async def scenario():
        started = asyncio.Event()

        async def health():
            started.set()
            await asyncio.Future()

        monkeypatch.setattr(review.review_model_client, "get_model_status", health)
        task = asyncio.create_task(review.run_proposal_benchmark("benchmark-1", "real_llm", db))
        await asyncio.wait_for(started.wait(), timeout=5)
        with pytest.raises(HTTPException) as duplicate:
            await review.run_proposal_benchmark("benchmark-1", "real_llm", db)
        assert duplicate.value.status_code == 409
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with review.single_operation("proposal benchmark", "benchmark-1"):
            assert db.query(BenchmarkTrialRecord).one().artifacts_json == artifacts
            assert db.query(ImprovementProposalRecord).one().status == "BENCHMARKED"

    asyncio.run(scenario())


def test_duplicate_proposal_generation_does_not_start_another_graph(db, monkeypatch):
    async def scenario():
        started = asyncio.Event()
        finish = asyncio.Event()

        async def graph(_state):
            started.set()
            await finish.wait()
            return {"sample_sufficient": True, "proposal": {"title": "Test draft"}}

        monkeypatch.setattr(review.continuous_improvement_graph, "ainvoke", graph)
        task = asyncio.create_task(review.generate_improvement_proposal_endpoint(db))
        await asyncio.wait_for(started.wait(), timeout=5)
        with pytest.raises(HTTPException) as duplicate:
            await review.generate_improvement_proposal_endpoint(db)
        assert duplicate.value.status_code == 409
        finish.set()
        assert await task == {"title": "Test draft"}

    asyncio.run(scenario())
