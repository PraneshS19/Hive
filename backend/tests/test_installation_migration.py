import sqlite3
from contextlib import closing
from hashlib import sha256

import pytest
from app.core import config
from app.core.installation_compat import PREVIOUS_PREFIX
from app.review import model_client
from scripts.migrate_database import migrate_database


def test_model_settings_reach_local_client(monkeypatch):
    monkeypatch.setenv("HIVE_MODEL_TIMEOUT_SECONDS", "79")
    monkeypatch.setenv("HIVE_MODEL_KEEP_ALIVE", "2m")
    monkeypatch.setenv("HIVE_MAX_REVISION_ATTEMPTS", "0")
    configured = config.Settings(_env_file=None)
    monkeypatch.setattr(model_client, "settings", configured)
    client = model_client.ReviewModelClient()
    assert (client.timeout, client.keep_alive, configured.HIVE_MAX_REVISION_ATTEMPTS) == (79, "2m", 0)


def test_previous_setting_warns_and_hive_takes_precedence(monkeypatch, tmp_path):
    new = "HIVE_MODEL_TIMEOUT_SECONDS"
    previous = PREVIOUS_PREFIX + new.removeprefix("HIVE_")
    monkeypatch.delenv(new, raising=False)
    monkeypatch.setenv(previous, "71")
    with pytest.warns(FutureWarning, match="HIVE_"):
        assert config.Settings(_env_file=None).HIVE_MODEL_TIMEOUT_SECONDS == 71
    monkeypatch.setenv(new, "88")
    with pytest.warns(FutureWarning, match="HIVE_"):
        assert config.Settings(_env_file=None).HIVE_MODEL_TIMEOUT_SECONDS == 88
    monkeypatch.delenv(new)
    monkeypatch.delenv(previous)
    env = tmp_path / ".env"
    env.write_text(f"{previous}=67\n", encoding="utf-8")
    with pytest.warns(FutureWarning, match="HIVE_"):
        assert config.Settings(_env_file=env).HIVE_MODEL_TIMEOUT_SECONDS == 67


def test_existing_database_cannot_be_silently_bypassed(tmp_path, monkeypatch):
    default = tmp_path / "hive.db"
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", default)
    previous = tmp_path / (PREVIOUS_PREFIX.removesuffix("_").lower() + ".db")
    previous.touch()
    with pytest.raises(ValueError, match="explicit DATABASE_URL"):
        config.Settings(_env_file=None, DATABASE_URL=f"sqlite:///{default.as_posix()}")
    assert config.Settings(_env_file=None, DATABASE_URL=f"sqlite:///{previous.as_posix()}").DATABASE_URL.endswith(previous.name)
    assert previous.exists() and not default.exists()


def test_sqlite_snapshot_keeps_committed_wal_and_evidence_bytes(tmp_path):
    source = tmp_path / "previous.db"
    destination = tmp_path / "hive.db"
    payload = b'{"observations": []}'
    digest = sha256(payload).hexdigest()
    with closing(sqlite3.connect(source)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.executescript(
            "CREATE TABLE accounts(id INTEGER PRIMARY KEY, cash REAL);"
            "CREATE TABLE assets(id INTEGER PRIMARY KEY);"
            "CREATE TABLE review_evidence(account INTEGER REFERENCES accounts(id), data BLOB, digest TEXT);"
        )
        db.execute("INSERT INTO accounts VALUES (1, 180.25)")
        db.execute("INSERT INTO review_evidence VALUES (1, ?, ?)", (payload, digest))
        db.commit()
        assert source.with_name(source.name + "-wal").stat().st_size > 0
        migrate_database(source, destination)
        assert db.execute("SELECT cash FROM accounts").fetchone() == (180.25,)

    with closing(sqlite3.connect(destination)) as snapshot:
        assert snapshot.execute("SELECT cash FROM accounts").fetchone() == (180.25,)
        assert snapshot.execute("SELECT account, data, digest FROM review_evidence").fetchone() == (1, payload, digest)
        assert snapshot.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(FileExistsError):
        migrate_database(source, destination)


def test_existing_foreign_key_violations_require_explicit_opt_in(tmp_path):
    source = tmp_path / "previous.db"
    destination = tmp_path / "hive.db"
    with closing(sqlite3.connect(source)) as db:
        db.executescript(
            "CREATE TABLE accounts(id INTEGER PRIMARY KEY);"
            "CREATE TABLE assets(id INTEGER PRIMARY KEY);"
            "CREATE TABLE positions(account INTEGER REFERENCES accounts(id));"
            "INSERT INTO positions VALUES (12);"
        )
    with pytest.raises(ValueError, match="Source already contains"):
        migrate_database(source, destination)
    assert not destination.exists()
    assert migrate_database(source, destination, allow_existing_violations=True) == 1
    with closing(sqlite3.connect(destination)) as snapshot:
        assert snapshot.execute("SELECT account FROM positions").fetchall() == [(12,)]
