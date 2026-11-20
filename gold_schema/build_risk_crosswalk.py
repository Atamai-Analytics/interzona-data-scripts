"""Risk crosswalk: links each critical mineral and supply stage across the datasets the supply_disruption / supply_risk tools join:
  USGS MCS 2026 supply tables (markets.supply_concentration, commodity + stage)  ->  CEPII BACI HS6 codes (markets.trade_flows)
  ->  OECD export-restriction commodity names (markets.export_restrictions)  ->  price series (markets.price_series)
  ->  USGS facility commodity names and stages (core.facility_capacity).
Hand-built and reviewed 20 Nov 2026. Every name and code is checked against the database before anything is written.

Tables (rebuilt on each run):
  markets.risk_minerals        one row per mineral: labels, restriction names, price series (monthly; recent annual; historical annual), facility names, notes
  markets.risk_mineral_stages  one row per mineral x stage: USGS commodity/stage (NULL = trade-only stage), trade form, HS6 codes, facility stages, flags

Trade form: 'ore' (ores and concentrates), 'intermediate' (mattes, hydroxides, anodes, ferroalloys - what a mining country actually ships
when it does not export ore), 'refined' (metal or refined chemical). For mine-stage scenarios the HS list is what the mining country
EXPORTS from that stage, which for cobalt (DRC) and nickel (Indonesia) is mainly intermediates, not ore.
Usage: python -P build_risk_crosswalk.py [--dry]
"""
import os, sys, json
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")

GROUPED = ("HS 8112.92/8112.99 group gallium, germanium, hafnium, indium, niobium, rhenium and vanadium articles in one code: trade values cover all seven metals "
           "(2022-24 exporters: China 26%, Brazil 16% - mostly niobium -, USA 12%, Germany 10%), so these codes do NOT show who exports this metal; "
           "do not compute importer exposure from them - report only that the code is grouped")

