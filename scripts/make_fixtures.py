"""Generate SYNTHETIC fixtures in the exact shapes of the live sources (NSE JSON, Yahoo bars, Screener HTML,
SEBI-format results PDF, appointment letter, transcript, annual report).

They exist so the parsers can be unit-tested and the UI developed offline. Every document is stamped
"SYNTHETIC FIXTURE - NOT A REAL FILING" and the app shows a permanent banner in fixture mode.
Run: python scripts/make_fixtures.py
"""
from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import pymupdf as fitz  # PyMuPDF

OUT = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"
DOCS = OUT / "docs"
SCR = OUT / "screener"
STAMP = "SYNTHETIC FIXTURE - NOT A REAL FILING"
ARCH = "https://nsearchives.nseindia.com/corporate/"


def pdf(name: str, pages: list[list[tuple[float, float, str, float]]]) -> None:
    d = fitz.open()
    for items in pages:
        p = d.new_page(width=842, height=595)
        p.insert_text((40, 20), STAMP, fontsize=8)
        for x, y, text, size in items:
            p.insert_text((x, y), text, fontsize=size)
    d.save(DOCS / name)


def text_pages(lines: list[str], per_page: int = 38) -> list[list[tuple]]:
    pages = []
    for i in range(0, len(lines), per_page):
        pages.append([(40, 50 + 13 * j, ln, 9) for j, ln in enumerate(lines[i:i + per_page])])
    return pages


def results_pdf() -> None:
    cols = [430, 505, 580, 655, 730]
    rows = [
        ("1  Revenue from operations", ["16,412.30", "15,208.75", "14,105.60", "31,621.05", "58,940.10"]),
        ("2  Other income", ["212.40", "198.10", "175.25", "410.50", "702.30"]),
        ("3  Total income (1+2)", ["16,624.70", "15,406.85", "14,280.85", "32,031.55", "59,642.40"]),
        ("4  Expenses", ["", "", "", "", ""]),
        ("   (a) Cost of materials consumed", ["9,850.00", "9,301.20", "8,790.40", "19,151.20", "36,020.55"]),
        ("   (b) Employee benefits expense", ["1,402.10", "1,377.45", "1,250.05", "2,779.55", "5,110.00"]),
        ("   (c) Finance costs", ["310.55", "295.40", "330.10", "605.95", "1,250.80"]),
        ("   (d) Depreciation and amortisation expense", ["645.20", "630.10", "590.75", "1,275.30", "2,410.20"]),
        ("   (e) Other expenses", ["1,890.35", "1,765.60", "1,702.30", "3,655.95", "6,920.10"]),
        ("   Total expenses", ["14,098.20", "13,369.75", "12,663.60", "27,467.95", "51,711.65"]),
        ("5  Profit before exceptional items and tax (3-4)", ["2,526.50", "2,037.10", "1,617.25", "4,563.60", "7,930.75"]),
        ("6  Exceptional items", ["-", "(120.00)", "-", "(120.00)", "-"]),
        ("7  Profit before tax (5+6)", ["2,526.50", "1,917.10", "1,617.25", "4,443.60", "7,930.75"]),
        ("8  Tax expense", ["640.10", "490.25", "410.60", "1,130.35", "2,010.40"]),
        ("9  Profit for the period (7-8)", ["1,886.40", "1,426.85", "1,206.65", "3,313.25", "5,920.35"]),
        ("10 Profit attributable to owners of the company", ["1,850.20", "1,401.10", "1,190.00", "3,251.30", "5,830.10"]),
    ]
    items = [(40, 45, "DIXON TECHNOLOGIES (INDIA) LIMITED  [fixture]", 11),
             (40, 62, "Statement of Unaudited Consolidated Financial Results for the quarter and half year ended 30 September 2026", 9),
             (40, 76, "(Rs. in Crores, except per share data)", 8),
             (40, 96, "Particulars", 8)]
    hdr = ["30.09.2026", "30.06.2026", "30.09.2025", "30.09.2026", "31.03.2026"]
    for x, h in zip(cols, hdr):
        items.append((x, 96, h, 8))
    for x, h in zip(cols, ["Unaudited", "Unaudited", "Unaudited", "Unaudited", "Audited"]):
        items.append((x, 108, h, 7))
    y = 126
    for label, vals in rows:
        items.append((40, y, label, 8))
        for x, v in zip(cols, vals):
            if v:
                items.append((x, y, v, 8))
        y += 16
    standalone = [(40, 45, "Statement of Unaudited Standalone Financial Results for the quarter ended 30 September 2026", 9),
                  (40, 70, "1  Revenue from operations", 8), (430, 70, "9,000.00", 8), (505, 70, "8,500.00", 8), (580, 70, "8,000.00", 8),
                  (40, 86, "7  Profit before tax", 8), (430, 86, "900.00", 8), (505, 86, "850.00", 8), (580, 86, "800.00", 8)]
    cover = text_pages([
        "Date: 29 October 2026", "To, National Stock Exchange of India Limited", "Symbol: DIXON",
        "Sub: Outcome of Board Meeting - Unaudited Financial Results for the quarter ended 30 September 2026",
        "The Board of Directors at its meeting held today approved the unaudited standalone and consolidated financial results.",
    ])
    pdf("FIXTURE_DIXON_RESULTS.pdf", cover + [standalone, items])


