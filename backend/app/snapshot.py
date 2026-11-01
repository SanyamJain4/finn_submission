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
import re
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .config import settings

log = logging.getLogger("finn.snapshot")
import os

SNAP_DIR = Path(os.environ.get("FINN_SNAPSHOT_DIR") or Path(__file__).resolve().parents[1] / "data" / "snapshot")


LIVE_NAME = "snapshot_live"
_NAME_OK = re.compile(r"^(meta|announcements|eod|details)\.json$|^reports/[A-Z0-9&_-]{1,20}\.json$")


def live_dir() -> Path:
    """Where /api/ingest puts data pushed from a machine the exchanges don't block (not in git, lost on redeploy)."""
    return settings.data_dir / LIVE_NAME


def _load(p: Path):
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("snapshot file %s unreadable: %s", p.name, e)
        return None


def _captured(m: dict | None) -> datetime | None:
    try:
        return datetime.fromisoformat(m["captured_at"]) if m else None
    except (KeyError, TypeError, ValueError):
        return None


def _dir() -> Path:
    """The pushed copy wins only when it is at least as recent as the one committed to the repo."""
    live, committed = _captured(_load(live_dir() / "meta.json")), _captured(_load(SNAP_DIR / "meta.json"))
    if live and (not committed or live >= committed):
        return live_dir()
    return SNAP_DIR


def _read(name: str):
    return _load(_dir() / name)


def reload() -> None:
    for f in (meta, announcements, eod, details):
        f.cache_clear()


def ingest(files: dict) -> dict:
    """Validate and atomically replace the pushed snapshot. Raises ValueError with a reason on bad input."""
    for name in files:
        if not _NAME_OK.match(name):
            raise ValueError(f"unexpected file name: {name!r}")
    meta_, ann, eod_ = files.get("meta.json"), files.get("announcements.json"), files.get("eod.json")
    if not isinstance(meta_, dict) or _captured(meta_) is None:
        raise ValueError("meta.json needs a valid captured_at")
    if not isinstance(ann, list) or not ann:
        raise ValueError("announcements.json must be a non-empty list")
    if not isinstance(eod_, dict):
        raise ValueError("eod.json must be an object")
    if "details.json" in files and not isinstance(files["details.json"], dict):
        raise ValueError("details.json must be an object")
    for name, body in files.items():
        if name.startswith("reports/") and not isinstance(body, dict):
            raise ValueError(f"{name} must be an object")
    cur = _captured(_load(_dir() / "meta.json"))
    if cur and _captured(meta_) < cur:
        raise ValueError("older than the snapshot already on the server")
    tmp = live_dir().with_name(LIVE_NAME + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    for name, body in files.items():
        out = tmp / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(body), encoding="utf-8")
    shutil.rmtree(live_dir(), ignore_errors=True)
    tmp.rename(live_dir())
    reload()
    return {"captured_at": meta_["captured_at"], "files": len(files), "announcements": len(ann)}


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
    name = f"reports/{symbol.upper()}.json"
    return _read(name) or _load(SNAP_DIR / name)  # a push without reports keeps the committed ones


def report_symbols() -> list[str]:
    if not available():
        return []
    found = {p.stem for d in (_dir(), SNAP_DIR) if (d / "reports").is_dir() for p in (d / "reports").glob("*.json")}
    return sorted(found)


def label() -> dict | None:
    m = meta()
    if not m:
        return None
    return {"captured_at": m["captured_at"], "sources": m.get("sources", []),
            "note": f"Server can't reach the exchanges directly; showing real data captured from "
                    f"{', '.join(m.get('sources', [])) or 'live sources'} at {m['captured_at'][:16].replace('T', ' ')} IST."}
