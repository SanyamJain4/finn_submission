import time

import pytest
from fastapi.testclient import TestClient

from app import http
from app.main import app

c = TestClient(app)


def test_health_and_status():
    assert c.get("/api/health").json()["ok"]
    s = c.get("/api/status").json()
    assert s["fixture_mode"] and "results" in s["categories"]


def test_feed_contract_and_validation():
    f = c.get("/api/feed?hours=48").json()
    assert {"window", "items", "counts", "sources", "market"} <= f.keys()
    i = f["items"][0]
    assert {"uid", "symbol", "company", "category", "tier", "priority", "why", "summary", "url", "published"} <= i.keys()
    assert c.get("/api/feed?hours=0").status_code == 422
    assert c.get("/api/feed?start=2026-10-10&end=2026-10-01").status_code == 400


def test_announcement_detail_and_404():
    f = c.get("/api/feed?hours=48").json()
    res = next(i for i in f["items"] if i["category"] == "results" and i["tier"] == "high")
    d = c.get(f"/api/announcements/{res['uid']}").json()
    assert d["results"]["status"] == "ok"
    noatt = next(i for i in f["items"] if not i["url"])
    d2 = c.get(f"/api/announcements/{noatt['uid']}").json()
    assert d2["notes"] and d2["document"] is None
    assert c.get("/api/announcements/NSE:doesnotexist").status_code == 404


def test_prefs_roundtrip_and_validation():
    p = c.put("/api/prefs/alerts", json={"categories": ["results"], "min_tier": "high", "price_move_pct": 3, "volume_multiple": 2.5, "volume_window": 20}).json()
    assert p["categories"] == ["results"] and p["price_move_pct"] == 3
    assert c.put("/api/prefs/alerts", json={"categories": ["nonsense"]}).status_code == 422
    assert c.put("/api/prefs/alerts", json={"volume_multiple": 0.5}).status_code == 422
    a = c.get("/api/alerts").json()
    assert all(x["category"] == "results" and x["tier"] == "high" for x in a["filing_alerts"])
    c.put("/api/prefs/alerts", json={"categories": ["results", "M&A", "management_change"], "min_tier": "medium"})


def test_search_and_research_job_outside_portfolio():
    r = c.get("/api/search?q=irctc").json()
    assert r["results"][0]["symbol"] == "IRCTC" and not r["results"][0]["in_portfolio"]
    j = c.post("/api/research", json={"query": "IRCTC", "force": True}).json()
    for _ in range(40):
        if j["status"] != "running":
            break
        time.sleep(0.25)
        j = c.get(f"/api/research/jobs/{j['job_id']}").json()
    assert j["status"] == "done" and j["report"]["in_portfolio"] is False
    cached = c.post("/api/research", json={"query": "IRCTC"}).json()
    assert cached["cached"] and cached["status"] == "done"


def test_research_errors():
    assert c.post("/api/research", json={"query": ""}).status_code == 422
    j = c.post("/api/research", json={"query": "NOSUCHCO"}).json()
    for _ in range(20):
        if j["status"] != "running":
            break
        time.sleep(0.2)
        j = c.get(f"/api/research/jobs/{j['job_id']}").json()
    assert j["status"] == "error" and "NOSUCHCO" in j["error"]
    assert c.get("/api/research/jobs/nope").status_code == 404


@pytest.mark.parametrize("url", ["http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "https://localhost/x", "https://evil.example.internal/x"])
def test_ssrf_guard(url):
    with pytest.raises(http.SourceError):
        http.check_url_allowed(url, allow_external_documents=True)


def test_trusted_hosts_allowed():
    http.check_url_allowed("https://www.bseindia.com/xml-data/corpfiling/AttachLive/x.pdf")
    with pytest.raises(http.SourceError):
        http.check_url_allowed("https://example.com/x.pdf")  # external docs need explicit opt-in


def test_circuit_breaker_short_circuits_dead_host(monkeypatch):
    import httpx as hx
    calls = []

    class Dead:
        def get(self, url, **kw):
            calls.append(url)
            raise hx.ConnectError("refused")
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    http._breaker.clear()
    for _ in range(4):
        with pytest.raises(http.SourceError):
            http.fetch(Dead(), "https://api.bseindia.com/x", "BSE")
    assert len(calls) == 3                       # 4th request never hits the network
    assert http._breaker["api.bseindia.com"][1] > 0
    http._breaker.clear()
