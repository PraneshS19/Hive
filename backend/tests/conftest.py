import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.db.init_db as init_db_module
import app.db.session as session_module
import app.execution.paper_proposals as pp_module
import app.market.event_detector as ed_module
import app.market.evidence_snapshot as ev_module
import app.market.ramm_adapter as ramm_module
from app.api.dependencies import get_db as dep_get_db
from app.db.base import Base, enforce_sqlite_foreign_keys
from app.db.init_db import init_db
from app.db.session import get_db as session_get_db
from app.main import app

# Shared in-memory SQLite database with StaticPool
TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
enforce_sqlite_foreign_keys(test_engine)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def stop_background_threads():
    from app.market.dhan_adapter import dhan_live_feed, raw_dhan_live_feed
    from app.market.ramm_adapter import ramm_market_feed
    ramm_market_feed.stop()
    raw_dhan_live_feed.stop()
    dhan_live_feed.stop()
    # Prevent background polling workers from spawning during test runs and racing SQLite
    ramm_market_feed.start = lambda: None
    raw_dhan_live_feed.start = lambda: None
    dhan_live_feed.start = lambda: None
    yield
    ramm_market_feed.stop()
    raw_dhan_live_feed.stop()
    dhan_live_feed.stop()


@pytest.fixture(scope="function", autouse=True)
def isolate_session_local(monkeypatch):
    # Unit and API tests must remain offline unless they install an explicit fake.
    from app.agents.llm_provider import local_llm_provider
    from app.review.model_client import review_model_client
    monkeypatch.setattr(local_llm_provider, "enabled", False)
    monkeypatch.setattr(review_model_client, "enabled", False)
    monkeypatch.setattr(init_db_module, "engine", test_engine)
    monkeypatch.setattr(init_db_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(session_module, "engine", test_engine)
    monkeypatch.setattr(session_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(ev_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(ed_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(ramm_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(pp_module, "SessionLocal", TestingSessionLocal)
    import app.market.snapshot_store as snap_module
    import app.review.execution_graph as eg_module
    import app.review.improvement_graph as ig_module

    monkeypatch.setattr(eg_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(ig_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(snap_module, "SessionLocal", TestingSessionLocal)


@pytest.fixture(scope="function", autouse=True)
def reset_dhan_feed():
    from app.market.dhan_adapter import dhan_live_feed
    dhan_live_feed.reset_cache()
    yield
    dhan_live_feed.reset_cache()


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    init_db(session)
    yield session
    session.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            db.rollback()

    app.dependency_overrides[session_get_db] = override_get_db
    app.dependency_overrides[dep_get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def operator_client(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "HIVE_OPERATOR_TOKEN", "test-fixture-local-token")
    client.headers["X-Hive-Operator-Token"] = "test-fixture-local-token"
    return client
