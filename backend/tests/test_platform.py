"""Holdings maths, indices, daily briefing and Copilot grounding."""
import pytest
from fastapi.testclient import TestClient

from app import briefing, copilot, llm, market
from app import holdings as hd
from app.main import app

c = TestClient(app)


def _bars(*closes):
    return [{"date": f"2026-10-{20 + i:02d}", "close": v, "volume": 1000} for i, v in enumerate(closes)]


def test_holdings_maths_exact(monkeypatch):
    series = {"AAA": _bars(100, 110), "BBB": _bars(50, 45)}
    monkeypatch.setattr(market, "get_eod", lambda syms: {"series": {s: series.get(s, []) for s in syms}, "status": {s: "ok" for s in syms}, "provider": "test"})
    v = hd.value([hd.Holding(symbol="AAA", qty=10, avg_price=90, sector="IT", cap="Large"),
                  hd.Holding(symbol="BBB", qty=20, avg_price=60, sector="Pharma", cap="Small"),
                  hd.Holding(symbol="AAA", qty=10, avg_price=110),          # merged: avg cost 100
                  hd.Holding(symbol="CCC", qty=1, avg_price=10)])           # no price available
    t = v["totals"]
    aaa = next(r for r in v["holdings"] if r["symbol"] == "AAA")
    assert aaa["qty"] == 20 and aaa["avg_price"] == pytest.approx(100) and aaa["value"] == pytest.approx(2200)
    assert aaa["pnl"] == pytest.approx(200) and aaa["pnl_pct"] == pytest.approx(10) and aaa["day_change"] == pytest.approx(200)
    assert t["invested_priced"] == pytest.approx(2000 + 1200) and t["value"] == pytest.approx(2200 + 900)
    assert t["pnl"] == pytest.approx(-100) and t["pnl_pct"] == pytest.approx(-100 / 3200 * 100)
    assert t["day_change"] == pytest.approx(200 - 100)                      # BBB fell 5 x 20
    assert t["day_change_pct"] == pytest.approx(100 / (3100 - 100) * 100)    # vs yesterday's value
    assert t["unpriced"] == ["CCC"] and t["invested"] == pytest.approx(3210)
    assert v["best"] == "AAA" and v["worst"] == "BBB"
    assert {a["name"]: round(a["pct"], 2) for a in v["allocation"]["cap"]} == {"Large": round(2200 / 3100 * 100, 2), "Small": round(900 / 3100 * 100, 2)}
    assert sum(r["weight"] for r in v["holdings"] if r["weight"]) == pytest.approx(100)


def test_holdings_validation():
    assert c.post("/api/holdings/value", json={"holdings": [{"symbol": "DROP TABLE", "qty": 1, "avg_price": 1}]}).status_code == 422
    assert c.post("/api/holdings/value", json={"holdings": [{"symbol": "TCS", "qty": 0, "avg_price": 1}]}).status_code == 422
    assert c.post("/api/holdings/value", json={"holdings": [{"symbol": "TCS", "qty": 1, "avg_price": 1, "cap": "Huge"}]}).status_code == 422
    empty = c.post("/api/holdings/value", json={"holdings": []}).json()
    assert empty["totals"]["count"] == 0 and empty["totals"]["value"] is None


def test_example_holdings_use_real_history():
    ex = c.get("/api/holdings/example").json()
    assert ex["holdings"] and "Example only" in ex["note"]
    eod = market.get_eod([h["symbol"] for h in ex["holdings"]])
    for h in ex["holdings"]:
        assert any(b["close"] == pytest.approx(h["avg_price"], abs=0.01) and b["date"] == h["bought"] for b in eod["series"][h["symbol"]])


def test_indices_have_timestamps_and_kind():
    r = c.get("/api/indices").json()
    assert [i["key"] for i in r["indices"]] == ["NIFTY50", "SENSEX", "BANKNIFTY", "NIFTYIT"]
    for i in r["indices"]:
        assert i["value"] and i["as_of"] and i["kind"] in ("end_of_day", "delayed") and i["change_pct"] is not None


def test_briefing_rule_based_and_grounding(monkeypatch):
    b = c.post("/api/briefing", json={"holdings": ["DIXON"]}).json()
    assert b["origin"] == "rules" and b["lines"] and all(l["cites"] for l in b["lines"])
    fs, _ = briefing.facts(["DIXON"])
    by_id = {f["id"]: f for f in fs}
    nifty = by_id["I:NIFTY50"]["text"]
    assert briefing._verify({"text": f"NIFTY 50 at {nifty.split(' at ')[1].split('%')[0]}%", "cites": ["I:NIFTY50"]}, by_id)
    assert not briefing._verify({"text": "NIFTY 50 jumped 9.99% today", "cites": ["I:NIFTY50"]}, by_id)
    assert not briefing._verify({"text": "Anything", "cites": ["I:NOPE"]}, by_id)


def test_copilot_symbol_detection():
    assert copilot.detect_symbols("How did Dixon do this quarter?", []) == ["DIXON"]
    assert "RELIANCE" in copilot.detect_symbols("compare reliance and tcs", [])
    assert "TCS" in copilot.detect_symbols("compare reliance and tcs", [])
    assert copilot.detect_symbols("tell me about the sun", []) == []          # generic first word ignored
    assert copilot.detect_symbols("what about XYZCO", ["XYZCO"]) == ["XYZCO"]  # holdings outside the watchlist


