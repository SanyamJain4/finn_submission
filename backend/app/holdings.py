"""Actual holdings (what the investor owns), kept separate from the watchlist (what FINN monitors).

Holdings live in the visitor's browser and are posted here for valuation, so a shared demo link never mixes two
people's positions and nothing personal is stored server-side. Every number is computed here, deterministically.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from . import finance, market, portfolio

CAPS = {"Large", "Mid", "Small"}


class Holding(BaseModel):
    symbol: str
    qty: float = Field(gt=0, le=1e9)
    avg_price: float = Field(gt=0, le=1e7)
    sector: str | None = Field(None, max_length=40)
    cap: str | None = None

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        s = portfolio.normalise_ticker(v)
        if not s:
            raise ValueError(f"'{v}' is not a valid NSE symbol")
        return s

    @field_validator("cap")
    @classmethod
    def _cap(cls, v: str | None) -> str | None:
        if v and v not in CAPS:
            raise ValueError("cap must be Large, Mid or Small")
        return v


def _alloc(rows: list[dict], key: str, total: float) -> list[dict]:
    agg: dict[str, float] = {}
    for r in rows:
        if r["value"] is not None:
            agg[r[key]] = agg.get(r[key], 0.0) + r["value"]
    return sorted(({"name": k, "value": v, "pct": v / total * 100 if total else 0.0} for k, v in agg.items()), key=lambda x: -x["value"])


def value(holdings: list[Holding]) -> dict:
    # merge duplicate symbols into one position (weighted average cost)
    merged: dict[str, Holding] = {}
    for h in holdings:
        if h.symbol in merged:
            m = merged[h.symbol]
            qty = m.qty + h.qty
            merged[h.symbol] = Holding(symbol=h.symbol, qty=qty, avg_price=(m.qty * m.avg_price + h.qty * h.avg_price) / qty,
                                       sector=m.sector or h.sector, cap=m.cap or h.cap)
        else:
            merged[h.symbol] = h
    syms = list(merged)
    eod = market.get_eod(syms) if syms else {"series": {}, "status": {}, "provider": None}
    rows = []
    for s, h in merged.items():
        w = portfolio.by_symbol(s) or {}
        q = market.latest(eod["series"].get(s) or [])
        price, prev = q["value"], q.get("prev_close")
        invested = h.qty * h.avg_price
        val = None if price is None else h.qty * price
        pnl = None if val is None else val - invested
        day = None if price is None or prev is None else h.qty * (price - prev)
        rows.append({
            "symbol": s, "name": w.get("name", s), "sector": h.sector or w.get("sector") or "Unclassified",
            "cap": h.cap or w.get("size") or "Unclassified", "qty": h.qty, "avg_price": h.avg_price,
            "price": price, "prev_close": prev, "as_of": q["as_of"], "price_kind": q["kind"],
            "price_status": eod["status"].get(s), "invested": invested, "value": val, "pnl": pnl,
            "pnl_pct": finance.pct_change(val, invested) if val is not None else None,
            "day_change": day, "day_change_pct": q["change_pct"], "watched": bool(w),
        })
    priced = [r for r in rows if r["value"] is not None]
    inv_p = sum(r["invested"] for r in priced)
    val_p = sum(r["value"] for r in priced)
    day_p = sum(r["day_change"] for r in priced if r["day_change"] is not None)
    base = val_p - day_p
    for r in rows:
        r["weight"] = r["value"] / val_p * 100 if r["value"] is not None and val_p else None
    ranked = sorted((r for r in priced if r["pnl_pct"] is not None), key=lambda r: r["pnl_pct"])
    return {
        "holdings": sorted(rows, key=lambda r: -(r["value"] or 0)),
        "totals": {
            "invested": sum(r["invested"] for r in rows), "invested_priced": inv_p, "value": val_p if priced else None,
            "pnl": val_p - inv_p if priced else None, "pnl_pct": finance.pct_change(val_p, inv_p) if priced else None,
            "day_change": day_p if priced else None, "day_change_pct": (day_p / base * 100) if priced and base else None,
            "count": len(rows), "priced": len(priced), "unpriced": [r["symbol"] for r in rows if r["value"] is None],
            "as_of": max((r["as_of"] for r in priced if r["as_of"]), default=None),
        },
        "allocation": {"sector": _alloc(priced, "sector", val_p), "cap": _alloc(priced, "cap", val_p)},
        "best": ranked[-1]["symbol"] if ranked else None, "worst": ranked[0]["symbol"] if ranked else None,
        "provider": eod["provider"],
        "note": "Values use the latest close from the price source; unrealised P&L excludes brokerage, taxes and dividends.",
    }


def example() -> list[dict]:
    """Clearly-labelled example: 6 watchlist names, cost = their real close ~60 sessions ago."""
    picks = [("RELIANCE", 20), ("HDFCBANK", 30), ("TCS", 10), ("DIXON", 2), ("POLYCAB", 5), ("AFFLE", 25)]
    eod = market.get_eod([p for p, _ in picks])
    out = []
    for s, qty in picks:
        bars = eod["series"].get(s) or []
        if len(bars) > 60:
            out.append({"symbol": s, "qty": qty, "avg_price": round(bars[-61]["close"], 2), "bought": bars[-61]["date"]})
    return out
