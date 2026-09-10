# Generate Phase-1 migration SQL for criticialmineralsexp.
#  - 02: insert 179 new deposits into locations + deposits (+ commodities + mineralogy)
#  - 03: populate deposit_endowment from sigam_ficha_grades (all deposits)
#  - 04: populate age_measured from sigam_ficha_ages (all deposits)
#  - 05: backfill deposits.deposit_type_id from SIGAM ficha codes (existing, where null)
#  - 06: targeted fixes (7 ficha-vs-curated type disagreements + Diablillos typo)
import json, csv, re, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
J = os.path.join(HERE, "..", "sigam_fichas", "sigam_fichas.jsonl")
XW = os.path.join(HERE, "..", "ls_deposit_extract")
SCR = os.path.join(HERE, "..", "..", "..", "AppData", "Local", "Temp", "claude",
                   "C--Users-dean-claude-lithosurfer", "b7dee605-079c-4830-8d35-2b4df883cc10", "scratchpad")
TAG = "claude_sigam_20260910"

def rows(p):
    return list(csv.DictReader(open(p, encoding="utf-8")))

def sql_str(v):
    if v is None or v == "":
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"

def sql_num(v):
    if v is None or v == "":
        return "NULL"
    try:
        float(v); return str(v)
    except (TypeError, ValueError):
        return "NULL"

# ---------- crosswalks ----------
comm_by_name = {}
comm_by_sym = {}
for r in rows(os.path.join(HERE, "db_commodities.csv")):
    comm_by_name[r["commodity_name"].lower()] = int(r["commodity_id"])
    if r["sym"]:
        comm_by_sym[r["sym"].lower()] = int(r["commodity_id"])

type_map = {}   # sigam_code -> hofstra deposit_type_id (or None)
for r in rows(os.path.join(HERE, "type_mapping.csv")):
    type_map[r["sigam_code"]] = int(r["deposit_type_id"]) if r["deposit_type_id"] else None

minerals = {}
for r in rows(os.path.join(HERE, "minerals.csv")):
    minerals[r["nm"]] = int(r["mineral_id"])

dbmap = {int(r["depno"]): r for r in rows(os.path.join(HERE, "db_deposit_map.csv"))}

# commodity resolver (elements, spanish industrial terms, oxide formulae)
SYM = {"pb":"pb","cu":"cu","ag":"ag","au":"au","zn":"zn","w":"w","fe":"fe","mn":"mn","ba":"ba","li":"li",
 "mo":"mo","sn":"sn","u":"u","bi":"bi","sb":"sb","v":"v","ni":"ni","f":"f","as":"as","s":"s","cr":"cr",
 "nb":"nb","th":"th","ta":"ta","k":"k","co":"co","ti":"ti","se":"se","pt":"pt","zr":"zr","b":"b","hg":"hg",
 "in":"in","al":"al","cs":"cs","be":"be","ree":"ree","pge":"pge","pd":"pge"}
FORMULA = {"wo3":"w","sno2":"sn","tio2":"ti","moo3":"mo","v2o5":"v","nb2o5":"nb","ta2o5":"ta","u3o8":"u",
 "tho2":"th","li2o":"li","bao":"ba","sb2o3":"sb","etr":"ree","tr":"ree","egp":"pge",
 "baritina":"ba","barita":"ba","feldesp":"feldspar","feldespato":"feldspar"}
IND = {"bentonita":"bentonite","caolín":"kaolin","caolin":"kaolin","caliza":"limestone","arcilla":"clay",
 "yeso":"gypsum","sal":"salt","arena":"sand and gravel","árido":"sand and gravel","arido":"sand and gravel",
 "granito":"granite","mármol":"marble","marmol":"marble","cuarzo":"quartz","feldespato":"feldspar",
 "travertino":"limestone","serpentin":"serpentine","asbesto":"serpentine","vermiculita":"vermiculite",
 "talco":"talc","diatomita":"diatomite","perlita":"perlite","fluorita":"fluorite","grava":"sand and gravel",
 "dolomía":"limestone","dolomia":"limestone","pizarra":"slate","basalto":"basalt","onyx":"onyx","ónix":"onyx",
 "sienita":"granite","gneis":"granite","áridos":"sand and gravel"}

