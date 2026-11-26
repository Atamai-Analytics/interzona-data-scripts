"""Load critical-minerals start-ups and their latest funding rounds (2026-11-26).

Lead: Fundable infographic "40 critical minerals startups that raised" (Nov 2026; library doc 567). Fundable is NOT the source of any
value loaded here: every company and round was checked against the company's own announcement or a news report quoting it
(startup_funding_verified_20261126.json, one object per company, source_url per round). Rounds we could not verify are not loaded.

- New table core.company_funding_rounds (one row per announced round; amount_usd NULL when undisclosed).
- New companies in core.companies (company_type 'Technology start-up', website, HQ country, primary commodity when there is one);
  an existing company (matched by name) only has NULL fields filled.
- core.company_commodities for each company's main commodities.
- core.data_sources row COMPANY_FUNDING_ANNOUNCEMENTS.

Backup: startup_funding_backup_<stamp>.csv (old values of filled fields on existing companies).
Rollback: python startup_funding_20261126.py --undo <backup.csv>  (deletes the rounds, companies, commodity links and data_sources row
created with this tag and restores the filled fields).
Usage: python startup_funding_20261126.py [--dry | --undo backup.csv]
"""
import csv, json, os, re, sys, time, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "startup_funding_20261126"
DATA = os.path.join(HERE, "startup_funding_verified_20261126.json")

COMMODITY = {"rare earths": "REE", "neodymium": "Nd", "dysprosium": "Dy", "lithium": "Li", "copper": "Cu", "nickel": "Ni", "cobalt": "Co",
             "magnesium": "Mg", "aluminium": "Al", "manganese": "Mn", "titanium": "Ti", "scandium": "Sc", "gallium": "Ga", "germanium": "Ge",
             "silver": "Ag", "gold": "Au", "zinc": "Zn", "silicon": "Si", "iron": "Fe", "vanadium": "V", "tungsten": "W", "platinum": "Pt",
             "palladium": "Pd", "graphite": "Graphite"}

DDL = """
CREATE TABLE IF NOT EXISTS core.company_funding_rounds (
  funding_round_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id         integer NOT NULL REFERENCES core.companies(company_id),
  round_type         text,              -- as the company describes it: Seed, Series A, Series B2, equity, ...
  amount_usd         numeric,           -- NULL when undisclosed
  amount_original    numeric,
  currency_original  text,
  announced_date     date,
  lead_investors     text,
  segment            text,              -- MAGNETS / RECYCLING / REFINING_PROCESSING / EXTRACTION_TECH / EXPLORATION_TECH / MOTORS
  activity           text,              -- what the company does, our words
  source_url         text NOT NULL,     -- company announcement or news report quoting the company
  verification       text NOT NULL,     -- COMPANY_ANNOUNCEMENT / NEWS_REPORT
  notes              text,
  is_active          boolean NOT NULL DEFAULT true,
  created_by         varchar NOT NULL DEFAULT CURRENT_USER,
  created_date       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS company_funding_rounds_company_idx ON core.company_funding_rounds (company_id);
COMMENT ON TABLE core.company_funding_rounds IS 'Announced private funding rounds of critical-minerals technology companies; each row checked against the company announcement or a news report (source_url). Not a complete record of sector financing.';
"""

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
    c.execute("DELETE FROM core.company_funding_rounds WHERE created_by = %s", (TAG,))
    print("rounds deleted", c.rowcount)
    c.execute("DELETE FROM core.company_commodities WHERE created_by = %s", (TAG,))
    print("commodity links deleted", c.rowcount)
    c.execute("DELETE FROM core.companies WHERE created_by = %s", (TAG,))
    print("companies deleted", c.rowcount)
    for r in rows:
        c.execute(f"UPDATE core.companies SET {r['field']} = %s, modified_by = %s, modified_date = %s WHERE company_id = %s",
                  (r["old"] or None, r["modified_by"] or None, r["modified_date"] or None, int(r["company_id"])))
    print("fields restored", len(rows))
    c.execute("DELETE FROM core.data_sources WHERE created_by = %s", (TAG,))
    g.commit(); print("undone (table core.company_funding_rounds kept; drop it by hand if empty and unwanted)"); sys.exit()

items = json.load(open(DATA, encoding="utf-8"))
c.execute("SELECT commodity_symbol, commodity_id FROM core.commodities WHERE is_active AND commodity_symbol IS NOT NULL AND parent_commodity_id IS NULL")
SYM = dict(c.fetchall()); SYM["Graphite"] = 994


def country_id(name):
    c.execute("""SELECT j.jurisdiction_id FROM core.jurisdictions j LEFT JOIN core.country_aliases a ON a.iso3 = j.iso_code3
                 WHERE j.level = 'COUNTRY' AND (lower(j.name) = lower(%s) OR a.alias_lower = lower(%s)) LIMIT 1""", (name, name))
    r = c.fetchone()
    assert r, f"country not found: {name}"
    return r[0]


def norm(s):
    return re.sub(r"\b(inc|ltd|limited|llc|corp|corporation|gmbh|sas|pvt|private|plc|co)\b\.?", "", s.lower()).replace(",", "").strip()