# key: label, export-restriction commodity names, monthly price series, recent annual (USGS MCS 2021-25), historical annual (USGS DS140, nominal $/t), facility commodity names, notes
M = {
 "aluminium":  ("Aluminium (bauxite, alumina, metal)", ["Aluminium (bauxite)", "Aluminium"], 42, 77, None, ["Bauxite", "Alumina", "Aluminum"], None),
 "antimony":   ("Antimony", ["Antimony"], None, 72, 237, ["Antimony"], None),
 "arsenic":    ("Arsenic", ["Arsenic"], None, 73, 239, ["Arsenic"], None),
 "barite":     ("Barite", ["Barite"], None, 75, 241, ["Barite"], None),
 "beryllium":  ("Beryllium", ["Beryllium"], None, 78, 243, ["Beryllium"], "Beryl ore has no HS6 code of its own (HS 2617.90, not loaded): only beryllium metal trade is available."),
 "bismuth":    ("Bismuth", ["Bismuth"], None, 79, 245, ["Bismuth"], "HS 8106.00 covers bismuth metal, articles and scrap together."),
 "chromium":   ("Chromium (chromite, ferrochrome)", ["Chromium", "Ferroalloys"], None, 93, 247, ["Chromium"], None),
 "cobalt":     ("Cobalt", ["Cobalt"], 53, 103, 249, ["Cobalt"], "USGS MCS gives cobalt mine production only, not refinery output (China refines most of the world's cobalt); HS 8105.20 mixes mattes and intermediates with unwrought cobalt metal."),
 "copper":     ("Copper", ["Copper"], 44, None, None, ["Copper"], None),
 "fluorspar":  ("Fluorspar", ["Fluorspar"], None, 112, 251, ["Fluorspar"], None),
 "gallium":    ("Gallium", ["Germanium, gallium, indium, vanadium, niobium, hafnium, rhenium (grouped)"], None, 114, 253, ["Gallium"], GROUPED + ". Treat gallium trade figures as an upper bound and say so."),
 "germanium":  ("Germanium", ["Germanium", "Germanium, gallium, indium, vanadium, niobium, hafnium, rhenium (grouped)"], None, 116, 255, ["Germanium"], "USGS MCS 2026 gives no world production table for germanium (no supply share). HS 2825.60 also contains zirconium dioxide; " + GROUPED + "."),
 "graphite":   ("Graphite (natural)", ["Graphite"], None, 119, 257, ["Graphite"], "Synthetic graphite and battery anode material (HS 3801) are not in the loaded trade data, though China's export controls cover them."),
 "indium":     ("Indium", ["Germanium, gallium, indium, vanadium, niobium, hafnium, rhenium (grouped)"], None, 124, 259, ["Indium"], GROUPED + "."),
 "lead":       ("Lead", ["Lead"], 45, None, None, ["Lead"], None),
 "lithium":    ("Lithium", ["Lithium", "Alkali and alkaline-earth metals (incl. lithium metal)"], None, 136, 261, ["Lithium"], "Spodumene concentrate has no HS6 code of its own (it is traded under HS 2530.90, not loaded), so Australian mine output is invisible in the trade data; lithium trade here is carbonate and hydroxide (chemical stage)."),
 "magnesium":  ("Magnesium metal", ["Magnesium"], None, 137, 263, ["Magnesium"], None),
 "manganese":  ("Manganese", ["Manganese", "Ferroalloys"], None, 139, 265, ["Manganese"], None),
 "nickel":     ("Nickel", ["Nickel", "Ferroalloys"], 47, None, None, ["Nickel"], "USGS MCS gives nickel mine production only. Indonesia has banned ore exports since 2020 and ships nickel pig iron/ferronickel (HS 7202.60), matte (7501.10) and MHP/intermediates (7501.20)."),
 "niobium":    ("Niobium", ["Niobium, tantalum, vanadium (ores)", "Ferroalloys"], None, 148, 269, ["Niobium", "Columbium"], "Brazil exports niobium mainly as ferroniobium (HS 7202.93); HS 2615.90 groups niobium, tantalum and vanadium ores."),
 "palladium":  ("Palladium", ["Platinum-group metals"], 54, None, 271, ["Palladium"], None),
 "platinum":   ("Platinum", ["Platinum-group metals"], 50, None, 271, ["Platinum"], None),
 "phosphate":  ("Phosphate rock", ["Phosphate rock"], 40, None, None, ["Phosphate"], None),
 "potash":     ("Potash", ["Potash"], 41, None, None, ["Potash"], "Potash fertiliser trade (HS 3104) is not in the loaded trade data: no importer exposure can be computed."),
 "rare_earths": ("Rare earths", ["Rare earths"], None, 169, 273, ["Rare earths"], "Rare-earth concentrates have no HS6 code of their own; trade here is compounds (HS 2846) and metals (2805.30). Magnets (HS 8505.11) also include non-rare-earth magnets. The OECD restriction inventory ends in 2024, so China's 2025 rare-earth and magnet controls are not in it."),
 "rhenium":    ("Rhenium", ["Germanium, gallium, indium, vanadium, niobium, hafnium, rhenium (grouped)"], None, 179, 275, ["Rhenium"], GROUPED + "."),
 "silver":     ("Silver", ["Silver"], 51, None, None, ["Silver"], None),
 "tantalum":   ("Tantalum", ["Tantalum", "Niobium, tantalum, vanadium (ores)"], None, 210, 279, ["Tantalum"], "HS 2615.90 groups tantalum, niobium and vanadium ores."),
 "tellurium":  ("Tellurium", ["Tellurium"], None, 211, 281, ["Tellurium"], "HS 2804.50 covers boron and tellurium together."),
 "tin":        ("Tin", ["Tin"], 46, None, 283, ["Tin"], None),
 "titanium":   ("Titanium (mineral concentrates, sponge)", ["Titanium"], None, 221, 285, ["Titanium"], "TiO2 pigment (HS 3206.11) is not in the loaded trade data."),
 "tungsten":   ("Tungsten", ["Tungsten", "Ferroalloys"], None, 224, 292, ["Tungsten"], None),
 "vanadium":   ("Vanadium", ["Vanadium", "Ferroalloys", "Niobium, tantalum, vanadium (ores)"], None, 225, 294, ["Vanadium"], "Most vanadium comes from steel slag and titanomagnetite (China, Russia, South Africa); trade here is oxides and ferrovanadium."),
 "zinc":       ("Zinc", ["Zinc"], 48, None, None, ["Zinc"], None),
 "zirconium":  ("Zirconium", ["Zirconium"], None, 233, 296, ["Zirconium"], None),
}