def resolve_commodity(tok):
    t = (tok or "").strip().strip("()").lower()
    if not t:
        return None
    t = FORMULA.get(t, t)
    if t in comm_by_name:
        return comm_by_name[t]
    if t in SYM and SYM[t] in comm_by_sym:
        return comm_by_sym[SYM[t]]
    if t in comm_by_sym:
        return comm_by_sym[t]
    for k, v in IND.items():
        if k in t and v in comm_by_name:
            return comm_by_name[v]
    return None

def split_commodities(s):
    if not s:
        return []
    s = s.replace("(", " ").replace(")", " ")
    out = []
    for p in re.split(r"[;,/+]| y |-(?=[A-Z(])", s):
        p = p.strip()
        if p and p.lower() not in ("etc", "otros", "y"):
            out.append(p)
    return out

# ---------- status / size maps ----------
STATUS = {  # first token of ficha estado -> deposits.deposit_status CHECK value
 "productor": "PRODUCER", "producción": "PRODUCER", "produccion": "PRODUCER",
 "cerrado": "CLOSED", "abandonado": "CLOSED", "inactiva": "CLOSED",
 "prospecto": "PROSPECT", "prospección": "PROSPECT", "prospeccion": "PROSPECT",
 "exploración": "EXPLORATION", "exploracion": "EXPLORATION",
 "ocurrencia": "OCCURRENCE", "manifestación": "OCCURRENCE", "manifestacion": "OCCURRENCE",
 "depósito": "UNKNOWN", "deposito": "UNKNOWN", "desconocido": "UNKNOWN",
}
def status_of(estado):
    e = (estado or "").split(";")[0].strip().lower()
    if e.startswith("productor") and ("pasad" in e or "pasa" in e):
        return "PAST_PRODUCER"
    for k, v in STATUS.items():
        if e.startswith(k):
            return v
    return "UNKNOWN"

SIZE = {"pequeño":"SMALL","pequeno":"SMALL","mediano":"MEDIUM","grande":"LARGE","gigante":"GIANT",
        "ocurrencia":"OCCURRENCE"}
def size_of(estado):
    m = re.search(r"tama[nñ]o:\s*([a-zñáéíóú]+)", (estado or "").lower())
    if m:
        return SIZE.get(m.group(1), "UNKNOWN")
    return "UNKNOWN"

def clean(s):
    """trim SIGAM '; Referencia:' / '; Comentario' / '; <prose>' tails and collapse ws"""
    if not s:
        return None
    s = re.split(r";\s*(Referencia|Comentario|No hay|Se |Podr|Comentario interpretativo)", s)[0].strip()
    s = re.sub(r"\s+", " ", s).strip(" ;/")
    # collapse an exact "X / X" duplication
    if " / " in s:
        a, b = s.split(" / ", 1)
        if a.strip() == b.strip():
            s = a.strip()
    return s or None

def fmt_refs(refs):
    if not refs:
        return None
    out = []
    for r in refs[:6]:
        if isinstance(r, dict):
            parts = [r.get("authors_year"), r.get("title"), r.get("publication")]
            out.append("\n".join(p for p in parts if p))
        else:
            out.append(str(r))
    return "\n\n".join(out) or None

# ---------- load JSONL ----------
fichas = {}
for line in open(J, encoding="utf-8"):
    o = json.loads(line)
    if o.get("_ok") and o.get("depno") is not None:
        fichas[int(o["depno"])] = o

new_depnos = sorted(d for d in fichas if d not in dbmap)
print(f"new deposits to insert: {len(new_depnos)}")

