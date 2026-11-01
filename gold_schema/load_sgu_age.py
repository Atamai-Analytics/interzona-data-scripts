"""SGU Swedish bedrock age database (Bergets alder, alder.csv, CC0 1.0) -> interzona_cm gold.

Per loadable record (age AND SWEREF99 TM coordinates present):
  geochem.samples (source_system 'SWEDEN_SGU_BEDROCK_AGE', one point sample per age record, no chemistry),
  core.external_ids (SGU_ALDER idnr_aldr), geochem.age_reference (one per distinct literature reference),
  geochem.age_measured (age in Ma, error = SGU's 2 standard deviation), geochem.lithology_observations.
Records with only min/max bounds (no age) or without coordinates are NOT loaded (age_ma and sample geom are mandatory).
Usage: python load_sgu_age.py [--dry]   (--dry = load, verify, ROLLBACK).  Credentials from ../.env, never printed.
"""
import os, sys, csv, re, hashlib, time
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_sgu_age_20261011"
CB = "sgu_age_20261011"
SRC = "SWEDEN_SGU_BEDROCK_AGE"
CSV_SRC = r"D:\CriticalMineralsDB\Sweden\alder.csv"

ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def lines(path):  # decode line by line: UTF-8 with Latin-1 fallback
    with open(path, "rb") as fb:
        for raw in fb:
            try:
                yield raw.decode("utf-8")
            except UnicodeDecodeError:
                yield raw.decode("cp1252", errors="replace")


NA = ("", "NA")


def val(x, key):
    v = (x.get(key) or "").strip()
    return None if v in NA else v


def num(x, key):
    v = val(x, key)
    return None if v is None else float(v)


rows = list(csv.DictReader(lines(CSV_SRC)))
log("alder.csv rows", len(rows))
load, skip_noage, skip_nocoord = [], 0, 0
for x in rows:
    if val(x, "age") is None:
        skip_noage += 1; continue
    if val(x, "n_sweref") is None or val(x, "e_sweref") is None:
        skip_nocoord += 1; continue
    load.append(x)
log("loadable", len(load), "skipped: no age", skip_noage, "| age but no coordinates", skip_nocoord)

METHOD = {"U-Pb": "U-Pb", "Rb-Sr": "Rb-Sr", "Ar-Ar": "Ar-Ar", "K-Ar": "K-Ar", "Pb-Pb": "Pb-Pb", "Sm-Nd": "Sm-Nd",
          "Fission track": "Fission Track", "Re-Os": "Re-Os", "U-Th_Pb": "U-Th-Pb", "Lu-Hf": "Lu-Hf"}
AGETYPE = {"Magmatic age": 1, "Metamorphic age": 5, "Cooling age": 19, "Hydrothermal age": 35, "Mineralisation age": 34,
           "Maximum depositional age": 23, "Detrital age": 24, "Inherited age": 4, "Minimum age": 2, "Maximum age": 3,
           "Uncertain age": 36, "Mixed age": 36, "not known": 36}

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                     user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")

# dating methods (add the two SGU uses that were missing)
for name in ("Re-Os", "Lu-Hf"):
    c.execute("SELECT 1 FROM geochem.dating_method_reference WHERE method_name = %s", (name,))
    if not c.fetchone():
        c.execute("INSERT INTO geochem.dating_method_reference (method_name, method_type, description, is_active, created_by) VALUES (%s,'RADIOMETRIC',%s,true,%s)",
                  (name, "Added for the SGU Swedish bedrock age database", CB))
c.execute("SELECT method_name, dating_method_id FROM geochem.dating_method_reference")
DM = dict(c.fetchall())
for m in set(METHOD.values()) | {"U-Pb LA-ICP-MS", "Laser Ar-Ar"}:
    assert m in DM, m
c.execute("SELECT sample_type_id FROM geochem.sample_types WHERE sample_type_code = 'ROCK_SAMPLE'"); ST = c.fetchone()[0]

