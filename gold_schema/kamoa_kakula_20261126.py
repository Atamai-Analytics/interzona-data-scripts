"""Kamoa-Kakula (DRC) fix, 2026-11-26 (found by gate question inv-kamoa-ownership).

- occurrence 1199605 status DEVELOPMENT (USGS WMED stage 'Pre-Production', last verified 2018) -> PRODUCER: the complex has produced
  copper concentrate since 2021 and Ivanhoe reports quarterly production (Q2 2026 results).
- 4 ownership rows (none existed), from Ivanhoe Mines' own pages: Ivanhoe Mines 39.6% and Zijin Mining 39.6% (each indirect, via a 49.5%
  share of Kamoa Holding, which holds 80%), Crystal River Global 0.8% (indirect, 1% of Kamoa Holding), Government of the DRC 20% (direct).
Usage: python kamoa_kakula_20261126.py [--dry | --undo]
"""
import os, sys, psycopg2

TAG = "kamoa_kakula_20261126"
OCC = 1199605
SRC = "COMPANY_IVANHOE_2026"
URL = ("Ivanhoe Mines, Kamoa-Kakula Copper Complex page https://www.ivanhoemines.com/operations/kamoa-kakula-mining-complex/ and Q2 2026 results "
       "https://www.ivanhoemines.com/news-stories/news-release/ivanhoe-mines-issues-2026-second-quarter-financial-results-overview-of-operations-and-exploration-activities/")
OWNERS = [("Ivanhoe Mines", 39.6, "Indirect: 49.5% of Kamoa Holding, which holds 80%. "),
          ("Zijin Mining Group", 39.6, "Indirect: 49.5% of Kamoa Holding, which holds 80%. "),
          ("Crystal River Global", 0.8, "Indirect: 1% of Kamoa Holding. "),
          ("Government of the Democratic Republic of the Congo", 20.0, "Direct 20% (5% plus 15% transferred under the November 2016 agreement). ")]
OLD_STATUS = "DEVELOPMENT"
NOTE = (" | 26 Nov 2026: status set to PRODUCER (copper production since 2021, reported quarterly by Ivanhoe Mines, Q2 2026 results); "
        "ownership from Ivanhoe Mines (" + TAG + ")")

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()

if "--undo" in sys.argv:
    c.execute("DELETE FROM core.occurrence_ownership WHERE created_by = %s", (TAG,)); print("ownership rows deleted", c.rowcount)
    c.execute("UPDATE core.occurrences SET status = %s, comments = replace(comments, %s, ''), modified_by = NULL, modified_date = NULL "
              "WHERE occurrence_id = %s AND modified_by = %s", (OLD_STATUS, NOTE, OCC, TAG)); print("status restored", c.rowcount)
    g.commit(); sys.exit()

c.execute("SELECT status, name FROM core.occurrences WHERE occurrence_id = %s", (OCC,))
st, name = c.fetchone()
assert name == "Kamoa-Kakula" and st == OLD_STATUS, (name, st)
c.execute("SELECT count(*) FROM core.occurrence_ownership WHERE occurrence_id = %s", (OCC,))
assert c.fetchone()[0] == 0
assert abs(sum(s for _, s, _ in OWNERS) - 100) < 1e-9
print(f"{name}: {st} -> PRODUCER; {len(OWNERS)} ownership rows")
if "--dry" in sys.argv: sys.exit("dry run")
c.execute("UPDATE core.occurrences SET status = 'PRODUCER', comments = comments || %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s",
          (NOTE, TAG, OCC))
for owner, pct, fn in OWNERS:
    c.execute("""INSERT INTO core.occurrence_ownership (occurrence_id, owner_name, company_id, ownership_role, share_pct, as_of_year, source_system,
                 footnote, is_active, created_by, created_date) VALUES (%s, %s, NULL, 'EQUITY_OWNER', %s, 2026, %s, %s, true, %s, now())""",
              (OCC, owner, pct, SRC, fn + "Source: " + URL, TAG))
g.commit(); print("done")