def appointment_pdf() -> None:
    lines = [
        "Date: 29 October 2026", "To, BSE Limited / National Stock Exchange of India Limited", "Symbol: POLYCAB",
        "Sub: Appointment of Chief Financial Officer under Regulation 30 of SEBI (LODR) Regulations, 2015",
        "We wish to inform that the Board of Directors, on the recommendation of the Nomination and Remuneration Committee,",
        "has approved the appointment of Ms. Anjali Verma as Chief Financial Officer (Key Managerial Personnel) of the Company",
        "with effect from 1 November 2026, in place of Mr. Rohan Mehta who has resigned to pursue opportunities outside the Company.",
        "", "Annexure A - Details under Regulation 30",
        "Reason for change: Appointment consequent to resignation of the previous CFO.",
        "Brief profile: Ms. Anjali Verma is a Chartered Accountant with over 22 years of experience in corporate finance.",
        "She was previously Chief Financial Officer of Fictional Electricals Limited, where she led treasury and investor relations,",
        "and earlier held finance leadership roles at Example Consumer Durables Limited. She is a commerce graduate from",
        "the University of Mumbai. She is not related to any Director of the Company.",
    ]
    pdf("FIXTURE_POLYCAB_CFO.pdf", text_pages(lines))


def order_pdf() -> None:
    lines = ["Date: 29 October 2026", "Symbol: HAL", "Sub: Press Release - Order received",
             "Hindustan Aeronautics Limited [fixture] has received an order valued at Rs. 2,450 crore for helicopter support services.",
             "The order is to be executed over 36 months."]
    pdf("FIXTURE_HAL_ORDER.pdf", text_pages(lines))


def transcript_pdf(name: str, quarter: str, lines_extra: list[str]) -> None:
    lines = [f"IRCTC [fixture] {quarter} Earnings Conference Call", "Moderator: Good afternoon and welcome.",
             "Management: Thank you. Let me take you through the performance for the quarter."] + lines_extra + [
             "Analyst: Could you explain why catering margins declined this quarter?",
             "Management: Input cost inflation weighed on catering, we are taking price actions."]
    pdf(name, text_pages(lines))


def annual_report_pdf() -> None:
    lines = ["IRCTC [fixture] Annual Report FY2026", "Management Discussion and Analysis",
             "Business overview: The Company operates four business segments - Internet Ticketing, Catering, Rail Neer",
             "(packaged drinking water) and Tourism. Internet Ticketing contributed 31% of revenue from operations, Catering 45%,",
             "Tourism 17% and Rail Neer 7% in FY2026.",
             "Risks and concerns: Competition from private platforms and changes in convenience-fee policy are key risks.",
             "Outlook: The Company plans capacity expansion at Rail Neer plants and new tourism trains."]
    pdf("FIXTURE_IRCTC_AR_FY2026.pdf", text_pages(lines))