def test_copilot_without_llm_returns_sources_and_actions():
    r = c.post("/api/copilot", json={"question": "How are Dixon's results?"}).json()
    assert r["origin"] == "none" and any(s["id"].startswith("F:") for s in r["sources"]) and {"type": "research", "symbol": "DIXON"} in r["actions"]
    r = c.post("/api/copilot", json={"question": "how is my portfolio doing", "holdings": [{"symbol": "TCS", "qty": 10, "avg_price": 500}]}).json()
    assert any(s["id"] == "H:total" for s in r["sources"])
    assert c.post("/api/copilot", json={"question": "x"}).status_code == 422


def test_copilot_flags_unsupported_numbers(monkeypatch):
    monkeypatch.setattr(type(copilot.settings), "llm_enabled", property(lambda s: True))

    def fake(schema, prompt, **kw):
        price_line = next(l for l in prompt.split("\n") if "closed at" in l)
        price = price_line.split("closed at ₹")[1].split(" ")[0]
        return copilot.Answer(blocks=[copilot.Block(text=f"Dixon closed at ₹{price}", cites=["P:DIXON"]),
                                      copilot.Block(text="Dixon will rise 40% next year.", cites=["P:DIXON"]),
                                      copilot.Block(text="Margins are great.", cites=["Z:NOPE"])],
                              missing=["Segment margins"], follow_ups=["Show the results table"])
    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "models", lambda: ("fast-m", "smart-m"))
    r = c.post("/api/copilot", json={"question": "Where does Dixon trade?", "symbol": "DIXON"}).json()
    v = [b["verified"] for b in r["blocks"]]
    assert v == [True, False, False] and r["missing"] == ["Segment margins"] and r["sources"][0]["id"] == "P:DIXON"


# ---------------- LLM model chain (from the first live Gemini run: 400 on one model, 503 on another)
AVAILABLE = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.5-flash-preview-tts', 'gemini-flash-latest', 'gemini-flash-lite-latest',
             'gemini-pro-latest', 'gemini-2.5-flash-lite', 'gemini-3.5-flash-lite', 'gemini-3.8-flash', 'gemini-3.6-flash-image']


def test_gemini_chain_prefers_latest_aliases():
    assert llm.gemini_chain("fast", AVAILABLE)[:3] == ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite"]
    assert llm.gemini_chain("smart", AVAILABLE)[:3] == ["gemini-flash-latest", "gemini-3.8-flash", "gemini-2.5-flash"]
    assert llm.gemini_chain("fast", ["gemini-2.5-flash"]) == ["gemini-2.5-flash"]       # only what exists


def test_complete_json_falls_back_and_remembers(monkeypatch):
    import httpx
    from pydantic import BaseModel
    from app import storage

    class P(BaseModel):
        x: int

    monkeypatch.setattr(type(llm.settings), "llm_enabled", property(lambda s: True))
    monkeypatch.setattr(llm, "_chain", lambda tier: ["m-bad", "m-busy", "m-ok"])
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = []

    def fake(model, system, prompt, max_tokens):
        calls.append(model)
        req = httpx.Request("POST", "https://x")
        if model == "m-bad":
            raise httpx.HTTPStatusError("400", request=req, response=httpx.Response(400, json={"error": {"message": "Invalid argument"}}, request=req))
        if model == "m-busy":
            raise httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, json={"error": {"message": "overloaded"}}, request=req))
        return '{"x": 7}', 10, 2

    monkeypatch.setattr(llm, "_call_provider", fake)
    out = llm.complete_json(P, "prompt-fallback-test", tier="fast", purpose="t")
    assert out.x == 7 and calls == ["m-bad", "m-busy", "m-busy", "m-ok"]
    monkeypatch.setattr(llm, "_call_provider", lambda *a: (_ for _ in ()).throw(AssertionError("should be cached")))
    assert llm.complete_json(P, "prompt-fallback-test", tier="fast").x == 7


def test_complete_json_reports_every_failure(monkeypatch):
    import httpx
    from pydantic import BaseModel

    class P(BaseModel):
        x: int

    monkeypatch.setattr(type(llm.settings), "llm_enabled", property(lambda s: True))
    monkeypatch.setattr(llm, "_chain", lambda tier: ["a", "b"])

    def fake(model, *a):
        req = httpx.Request("POST", "https://x")
        raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, json={"error": {"message": f"{model} not found"}}, request=req))
    monkeypatch.setattr(llm, "_call_provider", fake)
    with pytest.raises(llm.LLMError, match="a: HTTP 404 a not found .* b: HTTP 404 b not found"):
        llm.complete_json(P, "prompt-all-fail", tier="fast")


def test_screener_annual_report_title_year():
    from app.research.screener import _documents
    from bs4 import BeautifulSoup
    html = '<div class="documents annual-reports"><ul><li><a href="/x.pdf">Annual Report 2026</a></li><li><a href="/y.pdf">Financial Year 2025 from bse</a></li></ul></div>'
    d = _documents(BeautifulSoup(html, "lxml"))
    assert [a["year"] for a in d["annual_reports"]] == [2026, 2025]
