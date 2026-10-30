# FINN architecture and decisions

## Shape

```
React (Vite, TS)  ──/api──▶  FastAPI ─┬─ push/      sources (NSE→BSE) · classify · prioritise · results · people · service
 Today / Alerts /             │        ├─ market.py  yfinance → Yahoo chart API · anomaly rules
 Research / Settings          │        ├─ research/  screener · analysis · guidance · service (jobs)
                              │        ├─ documents  PDF → page text (row-preserving) · chunking · BM25
                              │        ├─ llm.py     fast/smart routing · JSON schemas · cache · usage log
                              │        └─ http.py    host allowlist · politeness · retries · circuit breaker
                              └── SQLite: TTL cache, documents by content hash, LLM usage, preferences
```

One process, one SQLite file, one Docker image. There's no vector DB, no queue and no agent framework; at this scale each would add moving parts without improving the answer.

## Push pipeline

1. **Fetch.** NSE's announcements API returns every equity filing in a window in *one* call, which is filtered to the portfolio. If NSE refuses (common from cloud IPs), FINN falls back to BSE's per-scrip API. Each source's status is returned with the feed.
2. **Dedupe** by exchange id, then by (company, normalised subject, minute).
3. **Classify, deterministically.** Ordered regex rules over the exchange subject and description map filings to the ENAM taxonomy, recording the phrase that decided it. Routine paperwork (ESOP allotments, trading-window notices, Reg. 74(5) certificates) is caught first. Umbrella subjects such as NSE's "Analysts/Institutional Investor Meet/Con. Call Updates" are decided from the description. No match means `unclassified` at low confidence; nothing is forced.
4. **Prioritise. Category is not priority.** Score = category base + content signals + context, and every adjustment is a human-readable reason shown in the UI. Examples: a results *filing* +15, a results *intimation* −45, a newspaper ad −40; CEO/CFO/MD +30, company secretary −20; rating downgrade +40, reaffirmation −20; an EOD move on the same stock +10; a repeat filing of the same type −15. Low classification confidence caps the score. FINN never claims to predict price impact.
5. **Enrich on open, not in bulk.** The feed costs zero LLM calls. Opening a filing downloads the PDF once (cached by content hash), then:
   * **Results:** finds the results table (preferring consolidated and recording the basis) and confirms the current / previous / year-ago column order from header dates. It reads the four rows verbatim, normalises units to ₹ crore, and derives EBITDA = PBT before exceptional items + finance costs + D&A − other income, with the formula shown. Each figure keeps its page number and raw row.
   * **Management change:** SEBI LODR requires a "brief profile" in appointment disclosures, so the bio comes from the filing itself (primary source). Incoming vs outgoing is decided by the nearest verb. An optional fast-model pass structures it, and every structured field must appear in the filing text or it's dropped.
   * **Everything else:** key lines (sentences with decisions, amounts or dates), plus an optional one-sentence model summary whose numbers must all appear in the filing.
6. **Alerts.** User rules (categories, minimum tier, ±price %, volume multiple, baseline window) are evaluated over the feed and the last completed EOD session. Insufficient history, zero-volume baselines, missing bars and stale data are all handled explicitly.

## Pull pipeline

```
resolve (portfolio / ticker / Screener search)
  → standardised statements (consolidated, else standalone) + capex schedule
  → deterministic analysis: CAGR, margins, D/E, CCC, CFO/PAT, FCF  →  metric ids "M:rev_cagr_5y"
  → discover docs: latest annual report + last 4 transcripts  →  page text  →  chunks  →  BM25
  → fast model: business snapshot (1 call) + guidance per transcript (≤4 calls)
  → code: verify each quote exists in its passage; compute verdicts against reported numbers
  → smart model: one synthesis call over metrics, verdicts and retrieved passages
  → groundedness check: each AI claim must cite a passage or metric, and every number in it must appear in what it cites
```

**Narrative vs numbers is the centrepiece, and the model never grades management.** The model only *reads*: it returns the exact quote, the metric, the scope, the comparator, the target and the period. The code then:

* rejects quotes not found in the cited passage (invented or paraphrased);
* downgrades to "no hard number" any target that isn't in the quote's own words;
* refuses segment-level, constant-currency/USD and non-standard metrics ("can't compare");
* resolves the Indian fiscal period and marks unreported periods "not yet reported";
* compares against reported figures: range → missed / met / beat; ≥X → met / missed. Tolerance covers rounding only (±0.5pp for "about X%"), so 11% against "12–14%" is a miss.

**Without an LLM** the report still has every number, table and rule-based observation, plus "candidate guidance sentences" clearly marked as not evaluated.

## Cost

| Step | Model calls |
|---|---|
| Feed, classification, ranking, alerts, results tables | 0 |
| Opening a non-results filing | ≤1 fast (cached per filing) |
| Opening a management change | ≤1 fast (cached) |
| Research report | 1 fast (business) + ≤4 fast (guidance) + 1 smart (synthesis) = **≤6**, capped by config |
| Repeat report within 24h / identical prompt within 30 days | 0 (report cache / prompt-hash cache) |

Retrieval keeps prompts small: 5–7 passages of ~1,400 characters each, never whole documents. Token usage per model is logged and shown in Settings.

## Reliability and safety

* Per-source status is surfaced on every feed and report. Nothing is invented on failure. When live data fails, the last cached EOD data can be shown, labelled as such.
* **Circuit breaker:** three consecutive network failures to a host skip it for two minutes, so an outage costs seconds rather than minutes. yfinance is time-boxed at 25s.
* **SSRF:** the app only fetches allow-listed hosts. Document links discovered on Screener may point to company IR sites, which are allowed only over https to public IPs, re-checked after redirects. User input is never used as a URL.
* **Prompt injection:** source text is wrapped as untrusted `<document>` data and the model has no tools. The worst an injected instruction can do is corrupt a field, which the grounding checks then catch.
* All inputs are validated (pydantic), and errors come back as a consistent JSON shape.

## Deliberately left out

Authentication, push notifications/scheduling, OCR, a vector store, chat. The brief rewards "thin but working". A chat box over this data would have been the obvious interaction model; triage plus cited research is the point of view instead.

## Next

1. A scheduled `/api/alerts` check with web-push, so "Push" is truly push.
2. Learn the priority weights from what the investor opens and dismisses (the reasons list is already the feature vector).
3. Track guidance across all available transcripts to give a management credibility score per company over time.
4. Use concall Q&A to surface what analysts keep pressing on, quarter over quarter.
