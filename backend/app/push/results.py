"""Quarterly-results extraction from the actual exchange filing.

SEBI's results format fixes the first three numeric columns as:
  [quarter ended (current)] [preceding quarter] [corresponding quarter of previous year] [YTD...] [year]
We confirm that order from the header dates when they are present, and say so when we had to assume it.

Values are read verbatim from the row text (grounded by construction), converted to ₹ crore, and the page
number + raw row are kept as evidence. EBITDA is rarely reported, so it is *derived* and labelled with its formula.
Consolidated is preferred over standalone and the basis is always reported - never mixed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .. import finance

NUM = r"\(?-?\d[\d,]*(?:\.\d+)?\)?|(?<!\w)[-–—](?!\w)"
NUM_RE = re.compile(NUM)
FORMULA_RE = re.compile(r"\(\s*[\dIVXivx]+\s*[-+±]\s*[\dIVXivx]+(?:\s*[-+]\s*[\dIVXivx]+)*\s*\)")
NOTE_RE = re.compile(r"\((?:refer\s+)?note\s*(?:no\.?\s*)?\d+[a-z]?\)|note\s+\d+", re.I)
DATE_RE = re.compile(
    r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})|(\d{1,2})[\s-]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,-]+(\d{4})|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})", re.I)
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}

ROW_PATTERNS = {
    "revenue": [r"revenue from operations", r"total revenue from operations", r"income from operations", r"interest earned"],
    "other_income": [r"other income"],
    "finance_costs": [r"finance costs?", r"interest expended", r"interest expense"],
    "dep": [r"depreciation"],
    "pbt_pre_exc": [r"profit.{0,12}before exceptional items? and tax"],
    "exceptional": [r"^exceptional items?"],
    "pbt": [r"profit.{0,12}before tax"],
    "pat": [r"^(?:net )?profit.{0,12}(?:for|after tax for) the (?:period|quarter)", r"^(?:net )?profit.{0,12}after tax", r"^net profit"],
}
EXCLUDE = {
    "pbt": re.compile(r"exceptional", re.I),
    "pat": re.compile(r"attributable|comprehensive|before|non-controlling|discontinued", re.I),
    "revenue": re.compile(r"other", re.I),
}
UNIT_RE = re.compile(r"(?:₹|rs\.?|inr|rupees)?\s*(?:in\s+)?(crores?|lakhs?|lacs|millions?|billions?)\b", re.I)


@dataclass
class Row:
    key: str
    page: int
    raw: str
    values: list[float]


@dataclass
class ResultsExtraction:
    status: str                       # ok | partial | not_found | unsupported
    basis: str | None = None          # consolidated | standalone
    unit_source: str | None = None
    periods: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def _parse_date(m: re.Match) -> date | None:
    try:
        if m.group(1):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif m.group(4):
            d, mo, y = int(m.group(4)), MONTHS[m.group(5).lower()[:3]], int(m.group(6))
        else:
            mo, d, y = MONTHS[m.group(7).lower()[:3]], int(m.group(8)), int(m.group(9))
        if y < 100:
            y += 2000
        return date(y, mo, d)
    except (ValueError, KeyError, TypeError):
        return None


def _numbers_after(text: str) -> list[float]:
    text = NOTE_RE.sub(" ", FORMULA_RE.sub(" ", text))
    vals = []
    for tok in NUM_RE.findall(text):
        v = finance.parse_number(tok)
        if v is not None:
            vals.append(v)
    return vals


def _page_basis(page: str) -> str | None:
    head = page[:1500].lower()
    if "consolidated" in head:
        return "consolidated"
    if "standalone" in head:
        return "standalone"
    return None


def _is_results_page(page: str) -> bool:
    low = page.lower()
    return ("before tax" in low) and ("revenue" in low or "income from operations" in low or "interest earned" in low)


def _find_rows(page_text: str, page_no: int) -> dict[str, Row]:
    lines = page_text.split("\n")
    found: dict[str, Row] = {}
    for i, line in enumerate(lines):
        stripped = re.sub(r"^\s*(?:\d{1,2}|[ivxIVX]{1,4}|\(?[a-hA-H]\))[\s.)]+", "", line).strip()
        low = stripped.lower()
        for key, pats in ROW_PATTERNS.items():
            if key in found:
                continue
            for p in pats:
                m = re.search(p, low)
                if not m:
                    continue
                if key in EXCLUDE and EXCLUDE[key].search(low[: m.end() + 40]):
                    continue
                vals = _numbers_after(stripped[m.end():])
                raw = line.strip()
                if len(vals) < 3 and i + 1 < len(lines):
                    nxt = lines[i + 1]
                    nv = _numbers_after(nxt)
                    if len(nv) >= 3 and len(re.sub(NUM, "", nxt).strip()) < 40:
                        vals, raw = nv, raw + " / " + nxt.strip()
                if len(vals) >= 3:
                    found[key] = Row(key, page_no, raw[:300], vals)
                break
    return found


def _detect_columns(page_text: str) -> tuple[list[date], str]:
    for line in page_text.split("\n")[:60]:
        ds = [d for d in (_parse_date(m) for m in DATE_RE.finditer(line)) if d]
        if len(ds) >= 3:
            return ds, line.strip()[:200]
    # dates may be stacked one per line in the header; collect in reading order
    ds = []
    for line in page_text.split("\n")[:60]:
        ds += [d for d in (_parse_date(m) for m in DATE_RE.finditer(line)) if d]
    return ds, ""


def extract_results(pages: list[str]) -> ResultsExtraction:
    candidates = [(i + 1, p) for i, p in enumerate(pages) if _is_results_page(p)]
    if not candidates:
        return ResultsExtraction("not_found", notes=["No results table found in the filing text."])
    by_basis: dict[str, list] = {"consolidated": [], "standalone": [], None: []}
    for n, p in candidates:
        by_basis[_page_basis(p)].append((n, p))
    for basis in ("consolidated", "standalone", None):
        for page_no, text in by_basis[basis]:
            rows = _find_rows(text, page_no)
            if {"revenue", "pbt"} <= rows.keys() or {"revenue", "pat"} <= rows.keys():
                return _build(rows, text, page_no, basis)
    return ResultsExtraction("not_found", notes=["Results pages found but key rows (revenue/PBT/PAT) could not be parsed."])


def _build(rows: dict[str, Row], text: str, page_no: int, basis: str | None) -> ResultsExtraction:
    notes: list[str] = []
    um = UNIT_RE.search(text[:3000])
    unit_word = um.group(1).lower().rstrip("s") if um else None
    unit_word = {"lac": "lakh"}.get(unit_word, unit_word)
    if unit_word not in finance.UNIT_TO_CRORE:
        notes.append("Unit not stated on the page; values shown as reported (assumed ₹ crore).")
        factor, unit_src = 1.0, None
    else:
        factor, unit_src = finance.UNIT_TO_CRORE[unit_word], um.group(0).strip()

    dates, header = _detect_columns(text)
    periods = {}
    if len(dates) >= 3:
        cur, prev, yoy = dates[:3]
        if cur > prev and abs((cur - yoy).days - 365) <= 3 and 80 <= (cur - prev).days <= 100:
            periods = {"current": cur.isoformat(), "prev_quarter": prev.isoformat(), "year_ago": yoy.isoformat(), "confirmed": True}
        else:
            notes.append("Header dates do not follow the standard current / previous / year-ago order; check the filing.")
            periods = {"confirmed": False, "header": header}
    else:
        periods = {"confirmed": False}
        notes.append("Column order assumed from the SEBI format (current, previous quarter, year-ago quarter).")

    def v(key: str, idx: int) -> float | None:
        r = rows.get(key)
        return None if not r or len(r.values) <= idx else r.values[idx] * factor

    if "interest earned" in (rows.get("revenue").raw.lower() if rows.get("revenue") else ""):
        notes.append("Bank format detected: 'Revenue' = interest earned; EBITDA is not meaningful for banks.")
        bank = True
    else:
        bank = False

    metrics = {}
    for key, label in (("revenue", "Revenue"), ("pbt", "PBT"), ("pat", "PAT")):
        metrics[key] = {"label": label, **finance.comparison(v(key, 0), v(key, 1), v(key, 2))}

    # EBITDA (derived): PBT before exceptional items + finance costs + D&A - other income
    ebitda = [None, None, None]
    if not bank:
        base_key = "pbt_pre_exc" if "pbt_pre_exc" in rows else "pbt"
        exc = rows.get("exceptional")
        for i in range(3):
            parts = [v(base_key, i), v("finance_costs", i), v("dep", i), v("other_income", i)]
            if None not in parts:
                ebitda[i] = parts[0] + parts[1] + parts[2] - parts[3]
        if base_key == "pbt" and exc and any(x != 0 for x in exc.values[:3]):
            notes.append("EBITDA includes exceptional items (no 'before exceptional items' line found).")
        missing = [k for k in ("finance_costs", "dep", "other_income") if k not in rows]
        if missing:
            notes.append(f"EBITDA not derivable: missing {', '.join(missing)} row(s).")
    metrics["ebitda"] = {"label": "EBITDA", "derived": True,
                         "formula": "PBT (pre-exceptional) + finance costs + D&A − other income",
                         **finance.comparison(*ebitda)}
    for key in ("ebitda", "pbt", "pat"):
        metrics[key]["margin_current"] = finance.margin(metrics[key]["current"], metrics["revenue"]["current"])
        metrics[key]["margin_year_ago"] = finance.margin(metrics[key]["year_ago"], metrics["revenue"]["year_ago"])

    if metrics["revenue"]["current"] is not None and metrics["revenue"]["current"] <= 0:
        notes.append("Revenue parsed as ≤ 0 - extraction is probably wrong; verify against the filing.")
    if basis is None:
        notes.append("Could not tell whether this table is consolidated or standalone.")

    evidence = [{"metric": r.key, "page": r.page, "row": r.raw, "values_as_reported": r.values[:3]} for r in rows.values()]
    core = [metrics[k]["current"] for k in ("revenue", "pbt", "pat")]
    status = "ok" if None not in core else "partial"
    return ResultsExtraction(status, basis, unit_src, periods, metrics, evidence, notes)
