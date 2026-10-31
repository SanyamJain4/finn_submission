"""Results parsing, people extraction, guidance verdicts, grounding, research pipeline (with a mocked LLM)."""
from pathlib import Path

import pymupdf
import pytest

from app import llm
from app.documents import BM25, chunk_pages, pdf_bytes_to_pages
from app.push import people, results
from app.research import guidance as gd
from app.research import service as rs

FIX = Path(__file__).resolve().parents[1] / "app" / "fixtures"


def _pages(name):
    return pdf_bytes_to_pages((FIX / "docs" / name).read_bytes())


def test_results_extraction_consolidated_with_evidence():
    r = results.extract_results(_pages("FIXTURE_DIXON_RESULTS.pdf"))
    assert r.status == "ok" and r.basis == "consolidated"
    assert r.periods["confirmed"] and r.periods["current"] == "2026-09-30" and r.periods["year_ago"] == "2025-09-30"
    m = r.metrics
    assert m["revenue"]["current"] == 16412.30 and m["revenue"]["prev_quarter"] == 15208.75 and m["revenue"]["year_ago"] == 14105.60
    assert m["pbt"]["current"] == 2526.50 and m["pbt"]["prev_quarter"] == 1917.10   # not the pre-exceptional line
    assert m["pat"]["current"] == 1886.40                                            # not 'attributable to owners'
    assert m["ebitda"]["current"] == pytest.approx(2526.50 + 310.55 + 645.20 - 212.40)
    assert m["revenue"]["yoy_pct"] == pytest.approx((16412.30 / 14105.60 - 1) * 100)
    assert {e["metric"] for e in r.evidence} >= {"revenue", "pbt", "pat"} and all(e["page"] == 3 for e in r.evidence)


def _pdf(lines):
    d = pymupdf.open()
    p = d.new_page(width=842, height=595)
    for i, (x, t) in enumerate(lines):
        p.insert_text((x, 40 + 14 * i), t, fontsize=8)
    return pdf_bytes_to_pages(d.tobytes())


def test_results_units_lakhs_and_losses():
    pages = _pdf([(40, "Standalone results (Rs. in Lakhs)"), (40, "Revenue from operations  50,000.00  40,000.00  45,000.00"),
                  (40, "Other income  100  100  100"), (40, "Finance costs  50  50  50"), (40, "Depreciation  200  200  200"),
                  (40, "Profit / (loss) before tax (5-6)  (1,000.00)  (2,000.00)  500.00"),
                  (40, "Net Profit / (loss) for the period  (800.00)  (1,500.00)  400.00")])
    r = results.extract_results(pages)
    assert r.basis == "standalone" and r.unit_source.lower().endswith("lakhs")
    assert r.metrics["revenue"]["current"] == pytest.approx(500.0)          # lakh -> crore
    assert r.metrics["pbt"]["current"] == pytest.approx(-10.0)              # (5-6) formula not read as numbers
    assert r.metrics["pat"]["qoq_note"] == "loss narrowed" and r.metrics["pat"]["yoy_pct"] is None
    assert any("Column order assumed" in n for n in r.notes)


def test_results_not_found_is_explicit():
    r = results.extract_results(_pdf([(40, "Intimation of board meeting to consider results")]))
    assert r.status == "not_found" and r.metrics == {}


def test_people_profile_from_filing():
    p = people.extract_people(_pages("FIXTURE_POLYCAB_CFO.pdf"), "Change in Management Polycab")
    assert "Anjali Verma" in p["names"] and p["effective"] == "1 November 2026"
    assert "Chartered Accountant" in p["profile_passage"] and p["profile_source"].startswith("Exchange filing")


def test_people_grounding_drops_invented_roles(monkeypatch):

    def fake(schema, prompt, **kw):
        return people.ProfileExtraction(people=[people.PersonProfile(
            name="Anjali Verma", direction="incoming", role="CFO",
            prior_roles=["Chief Financial Officer of Fictional Electricals Limited", "CEO of Imaginary Bank"])])
    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(type(people.settings), "llm_enabled", property(lambda s: True))
    p = people.extract_people(_pages("FIXTURE_POLYCAB_CFO.pdf"), "Polycab")
    assert p["structured"][0]["prior_roles"] == ["Chief Financial Officer of Fictional Electricals Limited"]


def test_bm25_returns_page_provenance():
    ch = chunk_pages("T1", ["We expect revenue growth of 12 percent " * 5, "catering margins declined " * 10])
    hits = BM25(ch).search("revenue growth guidance", 2)
    assert hits and hits[0][1].page == 1 and hits[0][1].doc_id == "T1"
    assert BM25([]).search("x") == []


