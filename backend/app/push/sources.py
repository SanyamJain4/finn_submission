"""Corporate-announcement adapters.

NSE is primary: one call returns every equity announcement in a date window (we then filter to the portfolio),
which is far cheaper than one call per company. NSE needs a cookie from its homepage and often blocks cloud IPs,
so BSE (per-scrip API) is the fallback. Both are undocumented public endpoints -> treated as unreliable,
errors are surfaced per source, and nothing is invented when both fail.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import portfolio, snapshot, storage
from ..config import settings
from ..http import SourceError, fetch, make_client

log = logging.getLogger("finn.push.sources")
IST = timezone(timedelta(hours=5, minutes=30))
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


@dataclass
class RawAnnouncement:
    uid: str                 # stable id: exchange + exchange id (or hash)
    exchange: str            # NSE | BSE | FIXTURE
    symbol: str
    company: str
    subject: str             # exchange category / subject line
    text: str                # exchange-provided description
    published: str           # ISO 8601 with IST offset
    url: str | None          # original filing attachment
    exchange_category: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_dt(s: str, fmts: list[str]) -> datetime | None:
    for f in fmts:
        try:
            return datetime.strptime(s.strip(), f).replace(tzinfo=IST)
        except (ValueError, AttributeError):
            continue
    return None


def parse_nse(rows: list[dict], symbols: set[str]) -> list[RawAnnouncement]:
    out = []
    for r in rows:
        sym = (r.get("symbol") or "").upper()
        if sym not in symbols:
            continue
        dt = _parse_dt(r.get("sort_date") or "", ["%Y-%m-%d %H:%M:%S"]) or _parse_dt(r.get("an_dt") or "", ["%d-%b-%Y %H:%M:%S"])
        if not dt:
            continue
        seq = r.get("seq_id") or storage.sha256(f"{sym}|{r.get('desc')}|{r.get('an_dt')}|{r.get('attchmntFile')}")[:16]
        att = r.get("attchmntFile") or None
        out.append(RawAnnouncement(
            uid=f"NSE:{seq}", exchange="NSE", symbol=sym, company=r.get("sm_name") or sym,
            subject=(r.get("desc") or "").strip(), text=(r.get("attchmntText") or "").strip(),
            published=dt.isoformat(), url=att if att and att != "-" else None,
            exchange_category=(r.get("desc") or "").strip(),
        ))
    return out


def parse_bse(rows: list[dict]) -> list[RawAnnouncement]:
    out = []
    for r in rows:
        co = portfolio.by_bse_code(str(r.get("SCRIP_CD", "")))
        dt = _parse_dt((r.get("DissemDT") or r.get("NEWS_DT") or "").split(".")[0], ["%Y-%m-%dT%H:%M:%S"])
        if not co or not dt:
            continue
        att = r.get("ATTACHMENTNAME")
        url = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else None
        out.append(RawAnnouncement(
            uid=f"BSE:{r.get('NEWSID')}", exchange="BSE", symbol=co["symbol"], company=r.get("SLONGNAME") or co["name"],
            subject=(r.get("NEWSSUB") or r.get("HEADLINE") or "").strip(),
            text=(r.get("HEADLINE") or "").strip(), published=dt.isoformat(), url=url,
            exchange_category=" / ".join(x for x in [r.get("CATEGORYNAME"), r.get("SUBCATNAME")] if x and x != "-"),
        ))
    return out


def fetch_nse(start: datetime, end: datetime, symbols: set[str]) -> list[RawAnnouncement]:
    key = f"nse:ann:{start:%Y%m%d}:{end:%Y%m%d%H}"
    rows = storage.cache_get(key)
    if rows is None:
        browser = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Accept-Language": "en-IN,en;q=0.9", "Upgrade-Insecure-Requests": "1", "Sec-Fetch-Dest": "document",
                   "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none"}
        with make_client(headers=browser) as c:
            fetch(c, "https://www.nseindia.com/", "NSE", retries=0)  # sets the Akamai cookies the API needs
            r = fetch(c, "https://www.nseindia.com/api/corporate-announcements", "NSE",
                      params={"index": "equities", "from_date": f"{start:%d-%m-%Y}", "to_date": f"{end:%d-%m-%Y}"},
                      headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
                               "Accept": "application/json, text/plain, */*", "Sec-Fetch-Mode": "cors",
                               "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Dest": "empty"})
            try:
                rows = r.json()
            except json.JSONDecodeError as e:
                raise SourceError("NSE", "non-JSON response (likely bot protection)") from e
        if isinstance(rows, dict):
            rows = rows.get("data", [])
        storage.cache_set(key, rows, 15 * 60)
    return parse_nse(rows, symbols)


def fetch_bse(start: datetime, end: datetime, companies: list[dict]) -> tuple[list[RawAnnouncement], list[str]]:
    out: list[RawAnnouncement] = []
    failures: list[str] = []
    with make_client(headers={"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}) as c:
        for co in companies:
            code = co.get("bse_code")
            if not code:
                continue
            key = f"bse:ann:{code}:{start:%Y%m%d}:{end:%Y%m%d%H}"
            rows = storage.cache_get(key)
            if rows is None:
                try:
                    r = fetch(c, "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w", "BSE", params={
                        "pageno": 1, "strCat": -1, "strPrevDate": f"{start:%Y%m%d}", "strScrip": code,
                        "strSearch": "P", "strToDate": f"{end:%Y%m%d}", "strType": "C", "subcategory": -1})
                    rows = r.json().get("Table", [])
                    storage.cache_set(key, rows, 15 * 60)
                except (SourceError, json.JSONDecodeError, AttributeError) as e:
                    failures.append(f"{co['symbol']}: {e}")
                    continue
            out.extend(parse_bse(rows))
    return out, failures


def load_fixture_announcements() -> list[RawAnnouncement]:
    rows = json.loads((FIXTURE_DIR / "nse_announcements.json").read_text())
    # Fixture timestamps are relative ("-3h") so the 24h default window always has content in dev.
    now = datetime.now(IST)
    for r in rows:
        if r.get("sort_date", "").startswith("-"):
            hours = float(r["sort_date"].strip("-h"))
            r["sort_date"] = (now - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    syms = {c["symbol"] for c in portfolio.portfolio()}
    items = parse_nse(rows, syms)
    for i in items:
        i.exchange = "FIXTURE"
    return items


def get_announcements(start: datetime, end: datetime) -> dict:
    """Returns {"items": [...RawAnnouncement], "sources": [{name, status, detail}]}"""
    companies = portfolio.portfolio()
    symbols = {c["symbol"] for c in companies}
    sources = []
    if settings.fixture_mode:
        items = [i for i in load_fixture_announcements() if start <= datetime.fromisoformat(i.published) <= end]
        return {"items": items, "sources": [{"name": "FIXTURE", "status": "fixture", "detail": "Synthetic offline data"}]}
    try:
        items = fetch_nse(start, end, symbols)
        sources.append({"name": "NSE", "status": "ok", "detail": f"{len(items)} portfolio filings"})
        return {"items": items, "sources": sources}
    except SourceError as e:
        sources.append({"name": "NSE", "status": "error", "detail": e.message})
    items, failures = fetch_bse(start, end, companies)
    ok = len(companies) - len(failures)
    status = "ok" if not failures else ("partial" if ok else "error")
    detail = f"{len(items)} filings from {ok}/{len(companies)} companies"
    if failures:
        reason = failures[0].split(":", 1)[1].strip()
        detail += f"; failed ({reason}): {', '.join(f.split(':')[0] for f in failures[:6])}{'…' if len(failures) > 6 else ''}"
    sources.append({"name": "BSE", "status": status, "detail": detail})
    if status == "error" and snapshot.available():
        snap_items = [RawAnnouncement(**r) for r in snapshot.announcements()]
        items = [i for i in snap_items if start <= datetime.fromisoformat(i.published) <= end]
        sources.append({"name": "Snapshot", "status": "snapshot", "detail": snapshot.label()["note"]})
        return {"items": items, "sources": sources, "snapshot": snapshot.label()}
    return {"items": items, "sources": sources}