def announcements() -> list[dict]:
    def a(sym, name, desc, text, hours, att=None, seq=None):
        return {"symbol": sym, "sm_name": name, "desc": desc, "attchmntText": text, "sort_date": f"-{hours}h",
                "an_dt": "", "attchmntFile": (ARCH + att) if att else "-", "seq_id": seq or f"fx{abs(hash((sym, desc, hours))) % 10**8}"}
    return [
        a("DIXON", "Dixon Technologies (India) Limited", "Outcome of Board Meeting", "Dixon Technologies has informed the Exchange that the Board approved unaudited financial results for the quarter ended September 30, 2026.", 3, "FIXTURE_DIXON_RESULTS.pdf", "fx1001"),
        a("POLYCAB", "Polycab India Limited", "Change in Management", "Polycab India Limited has informed the Exchange about appointment of Ms. Anjali Verma as Chief Financial Officer and resignation of Mr. Rohan Mehta as CFO.", 5, "FIXTURE_POLYCAB_CFO.pdf", "fx1002"),
        a("HAL", "Hindustan Aeronautics Limited", "Press Release", "HAL has received an order of Rs. 2,450 crore for helicopter support services.", 7, "FIXTURE_HAL_ORDER.pdf", "fx1003"),
        a("TATASTEEL", "Tata Steel Limited", "Credit Rating", "Tata Steel has informed the Exchange that CRISIL has reaffirmed the long-term rating at AA+/Stable.", 9, None, "fx1004"),
        a("SUNPHARMA", "Sun Pharmaceutical Industries Limited", "Litigation / Dispute / Regulatory Action", "Sun Pharma has received a Warning Letter from US FDA for its Halol facility.", 11, None, "fx1005"),
        a("ITC", "ITC Limited", "Board Meeting Intimation", "ITC Limited has informed the Exchange that a meeting of the Board will be held to consider financial results for the quarter ending September 2026.", 2, None, "fx1006"),
        a("TCS", "Tata Consultancy Services Limited", "Analysts/Institutional Investor Meet/Con. Call Updates", "TCS has informed the Exchange about the transcript of the earnings call held on October 9, 2026.", 14, None, "fx1007"),
        a("RELIANCE", "Reliance Industries Limited", "Certificate under SEBI (Depositories and Participants) Regulations, 2018", "Compliance certificate under Regulation 74(5).", 6, None, "fx1008"),
        a("HDFCBANK", "HDFC Bank Limited", "Allotment of Securities", "HDFC Bank has allotted equity shares under ESOS to employees.", 8, None, "fx1009"),
        a("MARUTI", "Maruti Suzuki India Limited", "Trading Window", "Closure of trading window.", 10, None, "fx1010"),
        a("BAJFINANCE", "Bajaj Finance Limited", "Issue of Securities", "Bajaj Finance has issued Commercial Paper aggregating Rs. 500 crore.", 12, None, "fx1011"),
        a("APOLLOHOSP", "Apollo Hospitals Enterprise Limited", "Acquisition", "Apollo Hospitals has informed about incorporation of a wholly owned subsidiary.", 15, None, "fx1012"),
        a("NTPC", "NTPC Limited", "Copy of Newspaper Publication", "Newspaper publication of financial results.", 16, None, "fx1013"),
        a("DEEPAKNTR", "Deepak Nitrite Limited", "Updates", "Deepak Nitrite has informed about commissioning of new phenol capacity of 200 KTPA at Dahej.", 18, None, "fx1014"),
        a("KAYNES", "Kaynes Technology India Limited", "Shareholders meeting", "Notice of Postal Ballot for approval of related party transactions.", 20, None, "fx1015"),
        a("PERSISTENT", "Persistent Systems Limited", "Change in Directorate", "Appointment of Mr. Arjun Rao as Independent Director.", 22, None, "fx1016"),
        a("AFFLE", "Affle (India) Limited", "Disclosure under SEBI Takeover Regulations", "Disclosure under Regulation 29(2) by promoter group for sale of shares.", 23, None, "fx1017"),
        a("LT", "Larsen & Toubro Limited", "Press Release", "L&T bags significant order (Rs. 1,000-2,500 crore) for power transmission in the Middle East.", 30, None, "fx1018"),
    ]


