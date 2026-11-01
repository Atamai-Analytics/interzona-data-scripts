#!/usr/bin/env python3
"""Ingest the 375 GTK rock samples flagged DUPLICATE$='D' (never ingested) into criticialmineralsexp.

  python finland_ingest_375.py <scratchpad dir>            -> DRY RUN: builds staging CSVs + summary, writes NOTHING to the database
  python finland_ingest_375.py <scratchpad dir> --sql      -> additionally writes the psql scripts (still nothing executed)

Rules: finland_ingest_rules.py (validated against the existing 6,169 samples: 6,166 reproduce exactly, 3 differ by
one FeO digit in a rounding tie).  Deliberate departures from the existing rows:
  * sampledate = the CORRECT date from SAMDATE$ (existing dates are all exactly 1 day early)
  * divisionid, legacy_id, samplenumberalt = NULL (no source / no boundary data)
  * every inserted row carries createdby/created_by = TAG so it can be located / rolled back
"""
import collections
import csv
import datetime as dt
import json
import sys
from pathlib import Path

from pyproj import Transformer

import finland_ingest_rules as R

HERE = Path(__file__).resolve().parent
TAG = "claude_finland_flagD_20261004"
EMPTY = "__EMPTY__"


def main():
    sp = Path(sys.argv[1])
    want_sql = "--sql" in sys.argv

    rows, acols = R.read_source()
    all_src = {str(int(r["LABNUM"])): r for r in rows}
    flagged = {k: d for k, d in all_src.items() if d["DUPLICATE$"] == "D"}

    # ---- lookups learned from the existing 6,169 ingested samples ------------------------------------
    ex_samples = {r["sampleid"]: r for r in R.read_csv(sp / "ex_samples.csv")}
    num_by_id = {sid: r["samplenumber"] for sid, r in ex_samples.items()}
    litho_map, age_map = {}, {}
    for r in R.read_csv(sp / "ex_litho.csv"):
        k = num_by_id[r["sampleid"]]
        litho_map[all_src[k]["ROCKTYPE$"]] = (r["lithology_id"], r["mindat_id"])
    for r in R.read_csv(sp / "ex_age.csv"):
        k = num_by_id[r["sampleid"]]
        age_map[str(all_src[k]["AGEGROUP"])] = (r["stratigraphic_age_id"], r["confidence_level"], r["observation_context"])
    pkg_id, an_id, unit_id, an_code = {}, {}, {}, {}
    for r in R.read_csv(sp / "ex_results.csv"):
        pkg_id[r["package_code"]] = r["package_id"]; an_id[r["analyte_code"]] = r["analyte_id"]; unit_id[r["unitcode"]] = r["unitid"]
        an_code[r["analyte_code"].upper()] = r["analyte_code"]

    missing_rock = sorted({str(d["ROCKTYPE$"]) for d in flagged.values() if d["ROCKTYPE$"] not in litho_map})
    missing_age = sorted({str(d["AGEGROUP"]) for d in flagged.values() if str(d["AGEGROUP"]) not in age_map})
    if missing_rock or missing_age:
        raise SystemExit(f"unmapped rock types {missing_rock} / age groups {missing_age} - stop")

    tf = Transformer.from_crs(2393, 4326, always_xy=True)
    loc, smp, lit, age, res = [], [], [], [], []
    skipped = collections.Counter(); per_pkg = collections.Counter(); dedup = 0; dates = []; types = collections.Counter()
    for k, d in sorted(flagged.items()):
        code = f"rock_{k}"
        lon, lat = tf.transform(float(d["YCOORD"]), float(d["XCOORD"]))
        loc.append([code, f"MAP100: {d['MAP100$']} & MAP20: {d['MAP20$']}", repr(lat), repr(lon), repr(float(d["YCOORD"])), repr(float(d["XCOORD"]))])
        sdate = R.sample_date(d["SAMDATE$"])
        dates.append(sdate)
        st = R.SAMTYPE_TO_SAMPLE_TYPE[d["SAMTYPE$"]]; types[st] += 1
        smp.append([code, k, st, sdate.isoformat() if sdate else ""])
        lid, mid = litho_map[d["ROCKTYPE$"]]
        lit.append([code, lid, (str(d["ROCKTYPE$"]) if d["ROCKTYPE$"] not in (None, "") else EMPTY), mid])
        aid, conf, ctx = age_map[str(d["AGEGROUP"])]
        age.append([code, aid, conf, ctx])
        seen = set()
        for col in acols:
            pc = R.parse_column(col)
            if pc is None:
                continue
            el, pkg, unit = pc
            pv = R.parse_value(d[col])
            if pv[0] == "skip":
                skipped[pv[1]] += 1; continue
            key = (pkg, an_code[el.upper()], unit, pv[1], pv[2])
            if key in seen:
                dedup += 1; continue
            seen.add(key)
            res.append([code, pkg_id[pkg], an_id[key[1]], unit_id[unit], pv[1] if pv[1] is not None else "", repr(pv[2])])
            per_pkg[pkg] += 1

    def w(name, header, data):
        with open(sp / name, "w", encoding="utf-8", newline="") as f:
            cw = csv.writer(f); cw.writerow(header); cw.writerows(data)
    w("stg_loc.csv", ["locationcode", "locationname", "latitude", "longitude", "projectedx", "projectedy"], loc)
    w("stg_sample.csv", ["locationcode", "samplenumber", "sample_type_id", "sampledate"], smp)
    w("stg_litho.csv", ["locationcode", "lithology_id", "lithologylocal", "mindat_id"], lit)
    w("stg_age.csv", ["locationcode", "stratigraphic_age_id", "confidence_level", "observation_context"], age)
    w("stg_res.csv", ["locationcode", "package_id", "analyte_id", "unitid", "qualifier_id", "value"], res)
    plan = {"locations": len(loc), "samples": len(smp), "lithology": len(lit), "age": len(age), "results": len(res)}
    (sp / "ingest_plan.json").write_text(json.dumps(plan), encoding="utf-8")

    print("DRY RUN - nothing written to the database")
    print("planned inserts:", plan)
    print("sample types:", dict(types), "(31 outcrop / 26 grab / 30 float)")
    print("results per package:", dict(per_pkg), "| empty cells skipped:", dict(skipped), "| identical duplicates collapsed:", dedup)
    print(f"sample dates: {min(dates)} .. {max(dates)} (blank: {sum(1 for x in dates if x is None)})")
    print("lat/lon range:", min(float(l[2]) for l in loc), max(float(l[2]) for l in loc), "/", min(float(l[3]) for l in loc), max(float(l[3]) for l in loc))
    print(f"expected results per sample: {len(res) / len(smp):.1f} avg (existing samples: {536166 / 6169:.1f})")

    if not want_sql:
        return
    scratch = str(sp).replace("\\", "/")
    ids_out = (HERE / "finland_gap_backups" / "flagD_375_new_ids.csv").as_posix()
    sql = f"""\\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE stg_loc(locationcode text, locationname text, latitude double precision, longitude double precision, projectedx double precision, projectedy double precision);
CREATE TEMP TABLE stg_sample(locationcode text, samplenumber text, sample_type_id integer, sampledate date);
CREATE TEMP TABLE stg_litho(locationcode text, lithology_id integer, lithologylocal text, mindat_id integer);
CREATE TEMP TABLE stg_age(locationcode text, stratigraphic_age_id integer, confidence_level text, observation_context text);
CREATE TEMP TABLE stg_res(locationcode text, package_id integer, analyte_id integer, unitid integer, qualifier_id integer, value numeric);
\\copy stg_loc FROM '{scratch}/stg_loc.csv' CSV HEADER
\\copy stg_sample FROM '{scratch}/stg_sample.csv' CSV HEADER
\\copy stg_litho FROM '{scratch}/stg_litho.csv' CSV HEADER
\\copy stg_age FROM '{scratch}/stg_age.csv' CSV HEADER
\\copy stg_res FROM '{scratch}/stg_res.csv' CSV HEADER
DO $$ DECLARE a int; b int; c int; d int; e int; clash int; BEGIN
  SELECT count(*) INTO a FROM stg_loc; SELECT count(*) INTO b FROM stg_sample; SELECT count(*) INTO c FROM stg_litho; SELECT count(*) INTO d FROM stg_age; SELECT count(*) INTO e FROM stg_res;
  IF a <> {plan['locations']} OR b <> {plan['samples']} OR c <> {plan['lithology']} OR d <> {plan['age']} OR e <> {plan['results']} THEN RAISE EXCEPTION 'staging counts differ from plan: % % % % %', a, b, c, d, e; END IF;
  SELECT count(*) INTO clash FROM locations WHERE locationcode IN (SELECT locationcode FROM stg_loc);
  IF clash <> 0 THEN RAISE EXCEPTION '% locationcodes already exist', clash; END IF;
END $$;
INSERT INTO locations (locationcode, locationname, locationtype, latitude, longitude, srid_geographic, projectedx, projectedy, srid_projected, countryid, divisionid, datasource, datasource_url, createdby, isactive)
  SELECT locationcode, locationname, 'SURFACE', latitude, longitude, 4326, projectedx, projectedy, 2393, 83, NULL, 'Geological Survey of Finland', 'https://www.gtk.fi/en/', '{TAG}', true FROM stg_loc;
INSERT INTO samples (locationid, samplenumber, sample_type_id, sample_context, sampledate, createdby, isactive)
  SELECT l.locationid, s.samplenumber, s.sample_type_id, 'SURFACE', s.sampledate, '{TAG}', true FROM stg_sample s JOIN locations l ON l.locationcode = s.locationcode;
INSERT INTO lithology_observations (lithology_id, lithologylocal, observation_context, sampleid, locationid, mindat_id, createdby, isactive)
  SELECT t.lithology_id, CASE WHEN t.lithologylocal = '{EMPTY}' THEN '' ELSE t.lithologylocal END, 'SAMPLE', sm.sampleid, l.locationid, t.mindat_id, '{TAG}', true
  FROM stg_litho t JOIN locations l ON l.locationcode = t.locationcode JOIN samples sm ON sm.locationid = l.locationid AND sm.createdby = '{TAG}';
INSERT INTO age_stratigraphic (stratigraphic_age_id, observation_context, sampleid, locationid, confidence_level, created_by, is_active)
  SELECT t.stratigraphic_age_id, t.observation_context, sm.sampleid, l.locationid, t.confidence_level, '{TAG}', true
  FROM stg_age t JOIN locations l ON l.locationcode = t.locationcode JOIN samples sm ON sm.locationid = l.locationid AND sm.createdby = '{TAG}';
INSERT INTO analytical_results (sampleid, package_id, analyte_id, unitid, qualifier_id, value, isactive, created_by, reviewed)
  SELECT sm.sampleid, t.package_id, t.analyte_id, t.unitid, t.qualifier_id, t.value, true, '{TAG}', false
  FROM stg_res t JOIN locations l ON l.locationcode = t.locationcode JOIN samples sm ON sm.locationid = l.locationid AND sm.createdby = '{TAG}';
DO $$ DECLARE a int; b int; c int; d int; e int; BEGIN
  SELECT count(*) INTO a FROM locations WHERE createdby = '{TAG}';
  SELECT count(*) INTO b FROM samples WHERE createdby = '{TAG}';
  SELECT count(*) INTO c FROM lithology_observations WHERE createdby = '{TAG}';
  SELECT count(*) INTO d FROM age_stratigraphic WHERE created_by = '{TAG}';
  SELECT count(*) INTO e FROM analytical_results WHERE created_by = '{TAG}';
  IF a <> {plan['locations']} OR b <> {plan['samples']} OR c <> {plan['lithology']} OR d <> {plan['age']} OR e <> {plan['results']} THEN
    RAISE EXCEPTION 'inserted counts differ from plan: loc % smp % lit % age % res % - rolling back', a, b, c, d, e; END IF;
END $$;
\\copy (SELECT 'locations' AS tbl, min(locationid) AS min_id, max(locationid) AS max_id, count(*) FROM locations WHERE createdby = '{TAG}' UNION ALL SELECT 'samples', min(sampleid), max(sampleid), count(*) FROM samples WHERE createdby = '{TAG}' UNION ALL SELECT 'lithology_observations', min(lithology_observation_id), max(lithology_observation_id), count(*) FROM lithology_observations WHERE createdby = '{TAG}' UNION ALL SELECT 'age_stratigraphic', min(age_stratigraphic_id), max(age_stratigraphic_id), count(*) FROM age_stratigraphic WHERE created_by = '{TAG}' UNION ALL SELECT 'analytical_results', min(result_id), max(result_id), count(*) FROM analytical_results WHERE created_by = '{TAG}') TO '{ids_out}' CSV HEADER
COMMIT;
\\echo 'INGEST-COMMITTED'
"""
    (sp / "ingest_375.sql").write_text(sql, encoding="utf-8")
    print("wrote", sp / "ingest_375.sql", "(NOT executed)")


if __name__ == "__main__":
    main()
