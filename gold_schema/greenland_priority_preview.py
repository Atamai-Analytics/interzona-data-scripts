"""PREVIEW ONLY (read-only): compare current Greenland method choice with a technique-by-element-group preference scheme."""
import os, collections
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
RANK = {  # lower wins; unlisted technique = 9
 "MAJOR":  ["XRF_BEAD", "ICPOES_FUS", "XRF_PELLET", "ICP_ACID", "XRF_LEGACY", "INAA"],
 "INAA_TRACE": ["ICPMS_FUS", "INAA", "ICPOES_FUS", "ICP_ACID", "XRF_BEAD", "XRF_PELLET", "XRF_LEGACY"],
 "XRF_TRACE":  ["ICPMS_FUS", "ICPOES_FUS", "XRF_BEAD", "XRF_PELLET", "ICP_ACID", "XRF_LEGACY", "INAA"],
 "PRECIOUS": ["FIRE_ASSAY", "ICPMS_FUS", "INAA", "ICPOES_FUS"],
}
GROUP = {}
for s in "Sc Cr Co Cs Hf Ta Th U As Sb Se Br La Ce Nd Sm Eu Tb Yb Lu Ho Tm W Hg".split(): GROUP[s] = "INAA_TRACE"
for s in "Ba Sr Rb Zr Y Nb Zn Ni Cu V Pb Ga Mo Sn Be Li Tl Bi Cd Pr Gd Dy Er".split(): GROUP[s] = "XRF_TRACE"
for s in "Au Ag Pt Pd Ir Rh Ru Os Re".split(): GROUP[s] = "PRECIOUS"
pkg_tech = {code: t for t, codes in TECH.items() for code in codes}
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 0")
P = "geochem.analytical_results_greenland_geus"; K = "geochem.result_classifications_greenland_geus"
c.execute(f"""
SELECT r.sample_id, r.analyte_id, r.analyte_symbol, a.is_oxide, p.package_code, r.package_id, w.priority,
  avg(CASE WHEN a.is_oxide OR (NOT a.is_element AND NOT a.is_oxide) THEN CASE r.unit_code WHEN '%' THEN r.value WHEN 'ppm' THEN r.value/10000.0 WHEN 'ppb' THEN r.value/1e7 END
       ELSE CASE r.unit_code WHEN 'ppm' THEN r.value WHEN '%' THEN r.value*10000.0 WHEN 'ppb' THEN r.value/1000.0 END END) v
FROM {P} r JOIN geochem.analytes a ON a.analyte_id = r.analyte_id JOIN geochem.analytical_packages p ON p.package_id = r.package_id
JOIN geochem.package_wide_rules w ON w.package_id = r.package_id JOIN {K} k ON k.result_id = r.result_id AND k.source_system = r.source_system
WHERE r.is_active AND r.value IS NOT NULL AND k.use_in_statistics AND w.basis = 'T' AND r.analyte_symbol <> 'C'
GROUP BY 1,2,3,4,5,6,7""")
combos = collections.defaultdict(list)
for sid, aid, sym, ox, code, pid, pr, v in c.fetchall():
    combos[(sid, aid)].append((sym, ox, code, pid, pr, float(v) if v is not None else None))
changed = collections.Counter(); multi = collections.Counter(); sizeable = collections.Counter(); ties_before = 0; ties_after = 0; total_multi = 0
bygrp = collections.Counter(); chg_pairs = collections.Counter(); relchg = collections.defaultdict(list)
def grp(sym, ox): return "MAJOR" if ox else GROUP.get(sym, "OTHER")
def newrank(g_, code):
    if g_ == "OTHER": return None
    t = pkg_tech.get(code)
    lst = RANK[g_]
    return lst.index(t) + 1 if t in lst else 9
for (sid, aid), lst in combos.items():
    if len(lst) < 2: continue
    total_multi += 1
    sym, ox = lst[0][0], lst[0][1]; G = grp(sym, ox)
    cur = min(lst, key=lambda x: (x[4], x[3]))
    if G == "OTHER": new = cur
    else: new = min(lst, key=lambda x: (newrank(G, x[2]), x[3]))
    bygrp[G] += 1
    if cur[3] != new[3]:
        changed[G] += 1; multi[(sym + ("(ox)" if ox else ""))] += 1; chg_pairs[(cur[2], new[2])] += 1
        if cur[5] and new[5] and cur[5] > 0: relchg[G].append(new[5] / cur[5])
print("combos with >1 total-basis package:", total_multi)
print("by group:", dict(bygrp)); print("winner changes by group:", dict(changed), "total", sum(changed.values()))
print("top elements changed:", multi.most_common(15))
print("top package switches (from -> to):", chg_pairs.most_common(8))
import statistics
for G, v in relchg.items(): print(G, "median new/old value", round(statistics.median(v), 2), "| share differing >25%:", round(100 * sum(1 for x in v if x > 1.25 or x < 0.8) / len(v)), "%")
uncl = [code for code in {x[2] for lst in combos.values() for x in lst} if code not in pkg_tech]
print("T packages with results but no technique assigned (stay on default priority):", sorted(uncl))
