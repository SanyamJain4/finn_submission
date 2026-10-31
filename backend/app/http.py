"""Outbound HTTP with guard rails.

* Host allowlist - the app never fetches an arbitrary user-supplied URL (SSRF protection). Document URLs
  discovered on Screener are only followed if they point at an exchange or an https host that is not private.
* Per-host politeness delay, bounded retries with backoff, timeouts, and a size cap.
* Errors are raised as SourceError so the API can report *which* source failed instead of inventing data.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from urllib.parse import urlparse

import httpx

from .config import settings

log = logging.getLogger("finn.http")

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# Hosts the data adapters talk to directly.
TRUSTED_HOSTS = {
    "www.nseindia.com", "nseindia.com", "nsearchives.nseindia.com", "archives.nseindia.com",
    "api.bseindia.com", "www.bseindia.com", "bseindia.com",
    "www.screener.in", "screener.in",
    "query1.finance.yahoo.com", "query2.finance.yahoo.com",
    "en.wikipedia.org",
}

_MIN_INTERVAL = {"www.nseindia.com": 0.8, "api.bseindia.com": 0.5, "www.screener.in": 1.0}
_last_hit: dict[str, float] = {}
# Circuit breaker: after 3 consecutive network-level failures (or HTTP 403s) a host is skipped for 2 minutes, so an outage
# costs one slow request instead of one per company.
_breaker: dict[str, tuple[int, float]] = {}
BREAK_AFTER, BREAK_FOR_S = 3, 120.0
_host_lock = threading.Lock()


class SourceError(Exception):
    def __init__(self, source: str, message: str, status: int | None = None):
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message
        self.status = status


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def check_url_allowed(url: str, allow_external_documents: bool = False) -> None:
    p = urlparse(url)
    if p.scheme not in {"https", "http"} or not p.hostname:
        raise SourceError("http", f"refused non-http(s) URL")
    host = p.hostname.lower()
    if host in TRUSTED_HOSTS:
        return
    if allow_external_documents and p.scheme == "https" and _is_public_host(host):
        # Company investor-relations PDFs linked from Screener: https + public IP only.
        return
    raise SourceError("http", f"host not allowed: {host}")


def _polite(host: str) -> None:
    gap = _MIN_INTERVAL.get(host, 0.2)
    with _host_lock:
        wait = _last_hit.get(host, 0) + gap - time.time()
        _last_hit[host] = max(time.time(), _last_hit.get(host, 0) + gap)
    if wait > 0:
        time.sleep(wait)


def make_client(**kw) -> httpx.Client:
    headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    headers.update(kw.pop("headers", {}))
    return httpx.Client(timeout=settings.http_timeout_s, headers=headers, follow_redirects=True, **kw)


def fetch(client: httpx.Client, url: str, source: str, *, params: dict | None = None, headers: dict | None = None,
          retries: int = 2, allow_external_documents: bool = False, max_bytes: int | None = None) -> httpx.Response:
    check_url_allowed(url, allow_external_documents)
    host = urlparse(url).hostname or ""
    fails, until = _breaker.get(host, (0, 0.0))
    if until > time.time():
        raise SourceError(source, f"{host} unreachable; retrying after {int(until - time.time())}s")
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        _polite(host)
        try:
            r = client.get(url, params=params, headers=headers)
            # Re-check final host after redirects.
            check_url_allowed(str(r.url), allow_external_documents)
            if r.status_code == 429 or r.status_code >= 500:
                raise SourceError(source, f"HTTP {r.status_code}", r.status_code)
            if r.status_code >= 400:
                raise SourceError(source, f"HTTP {r.status_code}", r.status_code)
            if max_bytes and len(r.content) > max_bytes:
                raise SourceError(source, "response too large")
            _breaker.pop(host, None)
            return r
        except SourceError as e:
            last_exc = e
            if e.status == 403:
                # Hosted IPs get 403 from NSE/BSE on every call; treat it like an outage so the feed falls back
                # to the snapshot after a few calls instead of crawling through every company at 0.5s each.
                n = _breaker.get(host, (0, 0.0))[0] + 1
                _breaker[host] = (n, time.time() + BREAK_FOR_S if n >= BREAK_AFTER else 0.0)
            if e.status is not None and 400 <= e.status < 500 and e.status != 429:
                break
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = SourceError(source, f"network error: {type(e).__name__}")
            n = _breaker.get(host, (0, 0.0))[0] + 1
            _breaker[host] = (n, time.time() + BREAK_FOR_S if n >= BREAK_AFTER else 0.0)
            if n >= BREAK_AFTER:
                break
        if attempt < retries:
            time.sleep(0.8 * (2 ** attempt))
    log.warning("fetch failed source=%s url=%s err=%s", source, url.split("?")[0], last_exc)
    assert last_exc is not None
    raise last_exc if isinstance(last_exc, SourceError) else SourceError(source, str(last_exc))