# ---------------- guidance verdicts
ANALYSIS = {
    "trajectory": [{"label": "Mar 2026", "period": "FY26", "revenue_growth": 11.0, "opm": 34.6, "pat_growth": 12.0},
                   {"label": "Mar 2025", "period": "FY25", "revenue_growth": 9.0, "opm": 34.0, "pat_growth": 8.0}],
    "quarters": [{"label": "Sep 2026", "period": "Q2 FY27", "revenue_yoy": 12.4, "opm": 35.4, "pat_yoy": 14.0}],
}


def S(**kw):
    base = dict(quote="We expect revenue growth of 12 to 14 percent for FY26.", evidence_id="E1", metric="revenue_growth",
                scope="company", measurable=True, comparator="range", target_low=12, target_high=14, period="FY26")
    base.update(kw)
    return gd.GuidanceStatement(**base)


def test_verdict_missed_met_exceeded():
    assert gd.evaluate(S(), ANALYSIS, False)["verdict"] == "missed"           # FY26 actual 11.0% vs 12-14%
    assert gd.evaluate(S(target_low=13, target_high=14, quote="growth of 13 to 14 percent"), ANALYSIS, False)["verdict"] == "missed"
    assert gd.evaluate(S(target_low=10, target_high=12, quote="growth of 10 to 12 percent"), ANALYSIS, False)["verdict"] == "met"
    assert gd.evaluate(S(target_low=6, target_high=8, quote="growth of 6 to 8 percent"), ANALYSIS, False)["verdict"] == "exceeded"
    r = gd.evaluate(S(metric="ebitda_margin", comparator="approx", target_low=35, target_high=35, period="Q2 FY27",
                      quote="EBITDA margin will be around 35% in Q2 FY27"), ANALYSIS, False)
    assert r["verdict"] == "met" and r["actual"] == 35.4 and r["actual_period"] == "Q2 FY27"


def test_verdict_refuses_to_manufacture_targets():
    assert gd.evaluate(S(measurable=False, comparator="none", target_low=None, target_high=None), ANALYSIS, False)["verdict"] == "qualitative"
    # Model claims a 20% target that is not in the quote -> treated as unverified commentary
    assert gd.evaluate(S(target_low=20, target_high=20, comparator="approx"), ANALYSIS, False)["verdict"] == "qualitative"
    assert gd.evaluate(S(quote="double-digit revenue growth in FY26", comparator="at_least", target_low=10, target_high=None), ANALYSIS, False)["verdict"] == "met"


def test_verdict_cannot_evaluate_or_pending():
    assert gd.evaluate(S(scope="segment"), ANALYSIS, False)["verdict"] == "cannot_evaluate"
    assert gd.evaluate(S(quote="growth of 12 to 14 percent in constant currency"), ANALYSIS, False)["verdict"] == "cannot_evaluate"
    assert gd.evaluate(S(metric="capex", quote="capex of 12 to 14"), ANALYSIS, False)["verdict"] == "cannot_evaluate"
    assert gd.evaluate(S(period=None), ANALYSIS, False)["verdict"] == "cannot_evaluate"
    assert gd.evaluate(S(period="FY28"), ANALYSIS, False)["verdict"] == "pending"
    assert gd.evaluate(S(metric="ebitda_margin"), ANALYSIS, True)["verdict"] == "cannot_evaluate"   # bank


def test_candidate_sentences_without_llm():
    c = gd.candidate_sentences(["Moderator: welcome. We expect revenue growth of 12 to 14 percent for FY27. Thanks for joining the call today."])
    assert c and "12 to 14" in c[0]["text"]


# ---------------- grounding
def test_grounding_flags_unsupported_numbers_and_missing_citations():
    ev = {"E1": {"text": "Catering contributed 45% of revenue in FY2026", "source": "AR1", "page": 3}}
    mets = {"rev_cagr_5y": {"value": 11.04}}
    ok, _ = rs._claim_supported({"text": "Catering is 45% of revenue.", "evidence": ["E1"]}, ev, mets)
    bad, issues = rs._claim_supported({"text": "Catering is 55% of revenue.", "evidence": ["E1"]}, ev, mets)
    none, issues2 = rs._claim_supported({"text": "Great company.", "evidence": ["E99"]}, ev, mets)
    metric_ok, _ = rs._claim_supported({"text": "Revenue grew 11.0% a year.", "evidence": ["M:rev_cagr_5y"]}, ev, mets)
    assert ok and not bad and "55" in issues[0] and not none and issues2 == ["cites no valid evidence"] and metric_ok


def test_quote_matching_tolerates_whitespace_not_invention():
    t = "Management: We expect revenue growth of 12 to 14 percent for FY27. Next question."
    assert rs._quote_in("we expect revenue growth of 12 to 14 percent  for FY27", t)
    assert not rs._quote_in("we expect revenue growth of 25 percent for FY27", t)