# project commodity codes (core.commodities.commodity_name used by core.projects.primary_commodity_id)
PROJ = {"aluminium": ["Al", "Alumina", "Bauxite"], "antimony": ["Sb"], "bismuth": ["Bi"], "chromium": ["Chrome"], "cobalt": ["Co"], "copper": ["Cu"],
        "fluorspar": ["Fluorite"], "gallium": ["Ga"], "germanium": ["Ge"], "graphite": ["Graphite"], "lead": ["Pb"], "lithium": ["Li"], "magnesium": ["Mg"],
        "manganese": ["Mn", "Manganese Ore"], "nickel": ["Ni"], "niobium": ["Nb"], "palladium": ["Pd", "PGE"], "platinum": ["PGE"], "phosphate": ["Phosphate Rock"],
        "potash": ["Potash"], "rare_earths": ["REE"], "silver": ["Ag"], "tin": ["Sn"], "titanium": ["Ti", "Heavy Mineral Sand"], "tungsten": ["W"], "vanadium": ["V"],
        "zinc": ["Zn"], "zirconium": ["Zircon", "Heavy Mineral Sand"]}

# mineral, USGS commodity, USGS stage (None = trade-only stage), trade form, HS6 list, facility stages, flag
S = [
 ("aluminium", "Bauxite", "mine_production", "ore", ["260600"], ["Mine"], None),
 ("aluminium", "Alumina", "refinery_production", "intermediate", ["281820", "281830"], ["Refinery"], None),
 ("aluminium", "Aluminum", "smelter_production", "refined", ["760110", "760120"], ["Smelter"], None),
 ("antimony", "Antimony", "mine_production", "ore", ["261710"], ["Mine", "Concentrator"], None),
 ("antimony", None, None, "refined", ["811010", "282580"], ["Smelter", "Refinery"], "No USGS refinery table: trade only (metal and oxide)."),
 ("arsenic", "Arsenic", "production", "refined", ["280480"], ["Smelter", "Refinery"], None),
 ("barite", "Barite", "mine_production", "ore", ["251110"], ["Mine"], None),
 ("beryllium", "Beryllium", "mine_production", "refined", ["811212"], ["Mine"], "Mine-stage share but metal-only trade (no beryl ore code)."),
 ("bismuth", "Bismuth", "refinery_production", "refined", ["810600"], ["Refinery"], "HS 8106.00 includes scrap and articles."),
 ("chromium", "Chromium", "mine_production", "ore", ["261000"], ["Mine"], None),
 ("chromium", None, None, "intermediate", ["720241", "720249"], ["Smelter"], "Ferrochrome: no USGS production table; trade only."),
 ("cobalt", "Cobalt", "mine_production", "intermediate", ["260500", "282200", "810520"], ["Mine", "Concentrator", "Other processing plant"], "Mining countries ship cobalt hydroxide and intermediates (HS 2822.00, 8105.20), not ore; 8105.20 also holds unwrought metal."),
 ("copper", "Copper", "mine_production", "ore", ["260300"], ["Mine", "Concentrator"], None),
 ("copper", "Copper", "refinery_production", "refined", ["740311", "740312", "740313", "740319"], ["Refinery", "Smelter, Refinery"], None),
 ("copper", None, None, "intermediate", ["740100", "740200"], ["Smelter"], "Matte and anodes/blister: no separate USGS smelter table; trade only."),
 ("fluorspar", "Fluorspar", "mine_production", "ore", ["252921", "252922"], ["Mine"], None),
 ("gallium", "Gallium", "primary_production", "refined", ["811292", "811299"], ["Refinery"], "Grouped HS code (seven metals)."),
 ("germanium", None, None, "refined", ["282560", "811292", "811299"], ["Refinery"], "No USGS production table; grouped HS codes."),
 ("graphite", "Graphite (Natural)", "mine_production", "ore", ["250410", "250490"], ["Mine"], "Natural graphite only."),
 ("indium", "Indium", "refinery_production", "refined", ["811292", "811299"], ["Refinery"], "Grouped HS code (seven metals)."),
 ("lead", "Lead", "mine_production", "ore", ["260700"], ["Mine", "Concentrator"], None),
 ("lead", None, None, "refined", ["780110"], ["Smelter", "Refinery"], "No USGS refinery table in the loaded tables: trade only."),
 ("lithium", "Lithium", "mine_production", "refined", ["283691", "282520"], ["Mine", "Brine operation", "Other processing plant"], "Mine-stage share, but trade is chemicals only (no spodumene code)."),
 ("magnesium", "Magnesium Metal", "smelter_production", "refined", ["810411", "810419"], ["Smelter"], None),
 ("manganese", "Manganese", "mine_production", "ore", ["260200"], ["Mine"], None),
 ("manganese", None, None, "intermediate", ["720211", "720219", "720230"], ["Smelter"], "Ferromanganese and silicomanganese: trade only."),
 ("nickel", "Nickel", "mine_production", "intermediate", ["260400", "750110", "750120", "720260"], ["Mine", "Smelter", "Other processing plant"], "Ore plus what ore-ban countries export instead (NPI/ferronickel, matte, MHP)."),
 ("nickel", None, None, "refined", ["750210"], ["Refinery", "Smelter, Refinery"], "No USGS refined-nickel table: trade only."),
 ("niobium", "Niobium (Columbium)", "mine_production", "intermediate", ["720293", "261590"], ["Mine"], "Ferroniobium plus grouped Nb-Ta-V ores."),
 ("palladium", "Palladium", "mine_production", "refined", ["711021"], ["Mine", "Refinery"], "Mine-stage share; trade is unwrought palladium."),
 ("platinum", "Platinum", "mine_production", "refined", ["711011"], ["Mine", "Refinery"], "Mine-stage share; trade is unwrought platinum."),
 ("phosphate", "Phosphate Rock", "mine_production", "ore", ["251010", "251020"], ["Mine"], None),
 ("potash", "Potash", "mine_production", "ore", [], ["Mine", "Brine operation"], "No potash trade codes loaded."),
 ("rare_earths", "Rare Earths", "mine_production", "refined", ["284610", "284690", "280530"], ["Mine", "Other processing plant"], "Mine-stage share; trade is compounds and metals (no concentrate code)."),
 ("rare_earths", None, None, "refined", ["850511"], [], "Permanent magnets (all types): trade only."),
 ("rhenium", "Rhenium", "mine_production", "refined", ["811292", "811299"], ["Refinery"], "Grouped HS code (seven metals)."),
 ("silver", "Silver", "mine_production", "refined", ["710691", "710692"], ["Mine", "Refinery"], "Mine-stage share; trade is silver metal."),
 ("tantalum", "Tantalum", "mine_production", "ore", ["261590"], ["Mine"], "Grouped Nb-Ta-V ores."),
 ("tantalum", None, None, "refined", ["810320"], ["Refinery"], "Trade only."),
 ("tellurium", "Tellurium", "refinery_production", "refined", ["280450"], ["Refinery"], "HS code shared with boron."),
 ("tin", "Tin", "mine_production", "ore", ["260900"], ["Mine", "Concentrator"], None),
 ("tin", None, None, "refined", ["800110"], ["Smelter", "Refinery"], "No USGS refinery table in the loaded tables: trade only."),
 ("titanium", "Titanium Mineral Concentrates", "mine_production", "ore", ["261400"], ["Mine"], None),
 ("titanium", "Titanium Sponge Metal", "sponge_production", "refined", ["810820"], ["Smelter", "Refinery"], None),
 ("tungsten", "Tungsten", "mine_production", "ore", ["261100"], ["Mine", "Concentrator"], None),
 ("tungsten", None, None, "refined", ["284180", "810194"], ["Refinery"], "APT/tungstates and metal: trade only."),
 ("vanadium", "Vanadium", "mine_production", "intermediate", ["282530", "720292"], ["Mine"], "Oxides and ferrovanadium."),
 ("zinc", "Zinc", "mine_production", "ore", ["260800"], ["Mine", "Concentrator"], None),
 ("zinc", None, None, "refined", ["790111", "790112"], ["Smelter", "Refinery"], "No USGS refinery table in the loaded tables: trade only."),
 ("zirconium", "Zirconium", "mine_production", "ore", ["261510"], ["Mine"], None),
]

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
problems = []
c.execute("SELECT hs6 FROM markets.trade_products"); HS = {r[0] for r in c.fetchall()}
c.execute("SELECT DISTINCT commodity, stage FROM markets.supply_concentration WHERE is_active"); US = set(c.fetchall())
c.execute("SELECT DISTINCT commodity FROM markets.export_restrictions"); EXR = {r[0] for r in c.fetchall()}
c.execute("SELECT series_id, frequency FROM markets.price_series WHERE is_active"); PS = dict(c.fetchall())
c.execute("SELECT commodity_name, count(*) FROM core.facility_capacity WHERE is_active GROUP BY 1"); FAC = dict(c.fetchall())
c.execute("SELECT DISTINCT stage_group FROM core.facility_list(NULL, NULL, NULL, false)"); FST = {r[0] for r in c.fetchall()} | {"Smelter, Refinery"}
c.execute("SELECT commodity_name FROM core.commodities"); CM = {r[0] for r in c.fetchall()}
for k, v in PROJ.items():
    if k not in M: problems.append(f"project codes for unknown mineral {k}")
    for x in v:
        if x not in CM: problems.append(f"{k}: project commodity '{x}' not in core.commodities")
