"""Deterministic financial analysis on standardised statements.

Produces metric records with stable ids ("M:rev_cagr_3y") that LLM claims must cite, plus rule-based
observations so the report is useful even with no LLM configured.
"""
from __future__ import annotations

from .. import finance
from .screener import period_from_label

ALIASES = {
    "sales": ["Sales", "Revenue", "Revenue from Operations"],
    "op_profit": ["Operating Profit", "Financing Profit", "EBITDA"],
    "opm": ["OPM %", "Financing Margin %"],
    "other_income": ["Other Income"],
    "interest": ["Interest"],
    "dep": ["Depreciation"],
    "pbt": ["Profit before tax"],
    "pat": ["Net Profit", "Profit after tax"],
    "eps": ["EPS in Rs"],
    "equity_capital": ["Equity Capital"],
    "reserves": ["Reserves"],
    "borrowings": ["Borrowings", "Borrowing"],
    "deposits": ["Deposits"],
    "total_assets": ["Total Assets"],
    "cwip": ["CWIP"],
    "cfo": ["Cash from Operating Activity"],
    "cfi": ["Cash from Investing Activity"],
    "cff": ["Cash from Financing Activity"],
    "debtor_days": ["Debtor Days"],
    "inventory_days": ["Inventory Days"],
    "payable_days": ["Days Payable"],
    "ccc": ["Cash Conversion Cycle"],
    "wc_days": ["Working Capital Days"],
    "roce": ["ROCE %"],
}


def series(table: dict | None, key: str) -> dict[str, float | None]:
    """label -> value for one row, dropping TTM so we only compare like-for-like fiscal periods."""
    if not table:
        return {}
    for alias in ALIASES[key]:
        row = table["rows"].get(alias)
        if row is not None:
            return {c: v for c, v in zip(table["columns"], row) if c.upper() != "TTM"}
    return {}


def _last(d: dict, n: int = 1) -> list[tuple[str, float | None]]:
    return list(d.items())[-n:]


class Metrics:
    def __init__(self, source_id: str):
        self.items: dict[str, dict] = {}
        self.source_id = source_id

    def add(self, mid: str, label: str, value: float | None, unit: str, period: str | None, note: str | None = None) -> None:
        self.items[mid] = {"id": f"M:{mid}", "label": label, "value": None if value is None else round(value, 2),
                           "unit": unit, "period": period, "source": self.source_id, "note": note}


