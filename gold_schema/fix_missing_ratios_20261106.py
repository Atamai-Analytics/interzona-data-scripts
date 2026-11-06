"""2026-11-06: statements that were loaded as the prior-period comparative column of a report (or from an investor presentation) never got
financials.financial_ratios rows, because ratios were computed by hand for the current period only. This fills them with the same
conventions as the existing rows:
  - margins only when there is real sales revenue (> 100,000 in the reporting currency); NULL for pre-revenue explorers/developers
  - gross margin NULL when gross profit is missing, or recorded as exactly 0 against real revenue (i.e. not reported)
  - current ratio, debt-to-equity, ROE and ROA when the balance-sheet items exist; interim ROE/ROA are period figures, not annualised
  - rows where nothing is computable (no revenue and no balance sheet) are skipped and listed
All arithmetic is done in SQL. Dry run by default; --apply to write. Rollback: DELETE FROM financials.financial_ratios WHERE created_by = TAG."""
import os, sys, psycopg2

TAG = "claude_missing_ratios_20261106"
NOTES = {
    "Arafura Rare Earths Limited": "FY2024 (prior-year comparative in the FY2025 annual report). Margins NULL: pre-revenue developer with no sales revenue. Effectively debt-free.",
    "Boss Energy Ltd": "FY2024 (prior-year comparative in the FY2025 annual report). Margins NULL: pre-revenue in FY2024. The positive ROE/ROA come from fair-value gains, not operations, so FY2024 is not comparable with FY2025.",
    "Deep Yellow Limited": "FY2024 (prior-year comparative in the FY2025 annual report). Margins NULL: no meaningful sales revenue (A$15,949 of other revenue). Effectively debt-free.",
    "Lotus Resources Limited": "FY2024 (prior-year comparative in the FY2025 annual report). Margins NULL: pre-revenue developer with no sales revenue. Effectively debt-free.",
    "Paladin Energy Ltd": "FY2024 (prior-year comparative in the FY2025 annual report). Margins NULL: no sales revenue in FY2024 (Langer Heinrich restart came in FY2025). The FY2024 profit and positive ROE/ROA come from a one-off non-cash impairment reversal, not operations.",
    "Liontown Resources Limited": "Half-year to 31 Dec 2024 (prior-period comparative in the H1 FY2026 interim report). Gross margin NULL: gross profit is not reported separately in the stored figures. No balance sheet is stored for this period, so no balance-sheet ratios.",
    "PLS Group Limited": "Half-year to 31 Dec 2024 (prior-period comparative in the H1 FY2026 interim report). No balance sheet is stored for this period, so no balance-sheet ratios.",
    "Amaroq Ltd": "Half-year to 30 Jun 2026, from the company's investor presentation (figures rounded, C$). ROA is a half-year figure over period-end total assets, not annualised. Total equity and current assets are not stored, so ROE, current ratio and debt-to-equity are not available.",
}

ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV.setdefault(k.strip(), v.strip())
conn = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                        user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
cur = conn.cursor()
SELECT = """
  SELECT c.name, i.company_id, i.period_end_date, i.period_type, i.source_document_id,
         CASE WHEN i.revenue > 100000 AND i.gross_profit IS NOT NULL AND i.gross_profit <> 0 THEN round((i.gross_profit / i.revenue)::numeric, 4) END AS gross_margin,
         CASE WHEN i.revenue > 100000 THEN round((i.operating_income / i.revenue)::numeric, 4) END AS operating_margin,
         CASE WHEN i.revenue > 100000 THEN round((i.net_income / i.revenue)::numeric, 4) END AS net_margin,
         round((b.total_current_assets / NULLIF(b.total_current_liabilities, 0))::numeric, 4) AS current_ratio,
         round((b.total_debt / NULLIF(b.total_equity, 0))::numeric, 4) AS debt_to_equity,
         CASE WHEN b.total_equity > 0 THEN round((i.net_income / b.total_equity)::numeric, 4) END AS return_on_equity,
         CASE WHEN b.total_assets > 0 THEN round((i.net_income / b.total_assets)::numeric, 4) END AS return_on_assets
  FROM financials.income_statement i
  JOIN core.companies c USING (company_id)
  LEFT JOIN financials.balance_sheet b ON b.company_id = i.company_id AND b.period_end_date = i.period_end_date AND b.period_type = i.period_type
  WHERE NOT EXISTS (SELECT 1 FROM financials.financial_ratios r WHERE r.company_id = i.company_id AND r.period_end_date = i.period_end_date
                    AND r.period_type = i.period_type AND r.is_active)"""
cur.execute(SELECT)
cols = [d[0] for d in cur.description]
rows = [dict(zip(cols, r)) for r in cur.fetchall()]
RATIOS = ["gross_margin", "operating_margin", "net_margin", "current_ratio", "debt_to_equity", "return_on_equity", "return_on_assets"]
todo, skipped = [], []
for r in rows:
    if all(r[k] is None for k in RATIOS):
        skipped.append(r); continue
    if r["name"] not in NOTES:
        sys.exit(f"no note written for {r['name']} - add one before applying")
    todo.append(r)
for r in todo:
    print(f"{r['name'][:28]:28s} {r['period_end_date']} {r['period_type']:3s} " + " ".join(f"{k.split('_')[0][:5]}={r[k]}" for k in RATIOS))
for r in skipped:
    print(f"SKIP (nothing computable): {r['name']} {r['period_end_date']} {r['period_type']}")
if "--apply" in sys.argv:
    for r in todo:
        cur.execute("""INSERT INTO financials.financial_ratios (company_id, period_end_date, period_type, gross_margin, operating_margin, net_margin,
                           current_ratio, debt_to_equity, return_on_equity, return_on_assets, ratio_data, calculated_at, source_document_id, is_active, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, jsonb_build_object('note', %s::text), now(), %s, true, %s)""",
                    (r["company_id"], r["period_end_date"], r["period_type"], *[r[k] for k in RATIOS], NOTES[r["name"]] + " Computed 2026-11-06 from rows already in the database.",
                     r["source_document_id"], TAG))
    conn.commit(); print("inserted", len(todo))
conn.close()
