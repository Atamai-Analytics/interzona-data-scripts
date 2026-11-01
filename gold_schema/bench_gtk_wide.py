import os, time, statistics
import psycopg2

ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor()
c.execute("SET statement_timeout = 0")
SRC = "FINLAND_GTK_ROCK"


def timeit(label, sql, params=None, runs=3, show=True):
    ts = []; res = None
    for _ in range(runs):
        t0 = time.perf_counter(); c.execute(sql, params); res = c.fetchall(); ts.append((time.perf_counter() - t0) * 1000)
    print(f"{label:34s} min {min(ts):9.1f} ms  median {statistics.median(ts):9.1f} ms  rows {len(res)}  first {res[0] if (show and res) else ''}", flush=True)
    return res


# Q1 graphite-style: non-carbonate C >= 1% AND S >= 1%
long1 = f"""SELECT count(*) FROM (SELECT r.sample_id FROM geochem.analytical_results r
 JOIN geochem.analytical_packages p ON p.package_id = r.package_id
 JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
 WHERE r.source_system = '{SRC}' AND k.use_in_statistics AND ((p.package_code = '816L' AND r.value >= 1) OR (p.package_code = '175X' AND r.analyte_symbol = 'S' AND r.value >= 10000))
 GROUP BY r.sample_id HAVING count(DISTINCT p.package_code) = 2) x"""
wide1 = f"SELECT count(*) FROM geochem.sample_chemistry_wide WHERE source_system = '{SRC}' AND c_noncarb_pct >= 1 AND s_t >= 10000"
print("Q1 graphite/sulfide filter")
a = timeit("  long (816L C + 175X S)", long1); b = timeit("  wide", wide1)

# Q2 REE median by lithology
long2 = f"""SELECT lit.lithology_name, r.analyte_symbol, count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value)
 FROM geochem.analytical_results r JOIN geochem.analytical_packages p ON p.package_id = r.package_id
 JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
 JOIN geochem.lithology_observations lo ON lo.sample_id = r.sample_id JOIN geochem.lithology lit ON lit.lithology_id = lo.lithology_id
 WHERE r.source_system = '{SRC}' AND p.package_code = '308M' AND r.analyte_symbol IN ('La','Ce','Nd','Y') AND k.use_in_statistics
 GROUP BY 1, 2 ORDER BY 1, 2"""
wide2 = f"""SELECT lithology_name, count(la_t), percentile_cont(0.5) WITHIN GROUP (ORDER BY la_t), percentile_cont(0.5) WITHIN GROUP (ORDER BY ce_t),
 percentile_cont(0.5) WITHIN GROUP (ORDER BY nd_t), percentile_cont(0.5) WITHIN GROUP (ORDER BY y_t) FROM geochem.sample_chemistry_wide WHERE source_system = '{SRC}' GROUP BY 1 ORDER BY 1"""
print("Q2 REE medians by lithology")
timeit("  long", long2, show=False); timeit("  wide", wide2, show=False)

# Q3 spatial: Nb > 20 ppm within 25 km of Sodankyla
long3 = f"""SELECT count(DISTINCT s.sample_id) FROM geochem.samples s JOIN geochem.analytical_results r ON r.sample_id = s.sample_id AND r.source_system = '{SRC}'
 JOIN geochem.analytical_packages p ON p.package_id = r.package_id JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
 WHERE s.source_system = '{SRC}' AND ST_DWithin(s.geog, ST_SetSRID(ST_MakePoint(26.59, 67.42), 4326)::geography, 25000)
 AND r.analyte_symbol = 'Nb' AND p.package_code = '308M' AND k.use_in_statistics AND r.value > 20"""
wide3 = f"""SELECT count(*) FROM geochem.sample_chemistry_wide WHERE source_system = '{SRC}' AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(26.59, 67.42), 4326)::geography, 25000) AND nb_t > 20"""
print("Q3 spatial 25 km + Nb filter")
timeit("  long", long3); timeit("  wide", wide3)

# Q4 CLR-style matrix fetch: 22 elements x 5000 samples
c.execute(f"SELECT sample_id FROM geochem.sample_chemistry_wide WHERE source_system = '{SRC}' ORDER BY sample_id LIMIT 5000")
ids = [r[0] for r in c.fetchall()]
syms = ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Y", "Th", "U", "Nb", "Ta", "Zr", "Hf", "Sc"]
long4 = "SELECT sample_id, analyte_symbol, value, unit_code FROM geochem.analytical_results WHERE sample_id = ANY(%s) AND analyte_symbol = ANY(%s) AND value > 0"
wide4 = "SELECT sample_id, " + ", ".join(s.lower() + "_t" for s in syms) + " FROM geochem.sample_chemistry_wide WHERE sample_id = ANY(%s)"
print("Q4 matrix fetch 22 elements x 5000 samples (rows returned differ: long = analyte rows, wide = samples)")
timeit("  long", long4, (ids, syms), show=False); timeit("  wide", wide4, (ids,), show=False)

# Q5 pathfinder screen: samples with Li_p >= 100 ppm AND Cs/Rb/Be style companions not available -> use Li_p + F + Nb
long5 = f"""SELECT count(*) FROM (SELECT r.sample_id FROM geochem.analytical_results r JOIN geochem.analytical_packages p ON p.package_id = r.package_id
 JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
 WHERE r.source_system = '{SRC}' AND k.use_in_statistics AND ((p.package_code = '511P' AND r.analyte_symbol = 'Li' AND r.value >= 100) OR (p.package_code = '707I' AND r.value * 10000 >= 1000))
 GROUP BY r.sample_id HAVING count(DISTINCT p.package_code) = 2) x"""
wide5 = f"SELECT count(*) FROM geochem.sample_chemistry_wide WHERE source_system = '{SRC}' AND li_p >= 100 AND f_t >= 1000"
print("Q5 Li (leach) + F filter")
timeit("  long", long5); timeit("  wide", wide5)
