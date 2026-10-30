"""Hosted-server scenario: every live source is blocked; FINN must fall back to the real-data snapshot,
label it, and still refuse honestly for anything the snapshot doesn't cover."""
import json
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import http, market, snapshot
from app.config import settings
from app.main import app
from app.push import sources
from app.push.service import filing_detail
from app.research import screener
from app.research import service as rs
from app import documents


def _blocked(*a, **k):
    raise http.SourceError("blocked", "HTTP 403", 403)


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    # Build snapshot content while still in fixture mode (stands in for a real capture on a laptop).
    report = rs.build_report("IRCTC")
    items = sources.load_fixture_announcements()
    for i in items:
        i.exchange = "BSE"
    eod = json.loads(market.FIXTURE.read_text())
    from app.push.service import build_feed
    build_feed(hours=48)
    detail = filing_detail("NSE:fx1001")
    assert detail and detail["results"]["status"] == "ok"
    cap = datetime.now(sources.IST) - timedelta(hours=1)
    snap = tmp_path / "snapshot"
    (snap / "reports").mkdir(parents=True)
    (snap / "meta.json").write_text(json.dumps({"captured_at": cap.isoformat(timespec="seconds"), "sources": ["BSE", "Yahoo Finance"]}))
    (snap / "announcements.json").write_text(json.dumps([i.to_dict() for i in items]))
    (snap / "eod.json").write_text(json.dumps(eod))
    (snap / "details.json").write_text(json.dumps({"NSE:fx1001": {k: v for k, v in detail.items() if k != "item"}}))
    (snap / "reports" / "IRCTC.json").write_text(json.dumps(report))

    # Now become a hosted server: live mode, all network blocked, fresh caches.
    object.__setattr__(settings, "fixture_mode", False)
    monkeypatch.setattr(snapshot, "SNAP_DIR", snap)
    for f in (snapshot.meta, snapshot.announcements, snapshot.eod, snapshot.details):
        f.cache_clear()
    monkeypatch.setattr(sources, "fetch", _blocked)
    monkeypatch.setattr(screener, "fetch", _blocked)
    monkeypatch.setattr(documents, "fetch", _blocked)
    monkeypatch.setattr(market, "_yfinance", lambda syms: {})
    monkeypatch.setattr(market, "_chart_api", _blocked)
    from app import storage
    storage.conn().execute("DELETE FROM kv")
    storage.conn().execute("DELETE FROM documents")
    storage.conn().commit()
    http._breaker.clear()
    yield TestClient(app)
    object.__setattr__(settings, "fixture_mode", True)
    for f in (snapshot.meta, snapshot.announcements, snapshot.eod, snapshot.details):
        f.cache_clear()
    storage.conn().execute("DELETE FROM kv")
    storage.conn().commit()


def test_feed_falls_back_to_labelled_snapshot(hosted):
    f = hosted.get("/api/feed?hours=24").json()
    assert f["snapshot"] and f["snapshot"]["sources"] == ["BSE", "Yahoo Finance"]
    assert f["counts"]["total"] > 0
    names = {s["name"]: s["status"] for s in f["sources"]}
    assert names["BSE"] == "error" and names["Snapshot"] == "snapshot"
    assert "HTTP 403" in next(s["detail"] for s in f["sources"] if s["name"] == "BSE")   # real reason surfaced
    assert f["window"]["end"].startswith(f["snapshot"]["captured_at"][:13])               # window anchored to capture
    assert f["market"]["provider"].startswith("snapshot of Yahoo Finance")
    assert any(m["signals"] for m in f["market"]["by_symbol"].values())


def test_filing_detail_and_research_from_snapshot(hosted):
    hosted.get("/api/feed?hours=48")
    d = hosted.get("/api/announcements/NSE:fx1001").json()
    assert d["results"]["status"] == "ok" and d["snapshot"]
    j = hosted.post("/api/research", json={"query": "IRCTC", "force": True}).json()
    for _ in range(40):
        if j["status"] != "running":
            break
        time.sleep(0.1)
        j = hosted.get(f"/api/research/jobs/{j['job_id']}").json()
    assert j["status"] == "done" and j["report"]["snapshot"]
    assert "unreachable from this server" in j["report"]["limitations"][0]
    j = hosted.post("/api/research", json={"query": "TRENT", "force": True}).json()
    for _ in range(40):
        if j["status"] != "running":
            break
        time.sleep(0.1)
        j = hosted.get(f"/api/research/jobs/{j['job_id']}").json()
    assert j["status"] == "error" and "IRCTC" in j["error"]                              # honest, with a pointer


def test_diagnostics_reports_blocked_sources(hosted):
    d = hosted.get("/api/diagnostics").json()
    assert {p["name"] for p in d["probes"]} >= {"NSE announcements", "BSE announcements", "Yahoo Finance prices"}
    assert d["snapshot"] and d["snapshot_reports"] == ["IRCTC"]