def analyse(company: dict, source_id: str) -> dict:
    pl, bs, cf, rt, q = (company.get(k) for k in ("profit_loss", "balance_sheet", "cash_flow", "ratios", "quarters"))
    M = Metrics(source_id)
    is_bank = "Financing Profit" in (pl or {}).get("rows", {}) or "Deposits" in (bs or {}).get("rows", {})
    unit = "₹ cr"

    sales, opp, pat, pbt = series(pl, "sales"), series(pl, "op_profit"), series(pl, "pat"), series(pl, "pbt")
    years = [c for c in sales if period_from_label(c)]
    trajectory = []
    for y in years[-10:]:
        p = period_from_label(y)
        s, o, n = sales.get(y), opp.get(y), pat.get(y)
        trajectory.append({"period": p["fy_label"], "label": y, "revenue": s, "op_profit": o, "pat": n,
                           "opm": finance.margin(o, s), "pat_margin": finance.margin(n, s)})
    for i, row in enumerate(trajectory):
        prev = trajectory[i - 1] if i else None
        row["revenue_growth"] = finance.pct_change(row["revenue"], prev["revenue"]) if prev else None
        row["pat_growth"] = finance.pct_change(row["pat"], prev["pat"]) if prev else None

    latest = trajectory[-1] if trajectory else None
    if latest:
        fy = latest["period"]
        M.add("revenue_fy", f"Revenue {fy}", latest["revenue"], unit, fy)
        M.add("op_profit_fy", f"{'Financing' if is_bank else 'Operating'} profit {fy}", latest["op_profit"], unit, fy)
        M.add("opm_fy", f"{'Financing' if is_bank else 'Operating'} margin {fy}", latest["opm"], "%", fy)
        M.add("pat_fy", f"PAT {fy}", latest["pat"], unit, fy)
        M.add("pat_margin_fy", f"PAT margin {fy}", latest["pat_margin"], "%", fy)
        M.add("rev_growth_fy", f"Revenue growth {fy}", latest["revenue_growth"], "%", fy)
        M.add("pat_growth_fy", f"PAT growth {fy}", latest["pat_growth"], "%", fy)
    for n in (3, 5):
        if len(trajectory) > n:
            a, b = trajectory[-1 - n], trajectory[-1]
            per = f"{a['period']}→{b['period']}"
            M.add(f"rev_cagr_{n}y", f"Revenue CAGR {n}y", finance.cagr(b["revenue"], a["revenue"], n), "%", per)
            M.add(f"pat_cagr_{n}y", f"PAT CAGR {n}y", finance.cagr(b["pat"], a["pat"], n), "%", per)
            M.add(f"opm_change_{n}y", f"Margin change {n}y", None if a["opm"] is None or b["opm"] is None else b["opm"] - a["opm"], "pp", per)

    # Quarterly (latest quarter vs year-ago quarter)
    quarters = []
    qs, qo, qp = series(q, "sales"), series(q, "op_profit"), series(q, "pat")
    for lbl in list(qs)[-13:]:
        p = period_from_label(lbl)
        if not p:
            continue
        quarters.append({"period": p["q_label"] or lbl, "label": lbl, "revenue": qs.get(lbl), "op_profit": qo.get(lbl),
                         "pat": qp.get(lbl), "opm": finance.margin(qo.get(lbl), qs.get(lbl))})
    for i, row in enumerate(quarters):
        ya = quarters[i - 4] if i >= 4 else None
        pq = quarters[i - 1] if i >= 1 else None
        row["revenue_yoy"] = finance.pct_change(row["revenue"], ya["revenue"]) if ya else None
        row["pat_yoy"] = finance.pct_change(row["pat"], ya["pat"]) if ya else None
        row["revenue_qoq"] = finance.pct_change(row["revenue"], pq["revenue"]) if pq else None
    if quarters:
        lq = quarters[-1]
        M.add("rev_q", f"Revenue {lq['period']}", lq["revenue"], unit, lq["period"])
        M.add("rev_yoy_q", f"Revenue YoY {lq['period']}", lq["revenue_yoy"], "%", lq["period"])
        M.add("pat_q", f"PAT {lq['period']}", lq["pat"], unit, lq["period"])
        M.add("pat_yoy_q", f"PAT YoY {lq['period']}", lq["pat_yoy"], "%", lq["period"])
        M.add("opm_q", f"Margin {lq['period']}", lq["opm"], "%", lq["period"])

    # Balance sheet
    bal = []
    eq_c, res, bor, ta = series(bs, "equity_capital"), series(bs, "reserves"), series(bs, "borrowings"), series(bs, "total_assets")
    for lbl in list(ta)[-6:]:
        p = period_from_label(lbl)
        equity = None if eq_c.get(lbl) is None or res.get(lbl) is None else eq_c[lbl] + res[lbl]
        bal.append({"period": p["fy_label"] if p else lbl, "label": lbl, "equity": equity, "borrowings": bor.get(lbl),
                    "total_assets": ta.get(lbl), "de": finance.safe_div(bor.get(lbl), equity)})
    if bal:
        lb = bal[-1]
        M.add("equity", f"Shareholders' equity {lb['period']}", lb["equity"], unit, lb["period"])
        M.add("borrowings", f"Borrowings {lb['period']}", lb["borrowings"], unit, lb["period"])
        M.add("de", f"Debt / equity {lb['period']}", lb["de"], "x", lb["period"],
              "Not meaningful for lenders (borrowings fund the loan book)" if is_bank else None)
        if len(bal) >= 4:
            M.add("de_3y_ago", f"Debt / equity {bal[-4]['period']}", bal[-4]["de"], "x", bal[-4]["period"])

    wc = []
    for key, label in (("debtor_days", "Debtor days"), ("inventory_days", "Inventory days"), ("payable_days", "Payable days"), ("ccc", "Cash conversion cycle"), ("roce", "ROCE")):
        s = series(rt, key)
        if s:
            wc.append({"metric": label, "values": [{"period": (period_from_label(k) or {}).get("fy_label", k), "value": v} for k, v in list(s.items())[-5:]]})
            last_lbl, last_v = _last(s)[0]
            mid = {"roce": "roce", "ccc": "ccc"}.get(key, key)
            fyl = (period_from_label(last_lbl) or {}).get("fy_label", last_lbl)
            M.add(mid, f"{label} {fyl}", last_v, "%" if key == "roce" else "days", fyl)
    if company.get("top_ratios", {}).get("ROE") is not None:
        M.add("roe", "ROE (latest, Screener)", company["top_ratios"]["ROE"], "%", "latest")
    if company.get("top_ratios", {}).get("Market Cap") is not None:
        M.add("mcap", "Market cap", company["top_ratios"]["Market Cap"], unit, "latest")

    # Cash quality
    cfo = series(cf, "cfo")
    capex_vals = (company.get("capex") or {}).get("values", {})
    cash = []
    for lbl in list(cfo)[-6:]:
        p = period_from_label(lbl)
        capex = capex_vals.get(lbl)
        capex = abs(capex) if capex is not None else None
        cash.append({"period": p["fy_label"] if p else lbl, "label": lbl, "cfo": cfo.get(lbl), "pat": pat.get(lbl),
                     "conversion": finance.safe_div(cfo.get(lbl), pat.get(lbl)) if (pat.get(lbl) or 0) > 0 else None,
                     "capex": capex, "fcf": None if capex is None or cfo.get(lbl) is None else cfo[lbl] - capex})
    if cash:
        tot_cfo = sum(r["cfo"] for r in cash if r["cfo"] is not None)
        tot_pat = sum(r["pat"] for r in cash if r["pat"] is not None)
        n = len(cash)
        M.add("cfo_pat_cum", f"Cumulative CFO / PAT ({cash[0]['period']}–{cash[-1]['period']})",
              finance.safe_div(tot_cfo, tot_pat) if tot_pat > 0 else None, "x", f"{n} years")
        M.add("cfo_fy", f"Operating cash flow {cash[-1]['period']}", cash[-1]["cfo"], unit, cash[-1]["period"])
        if cash[-1]["fcf"] is not None:
            M.add("fcf_fy", f"Free cash flow {cash[-1]['period']}", cash[-1]["fcf"], unit, cash[-1]["period"])
            fcfs = [r["fcf"] for r in cash if r["fcf"] is not None]
            M.add("fcf_cum", f"Cumulative FCF ({len(fcfs)}y)", sum(fcfs), unit, f"{len(fcfs)} years")

    obs = observations(M.items, trajectory, bal, cash, is_bank)
    return {"is_bank": is_bank, "metrics": M.items, "trajectory": trajectory, "quarters": quarters[-8:],
            "balance_sheet": bal, "working_capital": wc, "cash": cash, "observations": obs,
            "capex_available": bool(capex_vals)}


