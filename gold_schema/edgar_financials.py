"""Annual financial statements from SEC EDGAR XBRL company facts (US government public data) into financials.income_statement /
balance_sheet / cash_flow (period_type 'FY'). Source: data.sec.gov companyfacts (fetched by edgar_fetch.py with SEC_USER_AGENT).

Rules: annual forms only (10-K, 20-F, 40-F and amendments); duration facts of 340-380 days; for each fiscal year end the value comes
from the most recent filing that reports it (restated comparatives win); amounts in the filing's own currency; net_income is attributable
to the parent (us-gaap NetIncomeLoss / ifrs ProfitLossAttributableToOwnersOfParent); total_debt only when the filer tags total debt
or borrowings; every row's line_items records the XBRL tag and accession number used for each field.
Never touches companies that already have hand-extracted statements unless --compare (read-only comparison).

Usage: python edgar_financials.py --compare <company_id> ...      (print EDGAR vs stored, no writes)
       python edgar_financials.py --load <company_id> ... [--dry]   (company must have no active statements)
       python edgar_financials.py --undo                             (deletes all rows created by this tag)
"""
import datetime as dt, json, os, sys, psycopg2
from psycopg2.extras import Json

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "..", "edgar_cache", "companyfacts")
TAG = "edgar_xbrl_20261127"
FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT"}
DUR = {
    "revenue": [("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"), ("us-gaap", "SalesRevenueNet"),
                ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"), ("ifrs-full", "Revenue"), ("ifrs-full", "RevenueFromContractsWithCustomers")],
    "cost_of_revenue": [("us-gaap", "CostOfRevenue"), ("us-gaap", "CostOfGoodsAndServicesSold"), ("us-gaap", "CostOfGoodsSold"), ("ifrs-full", "CostOfSales")],
    "gross_profit": [("us-gaap", "GrossProfit"), ("ifrs-full", "GrossProfit")],
    "operating_income": [("us-gaap", "OperatingIncomeLoss"), ("ifrs-full", "ProfitLossFromOperatingActivities")],
    "net_income": [("us-gaap", "NetIncomeLoss"), ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic"), ("ifrs-full", "ProfitLossAttributableToOwnersOfParent")],
    "profit_total": [("us-gaap", "ProfitLoss"), ("ifrs-full", "ProfitLoss")],
    "eps_basic": [("us-gaap", "EarningsPerShareBasic"), ("ifrs-full", "BasicEarningsLossPerShare")],
    "eps_diluted": [("us-gaap", "EarningsPerShareDiluted"), ("ifrs-full", "DilutedEarningsLossPerShare")],
    "operating_cash_flow": [("us-gaap", "NetCashProvidedByUsedInOperatingActivities"), ("ifrs-full", "CashFlowsFromUsedInOperatingActivities")],
    "investing_cash_flow": [("us-gaap", "NetCashProvidedByUsedInInvestingActivities"), ("ifrs-full", "CashFlowsFromUsedInInvestingActivities")],
    "financing_cash_flow": [("us-gaap", "NetCashProvidedByUsedInFinancingActivities"), ("ifrs-full", "CashFlowsFromUsedInFinancingActivities")],
    "capital_expenditures": [("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"), ("us-gaap", "PaymentsToAcquireProductiveAssets"),
                             ("ifrs-full", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")],
}
INST = {
    "total_assets": [("us-gaap", "Assets"), ("ifrs-full", "Assets")],
    "total_current_assets": [("us-gaap", "AssetsCurrent"), ("ifrs-full", "CurrentAssets")],
    "cash_and_equivalents": [("us-gaap", "CashAndCashEquivalentsAtCarryingValue"), ("ifrs-full", "CashAndCashEquivalents")],
    "total_liabilities": [("us-gaap", "Liabilities"), ("ifrs-full", "Liabilities")],
    "total_current_liabilities": [("us-gaap", "LiabilitiesCurrent"), ("ifrs-full", "CurrentLiabilities")],
    "total_equity": [("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"), ("us-gaap", "StockholdersEquity"), ("ifrs-full", "Equity")],
}
# total_debt is NOT taken from XBRL: filers tag debt inconsistently (leases, current portions), and the pilot against hand-extracted
# statements (Albemarle, MP, Energy Fuels, Cameco, SQM, Rio Tinto, Sibanye) differed by 1-95%; left NULL rather than mismatch the convention.
D = lambda s: dt.date.fromisoformat(s)


def facts_for(cik):
    return json.load(open(os.path.join(CACHE, f"CIK{int(cik):010d}.json"), encoding="utf-8"))


def pick(facts, cands, instant):
    """{end_date: (value, unit, tag, accn)} for annual periods, most recent filing wins; first candidate tag with data per period."""
    out = {}
    for tx, tag in cands:
        node = facts["facts"].get(tx, {}).get(tag)
        if not node: continue
        for unit, arr in node["units"].items():
            for x in arr:
                if x.get("form") not in FORMS: continue
                if instant:
                    if "start" in x: continue
                else:
                    if "start" not in x or not (340 <= (D(x["end"]) - D(x["start"])).days <= 380): continue
                e = x["end"]
                cur = out.get(e)
                if cur and cur[4] != tag: continue          # an earlier-preferred tag already covers this period
                if cur is None or x["filed"] > cur[3]:
                    out[e] = (x["val"], unit, tag, x["filed"], tag, x["accn"])
    return {e: (v[0], v[1], v[2], v[5]) for e, v in out.items()}


def build(cik, years=10):
    f = facts_for(cik)
    dur = {k: pick(f, v, False) for k, v in DUR.items()}
    ends = sorted(set(dur["revenue"]) | set(dur["net_income"]) | set(dur["profit_total"]) | set(dur["operating_cash_flow"]))
    ends = [e for e in ends if D(e) >= D(ends[-1]) - dt.timedelta(days=366 * years)] if ends else []
    inst = {k: pick(f, v, True) for k, v in INST.items()}
    rows = []
    for e in ends:
        r = {"period_end_date": e, "src": {}}
        cur = set()
        for k in DUR:
            if e in dur[k]:
                v, u, t, a = dur[k][e]; r[k] = v; r["src"][k] = f"{t} ({a})"; r.setdefault("_u", {})[k] = u
                if "/" not in u: cur.add(u)
        for k in INST:
            if e in inst[k]:
                v, u, t, a = inst[k][e]; r[k] = v; r["src"][k] = f"{t} ({a})"; cur.add(u); r.setdefault("_u", {})[k] = u
        if r.get("net_income") is None and r.get("profit_total") is not None:   # no attributable figure tagged (typically no minorities)
            r["net_income"] = r["profit_total"]; r["src"]["net_income"] = r["src"]["profit_total"] + " - total profit; no attributable figure tagged"; r["_u"]["net_income"] = r["_u"]["profit_total"]
        # one currency per row: keep the most common unit among monetary fields, drop fields in another currency
        units = {}
        for k, u in r.get("_u", {}).items():
            if k in r and "/" not in u: units[k] = u
        if units:
            main = max(set(units.values()), key=lambda u: list(units.values()).count(u))
            for k, u in units.items():
                if u != main: r.pop(k, None); r["src"][k] = f"dropped: reported in {u}, not {main}"
            cur = {main}
        r["currency"] = sorted(cur)[0] if len(cur) == 1 else (",".join(sorted(cur)) or None)
        if r.get("operating_cash_flow") is not None and r.get("capital_expenditures") is not None:
            r["free_cash_flow"] = r["operating_cash_flow"] - r["capital_expenditures"]
        r.pop("_u", None)
        if r.get("total_assets") is not None:   # a fiscal year must have a balance sheet (drops stray partial periods)
            rows.append(r)
    return f["entityName"], rows


def conn():
    env = {}
    for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
    return psycopg2.connect(host=env["LITHODAT_DB_HOST"], port=env["LITHODAT_DB_PORT"], dbname="interzona_cm", user=env["LITHODAT_DB_USER"], password=env["LITHODAT_DB_PASSWORD"])


def cik_of(c, company_id):
    c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'company' AND entity_id = %s AND source_system = 'SEC_CIK'", (company_id,))
    r = c.fetchone(); return int(r[0]) if r else None


if __name__ == "__main__":
    g = conn(); c = g.cursor()
    if "--undo" in sys.argv:
        for t in ("income_statement", "balance_sheet", "cash_flow"):
            c.execute(f"DELETE FROM financials.{t} WHERE created_by = %s", (TAG,)); print(t, c.rowcount)
        g.commit(); sys.exit()
    mode = "--compare" if "--compare" in sys.argv else "--load"
    ids = [int(a) for a in sys.argv[sys.argv.index(mode) + 1:] if a.isdigit()]
    for cid in ids:
        ck = cik_of(c, cid)
        if not ck: print(cid, "no SEC CIK"); continue
        name, rows = build(ck)
        if mode == "--compare":
            c.execute("""SELECT i.period_end_date::date::text, i.currency, i.revenue, i.net_income, i.operating_income, b.total_assets, b.total_equity, b.total_debt,
                                cf.operating_cash_flow, cf.capital_expenditures
                         FROM financials.income_statement i
                         LEFT JOIN financials.balance_sheet b ON b.company_id = i.company_id AND b.period_end_date = i.period_end_date AND b.is_active
                         LEFT JOIN financials.cash_flow cf ON cf.company_id = i.company_id AND cf.period_end_date = i.period_end_date AND cf.is_active
                         WHERE i.company_id = %s AND i.is_active AND i.period_type = 'FY'""", (cid,))
            stored = {r[0]: r for r in c.fetchall()}
            print(f"== {cid} {name} (CIK {ck}): {len(rows)} EDGAR years, {len(stored)} stored years")
            keys = ["revenue", "net_income", "operating_income", "total_assets", "total_equity", "operating_cash_flow", "capital_expenditures"]
            pos = {"revenue": 2, "net_income": 3, "operating_income": 4, "total_assets": 5, "total_equity": 6, "total_debt": 7, "operating_cash_flow": 8, "capital_expenditures": 9}
            for r in rows:
                s = stored.get(r["period_end_date"])
                if not s: continue
                diffs = []
                for k in keys:
                    a, b = r.get(k), s[pos[k]]
                    if a is None or b is None: diffs.append(f"{k}:{'-' if a is None else 'E'}{'-' if b is None else 'S'}"); continue
                    b = float(b)
                    rel = abs(a - b) / max(abs(b), 1)
                    if rel > 0.005: diffs.append(f"{k}: E {a/1e6:,.0f} vs S {b/1e6:,.0f} ({rel*100:.1f}%)")
                print(f"  {r['period_end_date']} {r['currency']}/{s[1]}: {'OK' if not [d for d in diffs if '(' in d] else ''} " + "; ".join(diffs))
        else:
            c.execute("SELECT count(*) FROM financials.income_statement WHERE company_id = %s AND is_active", (cid,))
            if c.fetchone()[0]: print(cid, name, "already has statements - skipped"); continue
            print(f"== {cid} {name}: {len(rows)} years {rows[0]['period_end_date'] if rows else ''} .. {rows[-1]['period_end_date'] if rows else ''}")
            if "--dry" in sys.argv:
                for r in rows[-3:]: print("  ", r["period_end_date"], r["currency"], {k: round(r[k] / 1e6) for k in ("revenue", "net_income", "total_assets", "operating_cash_flow") if r.get(k) is not None})
                continue
            for r in rows:
                li = Json({"source": "SEC EDGAR XBRL company facts (data.sec.gov), annual filings; value from the most recent filing reporting the period",
                           "cik": ck, "tags": r["src"], "notes": "capital_expenditures = purchases of property, plant and equipment as tagged (may exclude mineral-property, exploration or intangible spending); free_cash_flow = operating cash flow minus that; total_debt not loaded from XBRL."})
                c.execute("""INSERT INTO financials.income_statement (company_id, period_end_date, period_type, currency, revenue, cost_of_revenue, gross_profit,
                             operating_income, net_income, eps_basic, eps_diluted, line_items, created_by, created_date, is_active)
                             VALUES (%s,%s,'FY',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),true)""",
                          (cid, r["period_end_date"], r["currency"], r.get("revenue"), r.get("cost_of_revenue"), r.get("gross_profit"), r.get("operating_income"),
                           r.get("net_income"), r.get("eps_basic"), r.get("eps_diluted"), li, TAG))
                c.execute("""INSERT INTO financials.balance_sheet (company_id, period_end_date, period_type, currency, total_assets, total_current_assets,
                             cash_and_equivalents, total_liabilities, total_current_liabilities, total_debt, total_equity, line_items, created_by, created_date, is_active)
                             VALUES (%s,%s,'FY',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),true)""",
                          (cid, r["period_end_date"], r["currency"], r.get("total_assets"), r.get("total_current_assets"), r.get("cash_and_equivalents"),
                           r.get("total_liabilities"), r.get("total_current_liabilities"), r.get("total_debt"), r.get("total_equity"), li, TAG))
                c.execute("""INSERT INTO financials.cash_flow (company_id, period_end_date, period_type, currency, operating_cash_flow, investing_cash_flow,
                             financing_cash_flow, capital_expenditures, free_cash_flow, line_items, created_by, created_date, is_active)
                             VALUES (%s,%s,'FY',%s,%s,%s,%s,%s,%s,%s,%s,now(),true)""",
                          (cid, r["period_end_date"], r["currency"], r.get("operating_cash_flow"), r.get("investing_cash_flow"), r.get("financing_cash_flow"),
                           r.get("capital_expenditures"), r.get("free_cash_flow"), li, TAG))
            g.commit()
