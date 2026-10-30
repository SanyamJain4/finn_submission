"""Pull research orchestration.

Pipeline: resolve -> standardised financials -> discover primary docs -> fetch & parse (page-level) ->
BM25 evidence per question -> (fast LLM) business + guidance extraction -> deterministic verdicts ->
(smart LLM) one synthesis call -> deterministic groundedness check -> report.

LLM budget per report: 1 business + <=4 guidance + 1 synthesis (<= settings.llm_max_calls_per_research),
all cached by prompt hash, so a repeated report costs zero model calls.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, Field

from .. import llm, portfolio, storage
from ..config import settings
from ..documents import BM25, chunk_pages, get_document
from ..http import SourceError
from . import analysis as an
from . import guidance as gd
from . import screener

log = logging.getLogger("finn.research")
_pool = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
STAGES = ["resolve", "financials", "documents", "business", "guidance", "synthesis", "verify"]


# ------------------------------------------------------------------ schemas for LLM output

class Claim(BaseModel):
    text: str = Field(description="One concise sentence")
    evidence: list[str] = Field(description="ids of <document> passages (E..) and/or metric ids (M:..) that support it")
    kind: Literal["fact", "management", "interpretation"] = "interpretation"


class Segment(BaseModel):
    name: str
    share_of_revenue_pct: float | None = None
    evidence: list[str] = Field(default_factory=list)


class BusinessSnapshot(BaseModel):
    what_it_does: Claim
    segments: list[Segment] = Field(default_factory=list)
    other_points: list[Claim] = Field(default_factory=list, description="<=3 points: customers, geographies, moats as stated in the documents")
    not_found: list[str] = Field(default_factory=list, description="Things you looked for but the passages did not cover")


class Synthesis(BaseModel):
    headline: str = Field(description="<= 25 words: the single most important takeaway, grounded")
    trajectory: list[Claim] = Field(default_factory=list, description="<=3")
    balance_sheet: list[Claim] = Field(default_factory=list, description="<=3")
    cash_quality: list[Claim] = Field(default_factory=list, description="<=3")
    narrative_vs_numbers: list[Claim] = Field(default_factory=list, description="<=3 reading the verdict table")
    bull: list[Claim] = Field(default_factory=list, description="3-4")
    bear: list[Claim] = Field(default_factory=list, description="3-4")
    open_questions: list[str] = Field(default_factory=list, description="<=3 things an analyst should ask next")


# ------------------------------------------------------------------ jobs

def start(query: str, force: bool = False) -> dict:
    sym = resolve(query)
    if not force:
        cached = storage.cache_get(f"report:{sym['symbol']}")
        if cached:
            return {"job_id": None, "status": "done", "report": cached, "cached": True}
    with _jobs_lock:
        for j in _jobs.values():
            if j["symbol"] == sym["symbol"] and j["status"] == "running":
                return _public(j)
        jid = uuid.uuid4().hex[:12]
        job = {"job_id": jid, "symbol": sym["symbol"], "name": sym.get("name"), "status": "running",
               "stage": "resolve", "stages_done": [], "started": time.time(), "report": None, "error": None}
        _jobs[jid] = job
    _pool.submit(_run, job)
    return _public(job)


def get(jid: str) -> dict | None:
    j = _jobs.get(jid)
    return _public(j) if j else None


def _public(j: dict) -> dict:
    return {k: j[k] for k in ("job_id", "symbol", "name", "status", "stage", "stages_done", "error", "report")} | {
        "elapsed_s": round(time.time() - j["started"], 1), "stages": STAGES}


def resolve(query: str) -> dict:
    q = (query or "").strip()
    if not q or len(q) > 60:
        raise ValueError("Enter an NSE ticker or company name")
    sym = portfolio.normalise_ticker(q)
    if sym and (portfolio.by_symbol(sym) or " " not in q):
        co = portfolio.by_symbol(sym)
        return {"symbol": sym, "name": co["name"] if co else None}
    hits = screener.search(q)
    if not hits:
        raise ValueError(f"No listed company found for '{q}'")
    return {"symbol": hits[0]["symbol"], "name": hits[0]["name"]}


def _stage(job: dict, name: str) -> None:
    if job["stage"] and job["stage"] not in job["stages_done"]:
        job["stages_done"].append(job["stage"])
    job["stage"] = name


def _run(job: dict) -> None:
    try:
        rep = build_report(job["symbol"], lambda s: _stage(job, s))
        job["report"] = rep
        job["status"] = "done"
        _stage(job, "")
        storage.cache_set(f"report:{job['symbol']}", rep, 24 * 3600)
    except (SourceError, ValueError) as e:
        job["status"], job["error"] = "error", str(e)
    except Exception as e:  # noqa: BLE001 - report any crash to the UI rather than hanging
        log.error("research crashed: %s\n%s", e, traceback.format_exc())
        job["status"], job["error"] = "error", f"Internal error: {type(e).__name__}"


# ------------------------------------------------------------------ the report

def build_report(symbol: str, stage=lambda s: None) -> dict:
    t0 = time.time()
    limits: list[str] = []
    stage("financials")
    co = screener.company(symbol)
    sources = [{"id": "S1", "kind": "standardised_financials", "title": f"Standardised {co.get('basis', '')} statements",
                "publisher": "Screener.in (compiled from exchange filings)", "url": co["url"], "date": co["retrieved"][:10], "status": "ok"}]
    A = an.analyse(co, "S1")
    if not A["trajectory"]:
        limits.append("No annual P&L history was available; trajectory and cash sections are empty.")
    if not A["capex_available"]:
        limits.append("Capex schedule not retrieved, so free cash flow is not computed.")

    # ---- documents
    stage("documents")
    docs = co["documents"]
    evidence: dict[str, dict] = {}
    chunks = []
    ars = sorted([d for d in docs["annual_reports"] if d.get("year")], key=lambda d: -d["year"])[:1]
    for i, d in enumerate(ars, 1):
        sid = f"AR{i}"
        doc = get_document(d["url"])
        sources.append({"id": sid, "kind": "annual_report", "title": f"Annual Report FY{d['year']}", "url": d["url"],
                        "date": str(d["year"]), "status": doc.status, "detail": doc.detail, "pages": len(doc.pages)})
        if doc.status == "ok":
            chunks += chunk_pages(sid, doc.pages)
    if not ars:
        limits.append("No annual report link found; business snapshot relies on transcripts only.")
    transcripts = [c for c in docs["concalls"] if c.get("transcript")][:4]
    t_ids = []
    for i, c in enumerate(transcripts, 1):
        sid = f"T{i}"
        doc = get_document(c["transcript"])
        sources.append({"id": sid, "kind": "transcript", "title": f"Earnings call transcript {c.get('date_label', '')}",
                        "url": c["transcript"], "date": c.get("date"), "status": doc.status, "detail": doc.detail, "pages": len(doc.pages)})
        if doc.status == "ok":
            chunks += chunk_pages(sid, doc.pages)
            t_ids.append((sid, c, doc))
    failed = [s for s in sources if s["status"] != "ok"]
    if failed:
        limits.append(f"{len(failed)} document(s) could not be read: " + ", ".join(f"{s['title']} ({s.get('detail', s['status'])})" for s in failed))
    if not transcripts:
        limits.append("No earnings-call transcripts listed; guidance tracking is unavailable.")
    index = BM25(chunks) if chunks else None

    def retrieve(query: str, k: int, doc_ids: set[str] | None = None) -> list[tuple[str, str]]:
        if not index:
            return []
        out = []
        for _, ch in index.search(query, k, doc_ids):
            eid = f"E{len(evidence) + 1}"
            key = (ch.doc_id, ch.page, ch.text[:60])
            existing = next((k2 for k2, v in evidence.items() if (v["source"], v["page"], v["text"][:60]) == key), None)
            if existing:
                out.append((existing, ch.text))
                continue
            evidence[eid] = {"id": eid, "source": ch.doc_id, "page": ch.page, "text": ch.text}
            out.append((eid, ch.text))
        return out

    calls_left = settings.llm_max_calls_per_research
    sections: dict = {}

    # ---- business snapshot (fast)
    stage("business")
    biz_passages = retrieve("business overview segments products services revenue mix customers geographies principal activities", 7,
                            {s["id"] for s in sources if s["kind"] == "annual_report"} or None)
    if settings.llm_enabled and biz_passages and calls_left > 0:
        try:
            calls_left -= 1
            b = llm.complete_json(BusinessSnapshot, tier="fast", purpose="business", prompt=(
                "Describe what the company does using ONLY these passages from its own documents. "
                "Give revenue shares only if a passage states them.\n" + llm.doc_block(biz_passages)))
            sections["business"] = {"status": "ok", **b.model_dump()}
        except llm.LLMError as e:
            sections["business"] = {"status": "error", "detail": str(e), "passages": [eid for eid, _ in biz_passages]}
    else:
        sections["business"] = {"status": "llm_disabled" if not settings.llm_enabled else "no_documents",
                                "passages": [eid for eid, _ in biz_passages[:4]]}

    # ---- guidance (fast, one call per transcript, newest 4)
    stage("guidance")
    rows, candidates = [], []
    for sid, c, doc in t_ids:
        passages = retrieve(gd.GUIDE_QUERY, 5, {sid})
        if settings.llm_enabled and passages and calls_left > 1:
            try:
                calls_left -= 1
                g = llm.complete_json(gd.GuidanceExtraction, tier="fast", purpose="guidance", prompt=(
                    f"Earnings call dated {c.get('date_label')} (Indian fiscal year runs April-March). "
                    "Extract up to 5 explicit forward-looking statements by management about revenue/growth, margins, "
                    "profit or capex. Copy quotes exactly. Do not invent targets from vague language; mark those measurable=false.\n"
                    + llm.doc_block(passages)), max_tokens=2500)
                valid_ids = {eid for eid, _ in passages}
                for st in g.statements:
                    if st.evidence_id not in valid_ids:
                        continue
                    if not _quote_in(st.quote, evidence[st.evidence_id]["text"]):
                        continue  # model paraphrased or invented the quote
                    r = gd.evaluate(st, A, A["is_bank"])
                    r["call_date"] = c.get("date_label")
                    r["source"] = sid
                    r["page"] = evidence[st.evidence_id]["page"]
                    rows.append(r)
            except llm.LLMError as e:
                limits.append(f"Guidance extraction failed for {c.get('date_label')}: {e}")
        else:
            for cand in gd.candidate_sentences(doc.pages, 3):
                eid = f"E{len(evidence) + 1}"
                evidence[eid] = {"id": eid, "source": sid, "page": cand["page"], "text": cand["text"]}
                candidates.append({"evidence": eid, "call_date": c.get("date_label"), "text": cand["text"]})
    order = {"missed": 0, "exceeded": 1, "met": 2, "pending": 3, "cannot_evaluate": 4, "qualitative": 5}
    rows.sort(key=lambda r: order.get(r["verdict"], 9))
    tally = {k: sum(1 for r in rows if r["verdict"] == k) for k in order}
    sections["guidance"] = {"status": "ok" if rows else ("candidates_only" if candidates else "none"),
                            "rows": rows, "tally": tally, "candidates": candidates,
                            "method": "LLM extracts quotes; FINN verifies the quote and computes the verdict against reported numbers."}

    # ---- synthesis (smart, single call)
    stage("synthesis")
    obs = A["observations"]
    for key in ("trajectory", "balance_sheet", "cash_quality"):
        sections[key] = {"claims": list(obs[key])}
    sections["bull_bear"] = {"bull": list(obs["bull"]), "bear": list(obs["bear"]), "origin": "rules"}
    sections["headline"] = None
    if settings.llm_enabled and calls_left > 0 and (chunks or A["trajectory"]):
        risk_p = retrieve("risk challenge headwind competition pressure decline concern slowdown regulatory", 5)
        outlook_p = retrieve("strategy outlook investment capacity expansion demand opportunity", 4)
        analyst_p = retrieve("question analyst could you explain why decline margin pressure", 3, {s for s, _, _ in t_ids} or None)
        metric_lines = "\n".join(f"{m['id']}: {m['label']} = {m['value']} {m['unit']} ({m['period']})" for m in A["metrics"].values() if m["value"] is not None)
        verdict_lines = "\n".join(f"- [{r['verdict']}] {r['call_date']}: \"{r['quote'][:160]}\" -> {r['reason']}" for r in rows[:8]) or "none extracted"
        try:
            calls_left -= 1
            s = llm.complete_json(Synthesis, tier="smart", purpose="synthesis", max_tokens=3500, prompt=(
                "You are writing an investor research note. Every claim MUST cite evidence ids: metric ids (M:...) from the "
                "METRICS list and/or passage ids (E...). Use only these inputs; quote numbers exactly as given. Label each claim "
                "kind=fact (reported numbers), management (what management says), or interpretation (your reasoning). "
                "No buy/sell recommendation, no price predictions.\n\nMETRICS (computed by FINN, authoritative):\n"
                f"{metric_lines}\n\nGUIDANCE VERDICTS (computed by FINN):\n{verdict_lines}\n\nPASSAGES:\n"
                + llm.doc_block(risk_p + outlook_p + analyst_p)))
            sections["headline"] = s.headline
            for key in ("trajectory", "balance_sheet", "cash_quality"):
                sections[key]["claims"] += [{**c.model_dump(), "origin": "llm"} for c in getattr(s, key)]
            sections["narrative"] = {"claims": [{**c.model_dump(), "origin": "llm"} for c in s.narrative_vs_numbers]}
            sections["bull_bear"] = {"bull": [{**c.model_dump(), "origin": "llm"} for c in s.bull] or obs["bull"],
                                     "bear": [{**c.model_dump(), "origin": "llm"} for c in s.bear] or obs["bear"], "origin": "llm"}
            sections["open_questions"] = s.open_questions
        except llm.LLMError as e:
            limits.append(f"Synthesis unavailable ({e}); showing rule-based observations.")
    elif not settings.llm_enabled:
        limits.append("No LLM configured: narrative sections show rule-based observations computed from the numbers only.")

    # ---- groundedness check
    stage("verify")
    vstats = verify_report(sections, evidence, A["metrics"])
    for e in evidence.values():
        e["text"] = e["text"][:900]
    return {
        "symbol": symbol, "name": co["name"], "bse_code": co.get("bse_code"), "basis": co.get("basis"),
        "in_portfolio": bool(portfolio.by_symbol(symbol)), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - t0, 1), "sources": sources, "evidence": evidence,
        "metrics": A["metrics"], "tables": {k: A[k] for k in ("trajectory", "quarters", "balance_sheet", "working_capital", "cash")},
        "is_bank": A["is_bank"], "sections": sections, "verification": vstats, "limitations": limits,
        "llm": {**llm.status(), "calls_budget": settings.llm_max_calls_per_research, "calls_used": settings.llm_max_calls_per_research - calls_left},
        "fixture": settings.fixture_mode,
    }


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _quote_in(quote: str, text: str) -> bool:
    q, t = _norm(quote), _norm(text)
    if not q:
        return False
    if q in t:
        return True
    # allow small ellipsis/whitespace differences: 85% of 8-char shingles present
    sh = [q[i:i + 8] for i in range(0, max(1, len(q) - 7), 4)]
    return sum(s in t for s in sh) / len(sh) >= 0.85


NUM_IN_TEXT = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _claim_supported(claim: dict, evidence: dict, metrics: dict) -> tuple[bool, list[str]]:
    issues = []
    ids = claim.get("evidence") or []
    known = [i for i in ids if i in evidence or (i.startswith("M:") and i[2:] in metrics)]
    if not known:
        return False, ["cites no valid evidence"]
    pool_nums: list[float] = []
    pool_text = ""
    for i in known:
        if i.startswith("M:"):
            v = metrics[i[2:]]["value"]
            if v is not None:
                pool_nums.append(float(v))
        else:
            pool_text += " " + evidence[i]["text"]
    pool_nums += [float(n.replace(",", "")) for n in NUM_IN_TEXT.findall(pool_text) if n.replace(",", "").replace(".", "").replace("-", "").isdigit()]
    for n in NUM_IN_TEXT.findall(claim["text"]):
        x = n.replace(",", "")
        try:
            val = float(x)
        except ValueError:
            continue
        if len(x.replace(".", "").lstrip("-")) < 2 or (1900 < val < 2100 and "." not in x):
            continue  # skip tiny numbers and years
        if not any(abs(abs(val) - abs(p)) <= max(0.06, abs(p) * 0.01) for p in pool_nums):
            issues.append(f"number {n} not found in cited evidence")
    return not issues, issues


def verify_report(sections: dict, evidence: dict, metrics: dict) -> dict:
    total = ok = 0

    def check(claims: list[dict]) -> None:
        nonlocal total, ok
        for c in claims:
            if c.get("origin") == "rules" or c.get("kind") == "limitation":
                continue  # computed deterministically from metrics
            total += 1
            good, issues = _claim_supported(c, evidence, metrics)
            c["verified"], c["issues"] = good, issues
            ok += good

    for key in ("trajectory", "balance_sheet", "cash_quality"):
        check(sections.get(key, {}).get("claims", []))
    check(sections.get("narrative", {}).get("claims", []))
    check(sections.get("bull_bear", {}).get("bull", []))
    check(sections.get("bull_bear", {}).get("bear", []))
    b = sections.get("business", {})
    if b.get("status") == "ok":
        check([b["what_it_does"]] + b.get("other_points", []))
    return {"llm_claims": total, "verified": ok, "unverified": total - ok,
            "method": "Each AI claim must cite a passage or metric; every number in it must appear in what it cites."}
