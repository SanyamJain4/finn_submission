"""Live end-to-end smoke test against the REAL sources. Run this on your laptop or the deployed box
(the build sandbox could not reach NSE/BSE/Yahoo/Screener):

    cd backend && FINN_FIXTURE_MODE=0 python ../scripts/smoke_live.py [SYMBOL]

It prints a PASS/FAIL line per integration and exits non-zero if any core path fails. Nothing is mocked.
"""
from __future__ import annotations

import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

os.environ["FINN_FIXTURE_MODE"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import llm, market, portfolio  # noqa: E402
from app.documents import get_document  # noqa: E402
from app.push import results  # noqa: E402
from app.push.service import build_feed, filing_detail  # noqa: E402
from app.push.sources import IST, fetch_bse, fetch_nse  # noqa: E402
from app.research import screener  # noqa: E402
from app.research.service import build_report  # noqa: E402

FAILS: list[str] = []


def check(name: str, fn, core: bool = True):
    t = time.time()
    try:
        detail = fn()
        print(f"PASS  {name:38} {time.time() - t:5.1f}s  {detail}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  {name:38} {time.time() - t:5.1f}s  {type(e).__name__}: {e}")
        if os.environ.get("VERBOSE"):
            traceback.print_exc()
        if core:
            FAILS.append(name)


def main(symbol: str) -> None:
    end = datetime.now(IST)
    start = end - timedelta(days=3)
    syms = {c["symbol"] for c in portfolio.portfolio()}

    def _eod():
        d = market.get_eod(sorted(syms))
        ok = sum(1 for s in d["status"].values() if s.startswith("ok"))
        if not ok:
            raise RuntimeError(next(iter(d["status"].values())))
        return f"provider={d['provider']} ok={ok}/{len(d['status'])}"
    check("Yahoo EOD (yfinance/chart API)", _eod)
    check("NSE announcements (3 days)", lambda: f"{len(fetch_nse(start, end, syms))} portfolio filings", core=False)
    def _bse():
        items, failures = fetch_bse(start, end, portfolio.portfolio())
        if failures and len(failures) == len(portfolio.portfolio()):
            raise RuntimeError(f"all {len(failures)} companies failed: {failures[0]}")
        return f"{len(items)} filings, {len(failures)} failures"
    check("BSE announcements (3 days)", _bse, core=False)
    feed = {}

    def _feed():
        feed.update(build_feed(hours=72))
        src = "; ".join(f"{s['name']}={s['status']}" for s in feed["sources"])
        if not any(s["status"] in ("ok", "partial") for s in feed["sources"]):
            raise RuntimeError(f"no announcement source worked ({src})")
        return f"{feed['counts']['total']} items {feed['counts']['tier']} [{src}]"
    check("Feed: fetch -> classify -> prioritise", _feed)

    def _results():
        items = [i for i in feed.get("items", []) if i["category"] == "results" and i["url"] and i["tier"] == "high"]
        if not items:
            return "no results filing in window (skipped)"
        d = filing_detail(items[0]["uid"])
        r = d.get("results") or {}
        rev = (r.get("metrics") or {}).get("revenue", {})
        return f"{items[0]['symbol']}: doc={d['document']['status'] if d['document'] else None} extraction={r.get('status')} basis={r.get('basis')} revenue={rev.get('current')}"
    check("Results PDF -> QoQ/YoY", _results, core=False)

    def _llm():
        if not llm.status()["enabled"]:
            raise RuntimeError("no LLM configured (set FINN_LLM_PROVIDER and FINN_LLM_API_KEY in .env)")
        from pydantic import BaseModel

        class Ping(BaseModel):
            company: str
            revenue_growth_pct: float

        out = []
        for tier in ("fast", "smart"):
            try:
                r = llm.complete_json(Ping, tier=tier, purpose="smoke", cache_ttl_s=1, prompt=(
                    "From the document, return the company and its revenue growth.\n" + llm.doc_block([("E1", "Acme Ltd revenue grew 12.5% year on year.")])))
                from app import storage as _st
                out.append(f"{tier}={_st.cache_get('llm:gemini_working:' + tier) or llm.models()[0 if tier == 'fast' else 1]} ok ({r.company}, {r.revenue_growth_pct})")
            except llm.LLMError as e:
                avail = [m for m in llm.list_models() if re.search(r"flash|pro", m) and not re.search(r"tts|image|live|audio", m)]
                raise RuntimeError(f"{tier}: {e}. Available: {avail}") from e
        return "; ".join(out)
    check("LLM structured output (fast + smart)", _llm)

    check("Screener search", lambda: f"{screener.search(symbol)[:2]}")

    def _company():
        c = screener.company(symbol)
        d = c["documents"]
        return f"{c['name']} basis={c['basis']} ARs={len(d['annual_reports'])} concalls={len(d['concalls'])} capex={'yes' if c.get('capex') else 'no'}"
    check(f"Screener company page ({symbol})", _company)

    def _doc():
        c = screener.company(symbol)
        t = next((x["transcript"] for x in c["documents"]["concalls"] if x.get("transcript")), None)
        if not t:
            return "no transcript listed"
        d = get_document(t)
        return f"{d.status} {d.detail} url={t[:70]}"
    check("Transcript PDF download + parse", _doc)

    def _report():
        r = build_report(symbol)
        g = r["sections"]["guidance"]
        return (f"sources={[(s['id'], s['status']) for s in r['sources']]} guidance={g['status']} rows={len(g['rows'])} "
                f"verified={r['verification']} llm_calls={r['llm']['calls_used']} limits={len(r['limitations'])}")
    check(f"Full research report ({symbol})", _report)
    print("LLM:", llm.status())
    print("\nRESULT:", "ALL CORE CHECKS PASSED" if not FAILS else f"FAILED: {', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "TRENT")
