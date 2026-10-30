"""Deterministic logic: tickers, maths, classification, prioritisation, dedupe, windows, EOD thresholds."""
from datetime import datetime, timedelta

import pytest

from app import finance, market, portfolio
from app.push.classify import classify
from app.push.prioritise import score
from app.push.service import dedupe
from app.push.sources import IST, RawAnnouncement, parse_bse, parse_nse


# ---------------- tickers
@pytest.mark.parametrize("raw,exp", [("reliance.ns", "RELIANCE"), ("M&M", "M&M"), ("BAJAJ-AUTO", "BAJAJ-AUTO"),
                                     ("NSE:TCS", "TCS"), ("tcs.bo", "TCS"), ("", None), ("DROP TABLE", None), ("A" * 25, None)])
def test_normalise_ticker(raw, exp):
    assert portfolio.normalise_ticker(raw) == exp


def test_portfolio_shape():
    p = portfolio.portfolio()
    assert 15 <= len(p) <= 20
    assert len({c["sector"] for c in p}) >= 10
    assert {c["size"] for c in p} == {"Large", "Mid", "Small"}
    assert 3 <= len(portfolio.research_demos()) <= 5
    assert not {d["symbol"] for d in portfolio.research_demos()} & {c["symbol"] for c in p}


# ---------------- maths
def test_pct_change_and_edge_cases():
    assert finance.pct_change(110, 100) == pytest.approx(10)
    assert finance.pct_change(-50, -100) == pytest.approx(50)   # loss narrowed
    assert finance.pct_change(10, 0) is None                     # division by zero
    assert finance.pct_change(None, 5) is None
    assert finance.pct_change(20, -10) is None                   # sign flip: % meaningless
    assert finance.change_note(20, -10) == "turned positive"
    assert finance.change_note(-5, 10) == "turned negative"


def test_comparison_qoq_yoy():
    c = finance.comparison(120, 100, 80)
    assert c["qoq_abs"] == 20 and c["qoq_pct"] == pytest.approx(20)
    assert c["yoy_abs"] == 40 and c["yoy_pct"] == pytest.approx(50)
    assert finance.comparison(None, 100, 80)["qoq_pct"] is None


def test_margin_and_cagr():
    assert finance.margin(25, 100) == pytest.approx(25)
    assert finance.margin(5, 0) is None
    assert finance.margin(5, -10) is None
    assert finance.cagr(200, 100, 5) == pytest.approx(14.87, abs=0.01)
    assert finance.cagr(100, -5, 3) is None


@pytest.mark.parametrize("tok,val", [("1,234.50", 1234.5), ("(12.3)", -12.3), ("-", 0.0), ("—", 0.0), ("-7", -7.0), ("abc", None)])
def test_parse_number(tok, val):
    assert finance.parse_number(tok) == val


# ---------------- classification
@pytest.mark.parametrize("subject,text,cat", [
    ("Outcome of Board Meeting", "Board approved unaudited financial results for the quarter ended September 30, 2026", "results"),
    ("Board Meeting Intimation", "to consider financial results", "results"),
    ("Change in Management", "Appointment of Chief Financial Officer", "management_change"),
    ("Credit Rating", "CRISIL reaffirmed AA+", "credit_rating"),
    ("Allotment of Securities", "allotted equity shares under ESOS to employees", "unclassified"),
    ("Issue of Securities", "Commercial Paper of Rs 500 crore", "fund_raise"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "transcript of the earnings call", "earnings_call"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "schedule of analyst meet with funds", "investor_meetings"),
    ("Trading Window", "Closure of trading window", "unclassified"),
    ("Disclosure under SEBI Takeover Regulations", "Regulation 29(2)", "insider_trading"),
    ("Litigation / Dispute / Regulatory Action", "Warning Letter from US FDA", "litigation"),
    ("Acquisition", "acquisition of 51% stake", "M&A"),
    ("Dividend", "Interim dividend of Rs 10 per share; record date", "dividend"),
    ("Bonus", "issue of bonus shares 1:1", "bonus_split"),
    ("Something odd", "nothing recognisable here", "unclassified"),
])
def test_classify(subject, text, cat):
    assert classify(subject, text).category == cat


def test_classify_low_confidence_fallback():
    c = classify("", "")
    assert c.category == "unclassified" and c.confidence < 0.5


# ---------------- prioritisation (category != priority)
def test_priority_separates_category_from_materiality():
    real = score("results", 0.9, "Outcome of Board Meeting", "approved unaudited financial results")
    intim = score("results", 0.9, "Board Meeting Intimation", "to consider financial results")
    ad = score("results", 0.9, "Newspaper Publication", "newspaper publication of results")
    assert real.tier == "high" and intim.tier == "low" and ad.tier == "low"
    ceo = score("management_change", 0.85, "Change in Management", "resignation of Chief Executive Officer")
    cs = score("management_change", 0.85, "Change in Management", "appointment of Company Secretary")
    assert ceo.score > cs.score and ceo.tier == "high"
    down = score("credit_rating", 0.9, "Credit Rating", "downgraded to AA-")
    reaff = score("credit_rating", 0.9, "Credit Rating", "reaffirmed")
    assert down.tier == "high" and reaff.tier == "low"
    assert all(isinstance(r, str) for r in ceo.reasons) and len(ceo.reasons) >= 2


def test_priority_context_and_confidence_cap():
    base = score("press_release", 0.8, "Press Release", "order received")
    moved = score("press_release", 0.8, "Press Release", "order received", market_move="Up 6%")
    assert moved.score == base.score + 10
    assert score("M&A", 0.4, "x", "merger").score <= 45
    assert score("results", 0.9, "Outcome", "approved", repeat_index=1).score < score("results", 0.9, "Outcome", "approved").score