# literature references (one per distinct full reference)
refs = {}
for x in load:
    r = val(x, "reference")
    if r and r not in refs:
        link = val(x, "ref_link")
        doi = None
        if link:
            m = re.search(r"doi\.org/(10\.\S+)", link)
            doi = m.group(1) if m else None
        refs[r] = (hashlib.md5(r.encode("utf-8")).hexdigest()[:12], r, val(x, "ref_short"),
                   int(val(x, "publ_year")) if val(x, "publ_year") and val(x, "publ_year").isdigit() else None, doi, link)
rid = {}
for key, (rec, cit, short, yr, doi, link) in refs.items():
    c.execute("""INSERT INTO geochem.age_reference (source_name, source_record_id, citation, authors, publication_year, doi, url, comments, is_active, created_by)
                 VALUES ('SGU Swedish bedrock age database', %s, %s, NULL, %s, %s, %s, %s, true, %s) RETURNING age_reference_id""",
              (rec, cit, yr, doi, link, "Short reference: " + (short or "") + ". SGU Bergets alder (CC0 1.0)", CB))
    rid[key] = c.fetchone()[0]
log("age_reference rows", len(rid))

# samples
srows = []
for x in load:
    idn = val(x, "idnr_aldr")
    com = "; ".join(p for p in (val(x, "locality"), "lithology: " + val(x, "lithology") if val(x, "lithology") else None,
                                "lithotectonic: " + val(x, "tect") if val(x, "tect") else None) if p)
    srows.append((float(val(x, "e_sweref")), float(val(x, "n_sweref")), idn, "ALDER-" + idn, val(x, "id_alt"), ST, com[:1000], True, CB, SRC))
execute_values(c, """INSERT INTO geochem.samples (geom, field_id, sample_number, sample_number_alt, sample_type_id, comments, is_active, created_by, source_system)
 VALUES %s""", srows, template="(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),3006),4326),%s,%s,%s,%s,%s,%s,%s,%s)", page_size=1000)
c.execute("SELECT sample_number, sample_id FROM geochem.samples WHERE source_system = %s", (SRC,))
SID = dict(c.fetchall())
assert len(SID) == len(load), (len(SID), len(load))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES %s",
               [("SAMPLE", SID["ALDER-" + val(x, "idnr_aldr")], "SGU_ALDER", val(x, "idnr_aldr"), TAG) for x in load], page_size=1000)
c.execute("""SELECT count(*), min(lat), max(lat), min(lon), max(lon) FROM geochem.samples WHERE source_system = %s""", (SRC,))
log("samples (count, lat range, lon range)", c.fetchone())

# ages
arows = []
for x in load:
    meth = DM[METHOD[val(x, "iso_sys_tx")]] if val(x, "iso_sys_tx") in METHOD else DM["Unknown"]
    m_txt = val(x, "method")
    if val(x, "iso_sys_tx") == "U-Pb" and m_txt == "Laser ICP-MS":
        meth = DM["U-Pb LA-ICP-MS"]
    if val(x, "iso_sys_tx") == "Ar-Ar" and m_txt and "laser" in m_txt.lower():
        meth = DM["Laser Ar-Ar"]
    err, pl, mi = num(x, "age_error"), num(x, "age_err_pl"), num(x, "age_err_mi")
    notes = ["SGU idnr_aldr " + val(x, "idnr_aldr"), "age error = 2 standard deviations"]
    if m_txt: notes.append("method: " + m_txt)
    if err is None and (pl is not None or mi is not None): notes.append("asymmetric error +%s/-%s Ma" % (pl, mi))
    for k, lab in (("age_min", "min age Ma"), ("age_max", "max age Ma"), ("li_age", "lower intercept age Ma"), ("li_age_err", "lower intercept error Ma"),
                   ("n_tot", "n total analyses"), ("age_type", "age type"), ("comment_", "SGU comment")):
        if val(x, k): notes.append(lab + ": " + val(x, k))
    if val(x, "locality") and "uncertain" in val(x, "locality").lower(): notes.append("coordinates flagged uncertain by SGU")
    interp = val(x, "age_int_tx")
    rel = val(x, "reliabilty")
    n_an = num(x, "n_calc") if num(x, "n_calc") is not None else num(x, "n_tot")
    arows.append((meth, "SAMPLE", SID["ALDER-" + val(x, "idnr_aldr")], num(x, "age"), err, "Ma", val(x, "id_lab"), val(x, "lab"),
                  val(x, "mat_dated") if val(x, "mat_dated") != "Not known" else None, num(x, "mswd"), num(x, "probabilit"),
                  int(n_an) if n_an is not None else None, AGETYPE.get(interp, 36), interp, rel, rid.get(val(x, "reference")),
                  " | ".join(notes)[:2000], True, CB))
