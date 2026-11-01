"""Create the technique-by-element-group method preference tables used by build_chem_wide.py for GREENLAND_GEUS.

geochem.package_technique(package_id, technique)            which technique family each lab package is
geochem.analyte_groups(analyte_symbol, analyte_group)        trace-element groups (major oxides = analytes.is_oxide, group MAJOR)
geochem.technique_rank(analyte_group, technique, rank)       lower rank wins; a technique not listed for a group ranks 9
Total-basis (T) results only; partial-leach (P) packages keep package_wide_rules.priority.  Chromium is in XRF_TRACE (user decision 2026-10-12).
Usage: python setup_greenland_priorities.py     (idempotent: rebuilds the three small tables)
"""
import os
import psycopg2

ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
TECH = {
 "XRF_BEAD": ["ACTLABS-FUS-XRF"],
 "XRF_PELLET": ["GEUS_ROCK-FUS-XRF", "ACTLABS-PWD-XRF", "GGU-CPH-PWD-XRF", "SGAB-XRF", "CLEGG-PWD-XRF"],
 "XRF_LEGACY": ["RIS-NON-XPU", "RIS-NON-XCD"],
 "ICPMS_FUS": ["ACTLABS-FUS-ICP-MS", "ACTLABS-4FUS-ICP-MS", "GEUS_ROCK-NAF-ICP-MS"],
 "ICPOES_FUS": ["ACTLABS-FUS-ICP", "ACTLABS-4FUS-ICP", "ACTLABS-4FUS-ICP-OES", "ACME-4FUS-ICP", "ACME-4A/MS"],
 "ICP_ACID": ["ACTLABS-4AC-ICP"],
 "INAA": ["ACTLABS-NON-INAA", "CLEGG-NON-INAA", "RIS-NON-INAA", "ACME-INAA", "ACME-G5A-INAA", "VTT-NON-INAA", "RIS-NON-DNC"],
 "FIRE_ASSAY": ["ACTLABS-FA-ICP-MS", "ACTLABS-FA-ICP-OES", "ACTLABS-FA-ICP", "ACTLABS-FA-INAA", "CLEGG-FA-INAA", "CHEMEX-FA-ICP", "UNK-FA", "CLEGG-AR-DCP"],
}
RANK = {
 "MAJOR": ["XRF_BEAD", "ICPOES_FUS", "XRF_PELLET", "ICP_ACID", "XRF_LEGACY", "INAA"],
 "INAA_TRACE": ["ICPMS_FUS", "INAA", "ICPOES_FUS", "ICP_ACID", "XRF_BEAD", "XRF_PELLET", "XRF_LEGACY"],
 "XRF_TRACE": ["ICPMS_FUS", "ICPOES_FUS", "XRF_BEAD", "XRF_PELLET", "ICP_ACID", "XRF_LEGACY", "INAA"],
 "PRECIOUS": ["FIRE_ASSAY", "ICPMS_FUS", "INAA", "ICPOES_FUS"],
}
GROUP = {}
for s in "Sc Co Cs Hf Ta Th U As Sb Se Br La Ce Nd Sm Eu Tb Yb Lu Ho Tm W Hg".split(): GROUP[s] = "INAA_TRACE"
for s in "Cr Ba Sr Rb Zr Y Nb Zn Ni Cu V Pb Ga Mo Sn Be Li Tl Bi Cd Pr Gd Dy Er".split(): GROUP[s] = "XRF_TRACE"
for s in "Au Ag Pt Pd Ir Rh Ru Os Re".split(): GROUP[s] = "PRECIOUS"

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS geochem.package_technique (package_id integer PRIMARY KEY, technique varchar(30) NOT NULL, note text)""")
c.execute("""CREATE TABLE IF NOT EXISTS geochem.analyte_groups (analyte_symbol varchar(10) PRIMARY KEY, analyte_group varchar(30) NOT NULL)""")
c.execute("""CREATE TABLE IF NOT EXISTS geochem.technique_rank (analyte_group varchar(30) NOT NULL, technique varchar(30) NOT NULL, rank integer NOT NULL, PRIMARY KEY (analyte_group, technique))""")
for t in ("package_technique", "analyte_groups", "technique_rank"):
    c.execute(f"DELETE FROM geochem.{t}")
n = 0
for tech, codes in TECH.items():
    for code in codes:
        c.execute("SELECT package_id FROM geochem.analytical_packages WHERE package_code = %s", (code,))
        row = c.fetchall()
        assert len(row) == 1, (code, row)
        c.execute("INSERT INTO geochem.package_technique (package_id, technique, note) VALUES (%s,%s,%s)", (row[0][0], tech, "Greenland method preference scheme 2026-10-12")); n += 1
for sym, grp in GROUP.items():
    c.execute("INSERT INTO geochem.analyte_groups VALUES (%s,%s)", (sym, grp))
for grp, lst in RANK.items():
    for i, t in enumerate(lst, 1):
        c.execute("INSERT INTO geochem.technique_rank VALUES (%s,%s,%s)", (grp, t, i))
g.commit()
c.execute("SELECT count(*) FROM geochem.package_technique"); a = c.fetchone()[0]
c.execute("SELECT count(*) FROM geochem.analyte_groups"); b = c.fetchone()[0]
c.execute("SELECT count(*) FROM geochem.technique_rank"); d = c.fetchone()[0]
print("package_technique", a, "| analyte_groups", b, "| technique_rank", d, "| Cr group:", GROUP["Cr"])
