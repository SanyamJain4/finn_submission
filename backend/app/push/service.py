"""Push orchestration: windowed digest, filing detail, triggered alerts."""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from .. import llm, market, portfolio, snapshot, storage
from ..config import settings
from ..documents import get_document
from . import people, results
from .classify import classify
from .prioritise import score
from .sources import IST, RawAnnouncement, get_announcements

log = logging.getLogger("finn.push")

DEFAULT_ALERT_PREFS = {
    "categories": ["results", "M&A", "management_change", "fund_raise", "litigation", "credit_rating", "pledging", "capex"],
    "min_tier": "medium",
    **market.DEFAULT_RULES,
}
TIER_RANK = {"high": 0, "medium": 1, "low": 2}


def alert_prefs() -> dict:
    return {**DEFAULT_ALERT_PREFS, **storage.pref_get("alerts", {})}


def _norm_subject(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())[:60]


def dedupe(items: list[RawAnnouncement]) -> list[RawAnnouncement]:
    seen_uid, seen_key, out = set(), set(), []
    for i in sorted(items, key=lambda x: x.published):
        k = (i.symbol, _norm_subject(i.subject + i.text[:80]), i.published[:16])
        if i.uid in seen_uid or k in seen_key:
            continue
        seen_uid.add(i.uid)
        seen_key.add(k)
        out.append(i)
    return out


ABBREV = {"mr", "ms", "mrs", "dr", "rs", "no", "co", "ltd", "smt", "sh", "shri", "vs", "inr", "pvt", "st"}


def one_liner(text: str, subject: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t or t.lower() == subject.lower():
        return subject
    # Split on sentence ends, but not after honorifics/abbreviations common in Indian filings (Mr., Ms., Rs., Ltd.).
    first = t
    for m in re.finditer(r"[.;]\s+(?=[A-Z])", t):
        prev = re.search(r"(\w+)$", t[:m.start()])
        if prev and prev.group(1).lower() in ABBREV:
            continue
        first = t[:m.start() + 1]
        break
    return first if len(first) <= 240 else first[:237].rsplit(" ", 1)[0] + "…"


def market_snapshot(rules: dict) -> dict:
    syms = [c["symbol"] for c in portfolio.portfolio()]
    eod = market.get_eod(syms)
    rows = {}
    for s in syms:
        bars = eod["series"].get(s) or []
        d = market.detect(bars, rules) if bars else {"status": "no_data", "signals": []}
        d["provider_status"] = eod["status"].get(s)
        d["spark"] = market.sparkline(bars)
        rows[s] = d
    return {"provider": eod["provider"], "by_symbol": rows}


def build_feed(hours: float = 24, start: datetime | None = None, end: datetime | None = None) -> dict:
    end = end or datetime.now(IST)
    start = start or end - timedelta(hours=hours)
    if end - start > timedelta(days=31):
        raise ValueError("Window cannot exceed 31 days")
    prefs = alert_prefs()
    raw = get_announcements(start, end)
    if raw.get("snapshot"):
        # Live sources are blocked: anchor the window to the capture time so "last 24 hours" means the 24 hours
        # before the snapshot, and say so in the UI.
        cap = datetime.fromisoformat(raw["snapshot"]["captured_at"])
        if end > cap:
            span = end - start
            end, start = cap, cap - span
            raw = get_announcements(start, end)
    try:
        mkt = market_snapshot(prefs)
    except Exception as e:  # market data must never break the filings digest
        log.warning("market snapshot failed: %s", e)
        mkt = {"provider": None, "by_symbol": {}, "error": str(e)}
    items = dedupe(raw["items"])
    counts: dict[tuple, int] = defaultdict(int)
    feed = []
    for i in sorted(items, key=lambda x: x.published):
        cls = classify(i.subject, i.text)
        m = mkt["by_symbol"].get(i.symbol, {})
        move = "; ".join(sig["text"] for sig in m.get("signals", [])) or None
        rep = counts[(i.symbol, cls.category)]
        counts[(i.symbol, cls.category)] += 1
        pr = score(cls.category, cls.confidence, i.subject, i.text, market_move=move, repeat_index=rep, has_document=bool(i.url))
        co = portfolio.by_symbol(i.symbol) or {}
        item = {
            **i.to_dict(), "company": co.get("name", i.company), "sector": co.get("sector"),
            "category": cls.category, "category_confidence": cls.confidence, "category_rule": cls.rule,
            "priority": pr.score, "tier": pr.tier, "why": pr.reasons, "summary": one_liner(i.text, i.subject),
            "enrichment": "results" if cls.category == "results" and pr.score >= 50 else
                          "people" if cls.category == "management_change" else None,
        }
        storage.cache_set(f"ann:{i.uid}", item, 30 * 86400)
        feed.append(item)
    feed.sort(key=lambda x: (TIER_RANK[x["tier"]], -x["priority"], x["published"]), reverse=False)
    # within tier newest first for equal priority
    feed.sort(key=lambda x: (TIER_RANK[x["tier"]], -x["priority"], -datetime.fromisoformat(x["published"]).timestamp()))
    by_tier = {t: sum(1 for x in feed if x["tier"] == t) for t in ("high", "medium", "low")}
    by_cat: dict[str, int] = defaultdict(int)
    for x in feed:
        by_cat[x["category"]] += 1
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "items": feed, "counts": {"tier": by_tier, "category": dict(by_cat), "total": len(feed)},
        "sources": raw["sources"], "market": mkt, "fixture": settings.fixture_mode,
        "snapshot": raw.get("snapshot"),
    }


