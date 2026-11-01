"""Match the 94 rows of Austrade's interactive-report table to core.project_prospectus (by stage, name similarity and state) and show the status comparison.
Usage: python match_austrade_report.py --dry | --run   (--run adds columns report_status / report_companies / report_minerals to core.project_prospectus and fills them)"""
import sys, os, re, json, difflib
sys.stdout.reconfigure(encoding="utf8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rag_ingest import load_env, get_conn
HERE = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(os.path.join(HERE, "austrade", "austrade_report_table.json"), encoding="utf8"))["rows"]
g = get_conn(load_env()); c = g.cursor()
c.execute("""SELECT k.prospectus_project_id, k.stage, k.name_as_published, k.state_as_published, p.project_id, p.status, k.company_as_published FROM core.project_prospectus k JOIN core.projects p USING (project_id) ORDER BY 1""")
db = c.fetchall()
def nk(s):
    s = s.lower().replace("–", " ").replace("-", " ").replace("mount ", "mt ").replace("&", " and ")
    s = re.sub(r"\b(project|projects|the|mine|operation|facility|plant)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()
import numpy as np
sys.path.append(r"C:\Users\dean\AppData\Roaming\Python\Python314\site-packages")
from scipy.optimize import linear_sum_assignment


def stage_of(name, status):
    return "midstream" if status == "Midstream" or name.rstrip().lower().endswith("midstream") else "upstream"


def cnk(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower().replace("ltd", "").replace("limited", "").replace("pty", ""))


# one-to-one assignment per stage: name similarity + company similarity + state agreement
out, low = [None] * len(rows), []
for stage in ("upstream", "midstream"):
    ri = [i for i, r in enumerate(rows) if stage_of(r[0], r[3]) == stage]
    dj = [d for d in db if d[1] == stage]
    M = np.zeros((len(ri), len(dj)))
    for a_, i in enumerate(ri):
        name, cos, mins, status, state = rows[i]
        nm = re.sub(r"\s*-\s*Midstream\s*$", "", name, flags=re.I)
        for b_, d in enumerate(dj):
            M[a_, b_] = (difflib.SequenceMatcher(None, nk(nm), nk(d[2])).ratio() + 0.5 * difflib.SequenceMatcher(None, cnk(cos.split(",")[0]), cnk(d[6])).ratio()
                         + (0.05 if (d[3] or "").split(",")[0].strip() == state else 0))
    r_, c_ = linear_sum_assignment(-M)
    for a_, b_ in zip(r_, c_):
        i = ri[a_]
        name, cos, mins, status, state = rows[i]
        out[i] = (name, stage, status, state, dj[b_], M[a_, b_])
        if M[a_, b_] < 1.2:
            low.append((name, dj[b_][2], round(float(M[a_, b_]), 2)))
print("matched", len(out), "of", len(rows), "| distinct DB rows:", len({o[4][0] for o in out}))
print("low-confidence matches (review):"); [print("  ", x) for x in low]
# compare statuses (upstream, new projects only)
MAP = {"Operating": "PRODUCER", "Construction": "DEVELOPMENT", "Pre Construction": "DEVELOPMENT", "Feasibility Study": "DEVELOPMENT", "Pre Feasibility Study": "EXPLORATION", "Scoping Study": "EXPLORATION", "Care and Maintenance": "CARE_AND_MAINTENANCE"}
diff = [(n, s, d[5], MAP.get(s)) for n, st, s, _, d, _ in out if st == "upstream" and d[5] and MAP.get(s) and d[5] != MAP[s]]
print(f"\nmy status vs Austrade's own label (mapped): {len(diff)} differ")
for n, s, mine, theirs in diff: print(f"   {n[:48]:48s} Austrade '{s}' -> {theirs:11s} | mine {mine}")
if "--run" in sys.argv:
    c.execute("ALTER TABLE core.project_prospectus ADD COLUMN IF NOT EXISTS report_status text, ADD COLUMN IF NOT EXISTS report_companies text, ADD COLUMN IF NOT EXISTS report_minerals text")
    c.execute("COMMENT ON COLUMN core.project_prospectus.report_status IS 'Project Status as shown in Austrade''s interactive Prospectus report table (read 2026-10-30): Operating, Construction, Pre Construction, Feasibility Study, Pre Feasibility Study, Scoping Study, Care and Maintenance, Midstream'")
    for (name, cos, mins, status, state), (n, stage, s, st, d, sc) in zip(rows, out):
        c.execute("UPDATE core.project_prospectus SET report_status=%s, report_companies=%s, report_minerals=%s WHERE prospectus_project_id=%s", (status, cos, mins or None, d[0]))
    c.execute("SELECT count(*), count(report_status) FROM core.project_prospectus")
    print("filled:", c.fetchone()); g.commit(); print("COMMITTED")
else:
    g.rollback(); print("DRY - nothing written")
