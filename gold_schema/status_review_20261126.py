"""Monthly status review, 26 Nov 2026: the 25 projects in the review queue of monthly_refresh_2026-11-25.md, each checked against
company / official sources (stock-exchange releases, company sites, government notices; trade press only where it reports a company release).
- 1 project status change: Tungsten West (Hemerdon) DEVELOPMENT -> PRODUCER (production from Sep 2026).
- 2 linked deposit changes: Hemerdon Mine PAST_PRODUCER -> PRODUCER; Dumont Nickel PRODUCER -> DEVELOPMENT (MRDS label wrong, never mined).
- All 25 projects get a dated stage note appended to description (own words, sources named) and modified_date = now, so they leave the
  front of next month's queue.
Backup: status_review_backup_<stamp>.csv. Rollback: python status_review_20261126.py --undo <backup.csv>
Usage: python status_review_20261126.py [--dry | --undo backup.csv]
"""
import csv, os, sys, time, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "status_review_20261126"
D = "Stage check 26 Nov 2026"

# project_id: (expected status, new status, note)
PROJECTS = {
    34: ("DEVELOPMENT", "DEVELOPMENT", "under construction - final investment decision 20-21 May 2026 with up to A$700m Australian government debt; construction from Sep 2026, production targeted late 2029 (Australian Treasurer and NT Government releases, May 2026)."),
    250: ("DEVELOPMENT", "DEVELOPMENT", "a smaller-scale PEA (14 May 2026) replaced the 2022 feasibility study; new feasibility study targeted H1 2027; final mining operations permit still outstanding (Euro Manganese releases May and Jul 2026)."),
    251: ("DEVELOPMENT", "DEVELOPMENT", "definitive feasibility study published 19 Dec 2025 and EIA filed 31 Dec 2025, EIA decision expected end-2026; no FID yet; owner Geomet (CEZ 51%, European Metals 49%) (CEZ and European Metals releases)."),
    253: ("DEVELOPMENT", "DEVELOPMENT", "EIA approved; Natura 2000 derogation still with the government (more information requested Oct 2026); pre-feasibility study due Dec 2026; staff cuts consulted Nov 2026 citing a revised timetable (Anglo American Finland, Finnish Government)."),
    254: ("DEVELOPMENT", "DEVELOPMENT", "construction complete, mining at Syvajarvi since Feb 2026, concentrator in hot commissioning at Q3 2026; no commercial production declared; start-up staged to lithium prices, steady state expected 2028 (Sibanye-Stillwater Q1/Q3 2026 updates). Re-check for PRODUCER."),
    255: ("DEVELOPMENT", "DEVELOPMENT", "combined environmental and water permit application for all Sotkamo operations plus Kolmisoppi filed 30 Apr 2026, decision expected 2027, mining targeted 2028 (Terrafame release 4 May 2026)."),
    260: ("DEVELOPMENT", "DEVELOPMENT", "mining concession for Imerys Beauvoir granted by decree Oct 2026 (reported, to 2075); French state stake agreed Feb 2026; FID expected 2027, lithium hydroxide from 2030 (Allier prefecture, press)."),
    268: ("DEVELOPMENT", "DEVELOPMENT", "under construction - FID Dec 2025, EUR 2.2bn financial close 28 May 2026; pipeline and geothermal plant works on schedule; first production targeted 2028 (Vulcan quarterly report to 30 Sep 2026)."),
    279: ("DEVELOPMENT", "DEVELOPMENT", "Phase 1 DFS Jul 2026; environmental compliance report (RECAPE) submitted 5 Nov 2026, decision expected by end-Jan 2027; FID moved to early 2027, first concentrate late 2028 (Savannah Resources RNS)."),
    281: ("DEVELOPMENT", "DEVELOPMENT", "the Neves-Corvo mine itself produces (owner Boliden Somincor since 16 Apr 2025, was Lundin Mining); this strategic project (Lombador North expansion, Semblana) is still being studied - Semblana feasibility update and Lombador North drilling are 2026 priorities (Boliden; Lusa, 2026)."),
    283: ("DEVELOPMENT", "DEVELOPMENT", "feasibility 2021, mining licence 2018; non-binding MoU for up to US$400m senior debt (Sep 2026) and Glencore offtake MoU (Jul 2026); no construction decision (Euro Sun Mining releases)."),
    290: ("DEVELOPMENT", "DEVELOPMENT", "Cobre Las Cruces sold by First Quantum to Global Panduro (Resource Capital Funds), closed Q2 2026; new owner is advancing the PMR underground mine and refinery, feasibility work ongoing (First Quantum release; IM Mining Jun 2026)."),
    294: ("DEVELOPMENT", "DEVELOPMENT", "Swedish Government adopted the Nunasvaara South detailed plan 27 Jan 2026; Lulea anode plant construction started; mine FID targeted early 2027 (Talga releases 2026)."),
    300: ("DEVELOPMENT", "DEVELOPMENT", "environmental permit still in process (supplementary information requested); refining MoU with Terrafame to be finalised by end-2026; parent Eurobattery Minerals (FinnCobalt releases 2026)."),
    316: ("DEVELOPMENT", "DEVELOPMENT", "PFS Mar 2025, DFS in progress; spatial planning completed Jan 2026; company acquired by AMG Lithium (scheme effective Jul 2026, delisted from AIM) (AMG and Zinnwald Lithium RNS)."),
    319: ("DEVELOPMENT", "DEVELOPMENT", "first copper-gold concentrate 8 Sep 2026; commercial production expected late Q4 2026, not yet declared (Eldorado Gold Q3 2026 report, 28 Oct 2026). Re-check for PRODUCER."),
    339: ("DEVELOPMENT", "DEVELOPMENT", "Touro project, operator Atalaya Mining (earn-in to 80%); environmental impact statement approval nearing completion, not yet issued (Atalaya Q3 2026 results, 12 Nov 2026)."),
    340: ("DEVELOPMENT", "DEVELOPMENT", "fully permitted and under construction - dewatering from 1 Oct 2025, processing plant construction 2026-2027, SEK 2.4bn raise Jun 2026; first production guided 2028 (Viscaria releases)."),
    343: ("DEVELOPMENT", "DEVELOPMENT", "fully permitted, before FID; financing and offtake being finalised, construction targeted 2027; owner Dumont Nickel LP (formerly Magneto Investments, Nion Nickel) (Dumont Nickel release Dec 2025; Metalla)."),
    346: ("DEVELOPMENT", "DEVELOPMENT", "mining permits granted 2026; first binding offtake term sheet Aug 2026; no FID yet (Evion Group ASX announcements)."),
    347: ("DEVELOPMENT", "DEVELOPMENT", "Amitsoq 30-year exploitation licence granted 8 Dec 2025; mine PFS pending after 2026 drilling; anode pilot plant in Denmark produced first spheronised graphite May 2026, Norwegian commercial plant not built (GreenRoc RNS)."),
    350: ("DEVELOPMENT", "DEVELOPMENT", "first of two DFSs published Oct 2026 (about 50 kt/y concentrate); construction targeted 2027 (Sarytogan ASX, Oct 2026)."),
    351: ("DEVELOPMENT", "DEVELOPMENT", "DFS 2022, front-end engineering funded by US DFC; no FID; Mkango Nasdaq SPAC merger approved by Crown PropTech shareholders 25 Nov 2026 (SEC 8-K; Mkango)."),
    352: ("DEVELOPMENT", "PRODUCER", "Hemerdon entered production in Sep 2026 (first ore 11 Sep), ramping up to full rate by end Q1 2027 (Tungsten West RNS 15 Sep 2026)."),
    353: ("DEVELOPMENT", "DEVELOPMENT", "DFS started Feb 2026, due H1 2027, with Carester offtake and US$20m IDC equity; mining right and environmental authorisation held; production targeted 2030 (Frontier Rare Earths release 5 Feb 2026)."),
}
# occurrence_id: (expected status, new status, note)
OCCS = {
    322551: ("PAST_PRODUCER", "PRODUCER", "Hemerdon restarted by Tungsten West - production from Sep 2026 (RNS 15 Sep 2026); earlier mined by Wolf Minerals c. 2015-2018."),
    339176: ("PRODUCER", "DEVELOPMENT", "MRDS label 'Producer' is wrong - Dumont has never been mined; it is a permitted development project before FID (Dumont Nickel release Dec 2025)."),
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
        tbl, key, txt = ("core.projects", "project_id", "description") if r["kind"] == "project" else ("core.occurrences", "occurrence_id", "comments")
        c.execute(f"UPDATE {tbl} SET status = %s, {txt} = %s, modified_by = %s, modified_date = %s WHERE {key} = %s",
                  (r["status"] or None, r["text"] or None, r["modified_by"] or None, r["modified_date"] or None, int(r["id"])))
    g.commit(); print("restored", len(rows)); sys.exit(0)

c.execute("SELECT project_id, name, status, description, modified_by, modified_date FROM core.projects WHERE project_id = ANY(%s) ORDER BY 1", (list(PROJECTS),))
prows = c.fetchall()
c.execute("SELECT occurrence_id, name, status, comments, modified_by, modified_date FROM core.occurrences WHERE occurrence_id = ANY(%s) ORDER BY 1", (list(OCCS),))
orows = c.fetchall()
assert len(prows) == len(PROJECTS) and len(orows) == len(OCCS), "missing rows"
for kind, rows, spec in (("project", prows, PROJECTS), ("occurrence", orows, OCCS)):
    for i, name, st, *_ in rows:
        assert st == spec[i][0], f"{kind} {i} {name}: status is {st}, expected {spec[i][0]} - stop"
        if spec[i][1] != st: print(f"{kind} {i} {name}: {st} -> {spec[i][1]}")
print(f"{len(prows)} project notes, {len(orows)} deposit notes")
if DRY:
    g.rollback(); print("DRY - nothing changed"); sys.exit(0)
path = os.path.join(HERE, f"status_review_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["kind", "id", "status", "text", "modified_by", "modified_date"])
    for i, _, st, tx, mb, md in prows: w.writerow(["project", i, st or "", tx or "", mb or "", md or ""])
    for i, _, st, tx, mb, md in orows: w.writerow(["occurrence", i, st or "", tx or "", mb or "", md or ""])
for i, (old, new, note) in PROJECTS.items():
    lead = f"{D}: status changed to {new}" if new != old else f"{D}: {new} confirmed"
    c.execute("""UPDATE core.projects SET status = %s, modified_by = %s, modified_date = now(),
                 description = concat_ws(E'\\n\\n', description, %s) WHERE project_id = %s""", (new, TAG, f"{lead} - {note}", i))
for i, (old, new, note) in OCCS.items():
    c.execute("""UPDATE core.occurrences SET status = %s, modified_by = %s, modified_date = now(),
                 comments = concat_ws(' | ', comments, %s) WHERE occurrence_id = %s""", (new, TAG, f"Status updated 2026-11-26 to {new}: {note}", i))
g.commit(); print("updated", len(PROJECTS), "projects +", len(OCCS), "deposits; backup", path)