for k, (lab, exr, pm, pa, ph, fac, note) in M.items():
    for e in exr:
        if e not in EXR: problems.append(f"{k}: restriction commodity '{e}' not found")
    if pm is not None and PS.get(pm) != "monthly": problems.append(f"{k}: monthly series {pm} missing")
    for p in (pa, ph):
        if p is not None and PS.get(p) != "annual": problems.append(f"{k}: annual series {p} missing")
    found = [f for f in fac if f in FAC]
    if not found: problems.append(f"{k}: no facility rows for {fac}")
    print(f"{k:12s} facilities {sum(FAC.get(f, 0) for f in fac):5d}  restrictions {exr}")
for (k, uc, st, form, hs, fs, fl) in S:
    if k not in M: problems.append(f"stage for unknown mineral {k}")
    if uc is not None and (uc, st) not in US: problems.append(f"{k}: USGS {uc}:{st} not found")
    for h in hs:
        if h not in HS: problems.append(f"{k}: HS {h} not in trade_products")
    for f in fs:
        if f not in FST: problems.append(f"{k}: facility stage {f} not found")
usgs_missing = sorted({x for x in US if x[1] not in ("reserves", "capacity")} - {(uc, st) for (_, uc, st, *_r) in S if uc})
print("USGS production stages not mapped (by design or to review):", usgs_missing)
if problems:
    print("PROBLEMS:"); [print("  ", p) for p in problems]; sys.exit(1)
