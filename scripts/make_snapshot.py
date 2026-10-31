"""Capture a LIVE data snapshot for hosts that NSE/BSE block (most cloud servers).

Run on a machine that can reach the exchanges (your laptop in India works), then commit + push:

    cd backend
    python ../scripts/make_snapshot.py                      # feed + prices + filing details + demo research reports
    python ../scripts/make_snapshot.py --reports TRENT IRCTC # choose which research reports to pre-build
    python ../scripts/make_snapshot.py --no-reports          # skip research (fast)

Writes backend/data/snapshot/{meta,announcements,eod,details}.json and reports/<SYMBOL>.json.
Everything is real data from the live sources; the server labels it with the capture time when it serves it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ["FINN_FIXTURE_MODE"] = "0"
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import market, portfolio  # noqa: E402
from app.config import settings  # noqa: E402
from app.push import service as push  # noqa: E402
from app.push.sources import IST, fetch_bse, fetch_nse  # noqa: E402
from app.research.service import build_report  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "backend" / "data" / "snapshot"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="how many days of filings to capture (default 7)")
    ap.add_argument("--reports", nargs="*", help="symbols to pre-build research for (default: research demos)")
    ap.add_argument("--no-reports", action="store_true")
    ap.add_argument("--max-details", type=int, default=30, help="filings to open and parse (high/medium first)")
    a = ap.parse_args()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    now = datetime.now(IST)
    start = now - timedelta(days=a.days)
    syms = {c["symbol"] for c in portfolio.portfolio()}
    used = []

    print(f"[1/4] Filings {start:%d %b} - {now:%d %b}")
    items = []
    try:
        items = fetch_nse(start, now, syms)
        used.append("NSE")
        print(f"      NSE: {len(items)} filings")
    except Exception as e:  # noqa: BLE001
        print(f"      NSE failed ({e}); trying BSE")
    if not items:
        items, failures = fetch_bse(start, now, portfolio.portfolio())
        print(f"      BSE: {len(items)} filings, {len(failures)} companies failed")
        if failures:
            print("      e.g.", failures[0])
        if items:
            used.append("BSE")
    if not items:
        sys.exit("No filings captured - this machine can't reach NSE or BSE either. Nothing written.")
    (OUT / "announcements.json").write_text(json.dumps([i.to_dict() for i in items], indent=0), encoding="utf-8")

    print("[2/4] End-of-day prices")
    idx_keys = [f"IDX:{k}" for k, _, _ in market.INDICES]
    eod = market.get_eod(sorted(syms) + idx_keys)
    good = {s: b for s, b in eod["series"].items() if b and eod["status"][s].startswith("ok")}
    print(f"      indices: {', '.join(k[4:] for k in idx_keys if k in good) or 'none'}")
    print(f"      {len(good)}/{len(syms)} symbols via {eod['provider']}")
    if good:
        used.append("Yahoo Finance")
    (OUT / "eod.json").write_text(json.dumps(good), encoding="utf-8")

    # meta must exist before build_feed so everything downstream is consistent; written again at the end
    meta = {"captured_at": now.isoformat(timespec="seconds"), "sources": used, "days": a.days,
            "llm": settings.llm_provider if settings.llm_enabled else None}
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    print("[3/4] Opening and parsing the important filings")
    feed = push.build_feed(start=start, end=now)
    todo = [i for i in feed["items"] if i["tier"] in ("high", "medium") and i["url"]][: a.max_details]
    details = {}
    for n, i in enumerate(todo, 1):
        try:
            d = push.filing_detail(i["uid"])
            if d and d.get("document") and d["document"]["status"] == "ok":
                d = {k: v for k, v in d.items() if k != "item"}
                details[i["uid"]] = d
            print(f"      {n}/{len(todo)} {i['symbol']:10} {i['category']:17} {(d or {}).get('document', {}) and d['document']['status']}")
        except Exception as e:  # noqa: BLE001
            print(f"      {n}/{len(todo)} {i['symbol']:10} failed: {e}")
        if settings.llm_enabled:
            time.sleep(2)  # stay under free-tier requests-per-minute
    (OUT / "details.json").write_text(json.dumps(details), encoding="utf-8")

    if not a.no_reports:
        targets = a.reports or [d["symbol"] for d in portfolio.research_demos()]
        print(f"[4/4] Research reports: {', '.join(targets)}")
        for s in targets:
            t0 = time.time()
            try:
                rep = build_report(s.upper())
                (OUT / "reports" / f"{s.upper()}.json").write_text(json.dumps(rep), encoding="utf-8")
                g = rep["sections"]["guidance"]
                print(f"      {s}: {time.time() - t0:.0f}s, sources ok {sum(x['status'] == 'ok' for x in rep['sources'])}/{len(rep['sources'])}, "
                      f"guidance rows {len(g['rows'])}, llm calls {rep['llm']['calls_used']}, verified {rep['verification']['verified']}/{rep['verification']['llm_claims']}")
                if "Screener" not in used:
                    used.append("Screener")
            except Exception as e:  # noqa: BLE001
                print(f"      {s}: FAILED {type(e).__name__}: {e}")
    else:
        print("[4/4] Research reports skipped")

    meta["sources"] = used
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.rglob("*.json")) / 1024
    print(f"\nSnapshot written to {OUT} ({size:,.0f} KB). Now: git add backend/data/snapshot && git commit -m 'Data snapshot' && git push")


if __name__ == "__main__":
    main()
