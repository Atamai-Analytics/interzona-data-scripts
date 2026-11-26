"""Monthly refresh routine for interzona_cm and app.interzona.ai (built 25 Nov 2026).

What it does, in order, and writes a short report to D:\\CriticalMineralsDB\\Documents\\Monthly_Refresh\\monthly_refresh_<date>.md:
  1. Prices: loads any new months from the newest World Bank Pink Sheet workbook in the prices folder (refresh_prices.py; the IMF
     series are skipped while held back) and updates the series summary rows. The download itself is a manual step: save the new
     CMO-Historical-Data-Monthly.xlsx from https://www.worldbank.org/en/research/commodity-markets as
     WB_CMO_Historical_Monthly_<YYYY-MM>.xlsx in D:\\CriticalMineralsDB\\Documents\\Market data\\prices before running.
  2. Price ranges: re-publishes markets.price_outlook (critical-minerals-ai/evals/forecast/publish_outlook.py --if-new) when new months loaded.
  3. Coverage: rebuilds core.country_coverage (build_country_coverage.py) so the world coverage map matches the data.
  4. Review queue: the 25 project / occurrence statuses most worth re-checking this month (moving statuses, highest-profile first,
     least recently touched first). Mark one as checked by updating its status or modified_date; it then drops to the back of the queue.
  5. Follow-ups: outreach rows whose next-action date has passed (Documents\\Outreach\\Outreach_Tracker_*.xlsx).
  6. Optional (--gate): runs the 40-question pre-deploy gate against the live app.
Usage:
  python monthly_refresh.py            dry run: report what would change, write nothing to the database (report still written)
  python monthly_refresh.py --run      apply steps 1-3 and write the report
  python monthly_refresh.py --run --gate   also run the gate (about 10 minutes, uses model credits)
"""
import datetime, glob, os, re, subprocess, sys, io
import psycopg2

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RUN, GATE = "--run" in sys.argv, "--gate" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
APP = r"C:\Users\dean\critical-minerals-ai"
PRICES = r"D:\CriticalMineralsDB\Documents\Market data\prices"
OUT_DIR = r"D:\CriticalMineralsDB\Documents\Monthly_Refresh"
OUTREACH = r"D:\CriticalMineralsDB\Documents\Outreach"
TODAY = datetime.date.today()
PY = sys.executable

ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.lstrip().startswith("#"):
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
admin = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                         password=ENV["LITHODAT_DB_PASSWORD"], connect_timeout=30)
cur = admin.cursor()
report = [f"# Monthly refresh - {TODAY.isoformat()} ({'applied' if RUN else 'DRY RUN - nothing written to the database'})", ""]
todo = []


def run(cmd, cwd, timeout=3600):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---- 1. prices -------------------------------------------------------------------------------------------------------------------
report.append("## 1. Prices (World Bank Pink Sheet)")
files = sorted(glob.glob(os.path.join(PRICES, "WB_CMO_Historical_Monthly*.xlsx")), key=os.path.getmtime)
new_rows = 0
if not files:
    report.append("- No Pink Sheet workbook found."); todo.append("Download the World Bank Pink Sheet monthly file (see step 1 in the script header).")