def eod() -> dict:
    random.seed(7)
    syms = ["RELIANCE", "HDFCBANK", "TCS", "ITC", "LT", "SUNPHARMA", "BAJFINANCE", "MARUTI", "TATASTEEL", "NTPC",
            "APOLLOHOSP", "HAL", "DIXON", "POLYCAB", "PERSISTENT", "DEEPAKNTR", "AFFLE", "KAYNES"]
    out = {}
    end = date.today() - timedelta(days=1)
    days = []
    d = end
    while len(days) < 70:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    for i, s in enumerate(syms):
        price, base_vol = 500 + i * 180.0, 1_000_000 + i * 150_000
        bars = []
        for j, day in enumerate(days):
            price *= 1 + random.gauss(0, 0.012)
            vol = base_vol * (1 + random.gauss(0, 0.15))
            if j == len(days) - 1 and s == "SUNPHARMA":
                price *= 0.93; vol *= 3.4
            if j == len(days) - 1 and s == "DIXON":
                price *= 1.055; vol *= 2.6
            if j == len(days) - 1 and s == "AFFLE":
                vol *= 2.2
            bars.append({"date": day.isoformat(), "close": round(price, 2), "volume": round(max(vol, 0))})
        out[s] = bars
    rnd = random.Random(11)
    for key, level in (("IDX:NIFTY50", 24800.0), ("IDX:SENSEX", 81300.0), ("IDX:BANKNIFTY", 54200.0), ("IDX:NIFTYIT", 36900.0)):
        bars, v = [], level
        for day in days:
            v *= 1 + rnd.gauss(0.0003, 0.007)
            bars.append({"date": day.isoformat(), "close": round(v, 2), "volume": None})
        out[key] = bars
    return out


