"""Loads the EU-owned parts of the JRC Raw Materials Information System (RMIS) profiles (fetched 2026-11-11 by fetch_jrc_rmis.py; scope
chosen by the user: EU-owned figures only, CC BY 4.0 under the European Commission legal notice) into:
  markets.rmis_indicators  - JRC / 2023 EU CRM assessment indicators per material: EU import reliance (primary, refined), EU sourcing
                             (top supplier countries, primary and refined, 2016-2020), EU self-sufficiency, end-of-life recycling input rate,
                             uses, EU share of world reserves / production, HHI concentration, CRM 2023 status, SRM status
  markets.rmis_eu_trade    - EU extra-EU trade series per material from Eurostat Comext as compiled by JRC (million EUR; EUR/kg; kt)
  markets.rmis_recycling   - recycling indicators whose source is JRC's own calculation/estimate or expert judgement in the EU CRM assessments
Third-party series (world producers/reserves, 2019 world trade tops, EPI, WGI, CAGR, world production figures, academic/industry recycling
studies) are NOT loaded. Re-runnable (replaces the tables). Usage: python load_jrc_rmis.py [--dry]
"""
import json, os, re, sys, datetime
import psycopg2

DRY = "--dry" in sys.argv
SRC, TAG = "JRC_RMIS", "migration_jrc_rmis_20261112"
DIR = r"D:/CriticalMineralsDB/World/jrc_rmis_20261111"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')

KEEP_IND = {"dsb_ind_ir1", "dsb_ind_ir2", "dsb_ind_eusrc1", "dsb_ind_eusrc2", "dsb_ind_euss", "dsb_ind_eolrir", "dsb_ind_uses",
            "dsb_ind_eures", "dsb_ind_euprod1", "dsb_ind_euprod2", "dsb_ind_hhi", "dsb_ind_kv5", "dsb_ind_ki1"}
EXTRA_DEF = {"dsb_ind_kv5": ("Critical Raw Material in 2023", "Whether the material is on the EU's 2023 Critical Raw Materials list"),
             "dsb_ind_ki1": ("Strategic Raw Material", "Statement on the Strategic Raw Materials list (Critical Raw Materials Act, 2024)")}
REC_KEEP = re.compile(r"^Source:\s*(JRC\b|Expert judg)", re.I)

defs = {d["ind"]: (d.get("title"), (d.get("tooltip") or "").replace("\\n", " ").replace("\n", " "), d.get("unit"))
        for d in json.load(open(os.path.join(DIR, "indicator_definitions.json"), encoding="utf-8"))}
mats = json.load(open(os.path.join(DIR, "available.json"), encoding="utf-8"))


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


