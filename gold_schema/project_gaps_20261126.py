"""Project gaps, 26 Nov 2026 (user: "start on the project gaps").
1. Stage for the 36 active projects with status NULL / UNKNOWN:
   - 33 Austrade Prospectus midstream projects: mapped from core.project_prospectus.status_inferred (Oct 2026 edition, already
     inferred with a stated basis) -> Operating = PRODUCER, Care and Maintenance = CARE_AND_MAINTENANCE, everything else
     (scoping / PFS / feasibility / pilot / demonstration / pre-construction / construction) = DEVELOPMENT. The detailed stage and
     basis are appended to the description.
   - 3 Rio Tinto Argentina lithium projects checked against Rio Tinto releases: Sal de Vida PRODUCER (first production Q2 2026),
     Rincon PRODUCER (3 kt/y starter plant shipping, 60 kt/y expansion under construction), Cauchari DEVELOPMENT (undeveloped,
     pilot plant planned 2027). Sal de Vida deposit FEASIBILITY -> PRODUCER.
2. Companies for the 2 Austrade projects with none: Alcoa Corporation (Wagerup gallium JV) and Tronox Holdings plc.
3. The 96 CRMA promoter companies (created_by crma_companies_20261126): HQ country (country of the legal entity; parent listing
   country for listed parents), website (as published by the Commission, typos fixed), ticker/exchange for listed companies only.
Backup: project_gaps_backup_<stamp>.csv; rollback: python project_gaps_20261126.py --undo <backup.csv> (also deletes the 2 new companies).
Usage: python project_gaps_20261126.py [--dry | --undo backup.csv]
"""
import csv, os, sys, time, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "project_gaps_20261126"
SRC = "Austrade Critical Minerals Prospectus, Oct 2026"

MAP = {"Operating": "PRODUCER", "Care and Maintenance": "CARE_AND_MAINTENANCE"}
RIO = {
    121: ("UNKNOWN", "DEVELOPMENT", "undeveloped brine resource next to Olaroz; pilot plant planned from 2027 (Rio Tinto operations page; El Economista 2026)."),
    122: ("UNKNOWN", "PRODUCER", "3 kt/y starter plant producing, first commercial shipment of lithium carbonate 2026; 60 kt/y expansion under construction (US$1.175bn financing Mar 2026), first expansion output 2028 (Rio Tinto releases 2026)."),
    123: ("UNKNOWN", "PRODUCER", "first production Q2 2026, ahead of plan, ramping up to 15 kt/y LCE; ramp-up slowed by equipment availability (Rio Tinto releases, Oct 2026)."),
}
NEW_COS = {  # name: (short, ticker, exchange, website, hq country, [project_ids])
    "Alcoa Corporation": ("Alcoa", "AA", "NYSE / ASX (AAI)", "https://www.alcoa.com", "United States", [770]),
    "Tronox Holdings plc": ("Tronox", "TROX", "NYSE", "https://www.tronox.com", "United Kingdom", [790]),
}
# CRMA promoter companies: name -> (hq override or None to use the project country, ticker, exchange, website override)
HQ_OVERRIDE = {
    "Anglo American Services (UK) Ltd.": "United Kingdom", "Euro Manganese Inc.": "Canada", "Euro Sun Mining Inc.": "Canada",
    "Evion Group NL": "Australia", "GreenRoc Strategic Materials plc": "United Kingdom", "Mkango Resources Ltd.": "Canada",
    "Sarytogan Graphite Limited": "Australia", "Pure Battery Technologies Ltd.": "Australia", "Leonardo S.p.A.": "Italy",
    "NGC Battery Materials GmbH": "Germany", "Zinnwald Lithium Plc": "United Kingdom",
    "Frontier Rare Earths Limited": None, "TDM Electronics Inc.": None,  # unclear - left NULL
}
LISTED = {
    "Euro Manganese Inc.": ("EMN", "TSX-V / ASX"), "Euro Sun Mining Inc.": ("ESM", "TSX"), "Evion Group NL": ("EVG", "ASX"),
    "GreenRoc Strategic Materials plc": ("GROC", "AIM"), "Mkango Resources Ltd.": ("MKA", "TSX-V / AIM"),
    "Sarytogan Graphite Limited": ("SGA", "ASX"), "Tungsten West PLC": ("TUN", "AIM"), "Eramet SA": ("ERA", "Euronext Paris"),
    "KGHM Polska Miedź S.A.": ("KGH", "Warsaw (WSE)"), "Aurubis AG": ("NDA", "Xetra"), "Leonardo S.p.A.": ("LDO", "Borsa Italiana"),
    "ElvalHalcor Hellenic Copper and Aluminium Industry S.A.": ("ELHA", "Athens"), "METLEN Energy & Metals S.A.": ("MTLN", "LSE / Athens"),
}
WEB_FIX = {"Orano Batteries": "https://www.orano.group/en", "Solvay Chimica Italia S.p.A.": "https://www.solvay.com/en"}

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
        k = r["kind"]
        if k == "project":
            c.execute("UPDATE core.projects SET status=%s, description=%s, company_id=%s, modified_by=%s, modified_date=%s WHERE project_id=%s",
                      (r["a"] or None, r["b"] or None, r["c"] or None, r["modified_by"] or None, r["modified_date"] or None, int(r["id"])))
        elif k == "occurrence":
            c.execute("UPDATE core.occurrences SET status=%s, comments=%s, modified_by=%s, modified_date=%s WHERE occurrence_id=%s",
                      (r["a"] or None, r["b"] or None, r["modified_by"] or None, r["modified_date"] or None, int(r["id"])))
        else:
            c.execute("UPDATE core.companies SET hq_jurisdiction_id=%s, website=%s, ticker=%s, exchange=%s, modified_by=%s, modified_date=%s WHERE company_id=%s",
                      (r["a"] or None, r["b"] or None, r["c"] or None, r["d"] or None, r["modified_by"] or None, r["modified_date"] or None, int(r["id"])))
    c.execute("DELETE FROM core.companies WHERE created_by = %s", (TAG,))
    g.commit(); print("restored", len(rows), "rows; deleted companies", c.rowcount); sys.exit(0)

