"""Monthly refresh of the IMF PCPS and World Bank Pink Sheet price series in markets.prices (interzona_cm).

Reads the two workbooks the October 2026 load used (same layout), matches each column to its existing markets.price_series row by
(source, source_series_code) and:
  * inserts months that are not in the database yet (the cm_app_write role may INSERT only);
  * REPORTS values the publisher has revised for months already stored (never overwrites them; apply by hand if wanted);
  * prints the series summary changes (last_period, n_observations) that the start screen reads, as SQL for an admin to run,
    because cm_app_write cannot UPDATE markets.price_series.
Usage:
  python refresh_prices.py [--imf PATH] [--wb PATH]          dry run: parse, compare, print, write nothing
  python refresh_prices.py [--imf PATH] [--wb PATH] --run    insert the new months (one transaction)
Default paths are the files in D:\\CriticalMineralsDB\\Documents\\Market data\\prices. Save each new download under a dated name
(e.g. IMF_PCPS_external_data_2026-11.xlsx) and pass it with --imf / --wb, so earlier files stay as evidence.
"""
import argparse, datetime, os, re, sys, io
import openpyxl, psycopg2
from psycopg2.extras import execute_values

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = r"D:\CriticalMineralsDB\Documents\Market data\prices"
ap = argparse.ArgumentParser()
ap.add_argument("--imf", default=os.path.join(BASE, "IMF_PCPS_external_data.xlsx"))
ap.add_argument("--wb", default=os.path.join(BASE, "WB_CMO_Historical_Monthly.xlsx"))
ap.add_argument("--run", action="store_true")
args = ap.parse_args()
TAG = "claude_prices_refresh_" + datetime.date.today().strftime("%Y%m%d")

ENV = {}
for l in open(r"C:\Users\dean\critical-minerals-ai\.env.local", encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"')

# Columns loaded in October 2026 (load_prices.py), by source series code.
WB_CODES = ["Coal, Australian", "Coal, South African", "Phosphate rock", "Potassium chloride", "Aluminum", "Iron ore, cfr spot", "Copper", "Lead", "Tin",
            "Nickel", "Zinc", "Gold", "Platinum", "Silver"]
IMF_CODES = ["PURAN", "PCOBA", "PPALLA", "PPLAT", "PGOLD", "PSILVER", "PCOPP", "PNICK", "PTIN", "PZINC", "PLEAD", "PALUM", "PIORECR", "PCOALAU", "PCOALSA_USD"]


def mdate(y, m):
    s = datetime.date(y, m, 1)
    return s, datetime.date(y + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1)


def num(x):
    if x is None: return None
    if isinstance(x, (int, float)): return float(x)
    try: return float(str(x).strip().replace(",", ""))
    except ValueError: return None


def parse_wb(path):
    rows = list(openpyxl.load_workbook(path, read_only=True, data_only=True)["Monthly Prices"].iter_rows(values_only=True))
    names = rows[4]
    out = {}
    for j, n in enumerate(names):
        key = re.sub(r"[\s\*]+$", "", str(n or "")).strip()
        if key not in WB_CODES: continue
        vals = {}
        for r in rows[6:]:
            m = re.match(r"^(\d{4})M(\d{2})$", str(r[0] or ""))
            v = num(r[j])
            if m and v is not None: vals[mdate(int(m[1]), int(m[2]))] = v
        out[("WORLD_BANK_PINK_SHEET", key)] = vals
    return out


def parse_imf(path):
    rows = list(openpyxl.load_workbook(path, read_only=True, data_only=True)["External"].iter_rows(values_only=True))
    hdr = rows[0]
    out = {}
    for code in IMF_CODES:
        j = hdr.index(code)
        vals = {}
        for r in rows[4:]:
            m = re.match(r"^(\d{4})M(\d{1,2})$", str(r[0] or ""))
            v = num(r[j])
            if m and v is not None: vals[mdate(int(m[1]), int(m[2]))] = v
        out[("IMF_PCPS", code)] = vals
    return out


fresh = {**parse_wb(args.wb), **parse_imf(args.imf)}
missing = [k for k in [("WORLD_BANK_PINK_SHEET", c) for c in WB_CODES] + [("IMF_PCPS", c) for c in IMF_CODES] if k not in fresh]
if missing: sys.exit(f"columns not found in the workbooks (layout changed?): {missing}")

conn = psycopg2.connect(host=ENV["PGHOST"], port=ENV["PGPORT"], dbname=ENV["PGDATABASE"], user=ENV["PGUSER_WRITE"], password=ENV["PGPASSWORD_WRITE"], connect_timeout=30)
cur = conn.cursor()
new_rows, revisions, summary = [], [], []
for (source, code), vals in sorted(fresh.items()):
    cur.execute("SELECT series_id FROM markets.price_series WHERE source = %s AND source_series_code = %s AND frequency = 'monthly' AND is_active", (source, code))
    hit = cur.fetchall()
    if len(hit) != 1: sys.exit(f"expected one series for {source} {code}, found {len(hit)}")
    sid = hit[0][0]
    cur.execute("SELECT period_start, value FROM markets.prices WHERE series_id = %s", (sid,))
    have = {r[0]: float(r[1]) for r in cur.fetchall() if r[1] is not None}
    add = [(sid, s, e, v, None, None, False, None, TAG) for (s, e), v in sorted(vals.items()) if s not in have]
    for (s, e), v in vals.items():
        if s in have and abs(have[s] - v) > 1e-6 * max(1.0, abs(v)):
            revisions.append((source, code, s.isoformat(), have[s], v))
    new_rows += add
    last = max(e for (s, e) in vals) if vals else None
    summary.append((sid, source, code, len(add), last, len(set(have) | {s for (s, _) in vals})))

print(f"workbooks: IMF {os.path.basename(args.imf)} | WB {os.path.basename(args.wb)}")
for sid, source, code, n_add, last, n_total in summary:
    print(f"  {source:22} {code:20} new months {n_add:3}  latest {last}  total {n_total}")
print(f"new monthly rows: {len(new_rows)}; revised values (reported, not applied): {len(revisions)}")
for r in revisions[:40]: print("  revision", r)
latest = {src: max(l for _, s, _, _, l, _ in summary if s == src) for src in ("IMF_PCPS", "WORLD_BANK_PINK_SHEET")}
print("latest month by source:", {k: str(v) for k, v in latest.items()})

if args.run and new_rows:
    execute_values(cur, "INSERT INTO markets.prices (series_id, period_start, period_end, value, value_low, value_high, is_estimate, note, created_by) VALUES %s ON CONFLICT (series_id, period_start) DO NOTHING", new_rows, page_size=500)
    conn.commit()
    print(f"COMMITTED {len(new_rows)} rows tagged {TAG}")
else:
    conn.rollback()
    print("DRY RUN - nothing written" if not args.run else "nothing new to write")
if any(n for _, _, _, n, _, _ in summary):
    print("\n-- series summary update for an admin (cm_app_write cannot UPDATE markets.price_series):")
    for sid, source, code, n_add, last, n_total in summary:
        if n_add:
            print(f"UPDATE markets.price_series SET last_period = '{last}', n_observations = {n_total} WHERE series_id = {sid};")
conn.close()
