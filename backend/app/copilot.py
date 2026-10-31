"""Copilot: questions answered only from what FINN has already retrieved and computed.

Retrieval is deterministic and scoped: FINN works out which companies and topics the question is about, then pulls
the matching facts (prices, filings and their parsed results, research metrics and guidance verdicts, the user's
holdings, index levels). The smart model writes the answer citing those source ids; FINN then checks every number
against the cited sources and marks anything it can't support. No web search, no outside knowledge.
"""
from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, Field

from . import holdings as hd
from . import llm, market, portfolio, snapshot, storage
from .config import settings
from .push import service as push


class Block(BaseModel):
    text: str = Field(description="1-3 sentences")
    cites: list[str] = Field(default_factory=list, description="source ids supporting this block")


class Answer(BaseModel):
    blocks: list[Block] = Field(description="2-5 short blocks answering the question")
    missing: list[str] = Field(default_factory=list, description="What the sources do NOT cover that the question needs")
    follow_ups: list[str] = Field(default_factory=list, description="<=3 natural next questions")


class Turn(BaseModel):
    role: str
    text: str = Field(max_length=2000)


class CopilotReq(BaseModel):
    question: str = Field(min_length=2, max_length=600)
    symbol: str | None = None
    uid: str | None = None
    page: str | None = None
    holdings: list[hd.Holding] = Field(default_factory=list, max_length=100)
    history: list[Turn] = Field(default_factory=list, max_length=8)


GENERIC_FIRST = {"tata", "bajaj", "hindustan", "state", "indian", "sun", "larsen", "dr."}
PORTFOLIO_RE = re.compile(r"\b(my |portfolio|holding|holdings|p&l|pnl|allocation|invested|own)\b", re.I)
MARKET_RE = re.compile(r"\b(market|nifty|sensex|index|indices|today|sector)\b", re.I)


def _report(sym: str) -> dict | None:
    return storage.cache_get_stale(f"report:v2:{sym}") or snapshot.report(sym)


def detect_symbols(q: str, extra: list[str]) -> list[str]:
    known = {c["symbol"]: c["name"] for c in portfolio.portfolio()}
    known.update({d["symbol"]: d["name"] for d in portfolio.research_demos()})
    for s in extra:
        known.setdefault(s, s)
    for s in snapshot.report_symbols():
        known.setdefault(s, s)
    low = q.lower()
    found = []
    for sym, name in known.items():
        nm = name.lower()
        first = nm.split()[0]
        if (re.search(rf"(?<![a-z0-9]){re.escape(sym.lower())}(?![a-z0-9])", low) or nm in low
                or (len(first) >= 5 and first not in GENERIC_FIRST and re.search(rf"\b{re.escape(first)}\b", low))
                or (len(nm.split()) > 1 and " ".join(nm.split()[:2]) in low)):
            found.append(sym)
    return found[:4]


