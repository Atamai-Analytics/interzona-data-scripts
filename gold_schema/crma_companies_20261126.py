"""EU CRMA strategic projects: add the promoter companies and fix odd deposit links (26 Nov 2026, user: "Yes, fix them").
- 100 active CRMA projects had company_id NULL. Each is linked to its promoter as published in the Commission list
  (core.project_designations.promoter_as_published), name cleaned; short_name gives the common / group name where well known.
  The same promoter on several projects (KGHM, Mkango, ElvalHalcor, Abenojar Tungsten) shares one row. Ownership changes found in the
  26 Nov status review are noted in short_name (e.g. Zinnwald -> AMG, Somincor -> Boliden), the project descriptions carry the detail.
- Relinks: Chvaletice (250) from an MRDS 'magnesite' record to the CGS reserved Mn-tailings deposit Chvaletice-odkaliste 1,2;
  Cinovec (251) from a generic MRDS W-Sn record to the CGS deposit Cinovec-jih (the Li DFS deposit).
- Deposit status: Cinovec-jih PAST_PRODUCER -> FEASIBILITY (Geomet DFS Dec 2025); Sakatti UNKNOWN -> EXPLORATION (pre-feasibility due Dec 2026).
Backup: crma_companies_backup_<stamp>.csv; rollback: python crma_companies_20261126.py --undo <backup.csv> (also deletes the companies created).
Usage: python crma_companies_20261126.py [--dry | --undo backup.csv]
"""
import csv, os, sys, time, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "crma_companies_20261126"

