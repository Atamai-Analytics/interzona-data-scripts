"""core.data_sources rows for the Canadian geochemistry / drilling sources loaded 2026-11-03 (CANADA_QC_SIGEOM, CANADA_SK_SGS). Idempotent (upsert).
Usage: python register_canada_geochem_sources.py [--dry]
"""
import os, sys
import psycopg2

DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
ROWS = [
    ("CANADA_QC_SIGEOM", "Gouvernement du Québec, Ministère des Ressources naturelles et des Forêts (MRNF), Géologie Québec (SIGÉOM)",
     "SIGÉOM Géochimie (rock samples and analyses) and Sondages (diamond drill holes, lithology logs, mineralised intercepts), GeoPackages dated 31 October 2026",
     "CC BY 4.0", "https://www.donneesquebec.ca/licence/#cc-by",
     "Ministère des Ressources naturelles et des Forêts, Québec. SIGÉOM: Géochimie and Sondages, Données Québec, 2026. CC BY 4.0.",
     "Cleared: CC BY 4.0 on the Données Québec dataset metadata (checked 2026-11-03). Loaded 2026-11-03: 587,000 rock samples, 18,131,405 results, "
     "190,035 drill holes, 1,150,632 log intervals, 337,966 intercepts. Sediment samples not loaded yet.",
     "Compiled by the provincial survey from government work and company assessment reports; about 21,000 rock samples were extracted from PDF "
     "reports by AI (SIGÉOM source type I). Drill-core samples have a projected vertical depth only. Labs are not recorded.",
     "D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_QUEBEC_SIGEOM_GEOCHEM_DRILLHOLES/"),
    ("CANADA_QC_SIGEOM_SED", "Gouvernement du Québec, Ministère des Ressources naturelles et des Forêts (MRNF), Géologie Québec (SIGÉOM)",
     "SIGÉOM Géochimie: secondary-environment samples (lake and stream sediment, soil, till) and analyses, GeoPackage dated 31 October 2026",
     "CC BY 4.0", "https://www.donneesquebec.ca/licence/#cc-by",
     "Ministère des Ressources naturelles et des Forêts, Québec. SIGÉOM: Géochimie, Données Québec, 2026. CC BY 4.0.",
     "Cleared: CC BY 4.0 on the Données Québec dataset metadata (checked 2026-11-03). Loaded 2026-11-04: 522,453 sediment, soil and till samples, "
     "about 20.5M results. Water samples (40,873) not loaded.",
     "Compiled by the provincial survey from government surveys (many 1970s-80s lake and stream sediment programmes) and assessment reports. "
     "Most analyses are partial or of unrecorded dissolution; labs are not recorded. Till heavy-mineral fractions are concentrates.",
     "D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_QUEBEC_SIGEOM_GEOCHEM_DRILLHOLES/"),
    ("CANADA_NRCAN_CDOGS", "Natural Resources Canada, Geological Survey of Canada",
     "Canadian Database of Geochemical Surveys (CDoGS): federal lake-sediment, stream-sediment, till, soil and rock surveys; per-quantity analytical files "
     "downloaded 2026-11-05 (database summary 2025-05-04)",
     "Open Government Licence - Canada", "https://open.canada.ca/en/open-government-licence-canada",
     "Contains information licensed under the Open Government Licence - Canada. Natural Resources Canada, Geological Survey of Canada, Canadian "
     "Database of Geochemical Surveys (CDoGS).",
     "Cleared: Open Government Licence - Canada on the Open Canada catalogue record (checked 2026-11-05). Loaded 2026-11-05: 233,875 samples, "
     "8,417,797 results from federal surveys.",
     "Federal surveys only (provincial-agency, company and US surveys in CDoGS are not loaded). Water, soil gas, vegetation, lab control samples, "
     "duplicates, microprobe grain analyses and mineral-grain counts are not loaded. 18,879 samples already in gold via the Saskatchewan GeoAtlas or "
     "Québec SIGÉOM were skipped. Many analyses are 1970s-90s partial (aqua regia AAS) or semi-quantitative (DC-arc) methods.",
     "D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_NRCAN_CDOGS/"),
    ("CANADA_ATHABASCA_OF7792", "Natural Resources Canada, Geological Survey of Canada",
     "Athabasca Basin Uranium Geochemistry Database v.2 (Wright, Potter and Comeau, 2015; GSC Open File 7792, doi:10.4095/296461): drill-core and "
     "outcrop geochemistry compiled from Saskatchewan assessment reports and data files, 2000-2011; downloaded 2026-11-06",
     "Open Government Licence - Canada", "https://open.canada.ca/en/open-government-licence-canada",
     "Contains information licensed under the Open Government Licence - Canada. Wright, D.M., Potter, E.G. and Comeau, J-S., 2015. Athabasca Basin "
     "Uranium Geochemistry Database v.2; Geological Survey of Canada, Open File 7792. doi:10.4095/296461.",
     "Cleared: Open Government Licence - Canada on the NRCan Open S&T Repository record (dc.rights.license, checked 2026-11-06). Loaded 2026-11-06: "
     "40,373 samples (38,805 drill-core intervals, 1,568 outcrops), 1,843,773 results, 1,285 holes (1,040 linked to Saskatchewan GeoAtlas collars, "
     "245 new).",
     "Company assessment-report data (Cameco, Denison, AREVA, UEX and others) and Saskatchewan Geological Survey data files; lab QAQC removed by the "
     "compilers. About 90% analysed at SRC Saskatoon: partial digest (9:1 HNO3:HCl), total (3-acid), boron by Na2O2 fusion, U by fluorimetry. Below "
     "detection stored as negative values; zeros (some companies used 0 for below detection) not loaded. Major elements may mix oxide and element "
     "reporting between labs. Drill-core samples are placed at the hole collar with from/to depths.",
     "D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_ATHABASCA_OF7792/"),
    ("CANADA_SK_SGS", "Government of Saskatchewan, Saskatchewan Geological Survey (with Geological Survey of Canada lake-sediment data)",
     "Saskatchewan Mining and Petroleum GeoAtlas: Minerals and Quaternary Drillhole Compilation, till geochemistry, GSC lake sediment analyses, "
     "1970s lake sediment geochemistry; map service retrieved 2026-11-03",
     "Government of Saskatchewan Standard Unrestricted Use Data Licence v2.0", None,
     "Saskatchewan Mining and Petroleum GeoAtlas, Drillholes; Surficial Geochemistry Analyses; GSC Lake Sediment Analyses; Lake Sediment Geochemistry; "
     "retrieved 3 November 2026. Contains information licensed under the Government of Saskatchewan Standard Unrestricted Use Data Licence (Version 2.0).",
     "Cleared: Government of Saskatchewan Standard Unrestricted Use Data Licence v2.0 stated in each layer's metadata (checked 2026-11-03). Loaded "
     "2026-11-03: 33,490 drill-hole collars, 19,739 till and lake-sediment samples, 567,594 results. Lake water (566) not loaded.",
     "Drill holes are collars only (no assays or logs published). Till data include off-confidential company assessment work. Lake-sediment "
     "methods are survey-level descriptions, not per-result.",
     "D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_SASKATCHEWAN_GEOCHEM_DRILLHOLES/"),
]
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
for r in ROWS:
    c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
                   licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
                 VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-03',true,'claude_licences_20261103',now())
                 ON CONFLICT (source_system) DO UPDATE SET publisher = excluded.publisher, dataset_name = excluded.dataset_name, licence = excluded.licence,
                   licence_url = excluded.licence_url, attribution_text = excluded.attribution_text, licence_status = excluded.licence_status,
                   caveats = excluded.caveats, evidence_location = excluded.evidence_location, evidence_date = excluded.evidence_date""",
              (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
c.execute("SELECT source_system, licence, is_loaded FROM core.data_sources WHERE source_system LIKE 'CANADA_%'"); print(c.fetchall())
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
