"""Screener.in adapter - used for (a) resolving any NSE company, (b) discovering primary documents
(annual reports, concall transcripts, investor decks) and (c) standardised multi-year statements compiled from
exchange filings. Screener's own AI "Notes" and its "About" blurb are deliberately ignored (secondary content).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import portfolio, storage
from ..config import settings
from ..http import SourceError, fetch, make_client

log = logging.getLogger("finn.screener")
BASE = "https://www.screener.in"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "screener"
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def search(q: str) -> list[dict]:
    q = q.strip()[:60]
    if not q:
        return []
    if settings.fixture_mode:
        out = []
        for f in FIXTURE_DIR.glob("*.html"):
            sym = f.stem.upper()
            co = portfolio.by_symbol(sym) or {"name": sym}
            if q.upper() in sym or q.lower() in co["name"].lower():
                out.append({"symbol": sym, "name": co["name"], "url": f"/company/{sym}/consolidated/"})
        return out
    key = f"scr:search:{q.lower()}"
    hit = storage.cache_get(key)
    if hit is not None:
        return hit
    with make_client() as c:
        r = fetch(c, f"{BASE}/api/company/search/", "Screener", params={"q": q, "v": 3, "fts": 1})
    out = []
    for row in r.json():
        url = row.get("url") or ""
        m = re.match(r"/company/([^/]+)/", url)
        if not m:
            continue
        out.append({"symbol": m.group(1).upper(), "name": row.get("name"), "url": url})
    storage.cache_set(key, out, 7 * 86400)
    return out


def _num(s: str) -> float | None:
    s = (s or "").strip().replace(",", "").replace("%", "").replace("₹", "")
    if s in {"", "-", "—"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_table(section) -> dict | None:
    if section is None:
        return None
    table = section.find("table")
    if table is None:
        return None
    head = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    cols = head[1:]
    rows: dict[str, list[float | None]] = {}
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        label = re.sub(r"\s*\+\s*$", "", cells[0].get_text(" ", strip=True)).strip()
        if not label or label in rows:
            continue
        rows[label] = [_num(td.get_text(strip=True)) for td in cells[1:]]
    return {"columns": cols, "rows": rows} if rows and cols else None


def period_from_label(label: str) -> dict | None:
    m = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", label.strip())
    if not m:
        return None
    mo, yr = MONTHS.get(m.group(1).lower()), int(m.group(2))
    if not mo:
        return None
    fy = yr + 1 if mo >= 4 else yr
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(mo)
    return {"label": label, "month": mo, "year": yr, "fy": fy, "fq": q, "fy_label": f"FY{fy % 100:02d}",
            "q_label": f"Q{q} FY{fy % 100:02d}" if q else None}


def _documents(soup: BeautifulSoup) -> dict:
    docs = {"annual_reports": [], "concalls": [], "announcements": []}
    ar = soup.select_one(".documents.annual-reports") or soup.select_one("div.annual-reports")
    if ar:
        for a in ar.select("a[href]"):
            text = a.get_text(" ", strip=True)
            m = re.search(r"(?:Financial Year|FY)\s*(\d{4})", text)
            docs["annual_reports"].append({"title": text, "year": int(m.group(1)) if m else None, "url": urljoin(BASE, a["href"])})
    cc = soup.select_one(".documents.concalls") or soup.select_one("div.concalls")
    if cc:
        for li in cc.select("li"):
            date_el = li.find(["div", "span"])
            date_txt = date_el.get_text(" ", strip=True) if date_el else ""
            entry = {"date_label": date_txt, "transcript": None, "ppt": None, "recording": None}
            for a in li.select("a[href]"):
                t = a.get_text(" ", strip=True).lower()
                if "transcript" in t:
                    entry["transcript"] = urljoin(BASE, a["href"])
                elif "ppt" in t or "presentation" in t:
                    entry["ppt"] = urljoin(BASE, a["href"])
                elif "rec" in t:
                    entry["recording"] = urljoin(BASE, a["href"])
                # "Notes" are Screener's AI summaries - secondary, deliberately skipped
            m = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", date_txt)
            if m and MONTHS.get(m.group(1).lower()):
                entry["date"] = f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
            docs["concalls"].append(entry)
    return docs


def parse_company_page(html: str, symbol: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    name = h1.get_text(" ", strip=True) if h1 else symbol
    info = soup.select_one("#company-info") or soup.find(attrs={"data-company-id": True})
    bse = None
    for a in soup.select("a[href*='bseindia.com']"):
        m = re.search(r"BSE:\s*(\d{6})", a.get_text(" ", strip=True))
        if m:
            bse = m.group(1)
    top = {}
    for li in soup.select("#top-ratios li"):
        n = li.select_one(".name")
        v = li.select_one(".number")
        if n and v:
            top[n.get_text(strip=True)] = _num(v.get_text(strip=True))
    return {
        "symbol": symbol, "name": name, "bse_code": bse, "url": url,
        "company_id": info.get("data-company-id") if info else None,
        "warehouse_id": info.get("data-warehouse-id") if info else None,
        "top_ratios": top,
        "quarters": parse_table(soup.select_one("section#quarters")),
        "profit_loss": parse_table(soup.select_one("section#profit-loss")),
        "balance_sheet": parse_table(soup.select_one("section#balance-sheet")),
        "cash_flow": parse_table(soup.select_one("section#cash-flow")),
        "ratios": parse_table(soup.select_one("section#ratios")),
        "documents": _documents(soup),
        "retrieved": datetime.utcnow().isoformat() + "Z",
    }


def company(symbol: str) -> dict:
    """Fetch consolidated statements, falling back to standalone when the company reports none."""
    key = f"scr:company:{symbol}"
    hit = storage.cache_get(key)
    if hit is not None:
        return hit
    if settings.fixture_mode:
        f = FIXTURE_DIR / f"{symbol.lower()}.html"
        if not f.exists():
            raise SourceError("Screener", f"no fixture for {symbol}", 404)
        data = parse_company_page(f.read_text(), symbol, f"{BASE}/company/{symbol}/consolidated/")
        data["basis"] = "consolidated"
        return data
    with make_client() as c:
        data = None
        for basis, path in (("consolidated", f"/company/{symbol}/consolidated/"), ("standalone", f"/company/{symbol}/")):
            try:
                r = fetch(c, BASE + path, "Screener")
            except SourceError as e:
                if e.status == 404:
                    raise SourceError("Screener", f"'{symbol}' not found on Screener", 404) from e
                raise
            parsed = parse_company_page(r.text, symbol, BASE + path)
            if parsed["profit_loss"] and any(v is not None for v in next(iter(parsed["profit_loss"]["rows"].values()))):
                data = parsed
                data["basis"] = basis
                break
            data = parsed
            data["basis"] = basis
        assert data is not None
        data["capex"] = _capex(c, data)
    storage.cache_set(key, data, 12 * 3600)
    return data


def _capex(c, data: dict) -> dict | None:
    """Fixed-asset purchases from the cash-flow schedule (needed for FCF). Optional; absent -> FCF not computed."""
    cid = data.get("warehouse_id") or data.get("company_id")
    if not cid:
        return None
    try:
        r = fetch(c, f"{BASE}/api/company/{cid}/schedules/", "Screener", retries=1, params={
            "parent": "Cash from Investing Activity", "section": "cash-flow",
            "consolidated": "true" if data.get("basis") == "consolidated" else ""})
        sched = r.json()
    except (SourceError, ValueError) as e:
        log.info("capex schedule unavailable for %s: %s", data["symbol"], e)
        return None
    for label, series in sched.items():
        if re.search(r"fixed assets purchased|purchase of (fixed|property)", label, re.I) and isinstance(series, dict):
            return {"label": label, "values": {k: _num(str(v)) for k, v in series.items()}}
    return None
