from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import settings

_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")


def normalise_ticker(raw: str) -> str | None:
    """'reliance.ns' -> 'RELIANCE'; 'M&M' stays; returns None for anything that cannot be a NSE symbol."""
    if not raw:
        return None
    t = raw.strip().upper()
    t = re.sub(r"\.(NS|BO)$", "", t)
    t = t.removeprefix("NSE:").removeprefix("BSE:")
    return t if _TICKER_RE.match(t) else None


def yahoo_symbol(symbol: str, exchange: str = "NS") -> str:
    return f"{symbol}.{exchange}"


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(settings.portfolio_file, encoding="utf-8") as f:
        return json.load(f)


def portfolio() -> list[dict]:
    return _load()["portfolio"]


def research_demos() -> list[dict]:
    return _load().get("research_demos", [])


def by_symbol(symbol: str) -> dict | None:
    for c in portfolio():
        if c["symbol"] == symbol:
            return c
    return None


def by_bse_code(code: str) -> dict | None:
    for c in portfolio():
        if c.get("bse_code") == str(code):
            return c
    return None
