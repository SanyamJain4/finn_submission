"""SQLite-backed cache. One small file, no server.

Tables:
  kv        - generic TTL cache (HTTP bodies, parsed pages, LLM outputs) keyed by a namespaced string.
  documents - downloaded documents keyed by URL with content hash, so we re-parse only when bytes change.
  llm_calls - usage log for cost visibility.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any

from .config import settings

_DB = settings.data_dir / "finn.sqlite3"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_DB, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (
                url TEXT PRIMARY KEY, sha256 TEXT NOT NULL, fetched REAL NOT NULL,
                content_type TEXT, size INTEGER, pages_json TEXT);
            CREATE TABLE IF NOT EXISTS llm_calls (
                ts REAL, purpose TEXT, model TEXT, cached INTEGER, input_tokens INTEGER,
                output_tokens INTEGER, ok INTEGER, error TEXT);
            CREATE TABLE IF NOT EXISTS prefs (k TEXT PRIMARY KEY, v TEXT NOT NULL);
            """
        )
    return _conn


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def cache_get(key: str) -> Any | None:
    with _lock:
        row = conn().execute("SELECT v, expires FROM kv WHERE k=?", (key,)).fetchone()
    if not row:
        return None
    if row[1] < time.time():
        return None
    return json.loads(row[0])


def cache_get_stale(key: str) -> Any | None:
    """Return a value even if expired - used to show last-known data when a provider is down (clearly labelled)."""
    with _lock:
        row = conn().execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_set(key: str, value: Any, ttl_s: float) -> None:
    with _lock:
        conn().execute(
            "INSERT OR REPLACE INTO kv (k, v, expires) VALUES (?, ?, ?)",
            (key, json.dumps(value, default=str), time.time() + ttl_s),
        )
        conn().commit()


def doc_get(url: str) -> dict | None:
    with _lock:
        row = conn().execute("SELECT sha256, fetched, content_type, size, pages_json FROM documents WHERE url=?", (url,)).fetchone()
    if not row:
        return None
    return {"sha256": row[0], "fetched": row[1], "content_type": row[2], "size": row[3],
            "pages": json.loads(row[4]) if row[4] else None}


def doc_put(url: str, sha: str, content_type: str, size: int, pages: list[str] | None) -> None:
    with _lock:
        conn().execute(
            "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?, ?)",
            (url, sha, time.time(), content_type, size, json.dumps(pages) if pages is not None else None),
        )
        conn().commit()


def log_llm_call(purpose: str, model: str, cached: bool, in_tok: int | None, out_tok: int | None, ok: bool, error: str | None = None) -> None:
    with _lock:
        conn().execute("INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?,?)",
                       (time.time(), purpose, model, int(cached), in_tok, out_tok, int(ok), (error or "")[:300]))
        conn().commit()


def llm_usage_summary() -> dict:
    with _lock:
        rows = conn().execute(
            "SELECT model, COUNT(*), SUM(cached), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), SUM(1-ok) FROM llm_calls GROUP BY model"
        ).fetchall()
    return {"by_model": [
        {"model": r[0], "calls": r[1], "cache_hits": r[2], "input_tokens": r[3], "output_tokens": r[4], "errors": r[5]} for r in rows
    ]}


def pref_get(key: str, default: Any) -> Any:
    with _lock:
        row = conn().execute("SELECT v FROM prefs WHERE k=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def pref_set(key: str, value: Any) -> None:
    with _lock:
        conn().execute("INSERT OR REPLACE INTO prefs VALUES (?, ?)", (key, json.dumps(value)))
        conn().commit()