else:
    wb = files[-1]
    cur.execute("SELECT max(period_start)::date FROM markets.prices p JOIN markets.price_series s USING (series_id) WHERE s.source='WORLD_BANK_PINK_SHEET' AND s.is_active")
    db_latest = cur.fetchone()[0]
    code, out = run([PY, "refresh_prices.py", "--wb", wb] + (["--run"] if RUN else []), HERE)
    m = re.search(r"new monthly rows: (\d+); revised values \(reported, not applied\): (\d+)", out)
    new_rows, revisions = (int(m[1]), int(m[2])) if m else (0, 0)
    report.append(f"- Workbook: {os.path.basename(wb)} (saved {datetime.date.fromtimestamp(os.path.getmtime(wb))}); latest month in the database before this run: {db_latest:%Y-%m}.")
    if code != 0:
        report.append(f"- ERROR from refresh_prices.py:\n```\n{out[-1500:]}\n```"); todo.append("Price refresh failed - see the error above.")
    elif new_rows == 0:
        report.append("- No new months in the workbook.")
        # The World Bank publishes month M early in month M+1 (about the 2nd-4th business day), so from the 5th the previous month should exist.
        first = TODAY.replace(day=1)
        prev = (first - datetime.timedelta(days=1)).replace(day=1)
        expected = prev if TODAY.day >= 5 else (prev - datetime.timedelta(days=1)).replace(day=1)
        if db_latest < expected:
            todo.append(f"Download the latest World Bank Pink Sheet (CMO-Historical-Data-Monthly.xlsx) and save it as WB_CMO_Historical_Monthly_{TODAY:%Y-%m}.xlsx in the prices folder, then run this again.")
    else:
        report.append(f"- {'Loaded' if RUN else 'Would load'} {new_rows} new monthly values.")
        if RUN:
            sql = [l for l in out.splitlines() if l.startswith("UPDATE markets.price_series SET last_period")]
            for s in sql: cur.execute(s)
            admin.commit()
            report.append(f"- Updated {len(sql)} series summary rows.")
    if revisions:
        report.append(f"- The publisher revised {revisions} earlier values; they are reported by refresh_prices.py and NOT applied (apply by hand if wanted).")
        todo.append(f"Review {revisions} World Bank price revisions (run refresh_prices.py for the list).")

# ---- 2. price ranges ----------------------------------------------------------------------------------------------------------------
report.append("\n## 2. Price ranges (markets.price_outlook)")
if RUN and new_rows:
    code, out = run([PY, os.path.join("evals", "forecast", "publish_outlook.py"), "--if-new"], APP)
    tail = [l for l in out.splitlines() if l.strip()][-3:]
    report.append(f"- publish_outlook.py exit {code}: " + " | ".join(tail))
    if code != 0: todo.append("publish_outlook.py failed - check evals/forecast/monthly_refresh.log or rerun by hand.")
else:
    cur.execute("SELECT to_char(max(as_of_month),'YYYY-MM') FROM markets.price_outlook")
    report.append(f"- Not re-run ({'no new prices' if RUN else 'dry run'}). Ranges are as of {cur.fetchone()[0]}. (The scheduled task CriticalMinerals-PriceOutlook-Monthly also runs on the 5th.)")

# ---- 3. coverage --------------------------------------------------------------------------------------------------------------------
report.append("\n## 3. World coverage table")
if RUN:
    code, out = run([PY, "build_country_coverage.py"], HERE, timeout=5400)
    report.append(f"- build_country_coverage.py exit {code}." + ("" if code == 0 else f"\n```\n{out[-1200:]}\n```"))
    if code != 0: todo.append("Coverage rebuild failed - see the error above.")
else:
    report.append("- Not rebuilt (dry run).")

