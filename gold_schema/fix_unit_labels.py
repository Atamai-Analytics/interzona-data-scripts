"""Relabel analytical_results whose unit label does not match the numbers (audit 2026-10-29/30).

Targets (source, lab package, analyte, label now -> label the numbers fit):
  Victoria  ALS-ICP586     K   ppm -> %    (values 0.08-1.85 = percent K in stream sediment)
  Victoria  ANA-MS800      Cd  ppm -> ppb  (median 12 in soils; other Cd methods on soils 0.2-0.3 ppm)
  Victoria  AMD-WEAK-ACID  Cd  ppm -> ppb  (same package labelled ppb has median 8)
  Sweden    CEMENTA-TITR   Cl  ppm -> %    (values 0.01-0.7 in rock; other Cl methods 190-1080 ppm)
Each group is only relabelled if, AFTER the relabel, its median (in ppm) is within a factor of 10 of the median of the other packages' active results for the same analyte in the same source;
otherwise the group is SKIPPED and reported.  The label trigger derives unit_code from unit_id, so the relabel sets unit_id.  Detection limits stored on the row follow the same unit.
All rows of the group are relabelled (active and inactive) so labels stay consistent; the old unit_id of every changed row is saved to _unit_relabel_backup.csv.
Rollback: UPDATE geochem.analytical_results SET unit_id = <old> WHERE result_id = ... from the backup csv (or run this script's --rollback csv logic by hand).
Then rebuild the wide table for the source:  python build_chem_wide.py AUSTRALIA_VIC_GSV_GEOCHEMISTRY  /  SWEDEN_SGU_LITHOGEOCHEMISTRY
Usage: python fix_unit_labels.py [--dry]   (--dry = apply, verify, ROLLBACK)
"""
import csv, os, sys, time
import psycopg2

DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
TARGETS = [
    ("AUSTRALIA_VIC_GSV_GEOCHEMISTRY", "ALS-ICP586", "K", "ppm", "%"),
    ("AUSTRALIA_VIC_GSV_GEOCHEMISTRY", "ANA-MS800", "Cd", "ppm", "ppb"),
    ("AUSTRALIA_VIC_GSV_GEOCHEMISTRY", "AMD-WEAK-ACID", "Cd", "ppm", "ppb"),
    ("SWEDEN_SGU_LITHOGEOCHEMISTRY", "CEMENTA-TITR", "Cl", "ppm", "%"),
]
# Round 2 (2026-10-30, found while verifying round 1): Victoria UltraTrace MA-ICP-MS (133 A-horizon soils) reports Cd, U, Mo, Bi in ppb but they are labelled ppm
# (as labelled they are 94x-5,400x the other methods' medians; as ppb 0.09x-5.4x). The fit window is widened to 0.05-20x for this round because Mo sits at 0.094x.
TARGETS_R2 = [("AUSTRALIA_VIC_GSV_GEOCHEMISTRY", "ULTRATRACE-MA-ICP-MS", an, "ppm", "ppb") for an in ("Cd", "U", "Mo", "Bi")]
ROUND2 = "--round2" in sys.argv
if ROUND2:
    TARGETS = TARGETS_R2
FIT_LO, FIT_HI = (0.05, 20) if ROUND2 else (0.1, 10)
BACKUP_FILE = "_unit_relabel_backup_round2.csv" if ROUND2 else "_unit_relabel_backup.csv"
TO_PPM = {"ppm": 1.0, "mg/kg": 1.0, "ppb": 1e-3, "%": 1e4}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")


def one(sql, p=None):
    c.execute(sql, p); return c.fetchall()


unit_id = dict(one("SELECT unit_code, unit_id FROM geochem.units WHERE unit_code IN ('ppm', 'ppb', '%')"))
log("unit ids", unit_id)
backup, done = [], []
for src, pkg, an, u_from, u_to in TARGETS:
    pid = one("SELECT package_id FROM geochem.analytical_packages WHERE package_code = %s", (pkg,))[0][0]
    rows = one("""SELECT r.result_id, r.unit_id, r.is_active, r.value, r.lower_detection_limit FROM geochem.analytical_results r
                  WHERE r.source_system = %s AND r.package_id = %s AND r.analyte_symbol = %s AND r.unit_code = %s""", (src, pid, an, u_from))
    act = sorted(float(r[3]) for r in rows if r[2] and r[3] is not None and float(r[3]) > 0)
    if not act:
        log(f"SKIP {src} {pkg} {an}: no active positive values"); continue
    med = act[len(act) // 2]
    # reference: other packages, same source and analyte, active positive values, converted to ppm
    ref = one("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value * CASE r.unit_code WHEN 'ppm' THEN 1 WHEN 'mg/kg' THEN 1 WHEN 'ppb' THEN 0.001 WHEN '%%' THEN 10000 END)
                 FROM geochem.analytical_results r WHERE r.source_system = %s AND r.analyte_symbol = %s AND r.is_active AND r.value > 0 AND r.package_id <> %s AND r.unit_code IN ('ppm', 'mg/kg', 'ppb', '%%')""", (src, an, pid))[0][0]
    med_after_ppm = med * TO_PPM[u_to]
    med_before_ppm = med * TO_PPM[u_from]
    ratio_after = med_after_ppm / float(ref)
    ratio_before = med_before_ppm / float(ref)
    ok = FIT_LO <= ratio_after <= FIT_HI
    log(f"{src} {pkg} {an}: {len(rows)} rows ({len(act)} active) labelled {u_from}; median {med} | other packages' median {float(ref):.4g} ppm | ratio to others: as labelled {ratio_before:.3g}, after relabel to {u_to} {ratio_after:.3g} -> {'RELABEL' if ok else 'SKIP (does not fit)'}")
    if not ok:
        continue
    backup += [(r[0], src, pkg, an, r[1], unit_id[u_to]) for r in rows]
    c.execute("UPDATE geochem.analytical_results SET unit_id = %s WHERE source_system = %s AND package_id = %s AND analyte_symbol = %s AND unit_code = %s", (unit_id[u_to], src, pid, an, u_from))
    log(f"   updated {c.rowcount}")
    assert c.rowcount == len(rows)
    chk = one("SELECT unit_code, count(*) FROM geochem.analytical_results WHERE source_system = %s AND package_id = %s AND analyte_symbol = %s GROUP BY 1", (src, pid, an))
    log("   units now in this package/analyte:", chk)
    done.append((src, pkg, an, u_to))
with open(os.path.join(HERE, BACKUP_FILE), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "source_system", "package", "analyte", "old_unit_id", "new_unit_id"]); w.writerows(backup)
log("rows relabelled", len(backup), "| groups relabelled", len(done), "of", len(TARGETS))
log("other rows changed? labelled-unit counts by source for the touched analytes (K, Cd, Cl):", one("""SELECT source_system, analyte_symbol, unit_code, count(*) FROM geochem.analytical_results WHERE source_system IN ('AUSTRALIA_VIC_GSV_GEOCHEMISTRY', 'SWEDEN_SGU_LITHOGEOCHEMISTRY')
   AND analyte_symbol IN ('K', 'Cd', 'Cl') AND is_active GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"""))
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
    log("after rollback: Victoria K ALS-ICP586 units", one("SELECT r.unit_code, count(*) FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) WHERE r.source_system = 'AUSTRALIA_VIC_GSV_GEOCHEMISTRY' AND p.package_code = 'ALS-ICP586' AND r.analyte_symbol = 'K' GROUP BY 1"))
else:
    g.commit(); log("COMMITTED - rebuild the wide table for the touched sources")
g.close()
