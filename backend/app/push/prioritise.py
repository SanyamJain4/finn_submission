"""Transparent priority scoring - category and priority are deliberately separate.

score = category base + content signals + context (market move on the same company, repeats) - confidence cap.
Every adjustment appends a human-readable reason; the UI shows them, so the investor can disagree with us.
We never claim to predict price impact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

BASE = {
    "results": 55, "M&A": 60, "fund_raise": 55, "management_change": 50, "litigation": 55, "credit_rating": 40,
    "pledging": 50, "capex": 55, "bonus_split": 50, "dividend": 30, "insider_trading": 30, "press_release": 30,
    "earnings_call": 25, "investor_meetings": 10, "postal_ballot": 15, "agm_egm": 15, "unclassified": 5,
}

# (category or "*", regex, delta, reason)
SIGNALS: list[tuple[str, str, int, str]] = [
    ("results", r"intimation|to consider|will be held|is scheduled|prior intimation", -45, "Only schedules a results meeting"),
    ("results", r"newspaper|publication", -40, "Newspaper ad of already-published results"),
    ("results", r"outcome|approved|(un)?audited (standalone |consolidated )?financial results", 15, "Actual results filing"),
    ("management_change", r"\b(ceo|chief executive|managing director|\bmd\b|cfo|chief financial|chairman|chairperson|whole[- ]time director)", 30, "Top-management role (CEO/MD/CFO/Chair)"),
    ("management_change", r"independent director|non-executive", -10, "Board-level, non-executive change"),
    ("management_change", r"company secretary|compliance officer", -20, "Company secretary / compliance role"),
    ("management_change", r"resign|cessation|step(s|ping)? down", 10, "Departure rather than routine appointment"),
    ("management_change", r"re-?appoint", -25, "Re-appointment (continuity)"),
    ("M&A", r"incorporation of|wholly[- ]owned subsidiary", -20, "Subsidiary incorporation - usually administrative"),
    ("M&A", r"scheme of arrangement|demerger|merger|amalgamation", 10, "Structural change to the company"),
    ("fund_raise", r"\bqip\b|qualified institution|rights issue|preferential|warrants", 15, "Equity issuance - possible dilution"),
    ("fund_raise", r"buy-?back", 15, "Buyback - capital returned to shareholders"),
    ("fund_raise", r"commercial paper|\bncds?\b|debenture", -20, "Routine debt instrument"),
    ("litigation", r"sebi|nclt|insolvency|cci|warning letter|import alert|form 483|search|seizure", 20, "Regulator/insolvency involvement"),
    ("litigation", r"no (material|significant) (impact|effect)|not material", -25, "Company states no material impact"),
    ("credit_rating", r"downgrad|negative|watch with negative", 40, "Rating downgrade / negative outlook"),
    ("credit_rating", r"upgrad|positive", 15, "Rating upgrade / positive outlook"),
    ("credit_rating", r"reaffirm", -20, "Rating reaffirmed - no change"),
    ("pledging", r"invoc|creation|created", 15, "New pledge / invocation by lender"),
    ("pledging", r"release|revocation", -20, "Pledge released"),
    ("dividend", r"special dividend|interim dividend", 10, "Interim/special payout"),
    ("dividend", r"record date", -10, "Record-date notice"),
    ("earnings_call", r"transcript", 15, "Transcript now available - management commentary"),
    ("earnings_call", r"audio|recording|intimation|schedule", -10, "Call logistics only"),
    ("press_release", r"order|letter of award|contract", 15, "Order win / contract"),
    ("press_release", r"clarification|rumou?r|news item|media report", 20, "Responds to market rumour/report"),
    ("press_release", r"investor presentation", 5, "Management's own framing of results"),
    ("*", r"(₹|rs\.?|inr)\s?[\d,]+(\.\d+)?\s?(crore|cr\b|bn|billion)", 5, "Discloses a rupee amount"),
]
_SIG = [(c, re.compile(p, re.I), d, r) for c, p, d, r in SIGNALS]

AMOUNT_RE = re.compile(r"(?:₹|rs\.?|inr)\s?([\d,]+(?:\.\d+)?)\s?(crore|cr\b)", re.I)


@dataclass
class Priority:
    score: int
    tier: str  # high | medium | low
    reasons: list[str] = field(default_factory=list)


def tier_for(score: int) -> str:
    return "high" if score >= 60 else "medium" if score >= 30 else "low"


def score(category: str, confidence: float, subject: str, text: str, *, market_move: str | None = None,
          repeat_index: int = 0, has_document: bool = True) -> Priority:
    s = BASE.get(category, 5)
    reasons = [f"Category '{category}' base {s}"]
    blob = f"{subject} {text}"
    for cat, rx, delta, reason in _SIG:
        if (cat == category or cat == "*") and rx.search(blob):
            s += delta
            reasons.append(f"{'+' if delta >= 0 else ''}{delta}: {reason}")
    m = AMOUNT_RE.search(blob)
    if m:
        try:
            amt = float(m.group(1).replace(",", ""))
            if amt >= 1000:
                s += 10
                reasons.append(f"+10: Large amount (₹{amt:,.0f} cr)")
        except ValueError:
            pass
    if market_move:
        s += 10
        reasons.append(f"+10: Stock also flagged on EOD data ({market_move})")
    if repeat_index > 0:
        s -= 15
        reasons.append("-15: Another filing of the same type from this company in the window")
    if not has_document:
        reasons.append("No attachment on the exchange - summary from exchange text only")
    if confidence < 0.6:
        s = min(s, 45)
        reasons.append("Capped: low classification confidence")
    s = max(0, min(100, s))
    return Priority(s, tier_for(s), reasons)
