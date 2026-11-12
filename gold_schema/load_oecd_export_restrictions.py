"""Loads the OECD Inventory of Export Restrictions on Critical Raw Materials (2009-2024, HS2007 6-digit; downloaded 2026-11-11 on user OK)
into markets.export_restrictions, and registers OECD_EXPORT_RESTRICTIONS in core.data_sources.

Source file: D:/CriticalMineralsDB/World/oecd_export_restrictions_20261111/oecd-industrial-raw-materials-complete-data_2025.xlsx
(86,986 rows: one per country x product x measure x year). Licence: OECD Terms & Conditions, Data - any purpose incl. commercial, with credit
(evidence Licence_Evidence/OECD_EXPORT_RESTRICTIONS/EVIDENCE.md).

Every published column is kept as text. Added: value_numeric (only when the published value is a plain number, '4,5' -> 4.5; 'N' and
wording such as '15%, but not less than 100 EUR per tonne' stay NULL), date_introduced / date_ending parsed from dd/mm/yyyy, is_temporary,
hs_heading, and commodity = OUR grouping of the HS code (heading map + keyword match on the HS description; e.g. 2605 and 8105 -> Cobalt,
283691 -> Lithium; mixed groups are named as published, e.g. 'Niobium, tantalum, vanadium (ores)'). Re-runnable: replaces the table.
Usage: python load_oecd_export_restrictions.py [--dry]
"""
import os, re, sys, datetime
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
SRC = "OECD_EXPORT_RESTRICTIONS"
TAG = "migration_oecd_exprestr_20261111"
FILE = r"D:/CriticalMineralsDB/World/oecd_export_restrictions_20261111/oecd-industrial-raw-materials-complete-data_2025.xlsx"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')

HEADING = {
    "2502": "Pyrite", "2504": "Graphite", "2505": "Natural sands", "2507": "Kaolin", "2508": "Clays (bentonite etc.)", "2510": "Phosphate rock",
    "2511": "Barite", "2512": "Diatomite", "2513": "Pumice and natural abrasives", "2519": "Magnesium (magnesite)", "2520": "Gypsum",
    "2521": "Limestone flux", "2522": "Lime", "2526": "Talc", "2528": "Boron (natural borates)", "2530": "Other minerals (mica, vermiculite etc.)",
    "2601": "Iron ore", "2602": "Manganese", "2603": "Copper", "2604": "Nickel", "2605": "Cobalt", "2606": "Aluminium (bauxite)", "2607": "Lead",
    "2608": "Zinc", "2609": "Tin", "2610": "Chromium", "2611": "Tungsten", "2612": "Uranium and thorium", "2613": "Molybdenum", "2614": "Titanium",
    "2616": "Precious metals (ores)", "2618": "Iron and steel slag", "2619": "Iron and steel slag", "2620": "Metal-bearing ash and residues",
    "2701": "Coal", "2704": "Coke", "2809": "Phosphate rock", "2810": "Boron (natural borates)", "2817": "Zinc", "2818": "Aluminium (bauxite)",
    "2819": "Chromium", "2820": "Manganese", "2821": "Iron ore", "2822": "Cobalt", "2823": "Titanium", "2824": "Lead", "2826": "Fluorspar",
    "2835": "Phosphate rock", "2840": "Boron (natural borates)", "2843": "Precious metals (compounds)", "2846": "Rare earths", "2852": "Mercury",
    "3104": "Potash", "4403": "Wood", "4407": "Wood", "7102": "Diamonds", "7105": "Diamonds", "7106": "Silver", "7107": "Silver", "7108": "Gold",
    "7109": "Gold", "7110": "Platinum-group metals", "7111": "Platinum-group metals", "7112": "Precious metals (waste and scrap)",
    "7202": "Ferroalloys", "7204": "Iron and steel scrap", "8101": "Tungsten", "8102": "Molybdenum", "8103": "Tantalum", "8104": "Magnesium",
    "8105": "Cobalt", "8106": "Bismuth", "8107": "Cadmium", "8108": "Titanium", "8109": "Zirconium", "8110": "Antimony", "8111": "Manganese",
}
CODE = {
    "261510": "Zirconium", "261590": "Niobium, tantalum, vanadium (ores)", "261710": "Antimony", "261790": "Other ores",
    "252910": "Feldspar", "252921": "Fluorspar", "252922": "Fluorspar", "252930": "Leucite, nepheline",
    "280519": "Alkali and alkaline-earth metals (incl. lithium metal)", "280530": "Rare earths", "280540": "Mercury",
    "282520": "Lithium", "282530": "Vanadium", "282540": "Nickel", "282550": "Copper", "282560": "Germanium", "282570": "Molybdenum",
    "282580": "Antimony", "283691": "Lithium", "283692": "Strontium",
    "811212": "Beryllium", "811213": "Beryllium", "811219": "Beryllium", "811221": "Chromium", "811222": "Chromium", "811229": "Chromium",
    "811292": "Germanium, gallium, indium, vanadium, niobium, hafnium, rhenium (grouped)",
    "811299": "Germanium, gallium, indium, vanadium, niobium, hafnium, rhenium (grouped)",
}
CHAPTER = {"72": "Iron and steel", "74": "Copper", "75": "Nickel", "76": "Aluminium", "78": "Lead", "79": "Zinc", "80": "Tin"}
KEYWORDS = [("lithium", "Lithium"), ("cobalt", "Cobalt"), ("nickel", "Nickel"), ("copper", "Copper"), ("zinc", "Zinc"), ("lead", "Lead"),
            ("mangan", "Manganese"), ("chrom", "Chromium"), ("molybd", "Molybdenum"), ("tungst", "Tungsten"), ("vanad", "Vanadium"),
            ("german", "Germanium"), ("gallium", "Gallium"), ("indium", "Indium"), ("antimon", "Antimony"), ("titan", "Titanium"),
            ("zircon", "Zirconium"), ("tantal", "Tantalum"), ("niob", "Niobium"), ("rare-earth", "Rare earths"), ("cerium", "Rare earths"),
            ("silicon", "Silicon"), ("selen", "Selenium"), ("tellur", "Tellurium"), ("arsen", "Arsenic"), ("boron", "Boron (natural borates)"),
            ("mercur", "Mercury"), ("stront", "Strontium"), ("magnes", "Magnesium"), ("alumin", "Aluminium (bauxite)"), ("iron", "Iron ore"),
            ("phosph", "Phosphate rock"), ("fluor", "Fluorspar"), ("barium", "Barite")]


