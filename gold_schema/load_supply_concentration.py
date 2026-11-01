"""Supply concentration from the USGS Mineral Commodity Summaries 2026 world tables -> gold (markets schema).

Reads the same MCS2026_Commodities_Data.csv that already feeds markets.price_series (source USGS_MCS_2026), keeps the World production / reserves / capacity tables of the
44 commodities USGS flags as critical, and builds:
  markets.mcs_world_raw                    every kept row, as published (value text kept), with parse result and any correction
  markets.supply_concentration             one row per commodity x stage x year: world total, top countries' shares, HHI, coverage, flags
  markets.supply_concentration_countries   one row per country in each group, with its share

Verified before loading against the MCS 2026 PDF (v1.3, May 2026, already in the document library): see CORRECTIONS for the few values the CSV has that the PDF revised.
Run with --dry to do everything and roll back."""
import csv, os, re, sys, time, collections, math
import psycopg2
sys.stdout.reconfigure(encoding="utf8")

DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
CSVF = r"D:\CriticalMineralsDB\Documents\Market data\prices\MCS2026_Commodities_Data.csv"
TAG = "claude_mcs_concentration_20261024"
SOURCE = "USGS_MCS_2026_WORLD"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# Values the data-release CSV has that the later PDF (v1.3, May 2026) revised; the PDF is used. (commodity, statistic, year, country) -> (new text, why)
CORRECTIONS = {
    ("Rare Earths", "Reserves", 2025, "Brazil"): ("11,000,000", "PDF v1.3 gives 11,000,000 (CSV 21,000,000); the PDF note says Brazil reserves were revised and its world total fell by the same 10 million"),
    ("Rare Earths", "Reserves", 2025, "World total"): (">75,000,000", "PDF v1.3 gives >75,000,000 (CSV >85,000,000)"),
    ("Manganese", "Reserves", 2025, "World total"): ("1,800,000", "PDF v1.3 gives 1,800,000 (CSV 1,700,000)"),
    ("Zinc", "Production", 2024, "India"): ("870", "PDF v1.3 gives 870 (CSV 866)"),
    ("Zinc", "Production", 2024, "Kazakhstan"): ("380", "PDF v1.3 gives 380 (CSV 375)"),
}
# Commodities whose world tables are split by product or have no country breakdown, so a single concentration figure would mislead.
NOT_COMPUTED = {
    "Boron": "figures are split across many product forms (crude ore, borates, compounds) that are not additive",
    "Silicon": "ferrosilicon and silicon metal are separate products and the CSV world total could not be matched to the PDF",
    "Scandium": "only a world figure is published, no country breakdown",
    "Cesium": "reserves are given only as a statement about four countries",
    "Rubidium": "reserves are given only as a statement about four countries",
}


def parse(v):
    """-> (number or None, kind). kind: number, lower_bound, withheld, na, small, not_applicable, range, text, blank"""
    s = (v or "").strip().replace(",", "")
    if s == "": return None, "blank"
    if s in ("—", "–", "--"): return 0.0, "zero"
    if re.fullmatch(r"\d+(\.\d+)?", s): return float(s), "number"
    if s == "W": return None, "withheld"
    if s == "NA": return None, "na"
    if s == "s": return None, "less_than_half_unit"
    if s == "XX": return None, "not_applicable"
    if re.fullmatch(r">\d+(\.\d+)?", s): return float(s[1:]), "lower_bound"
    if re.fullmatch(r"\d+(\.\d+)? ?- ?\d+(\.\d+)?", s): return None, "range"
    return None, "text"


def norm_detail(d):
    d = re.sub(r"[:,]? ?rounded$", "", (d or "").strip())
    return d.strip().lower()


def stage_of(stat, detail):
    d = detail.lower()
    if stat == "Reserves": return "reserves"
    if stat == "Capacity": return "capacity"
    if "mine" in d or "bauxite" in d: return "mine_production"
    if "refinery" in d: return "refinery_production"
    if "smelter" in d: return "smelter_production"
    if "primary" in d: return "primary_production"
    if "sponge" in d: return "sponge_production"
    return "production"


# ---- read -------------------------------------------------------------------------------------------------------------------------------------
rows = []
with open(CSVF, encoding="cp1252", errors="replace", newline="") as f:
    for r in csv.DictReader(f):
        sec = r["Section"].replace("\ufffd", "-")
        if not sec.startswith("World"): continue
        if r["Statistics"] not in ("Production", "Reserves", "Capacity"): continue
        if r["Is critical mineral 2025"] != "Yes": continue
        r["Section"] = sec
        r["Year"] = int(r["Year"])
        rows.append(r)