# company name: (short_name, [project_ids])
COMPANIES = {
    "9-Tech S.r.l.": ("9-Tech", [320]),
    "Abenójar Tungsten S.L.": ("Abenójar Tungsten", [338, 288]),
    "Alkeemia S.p.A.": ("Alkeemia", [321]),
    "ElvalHalcor Hellenic Copper and Aluminium Industry S.A.": ("ElvalHalcor", [318, 317]),
    "AMG Lithium GmbH": ("AMG Lithium", [311]),
    "Anglo American Services (UK) Ltd.": ("Anglo American", [253]),
    "Arctial Group Oy": ("Arctial", [301]),
    "Atlantic Copper S.L.U.": ("Atlantic Copper", [291]),
    "Aubert & Duval SAS": ("Aubert & Duval", [307]),
    "Aurubis AG": ("Aurubis", [314]),
    "Aurubis Bulgaria AD": ("Aurubis Bulgaria (Aurubis)", [297]),
    "Back to Battery B.V.": ("Back to Battery", [328]),
    "Caremag SAS": ("Caremag (Carester)", [259]),
    "Circular Materials S.r.l.": ("Circular Materials", [272]),
    "CMK s.r.o.": ("CMK", [336]),
    "Cobre Las Cruces S.A.U.": ("Cobre Las Cruces (Global Panduro / RCF since 2026)", [290]),
    "Cobre San Rafael S.L.": ("Cobre San Rafael (Atalaya Mining operator)", [339]),
    "Comet Traitements SA": ("Comet", [295]),
    "CRITICAL.": ("Circular Industries", [329]),
    "cylib Production I GmbH": ("cylib", [310]),
    "Eco Life Style S.R.L.": ("Eco Life Style", [334]),
    "Electro Mobility Materials Europe": ("EMME", [305]),
    "Elemental Battery Metals Sp. z o.o.": ("Elemental Battery Metals", [277]),
    "Eramet SA": ("Eramet", [265]),
    "Euro Manganese Inc.": ("Euro Manganese", [250]),
    "Euro Sun Mining Inc.": ("Euro Sun Mining", [283]),
    "Evion Group NL": ("Evion", [346]),
    "FinnCobalt Oy": ("FinnCobalt (Eurobattery Minerals)", [300]),
    "Fortum Battery Recycling Oy": ("Fortum", [256]),
    "Frontier Rare Earths Limited": ("Frontier Rare Earths", [353]),
    "Geomet s.r.o.": ("Geomet (CEZ / European Metals)", [251]),
    "GreenRoc Strategic Materials plc": ("GreenRoc", [347]),
    "Gruvaktiebolaget Viscaria": ("Viscaria", [340]),
    "Hellas Gold S.A.": ("Hellas Gold (Eldorado Gold)", [319]),
    "Hycamite TCD Technologies Ltd.": ("Hycamite", [257]),
    "HyProMag GmbH": ("HyProMag", [312]),
    "Iberian Resources Spain": ("Iberian Resources", [287]),
    "Imerys Ceramics France": ("Imerys", [260]),
    "Isabellenhütte Heusler GmbH & Co. KG": ("Isabellenhütte", [315]),
    "Italrecycling & Investment S.r.l.": ("Italrecycling", [322]),
    "Itelyum Regeneration S.p.A.": ("Itelyum", [274]),
    "Jervois Brasil Metalurgia Ltda.": ("Jervois", [349]),
    "Jervois Finland Oy": ("Jervois", [258]),
    "Keliber Technology Oy": ("Keliber (Sibanye-Stillwater)", [254]),
    "KGHM Polska Miedź S.A.": ("KGHM", [330, 331]),
    "Kobaloni Energy Zambia Limited": ("Kobaloni Energy", [345]),
    "Leonardo S.p.A.": ("Leonardo", [324]),
    "Lifthium Energy S.A.": ("Lifthium", [280]),
    "Lithium de France": ("Lithium de France", [306]),
    "Lithium Iberia S.L.": ("Lithium Iberia", [286]),
    "Luossavaara-Kirunavaara AB": ("LKAB", [293]),
    "Lusorecursos Portugal Lithium S.A.": ("Lusorecursos", [278]),
    "Dumont Nickel Limited Partnership": ("Dumont Nickel (formerly Magneto Investments LP)", [343]),
    "MagREEsource": ("MagREEsource", [262]),
    "METLEN Energy & Metals S.A.": ("Metlen (with European Bauxites)", [271]),
    "MINERALIA - Minas, Geotecnia e Construções, Lda.": ("Mineralia", [333]),
    "Mitsubishi Materials Europe B.V.": ("Mitsubishi Materials", [326]),
    "Mkango Resources Ltd.": ("Mkango", [276, 351]),
    "Myne Circular Metals B.V.": ("Myne Circular Metals", [327]),
    "NEOMAT PCAM": ("NEOMAT", [308]),
    "Neptune Energy Innovations GmbH": ("Neptune Energy", [309]),
    "NGC Battery Materials GmbH": ("NGC Battery Materials", [267]),
    "Northvolt Revolt AB": ("Northvolt", [292]),
    "NPM Silmet OÜ": ("Silmet (Neo Performance Materials)", [298]),
    "Nussir ASA": ("Nussir", [348]),
    "OMCD TEK HUB S.p.A.": ("OMCD", [323]),
    "Orano Batteries": ("Orano", [264]),
    "PCC Thorion GmbH": ("PCC Thorion", [269]),
    "Pobuzhzhya's Development LLC": ("Pobuzhzhya's Development", [341]),
    "Portovesme S.r.l.": ("Portovesme (Glencore)", [275]),
    "Pure Battery Technologies Ltd.": ("Pure Battery Technologies", [313]),
    "Recursos Minerales de Galicia S.A.": ("Recursos Minerales de Galicia", [285]),
    "UAB Refinis": ("Refinis", [325]),
    "Rhodia Operations": ("Rhodia (Solvay)", [304]),
    "Rio Narcea Recursos S.A.": ("Rio Narcea", [289]),
    "Rock Tech Guben GmbH": ("Rock Tech Lithium", [270]),
    "Sarytogan Graphite Limited": ("Sarytogan", [350]),
    "Savannah Lithium Unipessoal Lda": ("Savannah Resources", [279]),
    "Slovalco a.s.": ("Slovalco", [337]),
    "Societatea Națională a Sării S.A.": ("Salrom", [282]),
    "Société Le Nickel": ("SLN (Eramet)", [342]),
    "Sokli Oy": ("Sokli", [302]),
    "Solvay Chimica Italia S.p.A.": ("Solvay", [273]),
    "Somincor - Sociedade Mineira de Neves-Corvo, S.A.": ("Somincor (Boliden since Apr 2025)", [281]),
    "Suhanko Arctic Platinum Oy": ("Suhanko Arctic Platinum", [303]),
    "Talga AB": ("Talga", [294]),
    "TDM Electronics Inc.": ("TDM Electronics", [332]),
    "Terrafame Ltd": ("Terrafame", [255]),
    "Tokai COBEX Savoie": ("Tokai COBEX", [261]),
    "Tungsten West PLC": ("Tungsten West", [352]),
    "UP Catalyst OÜ": ("UP Catalyst", [252]),
    "Verde Magnesium Industries SRL": ("Verde Magnesium Industries", [335]),
    "Verde Magnesium SRL": ("Verde Magnesium", [284]),
    "Viridian Lithium": ("Viridian Lithium", [266]),
    "Vulcan Energie Ressourcen GmbH": ("Vulcan Energy", [268]),
    "Zinnwald Lithium Plc": ("Zinnwald Lithium (AMG since Jul 2026)", [316]),
}
RELINK = {250: (426311, 1264457), 251: (325354, 1264368)}  # project_id: (expected old occurrence, new occurrence)
OCC_STATUS = {
    1264368: ("PAST_PRODUCER", "FEASIBILITY", "Cinovec lithium: definitive feasibility study published 19 Dec 2025, EIA filed 31 Dec 2025, no FID (Geomet / CEZ / European Metals); linked to CRMA project 251 Cinovec lithium project."),
    3880: ("UNKNOWN", "EXPLORATION", "Sakatti (Anglo American): advanced exploration - EIA approved, Natura 2000 derogation pending, pre-feasibility study due Dec 2026 (Anglo American Finland, Finnish Government 2026)."),
}

ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()