c.execute("SELECT name, jurisdiction_id FROM core.jurisdictions WHERE parent_jurisdiction_id IS NULL AND is_active")
JUR = {n: i for n, i in c.fetchall()}

# ---- 1. stages
c.execute("""SELECT p.project_id, p.status, p.description, p.company_id, p.modified_by, p.modified_date, x.status_inferred, x.status_inferred_basis
             FROM core.projects p LEFT JOIN core.project_prospectus x USING (project_id)
             WHERE p.is_active AND (p.status IS NULL OR p.status = 'UNKNOWN') ORDER BY 1""")
prows = c.fetchall()
assert len(prows) == 36, len(prows)
stage = {}
for pid, st, desc, *_ , inf, basis in prows:
    if pid in RIO:
        assert st == RIO[pid][0]; stage[pid] = (RIO[pid][1], f"Stage check 26 Nov 2026: {RIO[pid][1]} - {RIO[pid][2]}")
    else:
        assert st is None and inf, f"{pid}: no inferred stage"
        new = MAP.get(inf, "DEVELOPMENT")
        stage[pid] = (new, f"Stage 26 Nov 2026: {new} (detailed stage: {inf}) - {basis.split(' (inferred by Interzona')[0]} ({SRC}; stage inferred by Interzona from its description).")
c.execute("SELECT o.occurrence_id, o.status, o.comments, o.modified_by, o.modified_date FROM core.occurrences o JOIN core.projects p USING (occurrence_id) WHERE p.project_id = 123")
orow = c.fetchone()
assert orow and orow[1] == "FEASIBILITY", orow

# ---- 2/3. companies
c.execute("""SELECT co.company_id, co.name, co.hq_jurisdiction_id, co.website, co.ticker, co.exchange, co.modified_by, co.modified_date,
                    min(top.name) AS proj_country, min(d.website) AS web
             FROM core.companies co JOIN core.projects p USING (company_id)
             LEFT JOIN core.jurisdictions j ON j.jurisdiction_id = p.jurisdiction_id
             LEFT JOIN core.jurisdictions top ON top.jurisdiction_id = coalesce(j.parent_jurisdiction_id, j.jurisdiction_id)
             LEFT JOIN core.project_designations d ON d.project_id = p.project_id AND d.is_active
             WHERE co.created_by = 'crma_companies_20261126' GROUP BY co.company_id ORDER BY co.company_id""")