plan = []
for it in items:
    assert it["source_url"].startswith("http"), it["name"]
    assert it["verification"] in ("COMPANY_ANNOUNCEMENT", "NEWS_REPORT", "REGULATORY_FILING"), it["name"]
    if it.get("convert"):   # announced in another currency: convert at the BIS monthly average for the announcement month
        c.execute("""SELECT rate_per_usd, period_start::date FROM markets.fx_rates WHERE currency = %s AND frequency = 'monthly'
                     AND period_start <= %s::date ORDER BY period_start DESC LIMIT 1""", (it["currency_original"], it["announced_date"]))
        rate, month = c.fetchone()
        it["amount_usd"] = round(float(it["amount_original"]) / float(rate), -4)
        it["notes"] = (it.get("notes") or "") + f" USD converted at the BIS monthly average {it['currency_original']} rate for {month:%b %Y} ({float(rate):.4f} per USD)."
    syms = [COMMODITY[m] for m in it.get("commodities", [])]
    c.execute("SELECT company_id, name, website, hq_jurisdiction_id, company_type, primary_commodity_id FROM core.companies WHERE is_active")
    match = [r for r in c.fetchall() if norm(r[1]) == norm(it["name"])]
    assert len(match) <= 1, f"ambiguous company {it['name']}: {match}"
    plan.append((it, match[0] if match else None, [SYM[s] for s in syms], country_id(it["hq_country"]) if it["hq_country"] else None))

print(f"{len(plan)} companies: {sum(1 for p in plan if p[1])} existing, {sum(1 for p in plan if not p[1])} new;",
      f"{sum(1 for p in plan if p[0]['amount_usd'] is not None)} rounds with an amount, total US${sum(p[0]['amount_usd'] or 0 for p in plan)/1e6:,.1f}M")
for it, m, cids, jid in plan:
    print(f"  {'EXIST' if m else 'NEW  '} {it['name'][:34]:34} {(it['hq_country'] or '-')[:14]:14} {it['round_type'][:16]:16} "
          f"{('$%.1fM' % (it['amount_usd']/1e6)) if it['amount_usd'] is not None else 'undisclosed':>11} {it['announced_date']} {it['segment']}"
          f"{'' if m else ''} {it['verification'][:4]}")
if DRY:
    print("dry run - nothing written"); sys.exit()

c.execute(DDL)
backup = os.path.join(HERE, f"startup_funding_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(backup, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["company_id", "field", "old", "modified_by", "modified_date"])
    for it, m, cids, jid in plan:
        primary = cids[0] if len(cids) == 1 else None
        if m:
            cid = m[0]
            c.execute("SELECT modified_by, modified_date FROM core.companies WHERE company_id = %s", (cid,)); mb, md = c.fetchone()
            for field, old, new in (("website", m[2], it["website"]), ("hq_jurisdiction_id", m[3], jid), ("company_type", m[4], "Technology start-up"),
                                    ("primary_commodity_id", m[5], primary)):
                if old is None and new is not None:
                    w.writerow([cid, field, "", mb or "", md or ""])
                    c.execute(f"UPDATE core.companies SET {field} = %s, modified_by = %s, modified_date = now() WHERE company_id = %s", (new, TAG, cid))
        else:
            c.execute("""INSERT INTO core.companies (name, short_name, hq_jurisdiction_id, company_type, primary_commodity_id, website, is_active, created_by, created_date)
                         VALUES (%s, %s, %s, 'Technology start-up', %s, %s, true, %s, now()) RETURNING company_id""",
                      (it["name"], it.get("short_name"), jid, primary, it["website"], TAG))
            cid = c.fetchone()[0]
        for i, k in enumerate(cids):
            c.execute("SELECT 1 FROM core.company_commodities WHERE company_id = %s AND commodity_id = %s AND is_active", (cid, k))
            if not c.fetchone():
                c.execute("""INSERT INTO core.company_commodities (company_id, commodity_id, commodity_role, is_active, created_by, created_date)
                             VALUES (%s, %s, %s, true, %s, now())""", (cid, k, "PRIMARY" if i == 0 else "SECONDARY", TAG))
        c.execute("""INSERT INTO core.company_funding_rounds (company_id, round_type, amount_usd, amount_original, currency_original, announced_date,
                     lead_investors, segment, activity, source_url, verification, notes, created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (cid, it["round_type"], it["amount_usd"], it.get("amount_original"), it.get("currency_original"), it["announced_date"],
                   it.get("lead_investors"), it["segment"], it["activity"], it["source_url"], it["verification"], it.get("notes"), TAG))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text,
             is_loaded, licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES ('COMPANY_FUNDING_ANNOUNCEMENTS', 'Company press releases and news reports (one source URL per round)',
             'Critical-minerals start-up funding rounds, Nov 2025 - Nov 2026 (core.company_funding_rounds; companies in core.companies)',
             'Facts only (company names, round sizes, dates, investors) taken from public announcements; no text reproduced', NULL, false,
             'Source: company announcements (link per round)', true,
             'Cleared: public facts from the companies'' own announcements or news reports quoting them; Fundable''s infographic used only as a lead, not as a source.',
             'Latest round per company in the 12 months to Nov 2026 only; not a complete record of sector financing; amounts as announced (some include non-equity).',
             'gold_schema/startup_funding_verified_20261126.json', '2026-11-26', true, %s, now())""", (TAG,))
g.commit()
print("loaded; backup", backup)
