"""POST /api/ingest: a laptop pushes a fresh snapshot to a hosted server that can't reach the exchanges."""
import json

import pytest
from fastapi.testclient import TestClient

from app import snapshot
from app.config import settings
from app.main import app


def _files(captured_at: str, symbol: str = "AAA") -> dict:
    return {"meta.json": {"captured_at": captured_at, "sources": ["NSE"]},
            "announcements.json": [{"uid": f"NSE:{symbol}", "symbol": symbol}],
            "eod.json": {symbol: []}, "details.json": {}, "reports/NEW.json": {"symbol": "NEW"}}


@pytest.fixture
def server(tmp_path, monkeypatch):
    committed = tmp_path / "committed"
    (committed / "reports").mkdir(parents=True)
    (committed / "meta.json").write_text(json.dumps({"captured_at": "2026-10-31T08:58:21+05:30", "sources": ["BSE"]}))
    (committed / "announcements.json").write_text(json.dumps([{"uid": "OLD", "symbol": "OLD"}]))
    (committed / "reports" / "IRCTC.json").write_text(json.dumps({"symbol": "IRCTC"}))
    monkeypatch.setattr(snapshot, "SNAP_DIR", committed)
    saved = (settings.data_dir, settings.ingest_token, settings.fixture_mode)
    object.__setattr__(settings, "data_dir", tmp_path / "data")
    object.__setattr__(settings, "ingest_token", "secret")
    object.__setattr__(settings, "fixture_mode", False)
    snapshot.reload()
    yield TestClient(app)
    object.__setattr__(settings, "data_dir", saved[0])
    object.__setattr__(settings, "ingest_token", saved[1])
    object.__setattr__(settings, "fixture_mode", saved[2])
    snapshot.reload()


def _post(c, files, token="secret"):
    return c.post("/api/ingest", json={"files": files}, headers={"X-Ingest-Token": token})


def test_disabled_without_token(server):
    object.__setattr__(settings, "ingest_token", "")
    assert _post(server, _files("2026-11-01T10:00:00+05:30")).status_code == 404


def test_wrong_token_rejected(server):
    assert _post(server, _files("2026-11-01T10:00:00+05:30"), token="nope").status_code == 401
    assert snapshot.meta()["captured_at"] == "2026-10-31T08:58:21+05:30"


def test_newer_push_replaces_committed_snapshot_but_keeps_its_reports(server):
    r = _post(server, _files("2026-11-01T10:00:00+05:30"))
    assert r.status_code == 200 and r.json()["announcements"] == 1
    assert snapshot.label()["captured_at"] == "2026-11-01T10:00:00+05:30"
    assert snapshot.announcements()[0]["symbol"] == "AAA"
    assert snapshot.report_symbols() == ["IRCTC", "NEW"]
    assert snapshot.report("irctc") == {"symbol": "IRCTC"}


def test_older_push_is_refused(server):
    assert _post(server, _files("2026-11-01T10:00:00+05:30")).status_code == 200
    r = _post(server, _files("2026-10-31T09:00:00+05:30", "BBB"))
    assert r.status_code == 400 and "older" in r.json()["detail"]
    assert snapshot.announcements()[0]["symbol"] == "AAA"


@pytest.mark.parametrize("bad", ["../evil.json", "reports/../x.json", "other.json", "reports/lower.json"])
def test_unexpected_file_names_refused(server, bad):
    files = _files("2026-11-01T10:00:00+05:30")
    files[bad] = {}
    assert _post(server, files).status_code == 400


def test_pushed_snapshot_not_used_when_older_than_committed(server):
    # a stale live copy left over from an earlier push must not shadow a newer commit
    assert _post(server, _files("2026-10-30T10:00:00+05:30")).status_code == 400
    assert not (snapshot.live_dir() / "meta.json").exists()
    assert snapshot.label()["captured_at"] == "2026-10-31T08:58:21+05:30"