ind_rows, trade_rows, rec_rows, rec_skipped = [], [], [], 0
for m in mats:
    d = os.path.join(DIR, m.replace("/", "_"))
    for x in json.load(open(os.path.join(d, "dashboard.json"), encoding="utf-8")) or []:
        if x["ind"] not in KEEP_IND: continue
        title, definition, unit = defs.get(x["ind"], (None, None, None))
        if x["ind"] in EXTRA_DEF: title, definition = EXTRA_DEF[x["ind"]]; unit = None
        pairs = [(x.get(f"k{i}"), x.get(f"v{i}")) for i in range(1, 6) if x.get(f"k{i}") is not None or x.get(f"v{i}") is not None]
        single = x["ind"] in {"dsb_ind_ir1", "dsb_ind_ir2", "dsb_ind_euss", "dsb_ind_eolrir", "dsb_ind_eures", "dsb_ind_euprod1", "dsb_ind_euprod2", "dsb_ind_kv5", "dsb_ind_ki1"}
        for rank, (k, v) in enumerate(pairs, start=1):
            item = None if single else k
            if x["ind"] == "dsb_ind_ki1": vt, vn = k, None          # statement text sits in k1
            else: vt, vn = (None if v is None else str(v)), num(v)
            ind_rows.append((m, x["ind"].replace("dsb_ind_", ""), title, definition, item, vn, vt, unit, None if single else rank))
    tr = json.load(open(os.path.join(d, "trade.json"), encoding="utf-8")) or {}
    for ds, rows in tr.items():
        if not isinstance(rows, list): continue
        for r in rows:
            imp = num(r.get("import"))
            trade_rows.append((m, ds, int(r["year"]) if r.get("year") else None, r.get("code") or r.get("code_group"), r.get("product") or r.get("group"),
                               r.get("description"), r.get("value_chain_stage") or r.get("stage"), r.get("country"), (r.get("flow") or "").lower() or None,
                               num(r.get("export")), None if imp is None else abs(imp), num(r.get("trade_balance")), num(r.get("value")),
                               num(r.get("totalexport")), num(r.get("totalimport")), num(r.get("shareexport")), num(r.get("shareimport")),
                               num(r.get("share")), num(r.get("changevsprev")), num(r.get("sharechangevsprev")),
                               int(r["prevyear"]) if r.get("prevyear") else None, num(r.get("price")), num(r.get("quantity")), r.get("unit"), r.get("aggregation")))
    for r in json.load(open(os.path.join(d, "recycling.json"), encoding="utf-8")) or []:
        if r.get("value") is None or not REC_KEEP.match(r.get("source") or ""):
            rec_skipped += 1; continue
        rec_rows.append((m, r.get("type"), num(r.get("value")), str(r.get("value")), r.get("scope"), r.get("source"), r.get("description")))
print("indicator rows", len(ind_rows), "| trade rows", len(trade_rows), "| recycling kept", len(rec_rows), "skipped (third-party or empty)", rec_skipped)

# check: tradePrices value (million EUR) ~ price (EUR/kg) x quantity (kt)
bad = [t for t in trade_rows if t[1] == "tradePrices" and t[21] and t[22] and t[12] and abs(t[21] * t[22] - t[12]) > 0.02 * t[12] + 0.05]
print("tradePrices rows where value != price x quantity (kt):", len(bad), bad[:2])

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("""
DROP TABLE IF EXISTS markets.rmis_indicators, markets.rmis_eu_trade, markets.rmis_recycling;
CREATE TABLE markets.rmis_indicators (id serial PRIMARY KEY, material text NOT NULL, indicator text NOT NULL, indicator_title text, definition text,
  item text, value_numeric numeric, value_text text, unit text, rank smallint, source_system text NOT NULL DEFAULT 'JRC_RMIS', created_by text NOT NULL);
CREATE TABLE markets.rmis_eu_trade (id serial PRIMARY KEY, material text NOT NULL, dataset text NOT NULL, year smallint, code text, product text,
  description text, value_chain_stage text, country text, flow text, export_meur numeric, import_meur numeric, trade_balance_meur numeric,
  value numeric, total_export_meur numeric, total_import_meur numeric, share_export_pct numeric, share_import_pct numeric, share_pct numeric,
  change_vs_prev_pct numeric, share_change_vs_prev numeric, prev_year smallint, price_eur_per_kg numeric, quantity_kt numeric, unit text,
  aggregation text, source_system text NOT NULL DEFAULT 'JRC_RMIS', created_by text NOT NULL);
CREATE TABLE markets.rmis_recycling (id serial PRIMARY KEY, material text NOT NULL, indicator_type text, value_numeric numeric, value_text text,
  scope text, source text, description text, source_system text NOT NULL DEFAULT 'JRC_RMIS', created_by text NOT NULL);
CREATE INDEX ON markets.rmis_indicators (material, indicator); CREATE INDEX ON markets.rmis_eu_trade (material, dataset, year);
CREATE INDEX ON markets.rmis_recycling (material);
COMMENT ON TABLE markets.rmis_indicators IS 'JRC RMIS EU indicators per material (2023 EU CRM assessment, reference 2016-2020): import reliance, EU sourcing, self-sufficiency, EoL-RIR, uses, EU shares, HHI, CRM/SRM status. CC BY 4.0, European Commission JRC.';
COMMENT ON TABLE markets.rmis_eu_trade IS 'JRC RMIS EU extra-EU trade series per material (Eurostat Comext as compiled by JRC): million EUR, EUR/kg, kt; imports stored as positive amounts. CC BY 4.0.';
COMMENT ON TABLE markets.rmis_recycling IS 'JRC RMIS recycling indicators from JRC calculations/estimates or EU CRM-assessment expert judgement only (third-party studies excluded). CC BY 4.0.';
GRANT SELECT ON markets.rmis_indicators, markets.rmis_eu_trade, markets.rmis_recycling TO cm_app_readonly;
""")
c.executemany("INSERT INTO markets.rmis_indicators (material, indicator, indicator_title, definition, item, value_numeric, value_text, unit, rank, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
              [r + (TAG,) for r in ind_rows])
