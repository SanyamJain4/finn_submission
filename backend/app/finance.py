"""Deterministic financial arithmetic. No LLM ever computes a number shown in FINN."""
from __future__ import annotations

UNIT_TO_CRORE = {"crore": 1.0, "lakh": 0.01, "million": 0.1, "billion": 100.0, "thousand": 0.0001, "rupee": 1e-7}


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def pct_change(cur: float | None, base: float | None) -> float | None:
    """% change. None when the base is missing/zero or the sign flips (a % on a loss->profit swing is meaningless)."""
    if cur is None or base is None or base == 0:
        return None
    if (cur < 0) != (base < 0) and cur != 0:
        return None
    return (cur - base) / abs(base) * 100.0


def change_note(cur: float | None, base: float | None) -> str | None:
    if cur is None or base is None:
        return None
    if base < 0 <= cur:
        return "turned positive"
    if base >= 0 > cur:
        return "turned negative"
    if base < 0 and cur < 0:
        return "loss narrowed" if cur > base else "loss widened"
    return None


def margin(profit: float | None, revenue: float | None) -> float | None:
    m = safe_div(profit, revenue)
    return None if m is None or revenue is None or revenue <= 0 else m * 100.0


def cagr(end: float | None, start: float | None, years: float) -> float | None:
    if end is None or start is None or start <= 0 or end <= 0 or years <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100.0


def comparison(cur: float | None, prev: float | None, yoy: float | None) -> dict:
    return {
        "current": cur, "prev_quarter": prev, "year_ago": yoy,
        "qoq_abs": None if cur is None or prev is None else cur - prev,
        "qoq_pct": pct_change(cur, prev), "qoq_note": change_note(cur, prev),
        "yoy_abs": None if cur is None or yoy is None else cur - yoy,
        "yoy_pct": pct_change(cur, yoy), "yoy_note": change_note(cur, yoy),
    }


def parse_number(tok: str) -> float | None:
    """'1,234.50' -> 1234.5 ; '(12.3)' -> -12.3 ; '-' / '—' -> 0.0 (nil in Indian statements)."""
    t = tok.strip().replace("₹", "")
    if t in {"-", "–", "—", "--", "nil", "Nil"}:
        return 0.0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    if t.startswith("-"):
        neg, t = True, t[1:]
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v
