# FINN: Financial Investment Agent

A mobile-first intelligence layer for a public-markets investor. FINN answers two questions:

* **Push: "What changed, and should I care?"** Every exchange filing across an 18-stock portfolio is classified, ranked by materiality (with the reasons shown), and folded away if it's routine. Results filings get a first cut of Revenue / EBITDA / PBT / PAT, QoQ and YoY, read from the actual PDF. Management changes show the incoming person's profile, taken from the filing itself. End-of-day price and volume moves fire alerts at thresholds you set.
* **Pull: "Tell me about this company."** For any NSE ticker, FINN reads the standardised statements, the latest annual report and the last four earnings-call transcripts. It then reports on trajectory, balance sheet, cash quality, **what management promised vs what it delivered**, and a bull/bear case. Every claim carries a tappable citation to a page or a computed figure.

Five sections:

| Section | Answers | What's there |
|---|---|---|
| **Today** | What's happening in the market and my investments? | NIFTY 50 / SENSEX / BANK NIFTY / NIFTY IT (with close date and source), portfolio snapshot, a daily briefing whose every line is checked against its source, then watchlist filings triaged into *needs you / worth a glance / routine* |
| **Alerts** | What specifically needs my decision? | Only items that matched your rules (price ±X%, volume ≥N×, filing types and rank), grouped by type, with read / acknowledged states and the rule that fired |
| **Research** | Tell me about this company | Primary-source report: KPIs, revenue/margin and cash charts, a promised-vs-delivered scorecard, balance sheet, bull/bear, cited evidence |
| **Copilot** | Ask anything about my holdings, filings, companies | Answers only from FINN's data (prices, filings and parsed results, research reports, your holdings); every claim cited, unsupported numbers flagged; reachable from any filing, alert, holding or report |
| **My portfolio** | What do I own and how is it doing? | Holdings (qty, avg price) → value, day change, unrealised P&L, sector and market-cap allocation, best/worst. Separate from the **watchlist** FINN monitors |

Holdings, alert states, profile and chat history live in the visitor's browser; the server only values them, so a shared demo link never mixes two people's data.

## Run it

**Windows, one command** (sets up a venv, runs tests and the live smoke test, starts the app):
`powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1`

Manual setup:

```bash
# backend
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
cp .env.example .env            # optional: add an LLM key
# frontend (built once, then served by FastAPI)
cd frontend && npm ci && npm run build && cd ..
# start
cd backend && uvicorn app.main:app --env-file ../.env --port 8000
# open http://localhost:8000 (best viewed at phone width)
```

Development with hot reload: run `uvicorn app.main:app --reload` in `backend/` and `npm run dev` in `frontend/` (Vite proxies `/api`).

**Offline mode.** `FINN_FIXTURE_MODE=1` serves synthetic fixtures in the exact shapes of NSE/Yahoo/Screener responses and SEBI-format PDFs (regenerate them with `python scripts/make_fixtures.py`). The UI shows a permanent "Synthetic fixture data" banner. Never enable it in production.

## API

`GET /api/feed` · `GET /api/announcements/{uid}` · `GET /api/alerts` · `GET|PUT /api/prefs/alerts` · `GET /api/indices` · `POST /api/holdings/value` · `GET /api/holdings/example` · `POST /api/briefing` · `POST /api/copilot` · `POST /api/research` + `GET /api/research/jobs/{id}` · `GET /api/search` · `GET /api/diagnostics` · `GET /api/status`

## Configuration

All settings are environment variables; see [.env.example](.env.example). Nothing secret is committed.

| Variable | Purpose |
|---|---|
| `FINN_LLM_PROVIDER` | `gemini` (free tier, recommended), `anthropic`, `openai` (any OpenAI-compatible API: Groq, OpenRouter…), or `none` |
| `FINN_LLM_API_KEY` | Provider key. Without one, FINN still classifies, ranks, extracts results, computes every number and alert, and says which narrative sections need a model |
| `FINN_LLM_FAST_MODEL` / `FINN_LLM_SMART_MODEL` | Override model routing. For Gemini, leave empty: FINN discovers the newest stable Flash-Lite (extraction, briefing) and Flash (research synthesis, Copilot) available to your key |
| `FINN_LLM_BASE_URL` | Required for `openai`-type providers |
| `FINN_LLM_MAX_CALLS_PER_RESEARCH` | Hard cap on model calls per report (default 8; typical use is 6) |
| `FINN_DATA_DIR` | SQLite cache location |

