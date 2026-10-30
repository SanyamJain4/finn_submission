"""Deterministic announcement classifier.

Ordered rules over the exchange subject + description. Each rule yields (category, confidence, matched phrase)
so the UI can show *why* something was classified. Anything that no rule matches confidently falls back to
`unclassified` with low confidence - we never force a category.

Category taxonomy follows the ENAM reference document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading", "earnings_call",
    "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex", "press_release", "postal_ballot",
    "agm_egm", "pledging", "unclassified",
]


@dataclass
class Classification:
    category: str
    confidence: float  # 0..1
    rule: str          # the phrase / rule that decided it


# (category, confidence, pattern). Order matters: specific before generic.
_RULES: list[tuple[str, float, str]] = [
    # Noise that superficially looks like other categories.
    ("unclassified", 0.9, r"trading window|loss of share certificate|duplicate share|reg(ulation)?\.?\s*74\s*\(5\)|certificate under sebi \(depositories|compliance certificate|esg report|business responsibility|book closure.*esop|change in (statutory |secretarial )?auditor|appointment of (statutory |secretarial )?auditor|kyc|investor complaints|spurt in volume"),
    ("pledging", 0.9, r"\bpledg|encumbrance|invocation of pledge|release of pledge"),
    ("insider_trading", 0.85, r"insider trading|regulation 7\(2\)|reg\.?\s*7\(2\)|sast|regulation 29|regulation 31|acquisition of shares by promoter|disclosure under sebi takeover"),
    ("credit_rating", 0.9, r"credit rating|\brating\b.*(crisil|icra|care|india ratings|fitch|moody|s&p|acuite|brickwork)|(crisil|icra|care ratings|india ratings).*(upgrad|downgrad|reaffirm|assign)"),
    ("earnings_call", 0.85, r"transcript|audio recording|earnings call|conference call|con\.? call|concall|analysts?/institutional investor meet/con\.? call updates.*(call|transcript)"),
    ("results", 0.9, r"financial results?|unaudited.*results|audited.*results|quarterly results|results for the (quarter|period)|financial result updates|integrated filing.*financial"),
    ("investor_meetings", 0.8, r"analysts?/institutional investor meet|investor meet|analyst meet|investor conference|one[- ]on[- ]one meeting|schedule of (analyst|investor)"),
    ("management_change", 0.85, r"change in (directorate|management|key managerial)|cessation|resignation|resigns|appointment of .*(director|ceo|cfo|chief|managing|company secretary|compliance officer|kmp|key managerial|chairman)|re-?appoint|retire(ment|s)? .*(director|ceo|md)|(ceo|cfo|managing director|whole[- ]time director|chief executive|chief financial).*(appoint|resign|step)"),
    ("M&A", 0.85, r"acquisition|acquire|amalgamation|merger|demerger|scheme of arrangement|joint venture|\bjv\b|stake sale|divest|disinvest|wholly[- ]owned subsidiary|incorporation of (a )?(new )?subsidiary|investment in (subsidiary|step-down)"),
    ("fund_raise", 0.85, r"qualified institutions? placement|\bqip\b|rights issue|preferential (issue|allotment)|buy-?back|non-convertible debenture|\bncds?\b|commercial paper|raising of funds|fund rais|issue of (equity|securities|warrants|bonds)|allotment of (equity|securities|debentures|warrants)"),
    ("litigation", 0.85, r"litigation|dispute|regulatory action|penalty|show cause|\border\b.*(sebi|court|tribunal|nclt|nclat|cci|gst|income tax)|nclt|insolvency|tax demand|demand notice|search (and|&) seizure|warning letter|fda|form 483|import alert|fine imposed"),
    ("bonus_split", 0.9, r"\bbonus\b|sub-?division|stock split|split of (equity )?shares"),
    ("dividend", 0.85, r"dividend|record date"),
    ("capex", 0.8, r"capex|capital expenditure|capacity expansion|new (plant|facility|manufacturing)|greenfield|brownfield|commissioning|commercial production"),
    ("postal_ballot", 0.9, r"postal ballot|e-?voting result"),
    ("agm_egm", 0.9, r"annual general meeting|\bagm\b|extra-?ordinary general meeting|\begm\b|shareholders'? meeting|scrutinizer'?s? report"),
    ("results", 0.6, r"board meeting.*(intimation|outcome)|outcome of board meeting|newspaper publication"),
    ("press_release", 0.75, r"press release|media release|order (win|received|bagged|inflow)|bags? (an )?order|letter of award|contract|partnership|launch|clarification|business update|updates?$|investor presentation"),
]
_UMBRELLA = re.compile(r"analysts?/institutional investor meet|^general updates?$|^updates?$|^outcome of board meeting$|^press release$", re.I)
_NOISE = re.compile(r"\b(esops?|esos|esps|employee stock option|employees? stock purchase)\b|trading window|loss of share certificate|duplicate share|reg(ulation)?\.?\s*74\s*\(5\)", re.I)
_COMPILED = [(c, conf, re.compile(p, re.I)) for c, conf, p in _RULES]


def classify(subject: str, text: str = "") -> Classification:
    subject = subject or ""
    text = text or ""
    # Routine paperwork is decided first on either field: "Allotment of Securities" under an ESOP is not a fund raise.
    m = _NOISE.search(subject) or _NOISE.search(text)
    if m:
        return Classification("unclassified", 0.85, f"routine: '{m.group(0)[:60]}'")
    # Subject (exchange-chosen category) is the strongest signal; then description. Some exchange subjects are
    # umbrella buckets (one NSE subject covers transcripts AND investor meetings), so for those the text decides.
    order = (("subject", subject, 1.0), ("text", text, 0.9))
    if _UMBRELLA.search(subject) and text:
        order = (("text", text, 0.9), ("subject", subject, 0.8))
    for field_name, s, weight in order:
        if not s:
            continue
        for cat, conf, rx in _COMPILED:
            m = rx.search(s)
            if m:
                # "Outcome of board meeting" often hides the real event in the description.
                if field_name == "subject" and conf < 0.7 and text:
                    deeper = _first_match(text)
                    if deeper and deeper.confidence >= 0.8:
                        return deeper
                return Classification(cat, round(conf * weight, 2), f"{field_name}: '{m.group(0)[:60]}'")
    return Classification("unclassified", 0.3, "no rule matched")


def _first_match(s: str) -> Classification | None:
    for cat, conf, rx in _COMPILED:
        m = rx.search(s)
        if m:
            return Classification(cat, round(conf * 0.9, 2), f"text: '{m.group(0)[:60]}'")
    return None