# ---- 4. review queue ----------------------------------------------------------------------------------------------------------------
report.append("\n## 4. Status review queue (25 to re-check this month)")
cur.execute("""
  WITH p AS (
    SELECT 'project' AS kind, p.project_id AS id, p.name, coalesce(j.name, '') AS country, p.status,
           coalesce(p.modified_date, p.created_date)::date AS last_touched,
           (EXISTS (SELECT 1 FROM core.project_designations d WHERE d.project_id = p.project_id AND d.is_active))::int * 3
         + (EXISTS (SELECT 1 FROM core.project_prospectus x WHERE x.project_id = p.project_id))::int * 2
         + (EXISTS (SELECT 1 FROM core.resource_estimates r WHERE r.occurrence_id = p.occurrence_id AND r.is_active))::int * 2 AS priority
    FROM core.projects p LEFT JOIN core.jurisdictions j ON j.jurisdiction_id = p.jurisdiction_id
    WHERE p.is_active AND p.status IN ('DEVELOPMENT', 'EXPLORATION', 'CARE_AND_MAINTENANCE')),
  o AS (
    SELECT 'occurrence', o.occurrence_id, o.name, coalesce(o.country_name, ''), o.status, coalesce(o.modified_date, o.created_date)::date,
           (EXISTS (SELECT 1 FROM core.resource_estimates r WHERE r.occurrence_id = o.occurrence_id AND r.is_active))::int * 2 + 1
    FROM core.occurrences o
    WHERE o.is_active AND o.is_deposit AND o.status IN ('DEVELOPMENT', 'FEASIBILITY', 'CARE_AND_MAINTENANCE')
      AND EXISTS (SELECT 1 FROM core.resource_estimates r WHERE r.occurrence_id = o.occurrence_id AND r.is_active))
  SELECT * FROM (SELECT * FROM p UNION ALL SELECT * FROM o) x ORDER BY priority DESC, last_touched ASC, name LIMIT 25""")
rows = cur.fetchall()
report.append("| Kind | Id | Name | Country | Status | Last touched |\n|---|---|---|---|---|---|")
for k, i, n, c, s, t, _ in rows:
    report.append(f"| {k} | {i} | {n} | {c} | {s} | {t} |")
report.append("\nCheck each against the company's latest announcement; update the status (and comments with the source and date) where it has changed.")

# ---- 5. follow-ups ------------------------------------------------------------------------------------------------------------------
report.append("\n## 5. Outreach follow-ups due")
due = []
try:
    from openpyxl import load_workbook
    trk = sorted(glob.glob(os.path.join(OUTREACH, "Outreach_Tracker_*.xlsx")), key=os.path.getmtime)
    if trk:
        ws = load_workbook(trk[-1], read_only=True, data_only=True)["Outreach"]
        for r in list(ws.iter_rows(values_only=True))[1:]:
            org, status, last, nxt, nd = r[1], r[7], r[8], r[9], r[10]
            d = nd if isinstance(nd, datetime.date) else (datetime.date.fromisoformat(str(nd)[:10]) if nd and re.match(r"\d{4}-\d{2}-\d{2}", str(nd)) else None)
            if org and status in ("Sent", "Drafting", "Open question pending") and d and d <= TODAY:
                due.append(f"- {org}: {status} (last contact {last}); next: {nxt} (due {d})")
except Exception as e:
    due.append(f"- Could not read the tracker: {e}")
report += due or ["- None due."]
if [d for d in due if d.startswith("- ") and "Could not" not in d]: todo.append(f"{len(due)} outreach follow-ups are due (section 5).")

# ---- 6. gate ------------------------------------------------------------------------------------------------------------------------
report.append("\n## 6. Live gate")
if GATE:
    code, out = run([PY, os.path.join("evals", "run_evals.py"), "--base", "https://app.interzona.ai", "--set", "gate", "--label", f"monthly-{TODAY:%Y%m%d}", "--concurrency", "3"], APP, timeout=3600)
    m = re.search(r"Passed \*\*(\d+)/(\d+)\*\*", out)
    report.append(f"- {m[0] if m else 'no result line'} (exit {code}).")
    fails = re.findall(r"^### (\S+)", out, re.M)
    if fails: report.append("- Failing: " + ", ".join(fails)); todo.append(f"Gate failures to look at: {', '.join(fails)}.")
else:
    report.append("- Not run (add --gate).")

report.insert(2, "## Needs you\n" + ("\n".join(f"- {t}" for t in todo) if todo else "- Nothing.") + "\n")
os.makedirs(OUT_DIR, exist_ok=True)
path = os.path.join(OUT_DIR, f"monthly_refresh_{TODAY.isoformat()}{'' if RUN else '_dryrun'}.md")
open(path, "w", encoding="utf-8").write("\n".join(report) + "\n")
admin.close()
print("\n".join(report))
print("\nreport:", path)