NAME_FIX = {"TUR": "Türkiye"}  # OECD's file has a broken character in this country name


def commodity(hs6, desc):
    if hs6 in CODE: return CODE[hs6]
    if hs6[:4] in HEADING: return HEADING[hs6[:4]]
    if hs6[:2] in CHAPTER: return CHAPTER[hs6[:2]]
    d = (desc or "").lower()
    for k, v in KEYWORDS:
        if k in d: return v
    return "Other inorganic chemicals"


def num(v):
    v = (v or "").strip()
    if re.fullmatch(r"-?\d+([.,]\d+)?", v):
        return float(v.replace(",", "."))
    return None


def dt(v):
    v = (v or "").strip()
    for f in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(v, f).date()
        except ValueError:
            pass
    return None


df = pd.read_excel(FILE, header=1, dtype=str, keep_default_na=False)
print("rows read", len(df))
rows = []
for i, r in enumerate(df.itertuples(index=False), start=3):  # spreadsheet row number (2 header rows)
    rows.append((r.Cou.strip(), NAME_FIX.get(r.Cou.strip(), r.Country.strip()),r.HS6.strip(), r.HS6.strip()[:4], r.HS_description.strip(), commodity(r.HS6.strip(), r.HS_description),
                 r.HS8.strip() or None, r.orig_leg_prod.strip() or None, r.type.strip(), r.tomx.strip() or None, int(r.year),
                 r.val.strip() or None, num(r.val), r.val_unit.strip() or None, r.val_condition.strip() or None, r.val_shared.strip() or None,
                 r.val_shared_products.strip() or None, r.dir.strip().lower() or None, r.dati.strip() or None, dt(r.dati), r.end.strip() or None,
                 dt(r.end), {"yes": True, "no": False}.get(r.temp.strip().lower()), r.exem.strip() or None, r.leg.strip() or None,
                 r.nod.strip() or None, r.link.strip() or None, r.host.strip() or None, r.agen.strip() or None, r.impl.strip() or None,
                 r.pom.strip() or None, r.add.strip() or None, i, SRC, TAG))

COLS = ("country_iso3, country_name, hs6, hs_heading, hs6_description, commodity, hs_national_code, product_as_in_law, measure_type, measure_key, "
        "year, value_text, value_numeric, value_unit, value_condition, value_shared, shared_products, direction_of_change, date_introduced_text, "
        "date_introduced, date_ending_text, date_ending, is_temporary, exemptions, legal_basis, document_name, document_link, agency_hosting, "
        "agency_in_charge, implementation, purpose, additional_info, source_row, source_system, created_by")