# ============================================================ 02: new deposits
lines = ["-- Phase 1 step 02: insert %d new SIGAM deposits" % len(new_depnos),
         "-- locations + deposits in one CTE, then commodities + mineralogy.",
         "BEGIN;", ""]

loc_vals, dep_vals = [], []
com_rows, min_rows = [], []
for dn in new_depnos:
    o = fichas[dn]
    name = clean(o.get("nombre")) or f"SIGAM deposit {dn}"
    lat = o.get("lat"); lon = o.get("lon")
    url = o.get("url")
    loc_vals.append(f"({dn}, {sql_str(name[:255])}, {sql_num(lat)}, {sql_num(lon)}, {sql_str(url)})")

    code = (o.get("tipo_deposito") or "").split(" ")[0].strip()
    dt_id = type_map.get(code)
    dt_local = clean(o.get("tipo_deposito"))
    prov = clean(o.get("provincia_geologica"))
    tect = clean(o.get("marco_tectonico"))
    mstyle = clean(o.get("estilos_mineralizacion"))
    form = clean(o.get("forma_deposito"))
    alt = clean(o.get("alteracion"))
    meta = clean(o.get("asociacion_metalogenica"))
    ign = clean(o.get("rocas_igneas_relacionadas"))
    refs = fmt_refs(o.get("referencias"))
    com = clean(o.get("dpcomment"))
    dep_vals.append("(" + ", ".join([
        str(dn), sql_num(dt_id), sql_str((dt_local or "")[:255]),
        sql_str(status_of(o.get("estado_deposito"))), sql_str(size_of(o.get("estado_deposito"))),
        sql_str((prov or "")[:255] or None), sql_str((tect or "")[:255] or None),
        sql_str((mstyle or "")[:255] or None), sql_str((form or "")[:255] or None),
        sql_str(alt), sql_str((meta or "")[:255] or None), sql_str((ign or "")[:255] or None),
        sql_str(refs), sql_str(com),
    ]) + ")")

    # commodities
    toks = split_commodities(o.get("commodities"))
    seen = set()
    for i, tk in enumerate(toks):
        cid = resolve_commodity(tk)
        if cid and cid not in seen:
            seen.add(cid)
            com_rows.append((dn, cid, "PRIMARY" if i == 0 else "SECONDARY"))
    # mineralogy
    for grp in (o.get("mineralogia") or []):
        zona = (grp or {}).get("zona")
        for mn in (grp or {}).get("minerales", []):
            mn = (mn or "").strip()
            if mn:
                min_rows.append((dn, mn[:120], (zona or "")[:120] or None, minerals.get(mn.lower())))

lines += ["WITH nl AS (",
          "  INSERT INTO locations (locationcode, locationname, locationtype, latitude, longitude,",
          "                         external_id, datasource, datasource_url, countryid, createdby)",
          "  SELECT 'País', v.name, 'DEPOSIT', v.lat, v.lon, v.depno::text,",
          "         'Argentine Geological and Mining Service SEGEMAR', v.url, 23, '%s'" % TAG,
          "  FROM (VALUES\n    " + ",\n    ".join(loc_vals),
          "  ) AS v(depno, name, lat, lon, url)",
          "  RETURNING locationid, external_id",
          ")",
          "INSERT INTO deposits (locationid, deposit_type_id, deposit_type_local, deposit_status,",
          "                      size_category, geological_province, tectonic_setting, mineralization_style,",
          "                      deposit_form, alteration, metallogenic_association, associated_igneous,",
          '                      "references", comments, createdby)',
          "SELECT nl.locationid, v.dt_id, v.dt_local, v.status, v.size_cat, v.prov, v.tect, v.mstyle,",
          "       v.form, v.alt, v.meta, v.ign, v.refs, v.com, '%s'" % TAG,
          "FROM nl JOIN (VALUES\n    " + ",\n    ".join(dep_vals),
          "  ) AS v(depno, dt_id, dt_local, status, size_cat, prov, tect, mstyle, form, alt, meta, ign, refs, com)",
          "  ON v.depno::text = nl.external_id;",
          ""]