## Deploy

One Docker image builds the React app and serves it from FastAPI.

* **Render:** push the repo, choose "New → Blueprint", and it picks up `render.yaml`. Set `FINN_LLM_API_KEY` in the dashboard.
* **Anywhere with Docker:** `docker build -t finn . && docker run -p 8000:8000 -e FINN_LLM_PROVIDER=gemini -e FINN_LLM_API_KEY=… finn`

### Hosting behind exchange IP blocks (important)

NSE and BSE block most cloud and datacenter IP ranges (Render, Railway, AWS, GCP…), so a hosted FINN usually can't fetch filings itself. You'll see this as *"Couldn't reach the exchanges"*, and Settings → **Test data sources from this server** shows exactly which sources are blocked.

FINN handles this with a **real-data snapshot**:

```bash
cd backend
python ../scripts/make_snapshot.py      # run where NSE/BSE work, e.g. your laptop in India
git add data/snapshot && git commit -m "Data snapshot" && git push
```

This captures the last 7 days of filings, EOD prices, the parsed details of the important filings, and research reports for the demo companies. When a live source fails, the server serves the snapshot and labels it ("Captured 31 Oct, 03:32 IST from BSE, Yahoo Finance"). The "last 24 hours" window is anchored to the capture time. Live sources are still tried first, so anything the host *can* reach (often Yahoo, Screener and the LLM) stays live. Research for a ticker outside the snapshot fails honestly and lists the companies that are available offline. Re-run the script to refresh.

## Tests

```bash
cd backend && python -m pytest -q                 # unit/API tests, no network
FINN_FIXTURE_MODE=1 uvicorn app.main:app &        # then:
node scripts/e2e_mobile.cjs                       # 28 mobile UI checks at 390x844 (Playwright)
cd backend && python ../scripts/smoke_live.py TRENT   # LIVE: real NSE/BSE/Yahoo/Screener + your LLM key
```

The unit suite covers ticker normalisation, QoQ/YoY/margin/CAGR maths (including zero bases, sign flips and losses), classification and fallback, priority scoring, dedupe, date windows, EOD thresholds and their edge cases, and results-PDF parsing (units, consolidated vs standalone, formula columns, losses). It also covers guidance verdicts, grounding of claims and quotes, the research pipeline with and without a (mocked) LLM, API validation, SSRF guards and the circuit breaker. **Mocked tests do not prove the live integrations work**; that's what `smoke_live.py` is for.

## What is verified and what isn't

| Area | Status |
|---|---|
| Classification, prioritisation, results extraction, EOD alerts, financial maths, guidance verdicts, grounding | Unit-tested |
| Full UI journeys on mobile | Playwright-tested against fixtures |
| Clean install + production start | Verified (fresh venv from `requirements.txt`) |
| Live NSE / BSE / Yahoo / Screener / LLM calls | **Not verified by me.** The build sandbox's network blocked every one of these hosts. Run `scripts/smoke_live.py` before relying on it |
| Docker image build | `Dockerfile` written; not built (no Docker daemon in the sandbox) |

The adapters follow these sources' public response formats as I understand them. Parsers are defensive and every failure is reported per source, but expect to adjust a selector or field name after the first live run.

## Known limitations

* **Alerts are pull-to-check, not push notifications.** End-of-day data plus a "Check now" button. A cron hitting `/api/alerts` is the obvious next step; I haven't claimed background monitoring.
* **Results extraction targets the SEBI table format.** Scanned PDFs (no text layer) and unusual layouts report "couldn't read" and link to the filing. There's no OCR. Bank formats get revenue/PBT/PAT but not EBITDA (not meaningful for lenders).
* **Pull uses Screener's standardised statements** (compiled from exchange filings) for multi-year numbers. Text evidence comes only from the company's own documents. Screener's AI "Notes" and "About" blurb are deliberately ignored.
* **Guidance verdicts are company-level, INR-reported metrics only.** Segment-level, constant-currency and capex guidance is shown as "can't compare" rather than forced.
* **Management bios come from the filing's "brief profile"** (a SEBI disclosure requirement). The Wikipedia fallback only accepts exact-name matches with company context. LinkedIn is not scraped (terms of service).
* Jobs live in process memory: a restart loses in-flight research. Finished reports are cached in SQLite for 24 hours.

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
