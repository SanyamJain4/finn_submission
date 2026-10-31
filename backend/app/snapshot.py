"""Live-data snapshot ("relay") for hosts the exchanges block.

NSE and BSE refuse most cloud/datacenter IPs, so a deployed FINN often cannot fetch filings itself.
`scripts/make_snapshot.py` runs on a machine that CAN reach them (e.g. the developer's laptop) and writes real,
already-processed data into backend/data/snapshot/. When a live source fails, the server falls back to it and
labels everything with the capture time and the source it came from. It is never mixed silently with live data,
and it is never synthetic (that is what FINN_FIXTURE_MODE is for).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from .config import settings

log = logging.getLogger("finn.snapshot")
import os

SNAP_DIR = Path(os.environ.get("FINN_SNAPSHOT_DIR") or Path(__file__).resolve().parents[1] / "data" / "snapshot")


def _read(name: str):
    p = SNAP_DIR / name
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("snapshot file %s unreadable: %s", name, e)
        return None


@lru_cache(maxsize=1)
def meta() -> dict | None:
    if settings.fixture_mode:
        return None
    return _read("meta.json")


def available() -> bool:
    return meta() is not None


@lru_cache(maxsize=1)
def announcements() -> list[dict]:
    return (_read("announcements.json") or []) if available() else []


@lru_cache(maxsize=1)
def eod() -> dict:
    return (_read("eod.json") or {}) if available() else {}


@lru_cache(maxsize=1)
def details() -> dict:
    return (_read("details.json") or {}) if available() else {}


def report(symbol: str) -> dict | None:
    if not available():
        return None
    return _read(f"reports/{symbol.upper()}.json")


def report_symbols() -> list[str]:
    if not available() or not (SNAP_DIR / "reports").is_dir():
        return []
    return sorted(p.stem for p in (SNAP_DIR / "reports").glob("*.json"))


def label() -> dict | None:
    m = meta()
    if not m:
        return None
    return {"captured_at": m["captured_at"], "sources": m.get("sources", []),
            "note": f"Server can't reach the exchanges directly; showing real data captured from "
                    f"{', '.join(m.get('sources', [])) or 'live sources'} at {m['captured_at'][:16].replace('T', ' ')} IST."}
