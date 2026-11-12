"""Loads the 8 public views of the EITI database (downloaded 2026-11-12 by fetch_eiti_database.py on user OK) into markets.eiti_* tables and
registers EITI_DATABASE in core.data_sources. Licence position (user decision 2026-11-12: load now and ask EITI): reuse invited by the
database ("reuse the open data in your own analysis, tools and publications"), no formal licence stated, commercial use not addressed -
confirmation requested from data@eiti.org (Licence_Evidence/EITI). Removal if refused: drop the markets.eiti_* tables and the data_sources row.

Tables (columns as published, values typed): eiti_countries, eiti_commodities, eiti_companies, eiti_projects, eiti_production_exports
(+ hs4 and commodity_group = our grouping via hs_commodity), eiti_project_production (+ hs4, commodity_group), eiti_revenues
(government-reported revenues by stream), eiti_payments (company-reported payments by stream). Re-runnable. Usage: python load_eiti_database.py [--dry]
"""
import io, os, re, sys, datetime
import pandas as pd
import psycopg2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -P drops the script folder from the path
from hs_commodity import commodity as hs_group

DRY = "--dry" in sys.argv
SRC, TAG = "EITI_DATABASE", "migration_eiti_20261112"
DIR = r"D:/CriticalMineralsDB/World/eiti_database_20261112"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')

NUMERIC = {"payment_value", "payment_value_usd", "revenue_value", "revenue_value_usd", "value_numeric", "value_usd", "production_volume",
           "production_value", "production_value_usd", "total_production_value_usd", "production_value_usd_projects",
           "production_value_usd_indicators", "n_producing_countries", "n_projects", "n_companies"}
INTEGER = {"year", "first_year_reported", "last_year_reported", "first_year_covered", "last_year_covered"}
TABLES = {"view_countries": "eiti_countries", "view_commodities": "eiti_commodities", "view_companies": "eiti_companies",
          "view_projects": "eiti_projects", "view_production_and_exports": "eiti_production_exports",
          "view_project_production": "eiti_project_production", "view_revenues_detailed": "eiti_revenues",
          "view_payments_detailed": "eiti_payments"}


def hs4_of(name):
    m = re.search(r"\((\d{4})\)\s*$", name or "")
    return m.group(1) if m else None


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
for view, table in TABLES.items():
    df = pd.read_csv(os.path.join(DIR, view + ".csv"), dtype=str, keep_default_na=False, encoding="utf-8")
    src_rows = len(df)
    if "id" in df.columns: df = df.rename(columns={"id": "eiti_row_id"})
    ccol = "commodity" if table == "eiti_production_exports" else ("commodity_name" if table == "eiti_project_production" else None)
    if ccol:
        df["hs4"] = df[ccol].map(hs4_of)
        # our grouping where the HS heading is known; otherwise EITI's own commodity name without the code (never a catch-all group)
        df["commodity_group"] = [None if not h else (lambda grp: re.sub(r"\s*\(\d{4}\)\s*$", "", nm) if grp == "Other inorganic chemicals" else grp)(hs_group(h + "00", nm))
                                 for h, nm in zip(df["hs4"], df[ccol])]
        df.loc[df["hs4"].isin(["2709", "2711"]), "commodity_group"] = df["hs4"].map({"2709": "Crude oil", "2711": "Natural gas"})
    cols = list(df.columns)
    defs = ", ".join(f'"{col}" {"numeric" if col in NUMERIC else "integer" if col in INTEGER else "text"}' for col in cols)
    c.execute(f"DROP TABLE IF EXISTS markets.{table}; CREATE TABLE markets.{table} ({defs}, source_system text NOT NULL DEFAULT '{SRC}', created_by text NOT NULL DEFAULT '{TAG}')")
    for col in cols:  # numbers: blanks and words such as 'Not available' become NULL in the typed column (kept as text in value columns where published)
        if col in NUMERIC or col in INTEGER:
            df[col] = pd.to_numeric(df[col].str.strip(), errors="coerce")
    buf = io.StringIO(); df.to_csv(buf, index=False, header=False, na_rep="", float_format="%.10g"); buf.seek(0)
    c.copy_expert(f"COPY markets.{table} ({', '.join(chr(34) + x + chr(34) for x in cols)}) FROM STDIN WITH (FORMAT csv, NULL '')", buf)
    c.execute(f"SELECT count(*) FROM markets.{table}"); n = c.fetchone()[0]
    print(table, "rows", n, "of", src_rows, "OK" if n == src_rows else "MISMATCH")
    c.execute(f"GRANT SELECT ON markets.{table} TO cm_app_readonly")
c.execute("""CREATE INDEX ON markets.eiti_payments (country_name, year); CREATE INDEX ON markets.eiti_payments (company_name);
             CREATE INDEX ON markets.eiti_revenues (country_name, year); CREATE INDEX ON markets.eiti_production_exports (commodity_group, year);
             CREATE INDEX ON markets.eiti_project_production (country_name, year);""")
c.execute("COMMENT ON TABLE markets.eiti_payments IS 'EITI database: company-reported payments to governments by revenue stream (GFS-classified), 2009-2024; payment_value in currency_code, payment_value_usd converted by EITI. Credit: EITI database.'")
c.execute("COMMENT ON TABLE markets.eiti_revenues IS 'EITI database: government-reported extractive revenues by stream and sector; revenue_value_usd converted by EITI. Credit: EITI database.'")
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text,
             is_loaded, licence_status, caveats, evidence_location, evidence_date, is_active, created_by)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,%s,true,%s)
             ON CONFLICT (source_system) DO UPDATE SET dataset_name = EXCLUDED.dataset_name, licence = EXCLUDED.licence, attribution_text = EXCLUDED.attribution_text,
             is_loaded = true, licence_status = EXCLUDED.licence_status, caveats = EXCLUDED.caveats, evidence_location = EXCLUDED.evidence_location""",
          (SRC, "Extractive Industries Transparency Initiative (EITI) International Secretariat",
           "EITI database public views (payments, revenues, production and exports, project production, companies, projects, commodities, countries)",
           "Reuse invited by the EITI database; no formal licence stated (confirmation requested)", "https://eiti.org/documents/eiti-open-data-policy",
           "Extractive Industries Transparency Initiative (EITI), EITI database (https://eiti-database.eiti.org), accessed 12 November 2026; data disclosed by EITI implementing countries.",
           "PENDING CONFIRMATION: loaded on user decision 2026-11-12; email to data@eiti.org drafted. Remove (drop markets.eiti_*) if EITI refuses commercial reuse.",
           "Covers EITI implementing countries only (55 reporting), by fiscal year as reported; oil and gas included; company payments are as disclosed in EITI reports (reconciled or unilateral); USD values converted by EITI; some country data may carry national open-data licences.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\EITI\EVIDENCE.md", datetime.date(2026, 11, 12), TAG))
c.execute("""SELECT country_name, round(sum(payment_value_usd)/1e6) musd FROM markets.eiti_payments WHERE year = 2022 GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT 5""")
print("top payment totals 2022 (USD m):", c.fetchall())
c.execute("""SELECT commodity_group, count(*) FROM markets.eiti_production_exports GROUP BY 1 ORDER BY 2 DESC LIMIT 12"""); print("production/export groups:", c.fetchall())
c.execute("SELECT count(*) FROM markets.eiti_production_exports WHERE commodity IS NOT NULL AND commodity <> '' AND hs4 IS NULL"); print("commodities without HS4:", c.fetchone()[0])
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
