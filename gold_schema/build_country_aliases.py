"""core.country_aliases: one lookup from any country name used in interzona_cm to its ISO3 code, so USGS supply tables, BACI trade,
World Bank governance indicators, facilities and projects can be joined by country. Function core.iso3_of(text) returns the code (NULL if unknown).

Sources (all already in the database) + a short hand-made list for USGS Mineral Commodity Summaries spellings that match nothing else.
Aggregates ("Other countries", "World total") are deliberately not mapped. Re-runnable: rebuilds the table each time.
Usage: python -P build_country_aliases.py [--dry]
"""
import os, sys
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")

# USGS MCS 2026 spellings not found in the jurisdiction, BACI or boundary lists (checked 2026-11-20).
MANUAL = {
    "Bolivia": "BOL", "Burma": "MMR", "Congo (Kinshasa)": "COD", "Congo (Brazzaville)": "COG", "Côte d’Ivoire": "CIV", "Côte d'Ivoire": "CIV",
    "Korea, North": "PRK", "Korea, Republic of": "KOR", "Laos": "LAO", "Russia": "RUS", "Tanzania": "TZA", "Turkey": "TUR", "Türkiye": "TUR",
    "United States": "USA", "Vietnam": "VNM", "DRC": "COD", "DR Congo": "COD", "South Korea": "KOR", "North Korea": "PRK", "Iran": "IRN",
    "Syria": "SYR", "Venezuela": "VEN", "Moldova": "MDA", "Macedonia": "MKD", "Swaziland": "SWZ", "Eswatini": "SWZ", "Czech Republic": "CZE", "Democratic Republic of Congo": "COD", "Korea": "KOR",  # IEA spellings (2026-11-21)
}

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("""CREATE TEMP TABLE a (alias text, iso3 text, source text)""")
c.execute("""INSERT INTO a SELECT name, iso_code3, 'core.jurisdictions' FROM core.jurisdictions WHERE level = 'COUNTRY' AND iso_code3 ~ '^[A-Z]{3}$'
             UNION ALL SELECT official_name, iso_code3, 'core.jurisdictions (official)' FROM core.jurisdictions WHERE level = 'COUNTRY' AND iso_code3 ~ '^[A-Z]{3}$' AND official_name IS NOT NULL
             UNION ALL SELECT country_name, iso3, 'markets.trade_countries' FROM markets.trade_countries WHERE iso3 ~ '^[A-Z]{3}$'
             UNION ALL SELECT name, iso_a3, 'core.country_boundaries' FROM core.country_boundaries WHERE iso_a3 ~ '^[A-Z]{3}$'
             UNION ALL SELECT name_long, iso_a3, 'core.country_boundaries (long)' FROM core.country_boundaries WHERE iso_a3 ~ '^[A-Z]{3}$'""")
c.executemany("INSERT INTO a VALUES (%s, %s, 'manual (USGS MCS spellings)')", list(MANUAL.items()))
c.execute("""SELECT lower(alias), string_agg(DISTINCT iso3, ',') FROM a GROUP BY 1 HAVING count(DISTINCT iso3) > 1""")
clash = c.fetchall()
if clash: sys.exit(f"names mapping to two codes - fix first: {clash}")
c.execute("""SELECT count(DISTINCT lower(alias)), count(DISTINCT iso3) FROM a"""); print("aliases, codes", c.fetchone())
# coverage checks
c.execute("""SELECT string_agg(DISTINCT country, ' | ') FROM markets.supply_concentration_countries s
             WHERE NOT EXISTS (SELECT 1 FROM a WHERE lower(a.alias) = lower(s.country))"""); print("USGS names still unmatched:", c.fetchone()[0])
c.execute("""SELECT count(*) FROM (SELECT DISTINCT country_name FROM core.occurrences o WHERE country_name IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM a WHERE lower(a.alias) = lower(o.country_name))) x"""); print("occurrence names unmatched:", c.fetchone()[0])
if "--dry" in sys.argv: sys.exit()
c.execute("""CREATE TABLE IF NOT EXISTS core.country_aliases (alias_lower text PRIMARY KEY, alias text NOT NULL, iso3 char(3) NOT NULL, source text NOT NULL,
             created_date timestamptz DEFAULT now())""")
c.execute("TRUNCATE core.country_aliases")
c.execute("""INSERT INTO core.country_aliases (alias_lower, alias, iso3, source)
             SELECT DISTINCT ON (lower(alias)) lower(alias), alias, iso3, source FROM a ORDER BY lower(alias), source""")
print("rows", c.rowcount)
c.execute("""CREATE OR REPLACE FUNCTION core.iso3_of(name text) RETURNS char(3) LANGUAGE sql STABLE AS
             $$ SELECT iso3 FROM core.country_aliases WHERE alias_lower = lower(trim(name)) $$""")
c.execute("COMMENT ON TABLE core.country_aliases IS 'Country name -> ISO3 for joining USGS, BACI, WGI, facilities, projects; build_country_aliases.py'")
c.execute("GRANT SELECT ON core.country_aliases TO cm_app_readonly"); c.execute("GRANT EXECUTE ON FUNCTION core.iso3_of(text) TO cm_app_readonly")
g.commit(); print("COMMITTED")