crows = c.fetchall()
assert len(crows) == 96, len(crows)
upd = {}
for cid, name, hq, web, tk, ex, mb, md, pc, dweb in crows:
    hqname = HQ_OVERRIDE[name] if name in HQ_OVERRIDE else pc
    hqid = JUR.get(hqname) if hqname else None
    if hqname and not hqid: print(f"  no jurisdiction '{hqname}' for {name} - left NULL")
    w = WEB_FIX.get(name) or (dweb.strip() if dweb else None)
    if w and not w.startswith("http"): w = "https://" + w
    t, e = LISTED.get(name, (None, None))
    upd[cid] = (hqid, w, t, e)
for n, v in NEW_COS.items():
    assert v[4] in JUR, v[4]
c.execute("SELECT 1 FROM core.companies WHERE name = ANY(%s)", (list(NEW_COS),))
assert not c.fetchall(), "Alcoa/Tronox already exist - stop"

print(f"stages: {sum(1 for v in stage.values() if v[0]=='PRODUCER')} PRODUCER, {sum(1 for v in stage.values() if v[0]=='CARE_AND_MAINTENANCE')} C&M, "
      f"{sum(1 for v in stage.values() if v[0]=='DEVELOPMENT')} DEVELOPMENT; companies: {sum(1 for v in upd.values() if v[0])} HQ, "
      f"{sum(1 for v in upd.values() if v[1])} websites, {sum(1 for v in upd.values() if v[2])} tickers; +{len(NEW_COS)} new companies")
if DRY:
    for pid, (s, note) in list(stage.items())[:4]: print(" ", pid, note[:150])
    g.rollback(); print("DRY - nothing changed"); sys.exit(0)

path = os.path.join(HERE, f"project_gaps_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["kind", "id", "a", "b", "c", "d", "modified_by", "modified_date"])
    for pid, st, desc, co, mb, md, *_ in prows: w.writerow(["project", pid, st or "", desc or "", co or "", "", mb or "", md or ""])
    w.writerow(["occurrence", orow[0], orow[1], orow[2] or "", "", "", orow[3] or "", orow[4] or ""])
    for cid, name, hq, web, tk, ex, mb, md, *_ in crows: w.writerow(["company", cid, hq or "", web or "", tk or "", ex or "", mb or "", md or ""])
for pid, (s, note) in stage.items():
    c.execute("""UPDATE core.projects SET status=%s, modified_by=%s, modified_date=now(),
                 description = concat_ws(E'\\n\\n', description, %s) WHERE project_id=%s""", (s, TAG, note, pid))
c.execute("""UPDATE core.occurrences SET status='PRODUCER', modified_by=%s, modified_date=now(),
             comments = concat_ws(' | ', comments, %s) WHERE occurrence_id=%s""",
          (TAG, "Status updated 2026-11-26 to PRODUCER: Sal de Vida (Rio Tinto) first production Q2 2026, ramping up to 15 kt/y LCE (Rio Tinto release Oct 2026).", orow[0]))
for cid, (hqid, web, t, e) in upd.items():
    c.execute("""UPDATE core.companies SET hq_jurisdiction_id=%s, website=%s, ticker=%s, exchange=%s, modified_by=%s, modified_date=now()
                 WHERE company_id=%s""", (hqid, web, t, e, TAG, cid))
for n, (short, t, e, web, hq, ps) in NEW_COS.items():
    c.execute("""INSERT INTO core.companies (name, short_name, ticker, exchange, website, hq_jurisdiction_id, is_active, created_by, created_date)
                 VALUES (%s,%s,%s,%s,%s,%s,true,%s,now()) RETURNING company_id""", (n, short, t, e, web, JUR[hq], TAG))
    cid = c.fetchone()[0]
    c.execute("UPDATE core.projects SET company_id=%s WHERE project_id = ANY(%s) AND company_id IS NULL", (cid, ps))
g.commit(); print("done; backup", path)
