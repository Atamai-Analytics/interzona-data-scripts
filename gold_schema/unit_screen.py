"""Read-only screen for plausible-looking UNIT errors in geochem.analytical_results (ingestion QC already flags physically impossible values).

Screen A (detection limit): a concentration labelled '%' whose lower detection limit is >= 1 for a non-major element (no lab reports trace metals
  with a 1 % detection limit, so these are almost always ppm values labelled %).
Screen B (same-sample disagreement): two or more usable results for the same analyte in the same sample whose values differ >= 300x after unit
  conversion (and the larger is >= 100 ppm), e.g. a ppb/ppm or ppm/% mix-up, or a mislabelled repeat. Only results in use (is_active, and
  classification use_in_statistics) are compared.
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
    w.writerows(a); w.writerows(b)
    f.flush()
    print(f"{src}: A {len(a)} results, B {len(b)} results in {len({x[3] for x in b})} samples ({(datetime.datetime.now() - t0).seconds}s)", flush=True)
    for scr, rows in (("A", a), ("B", b)):
        cnt = {}
        for x in rows: cnt[x[4]] = cnt.get(x[4], 0) + 1
        if cnt: print(f"   {scr} by analyte:", sorted(cnt.items(), key=lambda kv: -kv[1])[:12], flush=True)
f.close()
print("written", out)