# commodities / mineralogy (join through the now-existing new location rows)
if com_rows:
    cv = ",\n    ".join(f"({d}, {c}, '{r}')" for d, c, r in com_rows)
    lines += ["INSERT INTO deposit_commodities (depositid, commodity_id, commodity_role, createdby)",
              "SELECT d.depositid, v.cid, v.role, '%s'" % TAG,
              "FROM (VALUES\n    " + cv + "\n  ) AS v(depno, cid, role)",
              "JOIN locations l ON l.external_id = v.depno::text AND l.locationtype='DEPOSIT' AND l.createdby='%s'" % TAG,
              "JOIN deposits d ON d.locationid = l.locationid;", ""]
if min_rows:
    mv = ",\n    ".join(f"({d}, {sql_str(n)}, {sql_str(z)}, {sql_num(mid)})" for d, n, z, mid in min_rows)
    lines += ["INSERT INTO deposit_mineralogy (depositid, mineral_name_local, mineral_zone, mineral_id, createdby)",
              "SELECT d.depositid, v.nm, v.zona, v.mid, '%s'" % TAG,
              "FROM (VALUES\n    " + mv + "\n  ) AS v(depno, nm, zona, mid)",
              "JOIN locations l ON l.external_id = v.depno::text AND l.locationtype='DEPOSIT' AND l.createdby='%s'" % TAG,
              "JOIN deposits d ON d.locationid = l.locationid;", ""]

lines += ["SELECT 'new locations' t, count(*) n FROM locations WHERE createdby='%s'" % TAG,
          "UNION ALL SELECT 'new deposits', count(*) FROM deposits WHERE createdby='%s'" % TAG,
          "UNION ALL SELECT 'new commodities', count(*) FROM deposit_commodities WHERE createdby='%s'" % TAG,
          "UNION ALL SELECT 'new mineralogy', count(*) FROM deposit_mineralogy WHERE createdby='%s'" % TAG,
          "UNION ALL SELECT 'new deposits w/ type', count(*) FROM deposits WHERE createdby='%s' AND deposit_type_id IS NOT NULL;" % TAG,
          "",
          "COMMIT;"]
open(os.path.join(HERE, "02_new_deposits.sql"), "w", encoding="utf-8").write("\n".join(lines))
print(f"  02: {len(new_depnos)} deposits, {len(com_rows)} commodities, {len(min_rows)} mineralogy")

# ============================================================ 03: deposit_endowment
grades = rows(os.path.join(SCR, "src_grades.csv"))
ev = []
for g in grades:
    dn = int(g["depno"])
    cid = resolve_commodity(g["commodity"])
    dtp = "RESOURCE" if g["kind"] == "recurso" else "PRODUCTION"
    meas = "GRADE" if g["slot"] == "grade" else "AMOUNT"
    val = g["value"]
    vnum = val if re.fullmatch(r"-?\d+\.?\d*", (val or "").strip().replace(",", "")) else None
    ev.append((dn, cid, g["commodity"], dtp, meas, vnum, val, g["unit_note"], int(g["seq"])))
