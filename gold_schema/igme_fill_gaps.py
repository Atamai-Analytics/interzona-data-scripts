"""Fill gaps in an IGME one-element download (igme_download_test.py) from the per-sample detail records (2026-11-09).

IGME's table API counts some samples it does not return (seen for W: Badajoz Sur 913, Herrera del Duque 2,226). We already know every sample
id (geochem.samples, source SPAIN_IGME_GEOCHEMISTRY, loaded with Cu). For the given campaigns, every known sample missing from
igme_test_<EL>_rows.jsonl is fetched with fichaDetalle; if it has the element, a row in the same format as the table rows is appended
(value from the detail entry whose technique matches the campaign's dominant technique in the detail check; else the only entry).
Paced: PAUSE s between requests. Progress printed every 200. Usage: python igme_fill_gaps.py <EL> <campaign code> [<campaign code> ...]
"""
import json, os, sys, time, collections, urllib.request
import psycopg2

EL, CAMPS = sys.argv[1], [int(x) for x in sys.argv[2:]]
B = "https://info.igme.es/APIs/Geoquimica/Geoquimica/"
D = "D:/CriticalMineralsDB/Spain/download_20261108"
PAUSE = 0.5
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")

rows = [json.loads(l) for l in open(f"{D}/igme_test_{EL}_rows.jsonl", encoding="utf-8")]
have = {r["id"] for r in rows}
det = [json.loads(l) for l in open(f"{D}/igme_test_{EL}_detail.jsonl", encoding="utf-8")]
camp_of = {r["id"]: r["codCampana"] for r in rows}
tech = {}
for camp in CAMPS:
    c = collections.Counter(e["tecnica"] for d in det if camp_of.get(d["id"]) == camp for e in d["detail"]
                            if d["table_value"] is not None and e["concentracion"] is not None and abs(e["concentracion"] - d["table_value"]) < 1e-9)
    tech[camp] = c.most_common(1)[0][0] if c else None
print("dominant technique per campaign", tech, flush=True)
# a template row per campaign (campaign / programme names)
tmpl = {r["codCampana"]: r for r in rows}

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
known = {}
for camp in CAMPS:
    name = tmpl[camp]["nombreCamp"]
    c.execute("""SELECT sample_number, lon, lat, sample_type_local, comments FROM geochem.samples WHERE source_system = 'SPAIN_IGME_GEOCHEMISTRY'
                 AND comments LIKE %s""", (f"IGME campaign {name} (%",))
    for sid, lon, lat, stl, com in c.fetchall():
        if sid not in have: known[sid] = (camp, lon, lat, stl, com)
g.close()
print("missing samples to fetch:", collections.Counter(v[0] for v in known.values()), flush=True)

out = open(f"{D}/igme_test_{EL}_rows.jsonl", "a", encoding="utf-8")
stats = collections.Counter(); t0 = time.time()
for n, (sid, (camp, lon, lat, stl, com)) in enumerate(known.items(), 1):
    for k in range(3):
        try:
            d = json.loads(urllib.request.urlopen(B + f"fichaDetalle/{sid}", timeout=120).read().decode())[0]; break
        except Exception as e:
            stats["retries"] += 1; time.sleep(5 * (k + 1)); d = None
    time.sleep(PAUSE)
    if not d: stats["failed"] += 1; continue
    ents = [e for e in d["sp_reportGeoquimicaDetalleResult"] if e["sustancia"].strip() == EL and not e["restringido"]]
    if not ents: stats["no element"] += 1; continue
    e = next((x for x in ents if x["tecnica"] == tech[camp]), ents[0])
    if e["tecnica"] != tech[camp]: stats["other technique"] += 1
    t = tmpl[camp]
    tipo = stl.split(" (")[0] if stl else None
    out.write(json.dumps({"id": sid, "codCampana": camp, "codPrograma": t["codPrograma"], "nombrePrograma": t["nombrePrograma"], "nombreCamp": t["nombreCamp"],
                          "tipoMuestra": tipo, "refMuestra": None, "litologia": "Desconocida", "sustancia": EL, "concentracion": e["concentracion"],
                          "unidad": e["unidades"], "hoja": None, "huso": None, "x": None, "y": None, "xgeometria": lon, "ygeometria": lat,
                          "from_detail": True}, ensure_ascii=False) + "\n")
    out.flush()                                    # every row on disk at once, so a stop or shutdown loses nothing (resume skips these ids)
    stats["added"] += 1
    if n % 200 == 0: print(f"{n}/{len(known)} {dict(stats)} {round(time.time() - t0)} s", flush=True)
out.close()
print("DONE", dict(stats), round(time.time() - t0), "s", flush=True)