def _v(m: dict, k: str) -> float | None:
    return (m.get(k) or {}).get("value")


def observations(m: dict, traj: list, bal: list, cash: list, is_bank: bool) -> dict:
    """Rule-based statements, each tied to metric ids. These are 'facts' (computed), not interpretations."""
    out: dict[str, list] = {"trajectory": [], "balance_sheet": [], "cash_quality": [], "bull": [], "bear": []}

    def add(section, text, ids, kind="fact"):
        out[section].append({"text": text, "evidence": [f"M:{i}" for i in ids], "kind": kind, "verified": True, "origin": "rules"})

    c5, c3 = _v(m, "rev_cagr_5y"), _v(m, "rev_cagr_3y")
    if c5 is not None:
        add("trajectory", f"Revenue compounded at {c5:.1f}% a year over five years ({m['rev_cagr_5y']['period']}).", ["rev_cagr_5y"])
    if c3 is not None and c5 is not None and abs(c3 - c5) >= 3:
        add("trajectory", f"Growth has {'accelerated' if c3 > c5 else 'slowed'}: 3-year CAGR {c3:.1f}% vs 5-year {c5:.1f}%.", ["rev_cagr_3y", "rev_cagr_5y"])
    oc = _v(m, "opm_change_5y") if _v(m, "opm_change_5y") is not None else _v(m, "opm_change_3y")
    oc_id = "opm_change_5y" if _v(m, "opm_change_5y") is not None else "opm_change_3y"
    if oc is not None:
        add("trajectory", f"Operating margin {'expanded' if oc > 0 else 'compressed'} by {abs(oc):.1f} pp over {m[oc_id]['period']}.", [oc_id])
    p5, r5 = _v(m, "pat_cagr_5y"), c5
    if p5 is not None and r5 is not None and abs(p5 - r5) >= 4:
        add("trajectory", f"Profit grew {'faster' if p5 > r5 else 'slower'} than revenue (PAT CAGR {p5:.1f}% vs revenue {r5:.1f}%).", ["pat_cagr_5y", "rev_cagr_5y"])
    if not is_bank:
        de, de3 = _v(m, "de"), _v(m, "de_3y_ago")
        if de is not None:
            add("balance_sheet", f"Debt/equity is {de:.2f}x ({m['de']['period']})" + (f", vs {de3:.2f}x three years earlier." if de3 is not None else "."), ["de"] + (["de_3y_ago"] if de3 is not None else []))
            if de < 0.1:
                add("bull", f"Balance sheet is essentially un-levered (D/E {de:.2f}x).", ["de"], "interpretation")
            elif de > 1.0:
                add("bear", f"Leverage is meaningful at {de:.2f}x debt/equity.", ["de"], "interpretation")
            if de3 is not None and de - de3 > 0.3:
                add("bear", f"Leverage rose from {de3:.2f}x to {de:.2f}x in three years - check what the borrowing funded.", ["de", "de_3y_ago"], "interpretation")
    else:
        add("balance_sheet", "Lender: borrowings and deposits fund the loan book, so debt/equity is not a meaningful risk gauge here.", [])
    ccc = (m.get("ccc") or {}).get("value")
    if ccc is not None:
        add("balance_sheet", f"Cash conversion cycle is {ccc:.0f} days ({m['ccc']['period']}).", ["ccc"])
    conv = _v(m, "cfo_pat_cum")
    if conv is not None:
        add("cash_quality", f"Over {m['cfo_pat_cum']['period']}, operating cash flow was {conv:.2f}x reported profit.", ["cfo_pat_cum"])
        if conv >= 0.9:
            add("bull", f"Profits convert to cash (cumulative CFO/PAT {conv:.2f}x).", ["cfo_pat_cum"], "interpretation")
        elif conv < 0.7 and not is_bank:
            add("bear", f"Persistent gap between profit and cash (cumulative CFO/PAT {conv:.2f}x).", ["cfo_pat_cum"], "interpretation")
    fcf = _v(m, "fcf_cum")
    if fcf is not None:
        add("cash_quality", f"Cumulative free cash flow (CFO − capex) was ₹{fcf:,.0f} cr over {m['fcf_cum']['period']}.", ["fcf_cum"])
        if fcf < 0 and not is_bank:
            add("bear", "Capex has exceeded operating cash flow in aggregate - growth is being funded externally.", ["fcf_cum"], "interpretation")
    elif cash:
        out["cash_quality"].append({"text": "Free cash flow not computed: capital expenditure could not be retrieved.", "evidence": [], "kind": "limitation", "verified": True, "origin": "rules"})
    roce = _v(m, "roce")
    if roce is not None and not is_bank:
        if roce >= 20:
            add("bull", f"High return on capital (ROCE {roce:.0f}%).", ["roce"], "interpretation")
        elif roce < 10:
            add("bear", f"Low return on capital (ROCE {roce:.0f}%).", ["roce"], "interpretation")
    if c3 is not None and c3 >= 15:
        add("bull", f"Strong recent growth (3-year revenue CAGR {c3:.1f}%).", ["rev_cagr_3y"], "interpretation")
    if c3 is not None and c3 < 5:
        add("bear", f"Growth has stalled (3-year revenue CAGR {c3:.1f}%).", ["rev_cagr_3y"], "interpretation")
    if oc is not None and oc <= -3:
        add("bear", f"Margins have compressed {abs(oc):.1f} pp.", [oc_id], "interpretation")
    return out