def screener_html(sym: str, name: str, ar_url: str, transcripts: list[tuple[str, str]]) -> str:
    years = [f"Mar {y}" for y in range(2017, 2027)]
    rev = [1500 * (1.11 ** k) for k in range(10)]
    rev[3] *= 0.45  # covid-year dip
    op = [r * (0.30 + 0.004 * k) for k, r in enumerate(rev)]
    pat = [o * 0.68 for o in op]
    quarters = ["Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
    qrev = [1000, 1050, 1080, 1060, 1130, 1150, 1190, 1170, 1270]
    qop = [r * m for r, m in zip(qrev, [0.33, 0.34, 0.33, 0.34, 0.35, 0.345, 0.34, 0.35, 0.36])]
    qpat = [o * 0.7 for o in qop]

    def tr(label, vals, fmt="{:,.0f}"):
        tds = "".join(f"<td>{'' if v is None else fmt.format(v)}</td>" for v in vals)
        return f"<tr><td class='text'>{label}</td>{tds}</tr>"

    def table(cols, rows):
        th = "".join(f"<th>{c}</th>" for c in cols)
        return f"<table class='data-table'><thead><tr><th></th>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>"

    pl = table(years + ["TTM"], [tr("Sales +", rev + [rev[-1] * 1.05]), tr("Operating Profit", op + [op[-1]]),
                                 tr("OPM %", [o / r * 100 for o, r in zip(op, rev)] + [None], "{:.0f}%"),
                                 tr("Profit before tax", [p / 0.75 for p in pat] + [None]), tr("Net Profit +", pat + [pat[-1]])])
    qt = table(quarters, [tr("Sales +", qrev), tr("Operating Profit", qop), tr("OPM %", [o / r * 100 for o, r in zip(qop, qrev)], "{:.0f}%"), tr("Net Profit +", qpat)])
    bsy = years[-6:]
    bs = table(bsy, [tr("Equity Capital", [160] * 6), tr("Reserves", [1500 + 400 * k for k in range(6)]),
                     tr("Borrowings +", [20, 25, 30, 60, 40, 35]), tr("Total Liabilities", [2500 + 500 * k for k in range(6)]),
                     tr("Total Assets", [2500 + 500 * k for k in range(6)])])
    cf = table(bsy, [tr("Cash from Operating Activity +", [p * 0.95 for p in pat[-6:]]), tr("Cash from Investing Activity +", [-300] * 6),
                     tr("Cash from Financing Activity +", [-200] * 6), tr("Net Cash Flow", [50] * 6)])
    rt = table(bsy, [tr("Debtor Days", [40, 42, 45, 50, 47, 44]), tr("Cash Conversion Cycle", [-10, -8, -5, 0, -3, -6]), tr("ROCE %", [38, 40, 20, 35, 41, 44], "{:.0f}%")])
    cc = "".join(f"<li><div class='ink-600'>{d}</div><a class='concall-link' href='{u}'>Transcript</a><a class='concall-link' href='#'>Notes</a></li>" for d, u in transcripts)
    return f"""<html><body><p>{STAMP}</p><h1>{name}</h1>
<div id="company-info" data-company-id="999" data-warehouse-id="999"></div>
<a href="https://www.bseindia.com/stock-share-price/x/y/542830/">BSE: 542830</a>
<ul id="top-ratios"><li><span class="name">Market Cap</span><span class="number">56,000</span></li><li><span class="name">ROE</span><span class="number">38.5</span></li></ul>
<section id="quarters">{qt}</section><section id="profit-loss">{pl}</section><section id="balance-sheet">{bs}</section>
<section id="cash-flow">{cf}</section><section id="ratios">{rt}</section>
<section id="documents"><div class="documents annual-reports"><ul class="list-links"><li><a href="{ar_url}">Financial Year 2026 from bse</a></li></ul></div>
<div class="documents concalls"><ul class="list-links">{cc}</ul></div></section></body></html>"""


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    SCR.mkdir(parents=True, exist_ok=True)
    results_pdf(); appointment_pdf(); order_pdf(); annual_report_pdf()
    t = [("Nov 2026", "Q2FY27", ["We expect revenue growth of 12 to 14 percent for FY27.", "We are confident EBITDA margin will be around 35% in Q2 FY27."]),
         ("Aug 2026", "Q1FY27", ["For the full year FY27 we guide to double-digit revenue growth.", "Tourism will remain a focus area for us."]),
         ("May 2026", "Q4FY26", ["We expect EBITDA margin of about 36% for FY26 going forward.", "Catering demand remains strong."]),
         ("Feb 2026", "Q3FY26", ["We expect revenue growth of at least 15 percent in FY26 driven by catering.", "Capex of Rs 150 crore is planned for Rail Neer."])]
    links = []
    for i, (lbl, q, extra) in enumerate(t, 1):
        nm = f"FIXTURE_IRCTC_T{i}.pdf"
        transcript_pdf(nm, q, extra)
        links.append((lbl, ARCH + nm))
    (SCR / "irctc.html").write_text(screener_html("IRCTC", "Indian Railway Catering & Tourism Corporation Ltd [fixture]", ARCH + "FIXTURE_IRCTC_AR_FY2026.pdf", links))
    (OUT / "nse_announcements.json").write_text(json.dumps(announcements(), indent=1))
    (OUT / "eod.json").write_text(json.dumps(eod()))
    print("fixtures written to", OUT)


if __name__ == "__main__":
    main()
