"""Narrative vs numbers.

Division of labour:
  LLM (fast tier)  -> finds explicit forward-looking statements in a transcript and normalises them into a schema.
  Code             -> checks the quote really contains the target, resolves the period, finds the actual number in
                      the standardised statements and decides met / missed / exceeded / pending / cannot evaluate.
The model never grades management; it only reads.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from .screener import period_from_label

Metric = Literal["revenue_growth", "ebitda_margin", "pat_growth", "volume_growth", "capex", "other"]


class GuidanceStatement(BaseModel):
    quote: str = Field(description="Exact sentence(s) copied from the transcript, max 60 words")
    evidence_id: str = Field(description="id attribute of the <document> the quote came from")
    speaker: str | None = Field(None, description="Speaker name/role if shown in the transcript")
    metric: Metric
    scope: Literal["company", "segment", "geography", "product", "unclear"] = "company"
    measurable: bool = Field(description="True only if a numeric target or range is stated")
    comparator: Literal["approx", "range", "at_least", "at_most", "none"] = "none"
    target_low: float | None = Field(None, description="Lower bound in % (growth or margin) or ₹ crore (capex)")
    target_high: float | None = None
    period: str | None = Field(None, description="Fiscal period the target refers to, as FYxx or Qn FYxx (Indian FY, Apr-Mar). Resolve relative phrases ('this year', 'next quarter') using the call date. null if not stated")
    basis_caveat: str | None = Field(None, description="e.g. 'constant currency', 'USD terms', 'excluding acquisition' if the quote says so")


class GuidanceExtraction(BaseModel):
    statements: list[GuidanceStatement] = Field(default_factory=list)


GUIDE_QUERY = ("guidance expect outlook target growth margin ebitda revenue FY next year quarter double digit "
               "percent aspire capex visibility confident trajectory going forward")
CANDIDATE_RE = re.compile(r"(guid|expect|target|aspir|outlook|going forward|we (will|should|would) (be|see|deliver|achieve)|confident)", re.I)
PCT_RE = re.compile(r"\d+(?:\.\d+)?\s?(%|percent|per cent|bps|basis points)|double[- ]digit|high single|mid[- ]teens|low teens", re.I)


def candidate_sentences(pages: list[str], limit: int = 6) -> list[dict]:
    """No-LLM fallback: sentences that look like guidance (forward verb + a number). Not evaluated."""
    out = []
    for pno, p in enumerate(pages, 1):
        for s in re.split(r"(?<=[.?!])\s+", re.sub(r"\s+", " ", p)):
            if 50 <= len(s) <= 400 and CANDIDATE_RE.search(s) and PCT_RE.search(s):
                out.append({"page": pno, "text": s.strip()})
                if len(out) >= limit:
                    return out
    return out


WORD_NUMS = {"double digit": 10.0, "double-digit": 10.0, "mid teens": 14.0, "mid-teens": 14.0, "low teens": 11.0, "high single": 7.0}


def _quote_supports(stmt: GuidanceStatement) -> bool:
    q = stmt.quote.lower()
    for t in (stmt.target_low, stmt.target_high):
        if t is None:
            continue
        num_ok = any(abs(float(n) - t) < 0.051 for n in re.findall(r"\d+(?:\.\d+)?", q.replace(",", "")))
        word_ok = any(w in q and abs(v - t) <= 1 for w, v in WORD_NUMS.items())
        if not (num_ok or word_ok):
            return False
    return True


def _parse_period(p: str | None) -> tuple[str, int, int | None] | None:
    if not p:
        return None
    m = re.match(r"\s*(?:Q([1-4])\s*)?FY\s*'?(\d{2,4})", p.upper().replace("-", " "))
    if not m:
        return None
    fy = int(m.group(2))
    fy = fy + 2000 if fy < 100 else fy
    return ("quarter" if m.group(1) else "fy", fy, int(m.group(1)) if m.group(1) else None)


def _actual(metric: str, period: tuple, analysis: dict) -> tuple[float | None, str | None, str | None]:
    """Return (actual value, period label, metric id) for a resolved period or (None, ...) if not reported yet."""
    kind, fy, q = period
    if kind == "fy":
        rows = {r["label"]: r for r in analysis["trajectory"]}
        for lbl, r in rows.items():
            pp = period_from_label(lbl)
            if pp and pp["fy"] == fy and pp["month"] == 3:
                val = {"revenue_growth": r["revenue_growth"], "ebitda_margin": r["opm"], "pat_growth": r["pat_growth"]}.get(metric)
                return val, r["period"], f"traj:{r['period']}"
        return None, f"FY{fy % 100:02d}", None
    for r in analysis["quarters"]:
        pp = period_from_label(r["label"])
        if pp and pp["fy"] == fy and pp["fq"] == q:
            val = {"revenue_growth": r["revenue_yoy"], "ebitda_margin": r["opm"], "pat_growth": r["pat_yoy"]}.get(metric)
            return val, r["period"], f"qtr:{r['period']}"
    return None, f"Q{q} FY{fy % 100:02d}", None


def evaluate(stmt: GuidanceStatement, analysis: dict, is_bank: bool) -> dict:
    row = {**stmt.model_dump(), "actual": None, "actual_period": None, "verdict": "cannot_evaluate", "reason": "", "actual_ref": None}
    if not stmt.measurable or stmt.comparator == "none" or stmt.target_low is None and stmt.target_high is None:
        row.update(verdict="qualitative", reason="No measurable target - qualitative commentary only.")
        return row
    if not _quote_supports(stmt):
        row.update(verdict="qualitative", reason="Target value not found in the quoted words - treated as unverified commentary.")
        return row
    if stmt.scope != "company":
        row["reason"] = f"Target is {stmt.scope}-level; FINN only has company-level standardised figures."
        return row
    if stmt.basis_caveat or re.search(r"constant currency|\bcc\b|usd|\$|dollar", stmt.quote, re.I):
        row["reason"] = "Stated on a different basis (e.g. constant currency / USD) than reported INR figures."
        return row
    if stmt.metric not in ("revenue_growth", "ebitda_margin", "pat_growth"):
        row["reason"] = f"'{stmt.metric}' is not available in the standardised statements."
        return row
    if stmt.metric == "ebitda_margin" and is_bank:
        row["reason"] = "Margin guidance for a lender does not map to operating margin."
        return row
    per = _parse_period(stmt.period)
    if not per:
        row["reason"] = "No resolvable time horizon in the statement."
        return row
    actual, plabel, ref = _actual(stmt.metric, per, analysis)
    row["actual_period"], row["actual_ref"] = plabel, ref
    if ref is None:
        row.update(verdict="pending", reason=f"{plabel} has not been reported yet.")
        return row
    if actual is None:
        row["reason"] = f"{plabel} figure is missing or not comparable (e.g. base was a loss)."
        return row
    row["actual"] = round(actual, 2)
    # Tolerance covers rounding only; "about X%" gets ±0.5pp. A 12-14% range delivered at 11% is a miss.
    tol = 0.5 if stmt.comparator == "approx" else 0.05
    lo = stmt.target_low if stmt.target_low is not None else stmt.target_high
    hi = stmt.target_high if stmt.target_high is not None else stmt.target_low
    if stmt.comparator == "at_least":
        verdict = "met" if actual >= lo - tol else "missed"
    elif stmt.comparator == "at_most":
        verdict = "met" if actual <= hi + tol else "missed"
    else:
        verdict = "missed" if actual < lo - tol else "exceeded" if actual > hi + tol else "met"
    unit = "pp" if stmt.metric == "ebitda_margin" else "%"
    tgt = f"{lo:g}" if lo == hi else f"{lo:g}–{hi:g}"
    row.update(verdict=verdict, reason=f"Target {tgt}{'%' if unit else ''} vs actual {actual:.1f}% for {plabel}.")
    if stmt.metric == "ebitda_margin":
        row["reason"] += " Actual uses Screener operating margin (EBITDA excl. other income); company definitions may differ slightly."
    return row
