"""2026-11-06: Elevra Lithium's two annual statements (FY2025, FY2026; loaded 2026-09-23 from its investor presentation, doc 5) never got
financials.financial_ratios rows, so peer_comparison showed "no net margin" for Elevra. This computes the ratios the stored rows support
(operating margin, net margin, ROE, ROA; no gross profit, current items or debt are stored, so those stay NULL) in SQL, like the other
companies' ratio rows. Dry run by default; --apply to write. Rollback: DELETE FROM financials.financial_ratios WHERE created_by = TAG."""
import os, sys, psycopg2

TAG = "claude_elevra_ratios_20261106"
NOTE = ("Computed from the stored Elevra Lithium FY statements (US$; from the company's investor presentation, document 5, figures rounded "
        "to US$ millions). No gross profit, current assets or liabilities, or debt are stored, so gross margin, current ratio and "
        "debt-to-equity are not available. ROE and ROA are period figures over year-end equity and assets. FY2025 includes large losses "
        "(net margin about -170%); FY2026 is the first profitable year. Computed 2026-11-06 from rows already in the database.")

ENV = {}
for f in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),):
    for l in open(f, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1); ENV.setdefault(k.strip(), v.strip())
conn = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                        user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
cur = conn.cursor()
SELECT = """
  SELECT i.company_id, i.period_end_date, i.period_type,
         round((i.operating_income / NULLIF(i.revenue, 0))::numeric, 4) AS operating_margin,
         round((i.net_income / NULLIF(i.revenue, 0))::numeric, 4) AS net_margin,
         round((i.net_income / NULLIF(b.total_equity, 0))::numeric, 4) AS return_on_equity,
         round((i.net_income / NULLIF(b.total_assets, 0))::numeric, 4) AS return_on_assets,
         i.source_document_id
  FROM financials.income_statement i
  JOIN core.companies c USING (company_id)
  LEFT JOIN financials.balance_sheet b ON b.company_id = i.company_id AND b.period_end_date = i.period_end_date AND b.period_type = i.period_type
  WHERE c.name = 'Elevra Lithium' AND i.period_type = 'FY'
    AND NOT EXISTS (SELECT 1 FROM financials.financial_ratios r WHERE r.company_id = i.company_id AND r.period_end_date = i.period_end_date
                    AND r.period_type = i.period_type AND r.is_active)"""
cur.execute(SELECT)
rows = cur.fetchall()
for r in rows:
    print(r[1].date() if hasattr(r[1], "date") else r[1], "op", r[3], "net", r[4], "roe", r[5], "roa", r[6])
if "--apply" in sys.argv and rows:
    cur.execute(f"""INSERT INTO financials.financial_ratios (company_id, period_end_date, period_type, operating_margin, net_margin,
                       return_on_equity, return_on_assets, ratio_data, calculated_at, source_document_id, is_active, created_by)
                    SELECT company_id, period_end_date, period_type, operating_margin, net_margin, return_on_equity, return_on_assets,
                           jsonb_build_object('note', %s), now(), source_document_id, true, %s FROM ({SELECT}) s""", (NOTE, TAG))
    print("inserted", cur.rowcount); conn.commit()
conn.close()
