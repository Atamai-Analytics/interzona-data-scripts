"""NSW (AUSTRALIA_NSW_GSNSW) unit-screen fixes, 2026-11-17 (user OK).
1. Indium exactly 10 ppm, no '<', by ALS ME-XRF05 pressed-pellet XRF (packages ME-XRF05 / UNK-ME-XRF05; 83 results; typical In 0.03 ppm,
   10 ppm = that method's In detection limit) -> BELOW_DL_PROBABLE, dl 10, dl_source PLACEHOLDER_AT_DL, not used in statistics.
2. Three single unit slips (same sample measured twice, values 1,000-10,000x apart) -> the inconsistent value SUSPECT:
   Sn 0.14 'ppm' by pressed-powder XRF beside 0.29 % (report 9643; 0.14 ppm is far below XRF detection);
   As 3.9 '%' by NAA beside 3.06 ppm by ICP (report 6621).
3. Report 9229 file 24399, ALS ICP586 soils: the source has two columns labelled Mn - 'Mn PCT' (70 values 0.68-644, median 201: really ppm;
   QC had marked the >100 ones SUSPECT) and 'Mn ppm' (70 values, almost all <2: another element under the wrong label, probably Mo).
   -> the '%' results relabelled ppm (unit_id/unit_code; SUSPECT -> DETECTED), the 2-ppm column SUSPECT.
Every touched row goes to fix_nsw_in_units_<time>.csv first (old status, dl). Rollback: python fix_nsw_in_units.py --undo <csv>
"""
import csv, os, sys, time
import psycopg2
SRC, T = "AUSTRALIA_NSW_GSNSW", "geochem.analytical_results_australia_nsw_gsnsw"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30)
c = g.cursor(); c.execute("SET statement_timeout = 0")
RC = "geochem.result_classifications"
if len(sys.argv) > 2 and sys.argv[1] == "--undo":
    rows = list(csv.DictReader(open(sys.argv[2], encoding="utf-8")))
    mn = [int(r["result_id"]) for r in rows if r.get("old_unit") == "%"]
    c.execute(f"UPDATE {T} SET unit_code = '%%', unit_id = (SELECT unit_id FROM geochem.units WHERE unit_code = '%%') WHERE result_id = ANY(%s)", (mn,))
    for r in rows:
        c.execute(f"UPDATE {RC} SET result_status = %s, use_in_statistics = %s, dl_value = %s, dl_source = %s WHERE result_id = %s AND source_system = %s",
                  (r["old_status"], r["old_use"] == "True", r["old_dl"] or None, r["old_dl_source"] or None, int(r["result_id"]), SRC))
    g.commit(); print("undone"); sys.exit()

c.execute(f"""SELECT r.result_id FROM {T} r JOIN geochem.analytical_packages p USING (package_id)
              WHERE r.is_active AND r.analyte_symbol = 'In' AND r.value = 10 AND r.unit_code = 'ppm' AND r.qualifier_code IS NULL
              AND p.package_code IN ('ME-XRF05', 'UNK-ME-XRF05')""")
in_ids = [x[0] for x in c.fetchall()]
slip = []
for el, val, unit, pat in [("Sn", 0.14, "ppm", "%Pressed powder%"), ("As", 3.9, "%", "%NAA%")]:
    c.execute(f"""SELECT r.result_id FROM {T} r WHERE r.is_active AND r.analyte_symbol = %s AND r.value = %s AND r.unit_code = %s AND r.result_comment LIKE %s
                  AND EXISTS (SELECT 1 FROM {T} o WHERE o.sample_id = r.sample_id AND o.analyte_symbol = r.analyte_symbol AND o.result_id <> r.result_id
                  AND o.value * CASE o.unit_code WHEN '%%' THEN 10000 WHEN 'ppb' THEN 0.001 ELSE 1 END
                    / nullif(r.value * CASE r.unit_code WHEN '%%' THEN 10000 WHEN 'ppb' THEN 0.001 ELSE 1 END, 0) NOT BETWEEN 0.001 AND 1000)""", (el, val, unit, pat))
    ids = [x[0] for x in c.fetchall()]; print(el, val, unit, "->", ids); assert len(ids) == 1, ids; slip += ids
print("In placeholders", len(in_ids)); assert len(in_ids) == 83, len(in_ids)
MNQ = f"""SELECT r.result_id FROM {T} r JOIN geochem.samples s USING (sample_id) JOIN geochem.analytical_packages p USING (package_id)
          WHERE s.sample_number_alt = '24399' AND p.package_code = 'ALS-ICP586' AND r.analyte_symbol = 'Mn' AND r.unit_code = %s"""
c.execute(MNQ, ("%",)); mn_pct = [x[0] for x in c.fetchall()]
c.execute(MNQ, ("ppm",)); mn_bad = [x[0] for x in c.fetchall()]
print("file 24399 Mn '%'", len(mn_pct), "Mn 'ppm' column", len(mn_bad)); assert len(mn_pct) == 70 and len(mn_bad) == 70
slip += mn_bad
out = os.path.join(HERE, f"fix_nsw_in_units_{time.strftime('%Y%m%d_%H%M%S')}.csv")
c.execute(f"""SELECT k.result_id, k.result_status, k.use_in_statistics, k.dl_value, k.dl_source, r.unit_code FROM {RC} k JOIN {T} r USING (result_id)
              WHERE k.source_system = %s AND k.result_id = ANY(%s)""", (SRC, in_ids + slip + mn_pct))
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "old_status", "old_use", "old_dl", "old_dl_source", "old_unit"]); w.writerows(c.fetchall())
c.execute(f"""UPDATE {RC} SET result_status = 'BELOW_DL_PROBABLE', use_in_statistics = false, dl_value = 10, dl_source = 'PLACEHOLDER_AT_DL'
              WHERE source_system = %s AND result_id = ANY(%s)""", (SRC, in_ids)); print("In -> BELOW_DL_PROBABLE", c.rowcount)
c.execute(f"UPDATE {RC} SET result_status = 'SUSPECT', use_in_statistics = false WHERE source_system = %s AND result_id = ANY(%s)", (SRC, slip))
print("unit slips + Mn 2-ppm column -> SUSPECT", c.rowcount)
c.execute(f"UPDATE {T} SET unit_code = 'ppm', unit_id = (SELECT unit_id FROM geochem.units WHERE unit_code = 'ppm') WHERE result_id = ANY(%s)", (mn_pct,))
print("Mn % -> ppm", c.rowcount)
c.execute(f"""UPDATE {RC} SET result_status = CASE WHEN result_status = 'SUSPECT' THEN 'DETECTED' ELSE result_status END,
              use_in_statistics = CASE WHEN result_status IN ('SUSPECT', 'DETECTED') THEN true ELSE use_in_statistics END
              WHERE source_system = %s AND result_id = ANY(%s)""", (SRC, mn_pct)); print("Mn reclassified", c.rowcount)
if "--dry" in sys.argv: g.rollback(); print("DRY - rolled back")
else: g.commit(); print("COMMITTED; log", out)