execute_values(c, """INSERT INTO geochem.age_measured (dating_method_id, observation_context, sample_id, age_ma, age_error_ma, age_unit, lab_sample_id, laboratory,
 material_dated, mswd, probability, n_analyses, age_type_id, age_interpretation, age_quality, age_reference_id, comments, is_active, created_by) VALUES %s""",
               arows, page_size=1000)

# lithology observations (name match to geochem.lithology; otherwise local text only)
c.execute("SELECT lower(lithology_name), lithology_id FROM geochem.lithology")
LN = dict(c.fetchall())
c.execute("SELECT lithology_id FROM geochem.lithology WHERE lithology_code = 'UNKNOWN'"); UNK = c.fetchone()[0]  # lithology_id is mandatory; SGU's own wording stays in lithology_local
lrows = []
for x in load:
    lit = val(x, "lithology")
    loc = lit if not val(x, "litho_txt") or val(x, "litho_txt") == lit else "%s | %s" % (lit, val(x, "litho_txt"))
    if not loc: continue
    lrows.append((LN.get((lit or "").lower(), UNK), loc[:200], "SAMPLE", SID["ALDER-" + val(x, "idnr_aldr")], val(x, "stratgroup"), val(x, "lithodem"), True, CB))
execute_values(c, """INSERT INTO geochem.lithology_observations (lithology_id, lithology_local, observation_context, sample_id, strat_group, strat_formation, is_active, created_by)
 VALUES %s""", lrows, page_size=1000)

# verification
c.execute("SELECT count(*), count(DISTINCT sample_id), min(age_ma), max(age_ma), count(age_error_ma), count(age_reference_id) FROM geochem.age_measured WHERE created_by = %s", (CB,))
log("age_measured (rows, samples, min Ma, max Ma, with error, with reference)", c.fetchone())
c.execute("SELECT dm.method_name, count(*) FROM geochem.age_measured a JOIN geochem.dating_method_reference dm USING (dating_method_id) WHERE a.created_by = %s GROUP BY 1 ORDER BY 2 DESC", (CB,))
log("by method", c.fetchall())
c.execute("SELECT t.age_type_name, count(*) FROM geochem.age_measured a JOIN geochem.age_type_reference t USING (age_type_id) WHERE a.created_by = %s GROUP BY 1 ORDER BY 2 DESC", (CB,))
log("by age type", c.fetchall())
c.execute("SELECT count(*), count(*) FILTER (WHERE lithology_id <> %s) FROM geochem.lithology_observations WHERE created_by = %s", (UNK, CB)); log("lithology obs (total, matched to a dictionary lithology)", c.fetchone())
c.execute("""SELECT count(*) FROM geochem.samples WHERE source_system = %s AND (lat NOT BETWEEN 55 AND 70 OR lon NOT BETWEEN 10 AND 25)""", (SRC,)); log("samples outside Sweden bbox", c.fetchone()[0])
if not DRY:
    c.execute("UPDATE core.data_sources SET is_loaded = true, licence_status = 'Cleared: CC0 confirmed on SGU licence page and product description (2026-10-11). Loaded 2026-10-11 (2,519 of 2,749 records; others lack a point age or coordinates). Written confirmation requested from SGU for externally submitted data (pending).' WHERE source_system = %s", (SRC,))
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