def gather(req: CopilotReq) -> tuple[list[dict], list[str]]:
    srcs: list[dict] = []
    held = [h.symbol for h in req.holdings]
    syms = detect_symbols(req.question + " " + " ".join(t.text for t in req.history[-2:] if t.role == "user"), held)
    if req.symbol and req.symbol not in syms:
        syms.insert(0, req.symbol)

    def add(sid, kind, title, text, url=None):
        if sid not in {s["id"] for s in srcs}:
            srcs.append({"id": sid, "kind": kind, "title": title, "text": text[:700], "url": url})

    feed = push.build_feed(hours=168)
    if req.uid:
        it = next((i for i in feed["items"] if i["uid"] == req.uid), None) or storage.cache_get_stale(f"ann:{req.uid}")
        if it:
            add(f"F:{it['uid']}", "filing", f"{it['company']}: {it['subject']}", _filing_text(it), it.get("url"))
            if it["symbol"] not in syms:
                syms.insert(0, it["symbol"])
    eod = market.get_eod(syms) if syms else {"series": {}}
    for s in syms[:3]:
        w = portfolio.by_symbol(s) or {}
        bars = eod["series"].get(s) or []
        if bars:
            q = market.latest(bars)
            m1 = bars[-22]["close"] if len(bars) > 22 else None
            m3 = bars[0]["close"]
            add(f"P:{s}", "price", f"{s} price (Yahoo Finance)",
                f"{w.get('name', s)} ({s}{', ' + w['sector'] if w.get('sector') else ''}) closed at ₹{q['value']:,.2f} on {q['as_of']}"
                + (f", {q['change_pct']:+.2f}% on the day" if q["change_pct"] is not None else "")
                + (f"; {((q['value'] / m1) - 1) * 100:+.1f}% over ~1 month" if m1 else "")
                + f"; {((q['value'] / m3) - 1) * 100:+.1f}% since {bars[0]['date']}.")
        for it in [i for i in feed["items"] if i["symbol"] == s and i["tier"] != "low"][:4]:
            add(f"F:{it['uid']}", "filing", f"{it['company']}: {it['subject']}", _filing_text(it), it.get("url"))
        rep = _report(s)
        if rep:
            M = rep.get("metrics", {})
            keys = ["revenue_fy", "rev_growth_fy", "opm_fy", "pat_fy", "rev_cagr_3y", "rev_cagr_5y", "pat_cagr_5y", "rev_yoy_q", "pat_yoy_q", "roce", "roe", "de", "cfo_pat_cum", "fcf_cum"]
            lines = [f"{M[k]['label']}: {M[k]['value']} {M[k]['unit']} ({M[k]['period']})" for k in keys if k in M and M[k].get("value") is not None]
            add(f"R:{s}", "research", f"{rep['name']} research report (primary sources)",
                (rep["sections"].get("headline") or "") + " " + "; ".join(lines), f"#/research/{s}")
            g = rep["sections"].get("guidance", {})
            if g.get("rows"):
                add(f"G:{s}", "guidance", f"{rep['name']}: management guidance vs delivery",
                    " | ".join(f"[{r['verdict']}] {r.get('call_date')}: \"{r['quote'][:140]}\" -> {r['reason']}" for r in g["rows"][:5]), f"#/research/{s}")
            bb = rep["sections"].get("bull_bear", {})
            if bb.get("bull") or bb.get("bear"):
                add(f"B:{s}", "research", f"{rep['name']}: bull and bear points",
                    "For: " + "; ".join(c["text"] for c in bb.get("bull", [])[:3]) + " Against: " + "; ".join(c["text"] for c in bb.get("bear", [])[:3]), f"#/research/{s}")
    if req.holdings and (PORTFOLIO_RE.search(req.question) or req.page == "portfolio" or not syms):
        v = hd.value(req.holdings)
        t = v["totals"]
        if t["value"] is not None:
            add("H:total", "holdings", "Your holdings (valued by FINN)",
                f"{t['count']} holdings; invested ₹{t['invested_priced']:,.0f}, now worth ₹{t['value']:,.0f}, unrealised P&L ₹{t['pnl']:,.0f} ({t['pnl_pct']:+.2f}%)"
                + (f"; today {t['day_change']:+,.0f} ({t['day_change_pct']:+.2f}%)" if t["day_change_pct"] is not None else "")
                + f". Prices as of {t['as_of']}. Best: {v['best']}; worst: {v['worst']}. Sector mix: "
                + ", ".join(f"{a['name']} {a['pct']:.1f}%" for a in v["allocation"]["sector"][:6]), "#/portfolio")
            for r in v["holdings"][:12]:
                if r["value"] is not None:
                    add(f"H:{r['symbol']}", "holdings", f"Holding: {r['symbol']}",
                        f"{r['symbol']}: {r['qty']:g} shares at avg ₹{r['avg_price']:,.2f}; price ₹{r['price']:,.2f}; value ₹{r['value']:,.0f}; P&L {r['pnl_pct']:+.2f}%; weight {r['weight']:.1f}%.", "#/portfolio")
    if MARKET_RE.search(req.question) or not srcs:
        for i in market.indices()["indices"]:
            if i["value"] is not None and i["change_pct"] is not None:
                add(f"I:{i['key']}", "index", f"{i['name']} (Yahoo Finance)", f"{i['name']} at {i['value']:,.2f}, {i['change_pct']:+.2f}% on the day, as of {i['as_of']}.")
        for it in [i for i in feed["items"] if i["tier"] == "high"][:5]:
            add(f"F:{it['uid']}", "filing", f"{it['company']}: {it['subject']}", _filing_text(it), it.get("url"))
    return srcs[:24], syms


