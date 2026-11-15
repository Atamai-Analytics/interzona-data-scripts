"""Add the full country name to GEMAS sample comments ('GEMAS Ap AUS; country Austria; ...'). GEMAS uses its own 3-letter codes - the
mapping below was checked against the sample positions (2026-11-14). NOTE: AUS = Austria, not Australia. Idempotent."""
import os, psycopg2
GEMAS_COUNTRY = {"AUS": "Austria", "BEL": "Belgium", "BOS": "Bosnia and Herzegovina", "BUL": "Bulgaria", "CRO": "Croatia", "CYP": "Cyprus",
                 "CZR": "Czechia", "DEN": "Denmark", "EST": "Estonia", "FIN": "Finland", "FOM": "North Macedonia", "FRA": "France", "GER": "Germany",
                 "HEL": "Greece", "HUN": "Hungary", "IRL": "Ireland", "ITA": "Italy", "LAV": "Latvia", "LIT": "Lithuania", "LUX": "Luxembourg",
                 "MON": "Montenegro", "NEL": "Netherlands", "NOR": "Norway", "POL": "Poland", "PTG": "Portugal", "SIL": "Switzerland",
                 "SKA": "Slovakia", "SLO": "Slovenia", "SPA": "Spain", "SRB": "Serbia", "SWE": "Sweden", "UKR": "Ukraine", "UNK": "United Kingdom"}
if __name__ == "__main__":
    HERE = os.path.dirname(os.path.abspath(__file__)); ENV = {}
    for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
    g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
    c = g.cursor(); n = 0
    for code, name in GEMAS_COUNTRY.items():
        c.execute("""UPDATE geochem.samples SET comments = regexp_replace(comments, '^(GEMAS (?:Ap|Gr) ' || %s || ');', E'\\1; country ' || %s || ';')
                     WHERE source_system = 'EUROPE_GEMAS' AND comments ~ ('^GEMAS (Ap|Gr) ' || %s || ';') AND comments NOT LIKE '%%; country %%'""", (code, name, code))
        n += c.rowcount
    g.commit(); print("updated", n)
