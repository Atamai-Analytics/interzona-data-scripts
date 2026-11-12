"""Loads the mineral and metal products of CEPII BACI (version 202601, HS12 revision, years 2012-2024; downloaded 2026-11-11 on user OK)
into markets.trade_flows (+ markets.trade_countries, markets.trade_products, view markets.trade_flows_named) and registers CEPII_BACI in
core.data_sources. Licence: Etalab Open Licence 2.0 - any use with credit (Licence_Evidence/CEPII_BACI/EVIDENCE.md).

Reads the yearly CSVs straight from the zip (never unpacked) and keeps only products where hs_commodity.keep(hs6) is true (ores, industrial
minerals, critical-mineral chemicals, precious metals, ferroalloys and scrap, unwrought/refined base and minor metals, plus 850511
permanent magnets and 850760 lithium-ion batteries). Values: value_kusd = BACI v (thousands of current USD, FOB-reconciled), quantity_t =
BACI q (metric tons; NULL where BACI has none). Country codes are BACI/Comtrade codes (490 = 'Asia, n.e.s.', in practice Taiwan).
Re-runnable: replaces the three tables. Usage: python load_baci_minerals.py [--dry]
"""
import io, os, sys, zipfile, datetime
import pandas as pd
import psycopg2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -P drops the script folder from the path
from hs_commodity import commodity, keep

DRY = "--dry" in sys.argv
SRC = "CEPII_BACI"
TAG = "migration_baci_hs12_20261111"
ZIP = r"D:/CriticalMineralsDB/World/baci_hs12_v202601_20261111/BACI_HS12_V202601.zip"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')

z = zipfile.ZipFile(ZIP)
names = z.namelist()
print("zip members:", [n for n in names if not n.startswith("BACI_HS12_Y")], "| yearly files:", sum(n.startswith("BACI_HS12_Y") for n in names))
pfile = next(n for n in names if n.lower().startswith("product_codes"))
cfile = next(n for n in names if n.lower().startswith("country_codes"))
prod = pd.read_csv(z.open(pfile), dtype=str, keep_default_na=False, encoding="utf-8", encoding_errors="replace")
ctry = pd.read_csv(z.open(cfile), dtype=str, keep_default_na=False, encoding="utf-8", encoding_errors="replace")
print("product columns", list(prod.columns), "country columns", list(ctry.columns))
prod.columns = ["hs6", "description"][: len(prod.columns)] + list(prod.columns[2:])
prod["hs6"] = prod["hs6"].str.zfill(6)
kept = prod[prod["hs6"].map(keep)].copy()
kept["commodity"] = [commodity(h, d) for h, d in zip(kept["hs6"], kept["description"])]
codes = set(kept["hs6"])
print("products kept", len(kept), "of", len(prod))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("""
DROP VIEW IF EXISTS markets.trade_flows_named;
DROP TABLE IF EXISTS markets.trade_flows, markets.trade_products, markets.trade_countries;
CREATE TABLE markets.trade_countries (country_code integer PRIMARY KEY, country_name text NOT NULL, iso2 text, iso3 text);
CREATE TABLE markets.trade_products (hs6 text PRIMARY KEY, description text, commodity text NOT NULL);
CREATE TABLE markets.trade_flows (year smallint NOT NULL, hs6 text NOT NULL, exporter_code integer NOT NULL, importer_code integer NOT NULL,
  value_kusd numeric NOT NULL, quantity_t numeric, PRIMARY KEY (year, hs6, exporter_code, importer_code));
""")
# country file columns: country_code, country_name, country_iso2, country_iso3 (names may differ by version - take by position)
cc = ctry.iloc[:, :4].copy(); cc.columns = ["code", "name", "iso2", "iso3"]
for r in cc.itertuples(index=False):
    c.execute("INSERT INTO markets.trade_countries VALUES (%s,%s,%s,%s)", (int(r.code), r.name.strip(), r.iso2.strip() or None, r.iso3.strip() or None))
for r in kept.itertuples(index=False):
    c.execute("INSERT INTO markets.trade_products VALUES (%s,%s,%s)", (r.hs6, r.description.strip(), r.commodity))

total = 0
for n in sorted(x for x in names if x.startswith("BACI_HS12_Y")):
    year_rows = 0
    for ch in pd.read_csv(z.open(n), dtype={"k": str}, chunksize=2_000_000):
        ch["k"] = ch["k"].str.strip().str.zfill(6)
        ch = ch[ch["k"].isin(codes)]
        if ch.empty: continue
        q = pd.to_numeric(ch["q"], errors="coerce")
        buf = io.StringIO()
        pd.DataFrame({"t": ch["t"], "k": ch["k"], "i": ch["i"], "j": ch["j"], "v": ch["v"], "q": q}).to_csv(buf, index=False, header=False, na_rep="")
        buf.seek(0)
        c.copy_expert("COPY markets.trade_flows (year, hs6, exporter_code, importer_code, value_kusd, quantity_t) FROM STDIN WITH (FORMAT csv, NULL '')", buf)
        year_rows += len(ch)
    total += year_rows
    print(n, "rows kept", year_rows, flush=True)