if UNDO:
    rows = list(csv.DictReader(open(UNDO, encoding="utf-8")))
    for r in rows:
        if r["kind"] == "project":
            c.execute("UPDATE core.projects SET company_id = %s, occurrence_id = %s, modified_by = %s, modified_date = %s WHERE project_id = %s",
                      (r["a"] or None, r["b"] or None, r["modified_by"] or None, r["modified_date"] or None, int(r["id"])))
        else:
            c.execute("UPDATE core.occurrences SET status = %s, comments = %s, modified_by = %s, modified_date = %s WHERE occurrence_id = %s",
                      (r["a"] or None, r["b"] or None, r["modified_by"] or None, r["modified_date"] or None, int(r["id"])))
    c.execute("DELETE FROM core.companies WHERE created_by = %s", (TAG,))
    g.commit(); print("restored", len(rows), "rows; deleted companies", c.rowcount); sys.exit(0)

pids = sorted(p for _, ps in COMPANIES.values() for p in ps)
assert len(pids) == len(set(pids)) == 100, f"{len(pids)} project ids"
c.execute("SELECT project_id, company_id, occurrence_id, modified_by, modified_date FROM core.projects WHERE project_id = ANY(%s) ORDER BY 1", (pids,))
prows = c.fetchall()
assert len(prows) == 100 and all(r[1] is None for r in prows), "projects missing or already have a company - stop"
for pid, (old, new) in RELINK.items():
    assert next(r[2] for r in prows if r[0] == pid) == old, f"project {pid} occurrence changed - stop"
c.execute("SELECT occurrence_id, status, comments, modified_by, modified_date FROM core.occurrences WHERE occurrence_id = ANY(%s)", (list(OCC_STATUS),))
orows = c.fetchall()
for oid, st, *_ in orows:
    assert st == OCC_STATUS[oid][0], f"occurrence {oid} status {st} - stop"
c.execute("SELECT lower(name) FROM core.companies WHERE lower(name) = ANY(%s)", ([n.lower() for n in COMPANIES],))
assert not c.fetchall(), "a company already exists - stop"
print(f"{len(COMPANIES)} companies for {len(pids)} projects; relink {list(RELINK)}; deposit status {list(OCC_STATUS)}")
if DRY:
    g.rollback(); print("DRY - nothing changed"); sys.exit(0)
path = os.path.join(HERE, f"crma_companies_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["kind", "id", "a", "b", "modified_by", "modified_date"])
    for pid, co, oc, mb, md in prows: w.writerow(["project", pid, co or "", oc or "", mb or "", md or ""])
    for oid, st, cm, mb, md in orows: w.writerow(["occurrence", oid, st or "", cm or "", mb or "", md or ""])
for name, (short, ps) in COMPANIES.items():
    c.execute("INSERT INTO core.companies (name, short_name, is_active, created_by, created_date) VALUES (%s, %s, true, %s, now()) RETURNING company_id",
              (name, short, TAG))
    cid = c.fetchone()[0]
    c.execute("UPDATE core.projects SET company_id = %s, modified_by = %s, modified_date = now() WHERE project_id = ANY(%s)", (cid, TAG, ps))
for pid, (_, new) in RELINK.items():
    c.execute("UPDATE core.projects SET occurrence_id = %s WHERE project_id = %s", (new, pid))
for oid, (_, new, note) in OCC_STATUS.items():
    c.execute("""UPDATE core.occurrences SET status = %s, modified_by = %s, modified_date = now(),
                 comments = concat_ws(' | ', comments, %s) WHERE occurrence_id = %s""", (new, TAG, f"Status updated 2026-11-26 to {new}: {note}", oid))
g.commit(); print("done; backup", path)