DDL = """
DROP TABLE IF EXISTS markets.export_restrictions;
CREATE TABLE markets.export_restrictions (
  export_restriction_id serial PRIMARY KEY,
  country_iso3 text NOT NULL, country_name text NOT NULL, hs6 text NOT NULL, hs_heading text NOT NULL, hs6_description text, commodity text NOT NULL,
  hs_national_code text, product_as_in_law text, measure_type text NOT NULL, measure_key text, year integer NOT NULL,
  value_text text, value_numeric numeric, value_unit text, value_condition text, value_shared text, shared_products text,
  direction_of_change text, date_introduced_text text, date_introduced date, date_ending_text text, date_ending date, is_temporary boolean,
  exemptions text, legal_basis text, document_name text, document_link text, agency_hosting text, agency_in_charge text, implementation text,
  purpose text, additional_info text, source_row integer NOT NULL, source_system text NOT NULL, created_by text NOT NULL,
  created_date timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON markets.export_restrictions (country_iso3, year);
CREATE INDEX ON markets.export_restrictions (commodity, year);
CREATE INDEX ON markets.export_restrictions (hs6);
COMMENT ON TABLE markets.export_restrictions IS 'OECD Inventory of Export Restrictions on Critical Raw Materials, 2009-2024 (HS2007 6-digit), one row per country x product x measure x year as published; commodity is OUR grouping of the HS code. Credit: OECD (2026), Inventory of Export Restrictions on Critical Raw Materials, OECD Data Explorer.';
GRANT SELECT ON markets.export_restrictions TO cm_app_readonly;
"""
DS = (SRC, "OECD Trade and Agriculture Directorate", "Inventory of Export Restrictions on Critical Raw Materials (2009-2024, HS2007 6-digit; Data Explorer update 25 Sep 2026)",
      "OECD Terms and Conditions - Data: any use including commercial, with credit", "https://www.oecd.org/en/about/terms-conditions.html", True,
      "OECD (2026), Inventory of Export Restrictions on Critical Raw Materials, OECD Data Explorer, https://data-explorer.oecd.org (dataflow DSD_QDD_TAD_EXP_RESTRIC@DF_QDD_TAD_EXP_RESTRIC), accessed 11 November 2026.",
      True, "Cleared: OECD Terms & Conditions section 3 Data, Permitted Use (checked 2026-11-11); credit required and must be passed on in any sub-licence.",
      "Covers 60 countries with at least one restriction; 22 countries were reviewed with none found (incl. most EU members, UK, Korea, Norway). Measures known to OECD only; latest data year 2024. Some legal-document titles have broken accented characters in OECD's file. Commodity column is our grouping of HS codes.",
      r"D:\CriticalMineralsDB\Documents\Licence_Evidence\OECD_EXPORT_RESTRICTIONS\EVIDENCE.md", datetime.date(2026, 11, 11), True, TAG)

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute(DDL)
execute_values(c, f"INSERT INTO markets.export_restrictions ({COLS}) VALUES %s", rows, page_size=5000)
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text,
             is_loaded, licence_status, caveats, evidence_location, evidence_date, is_active, created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT (source_system) DO UPDATE SET publisher = EXCLUDED.publisher, dataset_name = EXCLUDED.dataset_name, licence = EXCLUDED.licence,
             licence_url = EXCLUDED.licence_url, attribution_text = EXCLUDED.attribution_text, is_loaded = true, licence_status = EXCLUDED.licence_status,
             caveats = EXCLUDED.caveats, evidence_location = EXCLUDED.evidence_location, evidence_date = EXCLUDED.evidence_date""", DS)
c.execute("SELECT count(*), count(DISTINCT country_iso3), count(DISTINCT hs6), min(year), max(year), count(value_numeric), count(date_introduced) FROM markets.export_restrictions")
print("loaded rows, countries, hs6, years, numeric values, parsed dates:", c.fetchone())
c.execute("SELECT commodity, count(DISTINCT hs6), count(*) FROM markets.export_restrictions GROUP BY 1 ORDER BY 3 DESC"); print("commodities:", c.fetchall())
c.execute("""SELECT country_name, measure_type, count(DISTINCT hs6) FROM markets.export_restrictions WHERE year = 2024 AND commodity IN ('Cobalt','Lithium','Rare earths','Graphite')
             GROUP BY 1, 2 ORDER BY 1, 2"""); print("2024 Co/Li/REE/graphite:", c.fetchall())
c.execute("SELECT count(*) FROM markets.export_restrictions WHERE commodity = 'Other inorganic chemicals'"); print("unmatched chemicals rows:", c.fetchone()[0])
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