c.execute("""
ALTER TABLE markets.trade_flows ADD FOREIGN KEY (hs6) REFERENCES markets.trade_products (hs6);
CREATE INDEX ON markets.trade_flows (hs6, year);
CREATE INDEX ON markets.trade_flows (exporter_code, year);
CREATE INDEX ON markets.trade_flows (importer_code, year);
CREATE VIEW markets.trade_flows_named AS
  SELECT f.year, f.hs6, p.description AS product, p.commodity, f.exporter_code, e.country_name AS exporter, e.iso3 AS exporter_iso3,
         f.importer_code, i.country_name AS importer, i.iso3 AS importer_iso3, f.value_kusd, f.quantity_t
  FROM markets.trade_flows f JOIN markets.trade_products p USING (hs6)
  JOIN markets.trade_countries e ON e.country_code = f.exporter_code JOIN markets.trade_countries i ON i.country_code = f.importer_code;
COMMENT ON TABLE markets.trade_flows IS 'CEPII BACI 202601 (HS12), 2012-2024, mineral and metal products only: one row per year x HS6 x exporter x importer; value_kusd = thousands of current USD (FOB-reconciled), quantity_t = metric tons. 2024 is provisional. Credit: CEPII BACI (Etalab 2.0).';
COMMENT ON VIEW markets.trade_flows_named IS 'markets.trade_flows with product, commodity (our grouping) and exporter/importer names.';
GRANT SELECT ON markets.trade_flows, markets.trade_products, markets.trade_countries, markets.trade_flows_named TO cm_app_readonly;
""")
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text,
             is_loaded, licence_status, caveats, evidence_location, evidence_date, is_active, created_by)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,%s,true,%s)
             ON CONFLICT (source_system) DO UPDATE SET dataset_name = EXCLUDED.dataset_name, licence = EXCLUDED.licence, attribution_text = EXCLUDED.attribution_text,
             is_loaded = true, licence_status = EXCLUDED.licence_status, caveats = EXCLUDED.caveats, evidence_location = EXCLUDED.evidence_location""",
          (SRC, "CEPII", "BACI bilateral trade flows, version 202601, HS12 revision (2012-2024), mineral and metal products only",
           "Etalab Open Licence 2.0", "https://www.etalab.gouv.fr/wp-content/uploads/2018/11/open-licence.pdf",
           "CEPII BACI (version 202601, HS12), Gaulier and Zignago (2010), https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37 - Etalab Open Licence 2.0.",
           "Cleared: BACI FAQ - any use authorised provided the source is mentioned (checked 2026-11-11).",
           "Values in thousands of current USD (FOB-reconciled from UN Comtrade), quantities in metric tons; 2024 is provisional and may be revised; country codes are BACI/Comtrade codes (490 = Asia n.e.s., in practice Taiwan); commodity is our grouping of HS codes; only mineral and metal products loaded.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\CEPII_BACI\EVIDENCE.md", datetime.date(2026, 11, 11), TAG))
c.execute("SELECT count(*), min(year), max(year), count(DISTINCT hs6), count(DISTINCT exporter_code), sum(value_kusd)/1e6, count(quantity_t) FROM markets.trade_flows")
print("loaded rows, years, products, exporters, total value (USD bn), rows with quantity:", c.fetchone())
c.execute("""SELECT exporter, round(sum(value_kusd)/1e3) musd, round(sum(quantity_t)) t FROM markets.trade_flows_named WHERE hs6 = '283691' AND year = 2023
             GROUP BY 1 ORDER BY 2 DESC LIMIT 5"""); print("lithium carbonate exporters 2023:", c.fetchall())
c.execute("""SELECT importer, round(sum(value_kusd)/1e3) musd FROM markets.trade_flows_named WHERE hs6 = '260500' AND year = 2023 GROUP BY 1 ORDER BY 2 DESC LIMIT 3"""); print("cobalt ore importers 2023:", c.fetchall())
c.execute("SELECT count(*) FROM markets.trade_flows f LEFT JOIN markets.trade_countries t ON t.country_code = f.exporter_code WHERE t.country_code IS NULL"); print("flows with unknown exporter code (must be 0):", c.fetchone()[0])
print("total kept", total)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
