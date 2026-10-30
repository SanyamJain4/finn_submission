from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import llm, portfolio, storage
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