log("critical world rows read:", len(rows), "commodities:", len({r["Commodity"] for r in rows}))

raw = []
for r in rows:
    val = r["Value"]
    corr = None
    k = (r["Commodity"], r["Statistics"], r["Year"], r["Country"])
    if k in CORRECTIONS:
        corr = f"CSV value {val or '(blank)'} replaced by {CORRECTIONS[k][0]}: {CORRECTIONS[k][1]}"
        val = CORRECTIONS[k][0]
    num, kind = parse(val)
    raw.append(dict(r, value_text=(r["Value"] or "").strip(), final_text=(val or "").strip(), num=num, kind=kind, corr=corr, dn=norm_detail(r["Statistics_detail"])))
log("corrections applied:", sum(1 for x in raw if x["corr"]))
assert sum(1 for x in raw if x["corr"]) == len(CORRECTIONS), "a correction did not match a row"

# ---- groups -----------------------------------------------------------------------------------------------------------------------------------
groups = collections.OrderedDict()
for x in raw:
    groups.setdefault((x["Commodity"], x["Statistics"], x["dn"], x["Unit"], x["Year"]), []).append(x)

out_groups, out_countries, skipped = [], [], []
for (com, stat, dn, unit, year), g in groups.items():
    world = [x for x in g if x["Country"] == "World total"]
    named = [x for x in g if x["Country"] not in ("World total", "Other countries")]
    other = [x for x in g if x["Country"] == "Other countries"]
    if com in NOT_COMPUTED:
        skipped.append((com, stat, dn, year, NOT_COMPUTED[com])); continue
    if len(named) < 3:
        if named: skipped.append((com, stat, dn, year, f"only {len(named)} countries listed"))
        continue
    stage = stage_of(stat, dn)
    if stage == "production" and ("ferrosilicon" in dn or "silicon metal" in dn):
        continue
    nums = [(x["Country"], x["num"]) for x in named if x["kind"] in ("number", "zero") and x["num"] is not None]
    n_listed, n_fig = len(named), len(nums)
    named_sum = sum(v for _, v in nums)
    other_num = sum(x["num"] for x in other if x["kind"] == "number") if other else 0.0
    w = world[0] if world else None
    w_exact = w["num"] if w and w["kind"] == "number" else None
    w_lower = w["num"] if w and w["kind"] == "lower_bound" else None
    flags = []
    if w_exact and named_sum + other_num <= 1.05 * w_exact:   # USGS rounds world totals to two or three significant figures
        denom = max(w_exact, named_sum + other_num)
        basis = "reported world total" if denom == w_exact else "sum of the countries listed (the reported world total is rounded and slightly smaller)"
    elif w_exact:
        denom, basis = named_sum + other_num, "sum of the countries listed (the reported world total is smaller than their sum)"
        flags.append("reported world total is below the sum of the countries")
    else:
        denom, basis = named_sum + other_num, "sum of the countries listed"
        if w_lower: flags.append("world total published only as a lower bound (>%s)" % f"{w_lower:,.0f}")
        elif not w: flags.append("no world total published")
        covers_lower_bound = bool(w_lower) and named_sum + other_num >= 0.85 * w_lower
        if n_fig < 0.7 * n_listed and not covers_lower_bound:
            skipped.append((com, stat, dn, year, f"only {n_fig} of {n_listed} listed countries have a figure and no world total to measure them against")); continue
    if denom <= 0 or n_fig < 3:
        skipped.append((com, stat, dn, year, "too few countries with a figure")); continue
    missing = [x["Country"] for x in named if x["kind"] not in ("number", "zero")]
    withheld = [x["Country"] for x in named if x["kind"] == "withheld"]
    if withheld: flags.append("withheld by USGS to avoid disclosing company data: " + ", ".join(withheld))
    qual = [x["Country"] + " (" + x["final_text"] + ")" for x in named if x["kind"] in ("text", "lower_bound", "range", "less_than_half_unit")]
    zeros = [x["Country"] for x in named if x["kind"] == "zero"]
    if zeros: flags.append("USGS shows zero for: " + ", ".join(zeros))
    if qual: flags.append("not a plain number: " + ", ".join(qual))
    if "United States" in missing and "United States" not in withheld: flags.append("United States has no figure")
    if len(missing) > 0: flags.append(f"{len(missing)} of {n_listed} listed countries have no figure (not available, withheld or blank)")
    if w and "Excludes U.S." in (w["Notes"] or ""): flags.append("world total excludes U.S. production")
    ranked = sorted(nums, key=lambda t: -t[1])
    shares = [(c, 100.0 * v / denom) for c, v in ranked]
    top = shares + [("", 0.0)] * 3
    hhi = sum(s * s for _, s in shares)
    gid = len(out_groups) + 1
    out_groups.append(dict(group_id=gid, commodity=com, stage=stage, statistic=stat, detail=named[0]["Statistics_detail"].strip(), unit=unit, data_year=year,
                           is_estimate=(year == 2025 and stat in ("Production", "Capacity")) or stat == "Reserves", n_listed=n_listed, n_fig=n_fig,
                           denominator=denom, basis=basis, world_reported=(w_exact if w_exact else w_lower), world_lower=bool(w_lower and not w_exact),
                           named_sum=named_sum, other_listed=other_num, coverage=100.0 * named_sum / denom,
                           t1=top[0][0], s1=top[0][1], t2=top[1][0], s2=top[1][1], s3=sum(s for _, s in shares[:3]), hhi=hhi, flags="; ".join(flags) or None))
    for i, (c, v) in enumerate(ranked, 1):
        out_countries.append((gid, c, v, 100.0 * v / denom, i, "zero" if v == 0 else "listed"))
    for x in named:
        if x["kind"] not in ("number", "zero"):
            out_countries.append((gid, x["Country"], None, None, None, x["kind"] if x["kind"] != "text" else "text: " + x["final_text"][:80]))
    if other and other[0]["kind"] == "number":
        out_countries.append((gid, "Other countries", other[0]["num"], 100.0 * other[0]["num"] / denom, None, "other"))