class FilingSummary(BaseModel):
    summary: str = Field(description="One sentence, <= 35 words, what the filing says. Only facts in the document.")
    key_facts: list[str] = Field(default_factory=list, description="Up to 3 short verbatim-grounded facts (amounts, dates, names)")


KEY_LINE_RE = re.compile(r"(approv|appoint|resign|declar|allot|record date|crore|lakh|acquir|order|rating|penalt|demand|dividend|effective)", re.I)


def key_lines(pages: list[str], limit: int = 5) -> list[dict]:
    out = []
    for pno, p in enumerate(pages[:5], 1):
        for sent in re.split(r"(?<=[.])\s+|\n", p):
            s = re.sub(r"\s+", " ", sent).strip()
            if 40 <= len(s) <= 320 and KEY_LINE_RE.search(s) and not re.search(r"regulation 30|listing obligations|dear sir|madam", s, re.I):
                out.append({"page": pno, "text": s})
                if len(out) >= limit:
                    return out
    return out


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s) if len(n.replace(",", "")) >= 2}


def filing_detail(uid: str) -> dict | None:
    item = storage.cache_get(f"ann:{uid}") or storage.cache_get_stale(f"ann:{uid}")
    if not item:
        return None
    cached = storage.cache_get(f"anndetail:{uid}")
    if cached:
        return cached
    detail = {"item": item, "document": None, "results": None, "people": None, "key_lines": [], "llm_summary": None, "notes": []}
    if not item.get("url"):
        detail["notes"].append("No attachment was filed with this announcement; showing exchange text only.")
        return detail
    doc = get_document(item["url"])
    detail["document"] = {"status": doc.status, "detail": doc.detail, "pages": len(doc.pages)}
    snap = snapshot.details().get(uid)
    if doc.status != "ok" and snap:
        snap = {**snap, "item": item, "snapshot": snapshot.label()}
        snap.setdefault("notes", []).append(f"Filing read when the snapshot was captured ({snapshot.label()['captured_at'][:16]}); this server can't download it live.")
        return snap
    if doc.status != "ok":
        detail["notes"].append(f"Filing could not be read: {doc.detail}. The original link still works.")
        return detail
    # Each enrichment fails independently: a parser bug must never hide the filing itself.
    if item["category"] == "results":
        try:
            detail["results"] = results.extract_results(doc.pages).to_dict()
        except Exception as e:  # noqa: BLE001
            log.exception("results extraction failed for %s", uid)
            detail["notes"].append(f"Results extraction failed ({type(e).__name__}); open the original filing.")
    if item["category"] == "management_change":
        try:
            detail["people"] = people.extract_people(doc.pages, item["subject"] + " " + item["company"])
        except Exception as e:  # noqa: BLE001
            log.exception("people extraction failed for %s", uid)
            detail["notes"].append(f"Profile extraction failed ({type(e).__name__}).")
    detail["key_lines"] = key_lines(doc.pages)
    if settings.llm_enabled and item["tier"] in ("high", "medium") and item["category"] != "results":
        try:
            text = "\n".join(doc.pages[:4])[:8000]
            s = llm.complete_json(FilingSummary, purpose="filing_summary",
                                  prompt=f"Company: {item['company']}\nSubject: {item['subject']}\n" + llm.doc_block([("filing", text)]))
            unsupported = _numbers(s.summary + " ".join(s.key_facts)) - _numbers(text)
            detail["llm_summary"] = {**s.model_dump(), "grounded": not unsupported,
                                     "unsupported_numbers": sorted(unsupported)}
        except Exception as e:  # noqa: BLE001 - LLMError or anything unexpected
            detail["notes"].append(f"AI summary unavailable: {e if isinstance(e, llm.LLMError) else type(e).__name__}")
    storage.cache_set(f"anndetail:{uid}", detail, 7 * 86400)
    return detail


def alerts(feed: dict | None = None) -> dict:
    prefs = alert_prefs()
    feed = feed or build_feed(24)
    cats = set(prefs["categories"])
    min_rank = TIER_RANK[prefs["min_tier"]]
    filings = [x for x in feed["items"] if x["category"] in cats and TIER_RANK[x["tier"]] <= min_rank]
    market_alerts = []
    for sym, d in feed["market"].get("by_symbol", {}).items():
        for sig in d.get("signals", []):
            co = portfolio.by_symbol(sym) or {}
            market_alerts.append({"symbol": sym, "company": co.get("name", sym), "as_of": d.get("as_of"), **sig})
    return {"prefs": prefs, "filing_alerts": filings, "market_alerts": market_alerts,
            "checked_at": datetime.now(IST).isoformat(), "market_provider": feed["market"].get("provider"),
            "note": "End-of-day signals computed on the last completed session; this is a pull-to-check, not a real-time stream."}