# ---------------- source parsing, dedupe, windows
def test_parse_nse_filters_and_keeps_metadata():
    rows = [{"symbol": "TCS", "desc": "Press Release", "attchmntText": "t", "sort_date": "2026-10-29 10:00:00", "seq_id": "1", "attchmntFile": "https://nsearchives.nseindia.com/x.pdf", "sm_name": "TCS Ltd"},
            {"symbol": "NOTMINE", "desc": "Press Release", "sort_date": "2026-10-29 10:00:00", "seq_id": "2"},
            {"symbol": "TCS", "desc": "bad date", "sort_date": "garbage", "seq_id": "3"}]
    out = parse_nse(rows, {"TCS"})
    assert len(out) == 1 and out[0].uid == "NSE:1" and out[0].url.endswith("x.pdf") and out[0].published.startswith("2026-10-29T10:00:00+05:30")


def test_parse_bse_maps_scrip_codes():
    rows = [{"NEWSID": "abc", "SCRIP_CD": 532540, "NEWSSUB": "Press Release", "HEADLINE": "h", "DissemDT": "2026-10-29T10:00:00.12", "ATTACHMENTNAME": "f.pdf", "CATEGORYNAME": "Company Update", "SUBCATNAME": "-"},
            {"NEWSID": "zzz", "SCRIP_CD": 999999, "DissemDT": "2026-10-29T10:00:00"}]
    out = parse_bse(rows)
    assert len(out) == 1 and out[0].symbol == "TCS" and out[0].url == "https://www.bseindia.com/xml-data/corpfiling/AttachLive/f.pdf"
    assert out[0].exchange_category == "Company Update"


def _ann(uid, sym="TCS", subj="Press Release", t="2026-10-29T10:00:00+05:30"):
    return RawAnnouncement(uid=uid, exchange="NSE", symbol=sym, company=sym, subject=subj, text="same text", published=t, url=None)


def test_dedupe_by_uid_and_content():
    items = [_ann("NSE:1"), _ann("NSE:1"), _ann("BSE:9"), _ann("NSE:2", subj="Credit Rating")]
    out = dedupe(items)
    assert [i.uid for i in out] == ["NSE:1", "NSE:2"]


def test_feed_window_filtering():
    from app.push.service import build_feed
    now = datetime.now(IST)
    narrow = build_feed(start=now - timedelta(hours=4), end=now)
    wide = build_feed(hours=48)
    assert 0 < narrow["counts"]["total"] < wide["counts"]["total"]
    for i in narrow["items"]:
        assert now - timedelta(hours=4) <= datetime.fromisoformat(i["published"]) <= now
    with pytest.raises(ValueError):
        build_feed(start=now - timedelta(days=60), end=now)


def test_feed_is_priority_ordered():
    from app.push.service import build_feed
    items = build_feed(hours=48)["items"]
    ranks = [{"high": 0, "medium": 1, "low": 2}[i["tier"]] for i in items]
    assert ranks == sorted(ranks)


# ---------------- EOD thresholds
def _bars(closes, vols):
    d0 = datetime.now().date() - timedelta(days=len(closes))
    return [{"date": (d0 + timedelta(days=i)).isoformat(), "close": c, "volume": v} for i, (c, v) in enumerate(zip(closes, vols))]


def test_price_and_volume_signals():
    b = _bars([100] * 25 + [106], [1000] * 25 + [2500])
    r = market.detect(b, {"price_move_pct": 5, "volume_multiple": 2, "volume_window": 20})
    types = {s["type"] for s in r["signals"]}
    assert types == {"price_move", "volume_spike"}
    assert r["volume_multiple"] == pytest.approx(2.5)


def test_thresholds_are_configurable():
    b = _bars([100] * 25 + [103], [1000] * 25 + [1800])
    assert market.detect(b, {"price_move_pct": 5, "volume_multiple": 2})["signals"] == []
    assert len(market.detect(b, {"price_move_pct": 2.5, "volume_multiple": 1.5})["signals"]) == 2


def test_eod_edge_cases():
    assert market.detect(_bars([100], [10]), {})["status"] == "insufficient_history"
    short = market.detect(_bars([100, 101, 102], [10, 10, 30]), {})
    assert "insufficient" in short["volume_status"]
    zeros = market.detect(_bars([100] * 25 + [101], [0] * 25 + [500]), {})  # zero-volume baseline skipped
    assert not any(s["type"] == "volume_spike" for s in zeros["signals"])
    novol = market.detect(_bars([100] * 25 + [101], [1000] * 25 + [None]), {})
    assert novol["volume_status"].startswith("no volume")
    stale = market.detect([{"date": "2020-01-01", "close": 1, "volume": 1}, {"date": "2020-01-02", "close": 1, "volume": 1}], {})
    assert stale["status"] == "stale"


# ---------------- summaries & people direction
def test_one_liner_respects_abbreviations():
    from app.push.service import one_liner
    s = one_liner("Polycab has informed about appointment of Ms. Anjali Verma as CFO. Second sentence here.", "x")
    assert s.endswith("as CFO.") and "Ms. Anjali" in s
    assert one_liner("HAL received an order of Rs. 2,450 crore.", "x").endswith("crore.")
    assert one_liner("", "Subject only") == "Subject only"


def test_people_direction():
    from app.push.people import direction
    t = "the Board approved the appointment of Ms. Anjali Verma as CFO in place of Mr. Rohan Mehta who has resigned."
    assert direction("Anjali Verma", t) == "incoming" and direction("Rohan Mehta", t) == "outgoing"
    assert direction("Nobody Here", t) == "unclear"