L = ["-- Phase 1 step 03: populate deposit_endowment from sigam_ficha_grades", "BEGIN;", ""]
CH = 400
for i in range(0, len(ev), CH):
    chunk = ev[i:i + CH]
    vv = ",\n    ".join(
        f"({d}, {sql_num(c)}, {sql_str(craw[:60])}, '{dt}', '{m}', {sql_num(vn)}, {sql_str((vt or '')[:60])}, {sql_str((u or '')[:100])}, {sq})"
        for d, c, craw, dt, m, vn, vt, u, sq in chunk)
    L += ["INSERT INTO deposit_endowment (depositid, commodity_id, commodity_raw, data_type, measure,",
          "                               value_num, value_text, unit, seq, createdby)",
          "SELECT d.depositid, v.cid, v.craw, v.dt, v.m, v.vn, v.vt, v.u, v.sq, '%s'" % TAG,
          "FROM (VALUES\n    " + vv + "\n  ) AS v(depno, cid, craw, dt, m, vn, vt, u, sq)",
          "JOIN locations l ON l.external_id = v.depno::text AND l.locationtype='DEPOSIT'",
          "JOIN deposits d ON d.locationid = l.locationid",
          "ON CONFLICT (depositid, data_type, measure, commodity_raw, seq) DO NOTHING;", ""]
L += ["SELECT count(*) endowment_rows, count(distinct depositid) deposits FROM deposit_endowment;", "COMMIT;"]
open(os.path.join(HERE, "03_endowment.sql"), "w", encoding="utf-8").write("\n".join(L))
print(f"  03: {len(ev)} endowment rows")

# ============================================================ 04: age_measured
ages = rows(os.path.join(SCR, "src_ages.csv"))
DM = {"K-Ar":2,"Ar-Ar":3,"Rb-Sr":5,"U-Pb":15,"U-Pb SHRIMP":16,"Sm-Nd":17,"Sm/Nd":17,"Pb-Pb":18,
      "Termoluminiscencia":19}
def age_type_id(ev_):
    e = (ev_ or "").lower()
    if "mineraliz" in e: return 34
    if "alterac" in e: return 35
    if "metamorf" in e: return 5
    if "enfriam" in e or "cooling" in e: return 19
    if "intrus" in e or "efusi" in e: return 1
    if "sediment" in e or "estrati" in e: return 21
    return 36
def anum(s):
    if not s: return None
    s = s.strip().replace(" ", "")
    if "," in s and "." not in s and len(s.split(",")[-1]) != 3:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    m = re.search(r"-?\d+\.?\d*", s)
    return m.group() if m else None
def aunc(s):
    if not s: return None
    v = [abs(float(x)) for x in re.findall(r"[+-]?\d+\.?\d*", s.replace(",", "."))]
    return max(v) if v else None

av = []
for a in ages:
    ma = anum(a["age_ma"])
    if ma is None:
        continue
    dn = int(a["depno"])
    dm = DM.get((a["method"] or "").strip(), 1)
    interp = " | ".join(x for x in [a.get("evento"), a.get("nombre_formal"), a.get("origen_roca")] if x) or None
    av.append((dn, dm, ma, aunc(a["uncertainty"]), age_type_id(a["evento"]),
               (a.get("objeto_datado") or "")[:100] or None, (a.get("concentrado") or "")[:100] or None,
               interp, (a.get("referencia") or "")[:500] or None, int(a["seq"])))
L = ["-- Phase 1 step 04: populate age_measured (POINT_LOCATION) from sigam_ficha_ages", "BEGIN;", ""]
CH = 300
for i in range(0, len(av), CH):
    chunk = av[i:i + CH]
    vv = ",\n    ".join(
        f"({d}, {dm}, {ma}, {sql_num(er)}, {at}, {sql_str(md)}, {sql_str(mnl)}, {sql_str(ip)}, {sql_str(rf)}, {sq})"
        for d, dm, ma, er, at, md, mnl, ip, rf, sq in chunk)
    L += ["INSERT INTO age_measured (locationid, observation_context, datingmethodid, age_ma, age_error_ma,",
          "                          age_type_id, material_dated, mineral, age_interpretation, reference,",
          "                          comments, createdby)",
          "SELECT l.locationid, 'POINT_LOCATION', v.dm, v.ma, v.er, v.at, v.md, v.mnl, v.ip, v.rf,",
          "       'SIGAM ficha dp'||v.depno||' #'||v.sq, '%s'" % TAG,
          "FROM (VALUES\n    " + vv + "\n  ) AS v(depno, dm, ma, er, at, md, mnl, ip, rf, sq)",
          "JOIN locations l ON l.external_id = v.depno::text AND l.locationtype='DEPOSIT';", ""]
