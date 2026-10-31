"""Daily briefing: a few sentences on what matters today, built from facts FINN has already verified.

Facts carry ids (I:NIFTY50, M:SUNPHARMA, F:<filing uid>, H:<symbol>). With an LLM the fast model only *rewrites*
those facts into a short note and must cite ids; every number it writes must appear in a cited fact or the line is
dropped. Without an LLM the same facts are assembled by rules, so the briefing never depends on the model.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from pydantic import BaseModel, Field

from . import llm, market, storage
from .config import settings
from .push import service as push
from .push.sources import IST


class Line(BaseModel):
    text: str = Field(description="One sentence, <= 30 words")
    cites: list[str] = Field(description="fact ids supporting the sentence")


class BriefingOut(BaseModel):
    headline: str = Field(description="<= 14 words, the single most important thing today")
    lines: list[Line] = Field(description="3-5 lines, most important first")


def _fmt_num(v: float) -> str:
    return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"


def facts(holdings_symbols: list[str] | None = None) -> tuple[list[dict], dict]:
    held = set(holdings_symbols or [])
    out: list[dict] = []
    idx = market.indices()
    for i in idx["indices"]:
        if i["value"] is not None and i["change_pct"] is not None:
            out.append({"id": f"I:{i['key']}", "kind": "index", "weight": 3 if i["key"] == "NIFTY50" else 1,
                        "text": f"{i['name']} at {_fmt_num(i['value'])}, {i['change_pct']:+.2f}% on the day (as of {i['as_of']})."})
    feed = push.build_feed(hours=24)
    for sym, m in feed["market"].get("by_symbol", {}).items():
        for sig in m.get("signals", []):
            out.append({"id": f"M:{sym}", "kind": "move", "weight": 6 + (3 if sym in held else 0),
                        "text": f"{sym}: {sig['text']} at the close of {m.get('as_of')}."})
            break
    for it in feed["items"]:
        if it["tier"] == "low":
            continue
        detail = storage.cache_get(f"anndetail:v2:{it['uid']}") or {}
        extra = ""
        r = (detail.get("results") or {}).get("metrics") or {}
        if r.get("revenue", {}).get("current") is not None:
            rv, pt = r["revenue"], r.get("pat", {})
            extra = (f" Revenue ₹{rv['current']:,.0f} cr ({rv['yoy_pct']:+.1f}% YoY)" if rv.get("yoy_pct") is not None else f" Revenue ₹{rv['current']:,.0f} cr")
            if pt.get("current") is not None and pt.get("yoy_pct") is not None:
                extra += f", PAT ₹{pt['current']:,.0f} cr ({pt['yoy_pct']:+.1f}% YoY)."
        w = (10 if it["tier"] == "high" else 4) + (4 if it["symbol"] in held else 0)
        out.append({"id": f"F:{it['uid']}", "kind": "filing", "weight": w, "symbol": it["symbol"],
                    "text": f"{it['company']} ({it['symbol']}): {it['summary']}{extra}".strip()})
    out.sort(key=lambda f: -f["weight"])
    return out[:14], {"provider": idx["provider"], "snapshot": feed.get("snapshot"), "window": feed["window"]}


def rule_based(fs: list[dict]) -> dict:
    lines = []
    nifty = next((f for f in fs if f["id"] == "I:NIFTY50"), None)
    if nifty:
        lines.append({"text": nifty["text"], "cites": [nifty["id"]], "verified": True})
    for f in [f for f in fs if f["kind"] == "filing"][:3] + [f for f in fs if f["kind"] == "move"][:2]:
        lines.append({"text": f["text"], "cites": [f["id"]], "verified": True})
    n_high = sum(1 for f in fs if f["kind"] == "filing" and f["weight"] >= 10)
    n_moves = sum(1 for f in fs if f["kind"] == "move")
    parts = [f"{n_high} filing{'s' if n_high != 1 else ''} need{'s' if n_high == 1 else ''} attention" if n_high else "No high-priority filings",
             f"{n_moves} unusual move{'s' if n_moves != 1 else ''}" if n_moves else ""]
    return {"headline": ", ".join(p for p in parts if p),
            "lines": lines[:5], "origin": "rules"}


NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _verify(line: dict, by_id: dict) -> bool:
    cited = " ".join(by_id[c]["text"] for c in line["cites"] if c in by_id)
    if not cited:
        return False
    have = {n.replace(",", "") for n in NUM.findall(cited)}
    for n in NUM.findall(line["text"]):
        x = n.replace(",", "")
        if len(x.replace(".", "")) >= 2 and x not in have and x.rstrip("0").rstrip(".") not in {h.rstrip("0").rstrip(".") for h in have}:
            return False
    return True


def build(holdings_symbols: list[str] | None = None) -> dict:
    fs, meta = facts(holdings_symbols)
    by_id = {f["id"]: f for f in fs}
    base = {"facts": fs, "generated_at": datetime.now(IST).isoformat(timespec="seconds"), **meta}
    if not fs:
        return {**base, "headline": "No market data or filings available right now", "lines": [], "origin": "rules"}
    if not settings.llm_enabled:
        return {**base, **rule_based(fs)}
    key = "brief:" + hashlib.sha256(json.dumps([f["text"] for f in fs]).encode()).hexdigest()
    hit = storage.cache_get(key)
    if hit:
        return {**base, **hit}
    try:
        out = llm.complete_json(BriefingOut, tier="fast", purpose="briefing", max_tokens=900, prompt=(
            "Write a morning note for an Indian equity investor from these verified facts. Lead with what most needs "
            "attention (holdings first if marked), then market context. Use only these facts and cite their ids. "
            "Copy numbers exactly. No advice, no predictions.\nFACTS:\n"
            + "\n".join(f"[{f['id']}] {f['text']}" + (" (HELD)" if f.get("symbol") in set(holdings_symbols or []) else "") for f in fs)
            + "\n(HELD marks stocks the user owns; never write the word HELD in your note.)"))
        lines = []
        for ln in out.lines:
            d = {"text": re.sub(r"\s*\(HELD\)", "", ln.text).strip(), "cites": [c for c in ln.cites if c in by_id]}
            d["verified"] = _verify(d, by_id)
            if d["verified"]:
                lines.append(d)
        if not lines:
            raise llm.LLMError("no verifiable lines")
        res = {"headline": out.headline if not NUM.search(out.headline) or _verify({"text": out.headline, "cites": list(by_id)}, by_id) else lines[0]["text"],
               "lines": lines, "origin": "llm", "model": llm.models()[0]}
        storage.cache_set(key, res, 3 * 3600)
        return {**base, **res}
    except llm.LLMError as e:
        return {**base, **rule_based(fs), "llm_error": str(e)}
