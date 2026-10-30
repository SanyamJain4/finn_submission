# Submission checklist and covering email

## Before sending

- [ ] Push the repo to GitHub (public, or add the reviewers).
- [ ] Get a free Gemini API key (aistudio.google.com) and put it in `.env` locally.
- [ ] Run `python scripts/smoke_live.py TRENT` from `backend/` on your laptop. Fix anything that fails (most likely a Screener selector or an NSE/BSE field name) and re-run until the core checks pass.
- [ ] Deploy to Render with the blueprint (`render.yaml`), set `FINN_LLM_API_KEY`, open `/api/health`, then try Today and one research report **on your phone**.
- [ ] If NSE is blocked from Render, confirm the Today screen shows BSE as the answering source.
- [ ] Export the AI build history: the Claude Code session link for this build, plus any other ChatGPT/Claude share links.
- [ ] Fill in the bracketed links below and send to assessment@enam.com.

## Email

**Subject:** ENAM - IIT screening - 2027

Hello ENAM team,

Please find my submission for the FINN build challenge.

- Prototype (open on a phone): [deployed URL]
- Repository: [GitHub URL]
- AI build history: [Claude Code session link] [other links]

**What I built.** FINN is a triage tool, not a dashboard. The home screen is one sentence, for example "4 filings need you. 6 worth a glance. 7 routine, folded away." Behind it, every NSE/BSE filing across an 18-stock portfolio (15 sectors, large to small cap) is classified against your taxonomy and ranked by materiality, with the reasons shown so you can disagree with the ranking. Results filings open straight to Revenue, EBITDA, PBT and PAT versus last quarter and last year, read from the actual PDF with page references. Management changes show the incoming person's profile, taken from the "brief profile" SEBI requires in the filing itself. End-of-day price and volume alerts fire at thresholds you set. On the Pull side, any NSE ticker gets a report built only from the company's own documents. It covers trajectory, balance sheet, cash conversion, bull/bear, and the piece I care most about: promised vs delivered across the last four earnings calls. Every claim has a tappable citation.

**Key decisions.**
1. *The model reads; code judges.* For guidance, the LLM only extracts the exact quote and target. Code checks that the quote exists in the transcript, that the number is in the quote, and that the metric and period are comparable, then computes met / missed / beat against reported numbers. It refuses rather than guesses on segment-level or constant-currency guidance.
2. *Category is not priority.* A results filing and a results-meeting intimation share a category but not a priority. Ranking is a transparent score, not a black box.
3. *Grounding is enforced, not requested.* Each AI claim must cite a passage or a computed figure, and every number in it must appear in what it cites. Anything else is shown as "unverified".
4. *Cost.* The feed uses zero LLM calls. A full research report uses at most 6 (5 on a cheap model, 1 on a stronger one), and repeats are free because results are cached by prompt hash. No vector DB: BM25 over page chunks gives citable page numbers at this scale.
5. *Honest failure.* Each source reports its own status. If the exchanges can't be reached, FINN says so instead of showing a "quiet day". No data is ever invented.

**Deliberately left out.** Real push notifications (alerts are check-on-open, end-of-day), OCR for scanned filings, chat, and login. I'd rather ship two workflows that work than six that half-work.

**Next.** A scheduled check with web-push. Learning the priority weights from what the investor opens and dismisses. A running management-credibility score across all past calls. Tracking which questions analysts keep asking quarter over quarter.

Thank you for your time.

Sanyam Jain
IIT Kanpur