L += ["SELECT count(*) FROM age_measured WHERE createdby='%s';" % TAG, "COMMIT;"]
open(os.path.join(HERE, "04_ages.sql"), "w", encoding="utf-8").write("\n".join(L))
print(f"  04: {len(av)} age rows")

# ============================================================ 05: backfill existing types
L = ["-- Phase 1 step 05: backfill deposits.deposit_type_id from SIGAM ficha codes (existing, null only)",
     "BEGIN;", "",
     "CREATE TEMP TABLE _bf(depno int, code text, dt_id int);",
     "INSERT INTO _bf VALUES"]
bf = []
for dn, r in dbmap.items():
    if r["deposit_type_id"]:
        continue
    o = fichas.get(dn)
    if not o:
        continue
    code = (o.get("tipo_deposito") or "").split(" ")[0].strip()
    if type_map.get(code):
        bf.append(f"  ({dn}, '{code}', {type_map[code]})")
L.append(",\n".join(bf) + ";")
L += ["",
      "UPDATE deposits d SET deposit_type_id = b.dt_id, modifiedby='%s', modifieddate=now()" % TAG,
      "FROM _bf b JOIN locations l ON l.external_id = b.depno::text AND l.locationtype='DEPOSIT'",
      "WHERE d.locationid = l.locationid AND d.deposit_type_id IS NULL;",
      "",
      "SELECT count(*) backfilled FROM deposits WHERE modifiedby='%s';" % TAG,
      "COMMIT;"]
open(os.path.join(HERE, "05_backfill_types.sql"), "w", encoding="utf-8").write("\n".join(L))
print(f"  05: {len(bf)} type backfills")

# ============================================================ 06: targeted fixes
# 7 ficha-vs-curated disagreements (ficha wins) + Diablillos typo
DIS = rows(os.path.join(XW, "review_type_disagreements.csv"))
L = ["-- Phase 1 step 06: fix 7 type disagreements (SIGAM ficha wins) + depno 24574 name typo",
     "BEGIN;", ""]
for r in DIS:
    # set the type id from the ficha; refresh deposit_type_local from the clean sigam_fichas value
    L.append(f"UPDATE deposits d SET deposit_type_id = {r['ficha_hofstra_id']}, "
             f"deposit_type_local = left(regexp_replace(f.tipo_deposito, ';.*$', ''), 255), "
             f"modifiedby='{TAG}', modifieddate=now() "
             f"FROM locations l JOIN sigam_fichas f ON f.depno = l.external_id::int "
             f"WHERE l.locationid=d.locationid AND l.locationtype='DEPOSIT' AND l.external_id = '{r['depno']}';")
L += ["",
      "UPDATE locations SET locationname = 'Salar de Diablillos', modifiedby='%s', modifieddate=now()" % TAG,
      "WHERE locationtype='DEPOSIT' AND external_id = '24574' AND locationname = 'Salar de Diabillos';",
      "UPDATE sigam_deposits SET nombre_de_yacimiento = replace(nombre_de_yacimiento,'Diabillos','Diablillos')",
      "WHERE deposit_id = 24574;",
      "",
      "SELECT d.deposit_type_id, l.locationname FROM deposits d JOIN locations l ON l.locationid=d.locationid",
      "WHERE l.external_id IN ('1','34','36','45','2014','3019','24538','24574') ORDER BY l.external_id;",
      "COMMIT;"]
open(os.path.join(HERE, "06_fixes.sql"), "w", encoding="utf-8").write("\n".join(L))
print("  06: 7 type fixes + 1 name fix")
print("done.")
