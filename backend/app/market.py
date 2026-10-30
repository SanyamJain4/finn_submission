"""End-of-day price/volume adapter + anomaly rules.

Provider: yfinance (as the brief suggests) with a direct Yahoo chart-API fallback, behind one function so it
can be swapped. These are END-OF-DAY signals computed on the last completed session - not real-time alerts.
"""
from __future__ import annotations

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from . import portfolio, snapshot, storage
from .config import settings
from .http import SourceError, fetch, make_client

log = logging.getLogger("finn.market")
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "eod.json"

_yf_pool = ThreadPoolExecutor(max_workers=1)
DEFAULT_RULES = {"price_move_pct": 4.0, "volume_multiple": 2.0, "volume_window": 20}


def _clean(bars: list[dict]) -> list[dict]:
    out = []
    for b in bars:
        c, v = b.get("close"), b.get("volume")
        if c is None or (isinstance(c, float) and math.isnan(c)):
            continue
        if v is None or (isinstance(v, float) and math.isnan(v)):
            v = None
        out.append({"date": b["date"], "close": float(c), "volume": None if v is None else float(v)})
    out.sort(key=lambda b: b["date"])
    return out


def _yfinance(symbols: list[str]) -> dict[str, list[dict]]:
    import yfinance as yf  # imported lazily: heavy

    tickers = [portfolio.yahoo_symbol(s) for s in symbols]
    df = yf.download(tickers=tickers, period="4mo", interval="1d", group_by="ticker", auto_adjust=False,
                     threads=False, progress=False)
    out = {}
    for s, t in zip(symbols, tickers):
        try:
            sub = df[t] if len(tickers) > 1 else df
            bars = [{"date": idx.date().isoformat(), "close": row["Close"], "volume": row["Volume"]} for idx, row in sub.iterrows()]
            out[s] = _clean(bars)
        except KeyError:
            out[s] = []
    return out


def _chart_api(symbol: str) -> list[dict]:
    with make_client() as c:
        r = fetch(c, f"https://query1.finance.yahoo.com/v8/finance/chart/{portfolio.yahoo_symbol(symbol)}", "Yahoo",
                  params={"range": "4mo", "interval": "1d"})
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = [{"date": datetime.utcfromtimestamp(ts + 19800).date().isoformat(), "close": c, "volume": v}
            for ts, c, v in zip(res["timestamp"], q["close"], q["volume"])]
    return _clean(bars)


def get_eod(symbols: list[str]) -> dict:
    """{"series": {sym: [bars]}, "status": {sym: "ok"|"error: ..."}, "provider": str}"""
    if settings.fixture_mode:
        data = json.loads(FIXTURE.read_text())
        return {"series": {s: data.get(s, []) for s in symbols}, "status": {s: "fixture" for s in symbols}, "provider": "FIXTURE"}
    today = date.today().isoformat()
    series, status, missing = {}, {}, []
    for s in symbols:
        hit = storage.cache_get(f"eod:{s}:{today}")
        if hit is not None:
            series[s], status[s] = hit, "ok (cached)"
        else:
            missing.append(s)
    provider = "yfinance"
    if missing and storage.cache_get(f"eod:fail:{today}"):
        for s in missing:  # recent total failure: don't hammer the provider on every feed refresh
            series[s] = storage.cache_get_stale(f"eod:{s}:last") or []
            status[s] = "error: provider unreachable (retrying in a few minutes)" + (" (showing last cached data)" if series[s] else "")
            if not series[s] and snapshot.eod().get(s):
                series[s], status[s] = snapshot.eod()[s], "snapshot"
        if any(v == "snapshot" for v in status.values()):
            provider = f"snapshot of Yahoo Finance, {snapshot.label()['captured_at'][:10]}"
        return {"series": series, "status": status, "provider": provider}
    if missing:
        try:  # yfinance has its own retry loop; bound it so a dead provider can't stall the feed
            got = _yf_pool.submit(_yfinance, missing).result(timeout=25)
        except Exception as e:  # noqa: BLE001 - yfinance raises many types, incl. TimeoutError here
            log.warning("yfinance failed: %s", type(e).__name__)
            got = {}
        got_any = False
        for s in missing:
            bars = got.get(s) or []
            if not bars:
                try:
                    bars = _chart_api(s)
                    provider = "yfinance + Yahoo chart API"
                except (SourceError, KeyError, IndexError, TypeError, ValueError) as e:
                    status[s] = f"error: {getattr(e, 'message', type(e).__name__)}"
                    series[s] = storage.cache_get_stale(f"eod:{s}:last") or []
                    if series[s]:
                        status[s] += " (showing last cached data)"
                    elif snapshot.eod().get(s):
                        series[s], status[s] = snapshot.eod()[s], "snapshot"
                        provider = f"snapshot of Yahoo Finance, {snapshot.label()['captured_at'][:10]}"
                    continue
            series[s], status[s] = bars, "ok"
            got_any = True
            storage.cache_set(f"eod:{s}:{today}", bars, 6 * 3600)
            storage.cache_set(f"eod:{s}:last", bars, 30 * 86400)
        if not got_any:
            storage.cache_set(f"eod:fail:{today}", True, 600)
    return {"series": series, "status": status, "provider": provider}


def detect(bars: list[dict], rules: dict) -> dict:
    """Evaluate the rules on the most recent completed session. Returns a dict with signals + diagnostics."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    window = int(rules["volume_window"])
    if len(bars) < 2:
        return {"status": "insufficient_history", "signals": []}
    last, prev = bars[-1], bars[-2]
    out = {"status": "ok", "as_of": last["date"], "close": last["close"], "signals": [],
           "day_change_pct": (last["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else None}
    chg = out["day_change_pct"]
    if chg is not None and abs(chg) >= float(rules["price_move_pct"]):
        out["signals"].append({"type": "price_move", "value": round(chg, 2), "threshold": rules["price_move_pct"],
                               "text": f"{'Up' if chg > 0 else 'Down'} {abs(chg):.1f}% on the day (rule: ±{rules['price_move_pct']}%)"})
    hist = [b["volume"] for b in bars[-(window + 1):-1] if b["volume"]]  # exclude today, skip zero/missing
    vol = last["volume"]
    if len(hist) < max(5, window // 2):
        out["volume_status"] = f"insufficient history ({len(hist)} sessions)"
    elif not vol:
        out["volume_status"] = "no volume reported for the last session"
    else:
        avg = sum(hist) / len(hist)
        out["avg_volume"], out["volume"] = avg, vol
        if avg > 0:
            mult = vol / avg
            out["volume_multiple"] = mult
            out["volume_status"] = "ok"
            if mult >= float(rules["volume_multiple"]):
                out["signals"].append({"type": "volume_spike", "value": round(mult, 2), "threshold": rules["volume_multiple"],
                                       "text": f"Volume {mult:.1f}× its {len(hist)}-session average (rule: ≥{rules['volume_multiple']}×)"})
    stale_days = (date.today() - date.fromisoformat(last["date"])).days
    if stale_days > 4:
        out["status"] = "stale"
        out["stale_note"] = f"Latest bar is {stale_days} days old"
    return out


def sparkline(bars: list[dict], n: int = 30) -> list[float]:
    return [round(b["close"], 2) for b in bars[-n:]]