# ---------------- research pipeline
def test_research_without_llm_is_honest():
    rep = rs.build_report("IRCTC")
    assert rep["sources"][0]["id"] == "S1" and all(s["status"] == "ok" for s in rep["sources"])
    assert any("No LLM configured" in l for l in rep["limitations"])
    assert rep["sections"]["guidance"]["status"] == "candidates_only"
    assert rep["metrics"]["rev_cagr_5y"]["value"] is not None
    for c in rep["sections"]["trajectory"]["claims"]:
        assert all(e.startswith("M:") for e in c["evidence"])


def test_research_with_mocked_llm(monkeypatch):
    """Exercises the full LLM path with deterministic fake outputs, incl. an invented quote and an unsupported claim."""
    monkeypatch.setattr(type(rs.settings), "llm_enabled", property(lambda s: True))
    calls = []

    def fake(schema, prompt, tier="fast", purpose="", **kw):
        calls.append(purpose)
        eids = __import__("re").findall(r'<document id="(E\d+)">\n(.*?)\n</document>', prompt, __import__("re").S)
        if schema is rs.BusinessSnapshot:
            eid = next(e for e, t in eids if "segments" in t)
            return rs.BusinessSnapshot(what_it_does=rs.Claim(text="Runs ticketing, catering, Rail Neer and tourism.", evidence=[eid], kind="fact"),
                                       segments=[rs.Segment(name="Catering", share_of_revenue_pct=45, evidence=[eid])])
        if schema is gd.GuidanceExtraction:
            sts = []
            for eid, text in eids:
                if "12 to 14 percent" in text:
                    sts.append(gd.GuidanceStatement(quote="We expect revenue growth of 12 to 14 percent for FY27.", evidence_id=eid,
                                                    metric="revenue_growth", measurable=True, comparator="range", target_low=12, target_high=14, period="FY27"))
                if "at least 15 percent" in text:
                    sts.append(gd.GuidanceStatement(quote="We expect revenue growth of at least 15 percent in FY26 driven by catering.", evidence_id=eid,
                                                    metric="revenue_growth", measurable=True, comparator="at_least", target_low=15, period="FY26"))
                    sts.append(gd.GuidanceStatement(quote="We promise 40% margins forever.", evidence_id=eid,   # invented quote
                                                    metric="ebitda_margin", measurable=True, comparator="approx", target_low=40, target_high=40, period="FY26"))
            return gd.GuidanceExtraction(statements=sts)
        if schema is rs.Synthesis:
            return rs.Synthesis(headline="Cash-generative, un-levered compounder.",
                                bull=[rs.Claim(text="Revenue compounded 11.0% over five years.", evidence=["M:rev_cagr_5y"], kind="fact")],
                                bear=[rs.Claim(text="Margins will hit 50% next year.", evidence=["M:opm_fy"], kind="interpretation")])
        raise AssertionError(schema)

    monkeypatch.setattr(llm, "complete_json", fake)
    rep = rs.build_report("IRCTC")
    rows = rep["sections"]["guidance"]["rows"]
    quotes = [r["quote"] for r in rows]
    assert "We promise 40% margins forever." not in quotes                      # invented quote rejected
    v = {r["period"]: r["verdict"] for r in rows}
    assert v["FY27"] == "pending" and v["FY26"] == "missed"                      # FY26 actual growth 11% < 15%
    bull, bear = rep["sections"]["bull_bear"]["bull"], rep["sections"]["bull_bear"]["bear"]
    assert bull[0]["verified"] and not bear[0]["verified"]                       # '50%' not in cited metric
    assert rep["verification"]["unverified"] >= 1
    assert calls.count("synthesis") == 1 and len(calls) <= rep["llm"]["calls_budget"]


# ---------------- regressions from real Oct-2026 filings (patterns replayed, not the documents themselves)
def _lines(*ls):
    return ["\n".join(ls)]


def test_real_pattern_split_thousands_and_roman_formula():
    # Sun Pharma: "31 ,593.7" spacing artefact and "(Ill-IV)" OCR'd roman formula; values in INR million.
    r = results.extract_results(_lines(
        "Statement of consolidated results (₹ in Million)",
        "Total revenue from operations (I)  161,987.1  152,998.8  144,783.1  314,985.9",
        "II  Other income  5,173.2  7,236.2  4,699.2  12,409.4",
        "Finance costs  746.7  996.7  998.6  1,743.4",
        "Depreciation and amortisation expense  7,583.4  7,387.2  7,295.0  14,970.6",
        "V  Profit I (loss) before exceptional items and tax (Ill-IV)  44,282.0  43,029.0  41 ,676.1  87,311.0",
        "VI  Exceptional items (Refer Note 4 and 5)  12,688.3  2,040.9  -  14,729.2",
        "VII  Profit I (loss) before tax (V-VI)  31 ,593.7  40,988.1  41 ,676.1  72,581.8",
        "XI  Net Profit I (loss) after taxes  19,950.7  29,012.3  31 ,249.5  48,963.0"))
    assert r.status == "ok"
    assert r.metrics["pbt"]["current"] == pytest.approx(3159.37)          # 31,593.7 million -> crore
    assert r.metrics["pbt"]["year_ago"] == pytest.approx(4167.61)
    assert r.metrics["revenue"]["current"] == pytest.approx(16198.71)


