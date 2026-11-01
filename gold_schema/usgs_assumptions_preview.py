"""PREVIEW ONLY (read-only): USGS wide-table assumptions - basis and technique per UNK-* package, effect on results by basis and on method conflicts."""
import os, collections, statistics
import psycopg2
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
# package_code -> (technique, proposed basis)
PROP = {
 "UNK-XRF": ("XRF", "T"), "UNK-ICP-MS": ("ICP_MS", "T"), "UNK-ICP-AES": ("ICP_AES", "T"), "UNK-INAA": ("INAA", "T"), "UNK-DNA": ("DNA", "T"),
 "UNK-FA": ("FIRE_ASSAY", "T"), "UNK-AAS": ("AAS", "T"), "UNK-USGS-ES": ("ES", "T"),
 "UNK-MSC": ("WET", "T"), "UNK-TITR": ("WET", "T"), "UNK-GRAV": ("WET", "T"), "UNK-COLOR": ("WET", "T"), "UNK-ISE": ("WET", "T"),
}  # everything else (P-suffixed packages, UNK-UNK-UNK, CV, FLOUR, Energy Geochemistry groups, tiny ones) stays partial / unknown
RANK = {
 "MAJOR": ["XRF", "ICP_AES", "WET", "AAS", "ICP_MS", "INAA"],
 "INAA_TRACE": ["ICP_MS", "INAA", "DNA", "ICP_AES", "XRF", "AAS"],
 "XRF_TRACE": ["ICP_MS", "ICP_AES", "XRF", "AAS", "INAA"],
 "PRECIOUS": ["FIRE_ASSAY", "ICP_MS", "INAA", "AAS", "ICP_AES"],
}
GROUP = {}
for s in "Sc Co Cs Hf Ta Th U As Sb Se Br La Ce Nd Sm Eu Tb Yb Lu Ho Tm W Hg".split(): GROUP[s] = "INAA_TRACE"
for s in "Cr Ba Sr Rb Zr Y Nb Zn Ni Cu V Pb Ga Mo Sn Be Li Tl Bi Cd Pr Gd Dy Er".split(): GROUP[s] = "XRF_TRACE"
for s in "Au Ag Pt Pd Ir Rh Ru Os Re".split(): GROUP[s] = "PRECIOUS"
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 0")
P = "geochem.analytical_results_usa_usgs_ngdb"; K = "geochem.result_classifications_usa_usgs_ngdb"
c.execute(f"""
SELECT r.sample_id, r.analyte_id, r.analyte_symbol, a.is_oxide, p.package_code, r.package_id, w.basis, w.priority, count(*) n,
  avg(CASE WHEN a.is_oxide OR (NOT a.is_element AND NOT a.is_oxide) THEN CASE r.unit_code WHEN '%' THEN r.value WHEN 'ppm' THEN r.value/10000.0 WHEN 'ppb' THEN r.value/1e7 END
       ELSE CASE r.unit_code WHEN 'ppm' THEN r.value WHEN '%' THEN r.value*10000.0 WHEN 'ppb' THEN r.value/1000.0 END END) v
FROM {P} r JOIN geochem.analytes a ON a.analyte_id = r.analyte_id JOIN geochem.analytical_packages p ON p.package_id = r.package_id
JOIN geochem.package_wide_rules w ON w.package_id = r.package_id JOIN {K} k ON k.result_id = r.result_id AND k.source_system = r.source_system
WHERE r.is_active AND r.value IS NOT NULL AND k.use_in_statistics AND r.analyte_symbol <> 'C'
GROUP BY 1,2,3,4,5,6,7,8""")
rows = c.fetchall()
print("detected (sample, analyte, package) rows:", len(rows))
cur_basis = collections.Counter(); new_basis = collections.Counter()
for sid, aid, sym, ox, code, pid, basis, pr, n, v in rows:
    cur_basis[basis] += n
    nb = PROP[code][1] if code in PROP else basis
    new_basis[nb] += n
print("detected results by basis  current:", dict(cur_basis), "| proposed:", dict(new_basis))
def grp(sym, ox): return "MAJOR" if ox else GROUP.get(sym, "OTHER")
def newrank(G, code):
    t = PROP.get(code, (None,))[0]; lst = RANK[G]
    return lst.index(t) + 1 if t in lst else 9
DEFAULT_PRIO = {"UNK-ICP-MS": 1, "UNK-ICP-AES": 2, "UNK-XRF": 3, "UNK-AAS": 4, "UNK-INAA": 5, "UNK-DNA": 5, "UNK-FA": 5, "UNK-MSC": 6, "UNK-TITR": 6, "UNK-GRAV": 6, "UNK-COLOR": 6, "UNK-ISE": 6, "UNK-USGS-ES": 9}
combos = collections.defaultdict(list)
for sid, aid, sym, ox, code, pid, basis, pr, n, v in rows:
    nb = PROP[code][1] if code in PROP else basis
    combos[(sid, aid, nb)].append((sym, ox, code, pid, DEFAULT_PRIO.get(code, pr), float(v) if v is not None else None))
multi = changed_vs_cur = 0; ties = 0; ch_by = collections.Counter(); relchg = []; bygrp = collections.Counter(); es_only = 0
for key, lst in combos.items():
    if len(lst) < 2: continue
    multi += 1
    sym, ox = lst[0][0], lst[0][1]; G = grp(sym, ox); bygrp[G] += 1
    win = min(lst, key=lambda x: (newrank(G, x[2]) if G != "OTHER" else x[4], x[3]))
    if all(x[2] == "UNK-USGS-ES" for x in lst[:1]) and win[2] == "UNK-USGS-ES": es_only += 1
    # compare with what the unmodified default would choose among same candidates (default priority incl. ES last)
    base = min(lst, key=lambda x: (x[4], x[3]))
    if base[3] != win[3]:
        changed_vs_cur += 1; ch_by[sym + ("(ox)" if ox else "")] += 1
        if base[5] and win[5] and base[5] > 0: relchg.append(win[5] / base[5])
print("combos with >1 package on the same basis:", multi, "| by group:", dict(bygrp))
print("winner differs from a plain package-priority rule:", changed_vs_cur, "| top elements:", ch_by.most_common(10))
if relchg: print("share of those with values differing >25%:", round(100 * sum(1 for x in relchg if x > 1.25 or x < 0.8) / len(relchg)), "%")
# how many samples/analytes rely ONLY on ES (semi-quantitative) values
only_es = collections.Counter()
for key, lst in combos.items():
    if all(x[2] == "UNK-USGS-ES" for x in lst): only_es[key[2]] += 1
print("sample-analyte values that exist ONLY from emission spectrography (so ES is used even though it is last):", sum(only_es.values()))
