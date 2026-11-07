"""Read-only screen for plausible-looking UNIT errors in geochem.analytical_results (ingestion QC already flags physically impossible values).

Screen A (detection limit): a concentration labelled '%' whose lower detection limit is >= 1 for a non-major element (no lab reports trace metals
  with a 1 % detection limit, so these are almost always ppm values labelled %).
Screen B (same-sample disagreement): two or more usable results for the same analyte in the same sample whose values differ >= 300x after unit
  conversion (and the larger is >= 100 ppm), e.g. a ppb/ppm or ppm/% mix-up, or a mislabelled repeat. Only results in use (is_active, and
  classification use_in_statistics) are compared.
Screen C (placeholder values): within one analyte and method, a single exact value that makes up >= 30 % of the usable detected results (>= 50 of
  them) and is >= 100x that analyte's median across the source - typically a detection limit stored without its '<' (e.g. Québec Tl 500 ppm).
  Reported as groups only (printed, and one row per group in the CSV with result_id empty).
Called by qc_results.py after every QC run (report only: nothing is changed; fix a group only with source evidence and the user's OK).
Writes unit_screen_<time>.csv (one row per flagged result) and prints counts per source / analyte. Usage: python unit_screen.py [SOURCE ...]
"""
import os, sys, csv, datetime
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"],
                     keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)
g.set_session(readonly=True)
c = g.cursor()
MAJORS = "('Si','Al','Fe','Ca','Mg','Na','K','C','S','O','H','Cl','Ti','Mn','P')"
PPM = "r.value * CASE r.unit_code WHEN '%%' THEN 10000 WHEN 'ppb' THEN 0.001 ELSE 1 END"
USABLE = "r.is_active AND coalesce(k.use_in_statistics, true)"
if len(sys.argv) > 1:
    sources = sys.argv[1:]
else:
    c.execute("SELECT DISTINCT source_system FROM geochem.samples ORDER BY 1")
    sources = [x[0] for x in c.fetchall()]
out = os.path.join(HERE, f"unit_screen_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
f = open(out, "w", newline="", encoding="utf-8")
w = csv.writer(f)
w.writerow(["screen", "source_system", "result_id", "sample_id", "analyte", "value", "unit", "lower_dl", "package_id", "other_values_ppm"])
for src in sources:
    t0 = datetime.datetime.now()
    c.execute(f"""SELECT 'A', r.source_system, r.result_id, r.sample_id, r.analyte_symbol, r.value, r.unit_code, r.lower_detection_limit, r.package_id, NULL
      FROM geochem.analytical_results r JOIN geochem.analytes a USING (analyte_id)
      LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
      WHERE r.source_system = %s AND {USABLE} AND r.unit_code = '%%' AND NOT a.is_oxide AND r.lower_detection_limit >= 1 AND r.analyte_symbol NOT IN {MAJORS}""", (src,))
    a = c.fetchall()
    c.execute(f"""WITH v AS (
        SELECT r.result_id, r.sample_id, r.analyte_id, r.analyte_symbol, r.value, r.unit_code, r.lower_detection_limit, r.package_id, {PPM} AS ppm
        FROM geochem.analytical_results r LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
        WHERE r.source_system = %s AND {USABLE} AND r.unit_code IN ('%%', 'ppm', 'ppb', 'mg/kg') AND r.value > 0),
      grp AS (SELECT sample_id, analyte_id, min(ppm) AS mn, max(ppm) AS mx, array_agg(ppm ORDER BY ppm) AS vals FROM v GROUP BY 1, 2
              HAVING count(*) > 1 AND max(ppm) >= 300 * min(ppm) AND max(ppm) >= 100)
      SELECT 'B', %s, v.result_id, v.sample_id, v.analyte_symbol, v.value, v.unit_code, v.lower_detection_limit, v.package_id, grp.vals::text
      FROM v JOIN grp USING (sample_id, analyte_id)""", (src, src))
    b = c.fetchall()
    c.execute(f"""WITH v AS (
        SELECT r.analyte_symbol, coalesce(r.method_name, r.method_code, '?') AS m, r.unit_code, r.value, {PPM} AS ppm
        FROM geochem.analytical_results r LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
        WHERE r.source_system = %s AND {USABLE} AND coalesce(k.result_status, 'DETECTED') = 'DETECTED' AND r.unit_code IN ('%%', 'ppm', 'ppb', 'mg/kg') AND r.value > 0),
      med AS (SELECT analyte_symbol, percentile_cont(0.5) WITHIN GROUP (ORDER BY ppm) AS med FROM v GROUP BY 1),
      grp AS (SELECT analyte_symbol, m, count(*) AS n FROM v GROUP BY 1, 2 HAVING count(*) >= 50),
      top AS (SELECT DISTINCT ON (v.analyte_symbol, v.m) v.analyte_symbol, v.m, v.value, v.unit_code, v.ppm, count(*) OVER (PARTITION BY v.analyte_symbol, v.m, v.value, v.unit_code) AS k
              FROM v ORDER BY v.analyte_symbol, v.m, count(*) OVER (PARTITION BY v.analyte_symbol, v.m, v.value, v.unit_code) DESC)
      SELECT 'C', %s, NULL, NULL, top.analyte_symbol, top.value, top.unit_code, NULL, NULL,
             format('%%s of %%s results by %%s; source median %%s ppm', top.k, grp.n, top.m, round(med.med::numeric, 3))
      FROM top JOIN grp USING (analyte_symbol, m) JOIN med USING (analyte_symbol)
      WHERE top.k >= 50 AND top.k >= 0.3 * grp.n AND top.ppm >= 100 * med.med""", (src, src))
    cc = c.fetchall()
    w.writerows(a); w.writerows(b); w.writerows(cc)
    f.flush()
    print(f"{src}: A {len(a)} results, B {len(b)} results in {len({x[3] for x in b})} samples, C {len(cc)} placeholder groups ({(datetime.datetime.now() - t0).seconds}s)", flush=True)
    for x in cc: print(f"   C {x[4]} = {x[5]} {x[6]}: {x[9]}", flush=True)
    for scr, rows in (("A", a), ("B", b)):
        cnt = {}
        for x in rows: cnt[x[4]] = cnt.get(x[4], 0) + 1
        if cnt: print(f"   {scr} by analyte:", sorted(cnt.items(), key=lambda kv: -kv[1])[:12], flush=True)
f.close()
print("written", out)
