"""USGS NGDB wide-table assumptions (Option A, agreed 2026-10-13).

geochem.source_package_rules  per-source basis/priority for the USGS 'UNK-*' packages (shared packages elsewhere are untouched) and, since
                              2026-11-13, the 'USGS-NGDB-*' sediment/soil packages (one per USGS method; load_usgs_ngdb_sedsoil.py)
geochem.package_technique     + USGS_* technique per package
geochem.technique_rank        + USGS_* ranks per element group (emission spectrography always last)
Basis: the NGDB names partial digestions with a P suffix (AES_AR_P ...), so non-P instrumental packages are treated as total/near-total.
Emission spectrography (UNK-USGS-ES, semi-quantitative) is Total but ranked last; UNK-UNK-UNK stays Partial and last.
Usage: python setup_usgs_priorities.py   (idempotent for the USGS rows)
"""
import os
import psycopg2

ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
SRC = "USA_USGS_NGDB"
# package_code: (basis, default priority, technique or None, note)
PKG = {
 "UNK-ICP-MS": ("T", 1, "USGS_ICP_MS", "ICP-MS, no P suffix = total/near-total (NGDB MS_HF/MS_ST)"),
 "UNK-ICP-AES": ("T", 2, "USGS_ICP_AES", "ICP-AES, no P suffix = fusion/four-acid/sinter (NGDB AES_Fuse/AES_HF/AES_ST)"),
 "UNK-XRF": ("T", 3, "USGS_XRF", "XRF pressed pellet"),
 "UNK-AAS": ("T", 4, "USGS_AAS", "AAS, no P suffix = total digestion assumed"),
 "UNK-INAA": ("T", 5, "USGS_INAA", "INAA, no digestion"),
 "UNK-DNA": ("T", 5, "USGS_DNA", "delayed neutron counting (U, Th)"),
 "UNK-FA": ("T", 5, "USGS_FIRE_ASSAY", "fire assay"),
 "UNK-MSC": ("T", 6, "USGS_WET", "classical wet chemistry"),
 "UNK-TITR": ("T", 6, "USGS_WET", "classical wet chemistry"),
 "UNK-GRAV": ("T", 6, "USGS_WET", "classical wet chemistry"),
 "UNK-COLOR": ("T", 6, "USGS_WET", "classical wet chemistry"),
 "UNK-ISE": ("T", 6, "USGS_WET", "classical wet chemistry"),
 "UNK-USGS-ES": ("T", 9, "USGS_ES", "emission spectrography burns the whole sample (total) but is semi-quantitative: ranked last"),
 "UNK-UNK-UNK": ("P", 9, None, "lab, method and digestion unknown: partial column, ranked last"),
}
RANK = {  # lower wins; techniques not listed rank 9; USGS_ES is 10 everywhere
 "MAJOR": ["USGS_XRF", "USGS_ICP_AES", "USGS_WET", "USGS_AAS", "USGS_ICP_MS", "USGS_INAA"],
 "INAA_TRACE": ["USGS_ICP_MS", "USGS_INAA", "USGS_DNA", "USGS_ICP_AES", "USGS_XRF", "USGS_AAS"],
 "XRF_TRACE": ["USGS_ICP_MS", "USGS_ICP_AES", "USGS_XRF", "USGS_AAS", "USGS_INAA"],
 "PRECIOUS": ["USGS_FIRE_ASSAY", "USGS_ICP_MS", "USGS_INAA", "USGS_AAS", "USGS_ICP_AES"],
}
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS geochem.source_package_rules (
  source_system varchar(40) NOT NULL, package_id integer NOT NULL, basis char(1) NOT NULL CHECK (basis IN ('T','P')), priority integer NOT NULL, note text,
  PRIMARY KEY (source_system, package_id))""")
c.execute("DELETE FROM geochem.source_package_rules WHERE source_system = %s", (SRC,))
c.execute("DELETE FROM geochem.package_technique WHERE technique LIKE 'USGS\\_%'")
c.execute("DELETE FROM geochem.technique_rank WHERE technique LIKE 'USGS\\_%'")
for code, (basis, prio, tech, note) in PKG.items():
    c.execute("SELECT package_id FROM geochem.analytical_packages WHERE package_code = %s", (code,))
    rows = c.fetchall(); assert len(rows) == 1, (code, rows)
    pid = rows[0][0]
    c.execute("INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note) VALUES (%s,%s,%s,%s,%s)", (SRC, pid, basis, prio, note))
    if tech:
        c.execute("INSERT INTO geochem.package_technique (package_id, technique, note) VALUES (%s,%s,%s) ON CONFLICT (package_id) DO UPDATE SET technique = EXCLUDED.technique, note = EXCLUDED.note", (pid, tech, "USGS NGDB assumptions 2026-10-13"))
# Sediment / soil packages (load_usgs_ngdb_sedsoil.py, one per USGS method 'USGS-NGDB-<amethod>'): basis by the _P rule, priority from the
# package's package_wide_rules row (set by the loader), technique family from the method code.
def technique(am):
    if am.startswith("MS_"): return "USGS_ICP_MS"
    if am.startswith("AES_"): return "USGS_ICP_AES"
    if am.startswith(("WDX", "EDX")): return "USGS_XRF"
    if am.startswith("NA_"): return "USGS_INAA"
    if am == "DN": return "USGS_DNA"
    if am.startswith("FA_"): return "USGS_FIRE_ASSAY"
    if am.startswith("ES_"): return "USGS_ES"
    if am.startswith(("AA_", "TC_")): return "USGS_AAS"
    return "USGS_WET"   # colorimetry, ISE, titration, fluorometry, combustion, gravimetry, ion chromatography
c.execute("""SELECT p.package_id, p.package_code, w.priority FROM geochem.analytical_packages p JOIN geochem.package_wide_rules w USING (package_id)
             WHERE p.package_code LIKE 'USGS-NGDB-%'""")
for pid, code, prio in c.fetchall():
    am = code[len("USGS-NGDB-"):]
    basis = "P" if am.endswith("_P") else "T"
    c.execute("INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note) VALUES (%s,%s,%s,%s,%s)",
              (SRC, pid, basis, prio, "USGS NGDB sediment/soil method " + am))
    c.execute("INSERT INTO geochem.package_technique (package_id, technique, note) VALUES (%s,%s,%s) ON CONFLICT (package_id) DO UPDATE SET technique = EXCLUDED.technique, note = EXCLUDED.note",
              (pid, technique(am), "USGS NGDB sediment/soil 2026-11-13"))
for grp, lst in RANK.items():
    for i, t in enumerate(lst, 1):
        c.execute("INSERT INTO geochem.technique_rank VALUES (%s,%s,%s)", (grp, t, i))
    c.execute("INSERT INTO geochem.technique_rank VALUES (%s,%s,%s)", (grp, "USGS_ES", 10))
g.commit()
c.execute("SELECT count(*) FROM geochem.source_package_rules WHERE source_system = %s", (SRC,)); a = c.fetchone()[0]
c.execute("SELECT count(*) FROM geochem.package_technique WHERE technique LIKE 'USGS\\_%'"); b = c.fetchone()[0]
c.execute("SELECT count(*) FROM geochem.technique_rank WHERE technique LIKE 'USGS\\_%'"); d = c.fetchone()[0]
print("source_package_rules", a, "| package_technique(USGS)", b, "| technique_rank(USGS)", d)