if "--dry" in sys.argv: sys.exit()

c.execute("""CREATE TABLE IF NOT EXISTS markets.risk_minerals (mineral text PRIMARY KEY, label text NOT NULL, restriction_commodities text[] NOT NULL,
             price_series_monthly int, price_series_annual int, price_series_historical int, facility_commodities text[] NOT NULL, notes text, project_commodities text[] NOT NULL DEFAULT '{}',
             created_date timestamptz DEFAULT now())""")
c.execute("""CREATE TABLE IF NOT EXISTS markets.risk_mineral_stages (id serial PRIMARY KEY, mineral text NOT NULL REFERENCES markets.risk_minerals(mineral),
             usgs_commodity text, usgs_stage text, trade_form text NOT NULL CHECK (trade_form IN ('ore','intermediate','refined')),
             hs6 text[] NOT NULL, facility_stages text[] NOT NULL, flag text, created_date timestamptz DEFAULT now())""")
c.execute("TRUNCATE markets.risk_mineral_stages, markets.risk_minerals")
c.execute("ALTER TABLE markets.risk_minerals ADD COLUMN IF NOT EXISTS project_commodities text[] NOT NULL DEFAULT '{}'")
c.executemany("INSERT INTO markets.risk_minerals (mineral, label, restriction_commodities, price_series_monthly, price_series_annual, price_series_historical, facility_commodities, notes, project_commodities) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
              [(k, *v, PROJ.get(k, [])) for k, v in M.items()])
c.executemany("INSERT INTO markets.risk_mineral_stages (mineral, usgs_commodity, usgs_stage, trade_form, hs6, facility_stages, flag) VALUES (%s,%s,%s,%s,%s,%s,%s)", S)
for t in ("markets.risk_minerals", "markets.risk_mineral_stages"):
    c.execute(f"GRANT SELECT ON {t} TO cm_app_readonly")
c.execute("COMMENT ON TABLE markets.risk_minerals IS 'Risk crosswalk (build_risk_crosswalk.py): mineral -> restriction names, price series, facility names'")
c.execute("COMMENT ON TABLE markets.risk_mineral_stages IS 'Risk crosswalk (build_risk_crosswalk.py): mineral x stage -> USGS supply table, HS6 codes, facility stages, flags'")
g.commit(); print(f"COMMITTED {len(M)} minerals, {len(S)} stages")