c.executemany("""INSERT INTO markets.rmis_eu_trade (material, dataset, year, code, product, description, value_chain_stage, country, flow, export_meur, import_meur,
                 trade_balance_meur, value, total_export_meur, total_import_meur, share_export_pct, share_import_pct, share_pct, change_vs_prev_pct,
                 share_change_vs_prev, prev_year, price_eur_per_kg, quantity_kt, unit, aggregation, created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [r + (TAG,) for r in trade_rows])
c.executemany("INSERT INTO markets.rmis_recycling (material, indicator_type, value_numeric, value_text, scope, source, description, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
              [r + (TAG,) for r in rec_rows])
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text,
             is_loaded, licence_status, caveats, evidence_location, evidence_date, is_active, created_by)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,%s,true,%s)
             ON CONFLICT (source_system) DO UPDATE SET dataset_name = EXCLUDED.dataset_name, licence = EXCLUDED.licence, attribution_text = EXCLUDED.attribution_text,
             is_loaded = true, licence_status = EXCLUDED.licence_status, caveats = EXCLUDED.caveats, evidence_location = EXCLUDED.evidence_location""",
          (SRC, "European Commission, Joint Research Centre", "Raw Materials Information System (RMIS) raw-material profiles - EU-owned indicators, EU trade and JRC recycling figures (88 materials)",
           "CC BY 4.0 (European Commission reuse policy, Decision 2011/833/EU)", "https://commission.europa.eu/legal-notice_en",
           "European Commission, Joint Research Centre, Raw Materials Information System (RMIS), https://rmis.jrc.ec.europa.eu, accessed 11 November 2026, CC BY 4.0 (EU trade based on Eurostat Comext).",
           "Cleared for EU-owned content (CC BY 4.0, checked 2026-11-11); third-party series displayed by RMIS were not loaded.",
           "EU view only: import reliance and EU sourcing are 2016-2020 averages from the 2023 EU CRM assessment; trade is extra-EU trade in EUR (not USD); recycling rows limited to JRC calculations and EU expert judgement.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\JRC_RMIS\EVIDENCE.md", datetime.date(2026, 11, 12), TAG))
c.execute("SELECT count(DISTINCT material), count(*) FROM markets.rmis_indicators"); print("indicators: materials, rows", c.fetchone())
c.execute("SELECT indicator, count(DISTINCT material) FROM markets.rmis_indicators GROUP BY 1 ORDER BY 2 DESC"); print(c.fetchall())
c.execute("SELECT dataset, count(DISTINCT material), count(*), min(year), max(year) FROM markets.rmis_eu_trade GROUP BY 1 ORDER BY 1"); print(c.fetchall())
c.execute("SELECT count(DISTINCT material), count(*) FROM markets.rmis_recycling"); print("recycling: materials, rows", c.fetchone())
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