def test_real_pattern_curly_formula_and_canonical_finance_row():
    # L&T: "{1-2)" mismatched bracket; an operating "Finance cost of financial services" line precedes the real one.
    r = results.extract_results(_lines(
        "Consolidated results  ₹ Crore",
        "a) Revenue from operations  78749.94  67941.74  67983.53  146691.68",
        "b) Other income (net)  2306.26  2376.73  1384.28  4682.99",
        "b) Finance cost of financial services business and finance lease activity  1968.86  2032.66  1706.83  4001.52",
        "f) Depreciation. amortisation. impairment and obsolescence  1036.91  1032.28  1091.77  2069.19",
        "Finance costs  472.95  487.94  1092.70  960.89",
        "3 Profit before exceptional items and tax {1-2)  7641.06  6922.26  6336.11  14563.32",
        "5 Profit before tax (3+4)  7641.06  6922.26  6336.11  14563.32",
        "7 Net profit after tax (5-6)  5915.15  4982.85  4687.09  10898.00"))
    assert r.status == "ok"
    assert r.metrics["ebitda"]["current"] == pytest.approx(7641.06 + 472.95 + 1036.91 - 2306.26)


def test_ocr_garbage_is_withheld_not_shown():
    # Scanned PDF with dropped decimal points: revenue columns 7835.93 vs 747164 -> must not be displayed.
    r = results.extract_results(_lines(
        "Statement of consolidated results (Amount in INR million)",
        "Revenue from operations  7835.93  747164  646718  15.307.57",
        "Other income  20047  25041  22275  450.88",
        "Finance costs  823  672  1167  2995",
        "Depreciation and amortisation expenses  412,14  34206  31885  571.52",
        "Profit before tax  159455  157787  13534  264529",
        "Profit for the period  129789  128439  110513  258238"))
    assert r.status == "unreliable" and r.metrics == {}
    assert any("withheld" in n for n in r.notes) and r.evidence                   # rows still shown as read


def test_two_digit_year_header_confirms_columns():
    r = results.extract_results(_lines(
        "STATEMENT OF CONSOLIDATED FINANCIAL RESULTS (Rupees in Crores)",
        "30-Sep-26  30-Jun-26  30-Sep-25  30-Sep-26  30-Sep-25  31-Mar-26",
        "1  Revenue from operations  21,793.64  15,547.66  14,855.04  37,341.30",
        "2  Other income  68.73  528.29  495.74  597.02",
        "d) Finance costs  25.95  24.12  38.35  50.07",
        "e) Depreciation and amortisation expense  110.06  106.95  96.28  217.01",
        "9  Profit before tax (7+8)  532.35  868.98  923.59  1,401.33",
        "11  Net Profit for the period/year (9-10)  410.87  717.83  745.70  1,128.70"))
    assert r.status == "ok" and r.periods["confirmed"] and r.periods["current"] == "2026-09-30"
    assert r.metrics["pbt"]["qoq_pct"] == pytest.approx((532.35 / 868.98 - 1) * 100)


def test_scanned_pdf_reported_as_scanned():
    r = results.extract_results(["Covering letter: un-audited results attached"] + [""] * 9)
    assert r.status == "not_found" and "scanned" in r.notes[0]


def test_fake_bold_duplicate_glyphs_are_merged():
    d = pymupdf.open()
    p = d.new_page(width=842, height=595)
    for dx in (0, 0.4):  # same text drawn twice, slightly offset
        p.insert_text((40 + dx, 60), "Revenue from operations", fontsize=9)
        p.insert_text((400 + dx, 60), "1,593.15", fontsize=9)
    p.insert_text((480, 60), "1,593.15", fontsize=9)  # a genuinely repeated value in another column survives
    text = pdf_bytes_to_pages(d.tobytes())[0]
    assert text.count("Revenue") == 1 and text.count("1,593.15") == 2


def test_gemini_model_discovery_prefers_newest_stable():
    from app.llm import pick_gemini
    avail = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash-preview-09-2026",
             "gemini-3.1-flash-live", "gemini-3.1-flash-tts", "gemini-3.1-pro", "text-embedding-005", "gemini-3.6-flash-image"]
    assert pick_gemini(avail) == ("gemini-3.5-flash-lite", "gemini-3.6-flash")
    assert pick_gemini(["gemini-9.0-flash-preview-01-2030"]) == ("gemini-9.0-flash-preview-01-2030",) * 2
    assert pick_gemini([]) == (None, None)