log("groups computed:", len(out_groups), "country rows:", len(out_countries), "skipped groups:", len(skipped))
for s in skipped: log("  skipped:", s)

# ---- print the review table ------------------------------------------------------------------------------------------------------------------
print()
print(f"{'commodity':30} {'stage':20} {'yr':4} {'top1':18} {'s1':>5} {'top3':>5} {'hhi':>6} {'cov':>5} basis/flags")
for g in out_groups:
    if g["data_year"] == 2025 or g["statistic"] == "Reserves":
        print(f"{g['commodity'][:30]:30} {g['stage']:20} {g['data_year']:4} {g['t1'][:18]:18} {g['s1']:5.1f} {g['s3']:5.1f} {g['hhi']:6.0f} {g['coverage']:5.1f} {g['basis'][:20]} | {(g['flags'] or '')[:90]}")

if "--review" in sys.argv:
    sys.exit(0)

# ---- load ------------------------------------------------------------------------------------------------------------------------------------
DDL = """
CREATE TABLE IF NOT EXISTS markets.mcs_world_raw (
  raw_id bigserial PRIMARY KEY, commodity text NOT NULL, mcs_chapter text, section text, statistic text NOT NULL, detail text, country text NOT NULL, unit text, data_year int NOT NULL,
  value_text text, value_num numeric, value_kind text NOT NULL, notes text, correction_note text, source_system varchar NOT NULL, is_active boolean NOT NULL DEFAULT true,
  created_by varchar NOT NULL, created_date timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS markets.supply_concentration (
  group_id serial PRIMARY KEY, commodity text NOT NULL, stage text NOT NULL, statistic text NOT NULL, detail text, unit text, data_year int NOT NULL, is_estimate boolean,
  n_countries_listed int, n_countries_with_figure int, denominator numeric, denominator_basis text, world_total_reported numeric, world_total_is_lower_bound boolean,
  named_countries_sum numeric, other_countries_listed numeric, named_coverage_pct numeric, top1_country text, top1_share_pct numeric, top2_country text, top2_share_pct numeric,
  top3_share_pct numeric, hhi_named numeric, flags text, source_system varchar NOT NULL, is_active boolean NOT NULL DEFAULT true, created_by varchar NOT NULL, created_date timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS markets.supply_concentration_countries (
  id bigserial PRIMARY KEY, group_id int NOT NULL REFERENCES markets.supply_concentration(group_id), country text NOT NULL, value_num numeric, share_pct numeric, rank int, row_kind text,
  created_by varchar NOT NULL, created_date timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS supply_conc_commodity_idx ON markets.supply_concentration (commodity, stage, data_year);
CREATE INDEX IF NOT EXISTS supply_conc_countries_group_idx ON markets.supply_concentration_countries (group_id);
COMMENT ON TABLE markets.supply_concentration IS 'World supply concentration per commodity, stage and year from the USGS Mineral Commodity Summaries 2026 world tables (critical minerals). Shares are of the reported world total where there is one; HHI uses the named countries only, so it is a lower bound.';
"""
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor()
c.execute(DDL)
c.execute("SELECT count(*) FROM markets.supply_concentration WHERE created_by = %s", (TAG,)); assert c.fetchone()[0] == 0, "already loaded"
for x in raw:
    c.execute("""INSERT INTO markets.mcs_world_raw (commodity, mcs_chapter, section, statistic, detail, country, unit, data_year, value_text, value_num, value_kind, notes, correction_note, source_system, created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (x["Commodity"], x["MCS chapter"], x["Section"], x["Statistics"], x["Statistics_detail"], x["Country"], x["Unit"].strip(), x["Year"], x["final_text"] or None, x["num"], x["kind"],
               (x["Notes"] or "")[:1500] or None, x["corr"], SOURCE, TAG))
gid_map = {}
for gr in out_groups:
    c.execute("""INSERT INTO markets.supply_concentration (commodity, stage, statistic, detail, unit, data_year, is_estimate, n_countries_listed, n_countries_with_figure, denominator, denominator_basis,
                   world_total_reported, world_total_is_lower_bound, named_countries_sum, other_countries_listed, named_coverage_pct, top1_country, top1_share_pct, top2_country, top2_share_pct,
                   top3_share_pct, hhi_named, flags, source_system, created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING group_id""",
              (gr["commodity"], gr["stage"], gr["statistic"], gr["detail"], gr["unit"].strip(), gr["data_year"], gr["is_estimate"], gr["n_listed"], gr["n_fig"], gr["denominator"], gr["basis"],
               gr["world_reported"], gr["world_lower"], gr["named_sum"], gr["other_listed"], round(gr["coverage"], 2), gr["t1"], round(gr["s1"], 2), gr["t2"] or None, round(gr["s2"], 2) if gr["t2"] else None,
               round(gr["s3"], 2), round(gr["hhi"], 1), gr["flags"], SOURCE, TAG))
    gid_map[gr["group_id"]] = c.fetchone()[0]
for (gid, country, v, s, rank, kind) in out_countries:
    c.execute("INSERT INTO markets.supply_concentration_countries (group_id, country, value_num, share_pct, rank, row_kind, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              (gid_map[gid], country, v, round(s, 3) if s is not None else None, rank, kind, TAG))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded, licence_status, caveats, evidence_location, evidence_date, is_active, created_by)
             SELECT %s, 'U.S. Geological Survey', 'Mineral Commodity Summaries 2026, world mine production, refinery production, capacity and reserves tables (critical minerals)', 'US public domain (USGS-authored)',
                    'https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits', false,
                    'Source: U.S. Geological Survey, Mineral Commodity Summaries 2026 (courtesy credit).', true, 'public domain',
                    'Estimates, not audited statistics: USGS withholds some company data (W), publishes world totals rounded, and 2025 production is an estimate. Reserves definitions differ by country. The data-release CSV pre-dates PDF v1.3 (May 2026); five values the PDF revised were taken from the PDF and are marked in markets.mcs_world_raw.correction_note.',
                    %s, CURRENT_DATE, true, %s
             WHERE NOT EXISTS (SELECT 1 FROM core.data_sources WHERE source_system = %s)""", (SOURCE, CSVF, TAG, SOURCE))
c.execute("GRANT SELECT ON markets.mcs_world_raw, markets.supply_concentration, markets.supply_concentration_countries TO cm_app_readonly")
c.execute("SELECT count(*) FROM markets.mcs_world_raw WHERE created_by=%s", (TAG,)); n1 = c.fetchone()[0]
c.execute("SELECT count(*) FROM markets.supply_concentration WHERE created_by=%s", (TAG,)); n2 = c.fetchone()[0]
c.execute("SELECT count(*) FROM markets.supply_concentration_countries WHERE created_by=%s", (TAG,)); n3 = c.fetchone()[0]
log("inserted raw", n1, "groups", n2, "country rows", n3)
assert (n1, n2, n3) == (len(raw), len(out_groups), len(out_countries))
if DRY:
    g.rollback(); log("DRY RUN: rolled back")
else:
    g.commit(); log("COMMITTED")
    open(os.path.join(HERE, "..", "..", "mcs_concentration_rollback_20261024.sql"), "w").write(
        "-- Rollback for load_supply_concentration.py\nDELETE FROM markets.supply_concentration_countries WHERE created_by = '%s';\nDELETE FROM markets.supply_concentration WHERE created_by = '%s';\n"
        "DELETE FROM markets.mcs_world_raw WHERE created_by = '%s';\nDELETE FROM core.data_sources WHERE source_system = '%s' AND created_by = '%s';\n" % (TAG, TAG, TAG, SOURCE, TAG))
