"""Management-change enrichment.

Key insight: SEBI LODR (Reg. 30, Schedule III) requires an appointment disclosure to include the appointee's
*brief profile*. So the most reliable bio is usually inside the filing itself - a primary source. We extract it
deterministically, optionally let the fast model structure it (every structured field must be found verbatim in
the passage, otherwise it is dropped), and only then try Wikipedia as a secondary, clearly labelled source.
LinkedIn is not scraped (terms of service).
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from .. import llm, storage
from ..config import settings
from ..http import SourceError, fetch, make_client

log = logging.getLogger("finn.people")

HONORIFIC = r"(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Shri|Smt\.?|Prof\.?)"
NAME_RE = re.compile(HONORIFIC + r"\s+([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){0,3})")
ROLE_RE = re.compile(r"(Chief [A-Z][a-z]+ Officer|CEO|CFO|COO|CTO|Managing Director(?: (?:&|and) (?:CEO|Chief Executive Officer))?|"
                     r"Whole[- ]time Director|Executive Director|Independent Director|Non-Executive Director|Chairman|Chairperson|"
                     r"Company Secretary(?: (?:&|and) Compliance Officer)?|President|Head of [A-Z][a-z]+)")
EFFECTIVE_RE = re.compile(r"(?:with effect from|w\.?e\.?f\.?|effective(?: from)?)\s*:?\s*([0-9]{1,2}[a-z]{0,2}[\s./-]+[A-Za-z0-9]+[\s.,/-]+\d{2,4})", re.I)
PROFILE_RE = re.compile(r"brief profile|profile of|background|experience", re.I)
IN_RE = re.compile(r"appoint|joined|elevat|designat|induct", re.I)
OUT_RE = re.compile(r"resign|cessation|ceas|step(?:s|ped)? down|retire|demise", re.I)


def direction(name: str, text: str) -> str:
    """Nearest verb within ~140 chars of the name decides incoming vs outgoing."""
    best: tuple[int, str] | None = None
    for m in re.finditer(re.escape(name), text):
        window_start = max(0, m.start() - 140)
        win = text[window_start:m.end() + 140]
        for rx, lab in ((IN_RE, "incoming"), (OUT_RE, "outgoing")):
            for v in rx.finditer(win):
                dist = abs((window_start + v.start()) - m.start())
                if best is None or dist < best[0]:
                    best = (dist, lab)
    return best[1] if best else "unclear"


class PersonProfile(BaseModel):
    name: str
    role: str | None = None
    direction: str = Field(description="incoming | outgoing | unclear")
    effective_date: str | None = None
    background: str | None = Field(None, description="2-3 sentence factual summary using only the passage")
    prior_roles: list[str] = Field(default_factory=list, description="verbatim employer/role phrases from the passage")
    education: list[str] = Field(default_factory=list)


class ProfileExtraction(BaseModel):
    people: list[PersonProfile]


def _profile_passage(text: str) -> str | None:
    m = PROFILE_RE.search(text)
    if not m:
        return None
    return re.sub(r"\s+", " ", text[m.start():m.start() + 1600]).strip()


def _grounded(phrase: str, source: str) -> bool:
    words = [w for w in re.findall(r"[a-z0-9]+", phrase.lower()) if len(w) > 2]
    low = source.lower()
    return bool(words) and sum(w in low for w in words) / len(words) >= 0.8


def extract_people(pages: list[str], subject: str) -> dict:
    text = "\n".join(pages[:6])
    names = list(dict.fromkeys(m.group(1).strip() for m in NAME_RE.finditer(text)))[:6]
    roles = list(dict.fromkeys(ROLE_RE.findall(text)))[:6]
    eff = EFFECTIVE_RE.search(text)
    passage = _profile_passage(text)
    flat = re.sub(r"\s+", " ", text)
    out = {"status": "ok" if (names or passage) else "not_found", "names": names, "roles": roles,
           "directions": {n: direction(n, flat) for n in names},
           "effective": eff.group(1) if eff else None, "profile_passage": passage,
           "profile_source": "Exchange filing (SEBI Reg. 30 disclosure)" if passage else None,
           "structured": None, "secondary": None, "notes": []}
    if not passage:
        out["notes"].append("The filing does not contain a brief-profile section.")
    if passage and settings.llm_enabled:
        try:
            res = llm.complete_json(ProfileExtraction, purpose="mgmt_profile", prompt=(
                f"Filing subject: {subject}\nExtract the people being appointed or leaving, from this passage only.\n"
                + llm.doc_block([("filing", text[:6000])])))
            people = []
            for p in res.people:
                if not _grounded(p.name, text):
                    continue
                p.prior_roles = [r for r in p.prior_roles if _grounded(r, text)]
                p.education = [e for e in p.education if _grounded(e, text)]
                people.append(p.model_dump())
            out["structured"] = people
        except Exception as e:  # noqa: BLE001
            out["notes"].append(f"Structuring skipped: {e if isinstance(e, llm.LLMError) else type(e).__name__}")
    incoming = [p["name"] for p in (out["structured"] or []) if p.get("direction") == "incoming"] or \
        [n for n, d in out["directions"].items() if d == "incoming"][:1]
    if incoming and not passage:
        out["secondary"] = wikipedia_profile(incoming[0], subject)
    return out


def wikipedia_profile(name: str, context: str) -> dict | None:
    """Secondary source, only accepted if the article text mentions a word from the company/subject context."""
    if settings.fixture_mode:
        return None
    key = f"wiki:{name.lower()}"
    hit = storage.cache_get(key)
    if hit is not None:
        return hit or None
    result: dict | None = None
    try:
        with make_client() as c:
            r = fetch(c, "https://en.wikipedia.org/w/rest.php/v1/search/page", "Wikipedia", params={"q": name, "limit": 3}, retries=1)
            ctx_words = {w for w in re.findall(r"[a-z]{4,}", context.lower())} - {"appointment", "resignation", "director", "officer", "chief", "change", "management", "limited"}
            for page in r.json().get("pages", []):
                if page.get("title", "").lower() != name.lower():
                    continue
                s = fetch(c, f"https://en.wikipedia.org/api/rest_v1/page/summary/{page['key']}", "Wikipedia", retries=1).json()
                extract = s.get("extract", "")
                if ctx_words & set(re.findall(r"[a-z]{4,}", extract.lower())):
                    result = {"source": "Wikipedia", "url": s.get("content_urls", {}).get("desktop", {}).get("page"),
                              "summary": extract[:700], "caveat": "Secondary source; matched on exact name + company context."}
                break
    except (SourceError, ValueError, KeyError) as e:
        log.info("wikipedia lookup failed: %s", e)
    storage.cache_set(key, result or {}, 7 * 86400)
    return result
