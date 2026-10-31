from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import briefing, copilot, llm, market, portfolio, storage
from . import holdings as hd
from .config import ROOT, settings
from .http import SourceError
from .push import service as push
from .push.classify import CATEGORIES
from .push.sources import IST
from .research import screener
from .research import service as research

logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","lvl":"%(levelname)s","mod":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("finn.api")

app = FastAPI(title="FINN - Financial Investment Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")], allow_methods=["GET", "POST", "PUT"], allow_headers=["*"])


@app.exception_handler(SourceError)
async def _source_err(_: Request, e: SourceError):
    return JSONResponse(status_code=502, content={"error": "source_unavailable", "source": e.source, "detail": e.message})


@app.exception_handler(ValueError)
async def _value_err(_: Request, e: ValueError):
    return JSONResponse(status_code=400, content={"error": "invalid_request", "detail": str(e)})


@app.get("/api/health")
def health():
    return {"ok": True, "fixture_mode": settings.fixture_mode, "llm": llm.status()}


@app.get("/api/status")
def status():
    return {"fixture_mode": settings.fixture_mode, "llm": llm.status(), "llm_usage": storage.llm_usage_summary(),
            "categories": CATEGORIES, "portfolio_size": len(portfolio.portfolio())}


@app.get("/api/diagnostics")
def diagnostics():
    """Probe each live source from THIS server (bypassing caches and the circuit breaker) and report what happened."""
    import time as _t
    from datetime import datetime, timedelta

    from . import http as h
    from . import snapshot

    h._breaker.clear()
    end = datetime.now(IST)
    probes = [
        ("NSE announcements", "https://www.nseindia.com/", None, {}),
        ("BSE announcements", "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
         {"pageno": 1, "strCat": -1, "strPrevDate": f"{end - timedelta(days=3):%Y%m%d}", "strScrip": "532540", "strSearch": "P",
          "strToDate": f"{end:%Y%m%d}", "strType": "C", "subcategory": -1}, {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}),
        ("Yahoo Finance prices", "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS", {"range": "5d", "interval": "1d"}, {}),
        ("Screener (research)", "https://www.screener.in/api/company/search/", {"q": "trent"}, {}),
    ]
    out = []
    with h.make_client() as c:
        for name, url, params, headers in probes:
            t0 = _t.time()
            try:
                r = h.fetch(c, url, name, params=params, headers=headers, retries=0)
                ok = True
                detail = f"HTTP {r.status_code}, {len(r.content):,} bytes"
                if "bseindia" in url:
                    try:
                        detail += f", {len(r.json().get('Table', []))} filings for TCS"
                    except ValueError:
                        ok, detail = False, "HTTP 200 but not JSON (blocked by bot protection)"
            except h.SourceError as e:
                ok, detail = False, e.message
            out.append({"name": name, "ok": ok, "detail": detail, "ms": int((_t.time() - t0) * 1000)})
    if settings.llm_enabled:
        t0 = _t.time()
        try:
            ms = llm.list_models() if settings.llm_provider == "gemini" else []
            fast, smart = llm.models()
            missing = [m for m in (fast, smart) if ms and m not in ms]
            out.append({"name": f"LLM ({settings.llm_provider})", "ok": not missing,
                        "detail": f"key valid; {fast} / {smart}" + (f"; NOT AVAILABLE: {missing}" if missing else ""), "ms": int((_t.time() - t0) * 1000)})
        except Exception as e:  # noqa: BLE001
            out.append({"name": f"LLM ({settings.llm_provider})", "ok": False, "detail": str(e)[:200], "ms": int((_t.time() - t0) * 1000)})
    else:
        out.append({"name": "LLM", "ok": False, "detail": "not configured (set FINN_LLM_API_KEY)", "ms": 0})
    h._breaker.clear()
    return {"checked_at": end.isoformat(), "probes": out, "snapshot": snapshot.label(),
            "snapshot_reports": snapshot.report_symbols()}


@app.get("/api/indices")
def get_indices():
    return market.indices()


class HoldingsReq(BaseModel):
    holdings: list[hd.Holding] = Field(default_factory=list, max_length=100)


@app.post("/api/holdings/value")
def holdings_value(r: HoldingsReq):
    return hd.value(r.holdings)


@app.get("/api/holdings/example")
def holdings_example():
    return {"holdings": hd.example(),
            "note": "Example only: quantities are illustrative; cost = each stock's actual close about 60 sessions ago."}


class BriefingReq(BaseModel):
    holdings: list[str] = Field(default_factory=list, max_length=100)


@app.post("/api/briefing")
def get_briefing(r: BriefingReq):
    return briefing.build([portfolio.normalise_ticker(s) for s in r.holdings if portfolio.normalise_ticker(s)])


@app.post("/api/copilot")
def ask_copilot(r: copilot.CopilotReq):
    return copilot.answer(r)


@app.get("/api/portfolio")
def get_portfolio():
    return {"portfolio": portfolio.portfolio(), "research_demos": portfolio.research_demos()}


@app.get("/api/feed")
def feed(hours: float = Query(24, gt=0, le=744), start: date | None = None, end: date | None = None):
    s = e = None
    if start:
        s = datetime.combine(start, dtime.min, IST)
        e = datetime.combine(end or date.today(), dtime.max, IST)
        if e < s:
            raise ValueError("end must be on or after start")
    return push.build_feed(hours=hours, start=s, end=e)


@app.get("/api/announcements/{uid:path}")
def announcement(uid: str):
    d = push.filing_detail(uid)
    if not d:
        raise HTTPException(404, "Unknown announcement - reload the feed")
    return d


@app.get("/api/alerts")
def alerts():
    return push.alerts()


class AlertPrefs(BaseModel):
    categories: list[str] = Field(default_factory=list)
    min_tier: str = "medium"
    price_move_pct: float = Field(4.0, gt=0, le=50)
    volume_multiple: float = Field(2.0, gt=1, le=50)
    volume_window: int = Field(20, ge=5, le=120)

    @field_validator("categories")
    @classmethod
    def _cats(cls, v):
        bad = [c for c in v if c not in CATEGORIES]
        if bad:
            raise ValueError(f"unknown categories: {bad}")
        return v

    @field_validator("min_tier")
    @classmethod
    def _tier(cls, v):
        if v not in ("high", "medium", "low"):
            raise ValueError("min_tier must be high|medium|low")
        return v


@app.get("/api/prefs/alerts")
def get_prefs():
    return push.alert_prefs()


@app.put("/api/prefs/alerts")
def put_prefs(p: AlertPrefs):
    storage.pref_set("alerts", p.model_dump())
    return push.alert_prefs()


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=60)):
    local = [{"symbol": c["symbol"], "name": c["name"], "in_portfolio": True} for c in portfolio.portfolio()
             if q.upper() in c["symbol"] or q.lower() in c["name"].lower()]
    try:
        remote = [{**r, "in_portfolio": bool(portfolio.by_symbol(r["symbol"]))} for r in screener.search(q)]
        err = None
    except SourceError as e:
        remote, err = [], e.message
    seen, out = set(), []
    for r in local + remote:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            out.append(r)
    return {"results": out[:10], "remote_error": err}


class ResearchReq(BaseModel):
    query: str = Field(..., min_length=1, max_length=60)
    force: bool = False


@app.post("/api/research")
def research_start(r: ResearchReq):
    return research.start(r.query, r.force)


@app.get("/api/research/jobs/{job_id}")
def research_job(job_id: str):
    j = research.get(job_id)
    if not j:
        raise HTTPException(404, "Unknown job (the server may have restarted) - start the research again")
    return j


# ---------------------------------------------------------------- frontend
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