def _filing_text(it: dict) -> str:
    t = f"{it['published'][:10]} {it['exchange']} filing, category {it['category']}, ranked {it['tier']}: {it['summary']}"
    d = storage.cache_get_stale(f"anndetail:v2:{it['uid']}") or {}
    r = (d.get("results") or {}).get("metrics") or {}
    for k in ("revenue", "ebitda", "pbt", "pat"):
        m = r.get(k) or {}
        if m.get("current") is not None:
            t += f" {m['label']} ₹{m['current']:,.1f} cr" + (f" (QoQ {m['qoq_pct']:+.1f}%" if m.get("qoq_pct") is not None else " (") + (f", YoY {m['yoy_pct']:+.1f}%)" if m.get("yoy_pct") is not None else ")") + ";"
    p = (d.get("people") or {})
    if p.get("names"):
        t += f" People named: {', '.join(p['names'][:3])}."
    return t


NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _supported(text: str, cites: list[str], by_id: dict) -> tuple[bool, list[str]]:
    pool = " ".join(by_id[c]["text"] for c in cites if c in by_id)
    if not pool:
        return False, ["no valid citation"]
    have = [float(n.replace(",", "")) for n in NUM.findall(pool) if n.replace(",", "").replace("-", "").replace(".", "").isdigit()]
    bad = []
    for n in NUM.findall(text):
        x = n.replace(",", "")
        try:
            v = float(x)
        except ValueError:
            continue
        if len(x.lstrip("-").replace(".", "")) < 2 or (1900 < v < 2100 and "." not in x):
            continue
        if not any(abs(abs(v) - abs(h)) <= max(0.06, abs(h) * 0.005) for h in have):
            bad.append(n)
    return not bad, [f"{b} not in cited sources" for b in bad]


def answer(req: CopilotReq) -> dict:
    srcs, syms = gather(req)
    by_id = {s["id"]: s for s in srcs}
    actions = [{"type": "research", "symbol": s} for s in syms if not _report(s)]
    public = [{k: v for k, v in s.items()} for s in srcs]
    if not settings.llm_enabled:
        return {"blocks": [], "sources": public, "actions": actions, "origin": "none", "missing": [],
                "follow_ups": [], "note": "Copilot needs an AI model (set FINN_LLM_API_KEY). The sources FINN would use are listed below."}
    if not srcs:
        return {"blocks": [{"text": "I don't have data on that yet. Try naming a company on your watchlist, or run Research on it first.", "cites": [], "verified": True}],
                "sources": [], "actions": actions, "origin": "llm", "missing": [], "follow_ups": []}
    hist = "\n".join(f"{t.role}: {t.text[:400]}" for t in req.history[-4:])
    prompt = ("Answer the investor's question using ONLY the sources. Cite source ids for every claim. Copy numbers exactly "
              "from sources; do not compute new figures. If the sources don't cover something, put it in 'missing' instead of guessing. "
              "No buy/sell advice, no price predictions. Be concise.\n"
              + (f"Conversation so far:\n{hist}\n" if hist else "") + f"Question: {req.question}\nSOURCES:\n"
              + llm.doc_block([(s["id"], f"{s['title']}\n{s['text']}") for s in srcs]))
    try:
        out = llm.complete_json(Answer, tier="smart", purpose="copilot", max_tokens=1500, prompt=prompt, cache_ttl_s=3600)
    except llm.LLMError as e:
        return {"blocks": [], "sources": public, "actions": actions, "origin": "error", "missing": [], "follow_ups": [],
                "note": f"The AI model didn't answer ({llm.public_message(e)}). The sources FINN found are listed below."}
    blocks = []
    for b in out.blocks:
        cites = [c for c in b.cites if c in by_id]
        ok, issues = _supported(b.text, cites, by_id)
        blocks.append({"text": b.text, "cites": cites, "verified": ok, "issues": issues})
    used = {c for b in blocks for c in b["cites"]}
    return {"blocks": blocks, "sources": [s for s in public if s["id"] in used] + [s for s in public if s["id"] not in used],
            "actions": actions, "origin": "llm", "missing": out.missing, "follow_ups": out.follow_ups[:3], "model": llm.models()[1],
            "id": hashlib.sha1(json.dumps([req.question, [s['id'] for s in srcs]]).encode()).hexdigest()[:10]}
