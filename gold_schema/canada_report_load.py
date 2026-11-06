"""Canada phase 3 report summaries -> interzona_cm (tag claude_report_summaries_canada_20261105).

For each of 20 Canadian critical-mineral projects: one docs.documents row (the summary unit: NI 43-101 Item 1 + Items 25-26, a filed-report
exhibit, or the company's study-results release when the full report is not openly downloadable) with ~900-word chunks embedded with
voyage-3-large; core.resource_estimates rows (one per class, never summed beyond what the report states); docs.extracted_facts fs_* economics
and a full_report_reference. Source text: D:/CriticalMineralsDB/Documents/RAG/Ingest/report_summaries_canada_20261105/<nn_project>/summary.txt
(canada_report_extract.py). Figures below were read from those summaries; currency as reported (C$ unless stated).
Usage: python -E -P canada_report_load.py [--dry]
"""
import os, re, sys, time, json, requests, psycopg2

DRY = "--dry" in sys.argv
TAG = "claude_report_summaries_canada_20261105"
ROOT = "D:/CriticalMineralsDB/Documents/RAG/Ingest/report_summaries_canada_20261105"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for f in (os.path.join(HERE, "..", ".env"), r"C:\Users\dean\critical-minerals-ai\.env.local"):
    for l in open(f, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1); ENV.setdefault(k.strip(), v.strip().strip('"').strip("'"))
TARGET, OVERLAP, VERSION = 900, 100, "2026-10-08"
NI = "NI 43-101 (CIM 2014)"
LI, NI_, U, CU, W, GR, REE, PD, AU = 1089, 1107, 1102, 1106, 1103, 994, 1123, 1119, 1116

# folder, project_id, title, document_type, publication_date, source_url, label, resources, facts
# resources: (commodity_id, class, tonnage Mt, grade, grade_unit, contained, contained_unit, effective_date, note)
# facts: (fact_type, numeric, unit, text)
P = [
 ("01_shaakichiuwaanaan", 3304, "PMET Resources (formerly Patriot Battery Metals) - CV5 Pegmatite Lithium-Only Feasibility Study, Shaakichiuwaanaan Project, Quebec: results release (20 Oct 2025; NI 43-101 report filed 14 Nov 2025)",
  "Feasibility Study Results Release (NI 43-101)", "2025-10-20", "https://www.stocktitan.net/news/PMETF/pmet-resources-delivers-positive-cv5-lithium-only-feasibility-study-9cw7ds3fa080.html", "Shaakichiuwaanaan CV5 FS",
  [(LI, "Probable", 84.3, 1.26, "% Li2O", 2.62, "Mt LCE", "2025-10-20", "Maiden reserve, CV5 lithium-only FS")],
  [("fs_npv_posttax_8pct", 1594, "C$M", "After-tax NPV8 ~C$1,594M (US$1,190M) at long-term US$1,221/t SC5.5"), ("fs_irr_posttax", 18.1, "%", "After-tax IRR ~18.1%"),
   ("fs_initial_capex", 1978, "C$M", "Total development capital ~C$1,978M (~C$1,510M net of anticipated pre-production credits)"), ("fs_mine_life", 20, "years", "~20-year mine life, ~800,000 tpa SC5.5"),
   ("fs_price_assumption", 1221, "US$/t SC5.5", "Long-term spodumene concentrate price"), ("fs_aisc", 597, "US$/t SC5.5", "AISC ~US$597/t")]),
 ("02_whabouchi", 3316, "BBA / DRA / SGS / WSP for Nemaska Lithium (Allkem, Livent) - Whabouchi Mine NI 43-101 Pre-Feasibility Technical Report, Quebec (effective 30 Sep 2023): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2023-09-30", "https://www.costmine.com/wp-content/uploads/2023/11/Whabouchi.pdf", "Whabouchi PFS 2023",
  [(LI, "Probable", 38.2, 1.31, "% Li2O", None, None, "2023-09-30", "Total Mineral Reserves 38.2 Mt at 1.31% Li2O (Table 1-4; open pit then underground)")],
  [("fs_npv_posttax_8pct", 2080.1, "C$M", "After-tax NPV8"), ("fs_irr_posttax", 36.9, "%", "After-tax IRR"), ("fs_npv_pretax_8pct", 3588.4, "C$M", "Pre-tax NPV8; pre-tax IRR 50.2%"),
   ("fs_initial_capex", 473.2, "C$M", "Capex for the remaining scope of work at Whabouchi (initial capital)"), ("fs_mine_life", 34, "years", "34-year mine life (open pit then 10 years underground)")]),
 ("03_rose", 3554, "WSP / InnovExplo / Bumigeme for Critical Elements Lithium - Rose Lithium-Tantalum Project NI 43-101 Feasibility Study, Quebec (effective 29 Aug 2023): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2023-08-29", "https://www.costmine.com/wp-content/uploads/2023/11/Rose-Lithium-Critical.pdf", "Rose FS 2023",
  [(LI, "Probable", 26.3, 0.87, "% Li2O", None, None, "2023-08-01", "Probable reserve; 138 ppm Ta2O5; Li2O_eq 0.92%"),
   (LI, "Indicated", 30.6, 0.93, "% Li2O", None, None, "2023-08-01", "145 ppm Ta2O5; $31.4 NSR cut-off (open pit)"),
   (LI, "Inferred", 2.4, 0.78, "% Li2O", None, None, "2023-08-01", "129 ppm Ta2O5")],
  [("fs_npv_posttax_8pct", 2851, "C$M", "After-tax NPV8 (~US$2.2B at 1.3 C$/US$)"), ("fs_irr_posttax", 65.7, "%", "After-tax IRR; payback 1.8 years"),
   ("fs_mine_life", 19, "years", "LOM ~19 years at 1.61 Mtpa ore, incl. 19 months pre-production"), ("fs_price_assumption", 20000, "US$/t Li2O", "Reserve price US$20,000/t Li2O, US$130/kg Ta2O5")]),
 ("04_moblan", 3313, "Sayona Mining (now Elevra Lithium) - Moblan Lithium Project Definitive Feasibility Study results release, Quebec (Feb 2024)",
  "Feasibility Study Results Release (NI 43-101)", "2024-02-01", "https://www.newswire.ca/news-releases/moblan-lithium-project-feasibility-study-positive-results-deliver-c-2-2b-npv-825385350.html", "Moblan DFS 2024",
  [(LI, "Probable", 34.5, 1.36, "% Li2O", None, None, "2024-01-24", "100% project basis; 0.60% Li2O cut-off")],
  [("fs_npv_posttax_8pct", 2200, "C$M", "Post-tax NPV8 C$2.2B"), ("fs_irr_posttax", 34.4, "%", "Post-tax IRR; payback 2.3 years"), ("fs_total_capex", 962.5, "C$M", "Total CAPEX C$962.5M; SUSEX C$96.1M"),
   ("fs_mine_life", 21.1, "years", "21-year LOM, 300 ktpa 6% spodumene concentrate"), ("fs_price_assumption", 1990, "US$/t SC6", "Average LOM SC6 price US$1,990/t (Benchmark Q3 2023)")]),
 ("05_james_bay", 3318, "SLR Consulting / Wave International for Allkem (now Rio Tinto) - Technical Report on the James Bay Lithium Project (Galaxy), Quebec (effective 30 Jun 2023): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2023-06-30", "https://www.costmine.com/wp-content/uploads/2023/11/James-Bay-Lithium.pdf", "James Bay TR 2023",
  [(LI, "Probable", 37.3, 1.27, "% Li2O", None, None, "2023-06-30", "Open pit reserve (Table 1-2)"),
   (LI, "Indicated", 54.3, 1.30, "% Li2O", None, None, "2023-06-30", "0.5% Li2O cut-off"), (LI, "Inferred", 55.9, 1.29, "% Li2O", None, None, "2023-06-30", "")],
  [("fs_npv_posttax_8pct", 2244, "C$M", "NPV8 after-tax"), ("fs_irr_posttax", 45.4, "%", "After-tax IRR; before-tax 62.2%"), ("fs_initial_capex", 508.7, "C$M", "Initial project capex incl. 6.2% contingency"),
   ("fs_mine_life", 19, "years", "LOM 19 years at 2.0 Mtpa")]),
 ("06_georgia_lake", 3381, "Rock Tech Lithium - Georgia Lake Project Pre-Feasibility Study results release, Ontario (Nov 2022; AMC)",
  "Pre-Feasibility Study Results Release (NI 43-101)", "2022-11-15", "https://www.newswire.ca/news-releases/rock-tech-lithium-completes-pre-feasibility-study-for-its-georgia-lake-project-832189550.html", "Georgia Lake PFS 2022",
  [(LI, "Probable", 7.33, 0.82, "% Li2O", None, None, "2022-07-31", ""), (LI, "Indicated", 10.6, 0.88, "% Li2O", None, None, "2022-07-31", ""), (LI, "Inferred", 4.2, 1.00, "% Li2O", None, None, "2022-07-31", "")],
  [("fs_npv_pretax_8pct", 223, "US$M", "Pre-tax NPV8 at US$1,500/t SC6; after-tax NPV US$146M, after-tax IRR 35.6%"), ("fs_irr_pretax", 47.8, "%", "Pre-tax IRR"),
   ("fs_initial_capex", 192.2, "US$M", "Pre-production costs; sustaining US$98.5M"), ("fs_mine_life", 9, "years", "9-year LOM (4 open pit, 5 underground)"), ("fs_price_assumption", 1500, "US$/t SC6", "Average LOM SC6 price")]),
 ("07_pak", 3386, "BBA for Frontier Lithium - PAK Project NI 43-101 Pre-Feasibility Study, Ontario (effective 31 May 2023): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2023-05-31", "https://minedocs.com/27/PAK-PFS-05312023.pdf", "PAK PFS 2023",
  [(LI, "Probable", 22.1, 1.55, "% Li2O", None, None, "2023-05-31", "PAK + Spark deposits")],
  [("fs_npv_posttax_8pct", 2261, "C$M", "After-tax NPV8 (pre-tax C$3,365M); integrated mine-to-chemical PFS"), ("fs_irr_posttax", 24.1, "%", "After-tax IRR; pre-tax 28.6%"),
   ("fs_mine_life", 24, "years", "24-year project life (2023 PFS); a 2025 mine-and-mill FS by DRA exists but is not in this library")]),
 ("08_matawinie", 3303, "BBA for Nouveau Monde Graphite - Phase-2 Matawinie Mine Feasibility Study NI 43-101, Quebec (Nov 2025, SEC 6-K exhibit): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2025-11-12", "https://www.sec.gov/Archives/edgar/data/0001649752/000110465925113538/tm2530895d2_ex99-1.htm", "Matawinie FS 2025",
  [(GR, "Proven", 17.3, 4.16, "% Cg", None, None, "2025-01-31", ""), (GR, "Probable", 44.3, 4.26, "% Cg", None, None, "2025-01-31", "P+P 61.7 Mt at 4.23% Cg"),
   (GR, "Measured", 28.5, 4.28, "% Cg", None, None, None, "West Zone, 1.78% C(g) cut-off"), (GR, "Indicated", 101.8, 4.26, "% Cg", None, None, None, "West Zone"), (GR, "Inferred", 23.0, 4.28, "% Cg", None, None, None, "West Zone")],
  [("fs_npv_posttax_8pct", 238, "C$M", "After-tax NPV8 (mine and concentrator); pre-tax C$379M"), ("fs_irr_posttax", 15.8, "%", "After-tax IRR; pre-tax 17.3%"),
   ("fs_initial_capex", 421, "C$M", "Initial capital, mine and concentrator (excl. working capital)"), ("fs_mine_life", 25, "years", "25-year LOM, ~105,900 tpy concentrate")]),
 ("09_lac_knife", 3294, "Focus Graphite - Lac Knife Graphite Project Feasibility Study Update results release, Quebec (Mar 2023; DRA)",
  "Feasibility Study Results Release (NI 43-101)", "2023-03-06", "https://resourceworld.com/focus-graphite-announces-benchmark-feasibility-study-update-for-its-lac-knife-graphite-project-quebec/", "Lac Knife FSU 2023",
  [(GR, "Probable", 9.31, 14.97, "% Cg", None, None, "2023-03-06", "")],
  [("fs_npv_posttax_8pct", 285.7, "C$M", "After-tax NPV8; pre-tax C$500.9M"), ("fs_irr_posttax", 22.4, "%", "After-tax IRR; pre-tax 28.7%"), ("fs_mine_life", 27, "years", "27-year mine life")]),
 ("10_crawford", 3372, "Ausenco for Canada Nickel - Crawford Nickel Sulphide Project NI 43-101 Technical Report and Feasibility Study, Ontario (2023, rev. Nov 2024): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2023-10-12", "https://wp-canadanickel-2025.s3.ca-central-1.amazonaws.com/media/2024/12/Crawford-NI-43-101-FINAL-REPORT_Nov24_R2.pdf", "Crawford FS 2023",
  [(NI_, "Proven", 994, 0.24, "% Ni", 2345, "kt Ni", "2023-08-31", "Table 1-9"), (NI_, "Probable", 721, 0.20, "% Ni", 1444, "kt Ni", "2023-08-31", "P+P 1,715 Mt at 0.22% Ni, 3,789 kt Ni")],
  [("fs_npv_posttax_8pct", 2475, "US$M", "After-tax NPV8"), ("fs_irr_posttax", 17.1, "%", "After-tax IRR"),
   ("fs_initial_capex", 2556, "C$M", "Initial capital for 60 kt/d; expansion to 120 kt/d C$2,105M; sustaining C$1,950M; LOM capital C$6,611M"), ("fs_mine_life", 41, "years", "FS life of mine 41 years")]),
 ("11_nal", 3333, "Elevra Lithium - North American Lithium (NAL) Expansion Pre-Feasibility Study, Quebec: ASX announcement 7 Sep 2026 (SEC 6-K exhibit)",
  "Pre-Feasibility Study Results Release (JORC / NI 43-101)", "2026-09-07", "https://www.sec.gov/Archives/edgar/data/0001739016/000114036126036060/ef20081740_ex99-1.htm", "NAL Expansion PFS 2026",
  [(LI, "Proven", 0.2, 1.12, "% Li2O", None, None, "2026-09-07", "Ore reserve (JORC); total 47.2 Mt at 1.12% Li2O"), (LI, "Probable", 47.0, 1.12, "% Li2O", None, None, "2026-09-07", ""),
   (LI, "Indicated", 74.4, 1.17, "% Li2O", None, None, None, "Open pit, 0.60% cut-off"), (LI, "Inferred", 18.9, 1.07, "% Li2O", None, None, None, "Open pit 8.6 Mt at 1.13% + underground 10.3 Mt at 1.01%")],
  [("fs_npv_posttax_8pct", 3218, "C$M", "Post-tax NPV8, expansion case (incremental C$943M over base case)"), ("fs_irr_posttax", 49.9, "%", "Expansion-only post-tax IRR; payback 34 months"),
   ("fs_initial_capex", 366, "C$M", "Initial expansion capex (US$271M); sustaining C$527M"), ("fs_mine_life", 20, "years", "Revised LOM 20 years"), ("fs_c1_cost", 876, "C$/t", "LOM C1 cost per t concentrate (US$649)")]),
 ("12_mcilvenna_bay", 3431, "Foran Mining - McIlvenna Bay Initial Phase Feasibility Study results, Saskatchewan (28 Feb 2022; Stantec; summary via S&P Capital IQ)",
  "Feasibility Study Results Release (NI 43-101)", "2022-02-28", "https://www.marketscreener.com/quote/stock/FORAN-MINING-CORPORATION-11771943/news/Foran-Mining-Corporation-Announces-McIlvenna-Bay-Initial-Phase-Feasibility-Study-Results-Outlining-R-39625606/", "McIlvenna Bay FS 2022",
  [], [("fs_mine_life", 18, "years", "18-year mine life, ~65 Mlb CuEq per year; reserves 25.7 Mt")]),
 ("13_wicheeda", 3489, "Defense Metals - Wicheeda Rare Earth Element Project Pre-Feasibility Study results (18 Feb 2025; Hatch / SRK) and NI 43-101 filing notices, British Columbia",
  "Pre-Feasibility Study Results Release (NI 43-101)", "2025-02-18", "https://www.finanzen.net/nachricht/aktien/defense-metals-robust-economics-from-wicheeda-rare-earth-deposit-pfs-14248875", "Wicheeda PFS 2025",
  [], [("fs_npv_posttax_8pct", 1000, "US$M", "After-tax NPV8 ~$1.0B; pre-tax NPV8 $1.8B, pre-tax IRR 24.6%"), ("fs_irr_posttax", 18.9, "%", "After-tax IRR"),
       ("fs_initial_capex", 1400, "US$M", "Initial capital ~$1.4B"), ("fs_mine_life", 15, "years", "15-year open pit LOM (excl. pre-production), 5,000 tpd flotation")]),
 ("14_wheeler_river", 3443, "WSP / SRK / Stantec / CanCost for Denison Mines - NI 43-101 Technical Report on the Wheeler River Project (Phoenix ISR FS and Gryphon update), Saskatchewan (effective 23 Jun 2023): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2023-06-23", "https://minedocs.com/25/WheelerRiverwheeler-FS-06232023.pdf", "Wheeler River FS 2023",
  [(U, "Proven", 0.0063, 24.5, "% U3O8", 3.4, "Mlb U3O8", "2023-06-23", "Phoenix ISR (recoverable lb)"), (U, "Probable", 0.2127, 11.4, "% U3O8", 53.3, "Mlb U3O8", "2023-06-23", "Phoenix ISR; P+P 219.0 kt at 11.7%, 56.7 Mlb recoverable"),
   (U, "Probable", 1.257, 1.8, "% U3O8", 49.7, "Mlb U3O8", "2018-09-01", "Gryphon underground (2018 PFS reserve)")],
  [("fs_npv_posttax_8pct", 1430, "C$M", "Phoenix after-tax NPV8 ~C$1.43B"), ("fs_irr_posttax", 82.3, "%", "Phoenix after-tax IRR"), ("fs_initial_capex", 419.4, "C$M", "Phoenix initial capital (excl. pre-commitment costs)")]),
 ("15_arrow", 3446, "Stantec / Wood / RPA / Golder for NexGen Energy - Arrow Deposit, Rook I Project NI 43-101 Feasibility Study, Saskatchewan (effective 22 Feb 2021; SEC 6-K exhibit): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2021-02-22", "https://www.sec.gov/Archives/edgar/data/1698535/000127956921000216/ex991.htm", "Arrow FS 2021",
  [(U, "Probable", 4.575, 2.37, "% U3O8", 239.6, "Mlb U3O8", "2021-01-21", ""), (U, "Measured", 2.183, 4.35, "% U3O8", 209.6, "Mlb U3O8", "2019-07-19", "Resources inclusive of reserves"),
   (U, "Indicated", 1.572, 1.36, "% U3O8", 47.1, "Mlb U3O8", "2019-07-19", ""), (U, "Inferred", 4.399, 0.83, "% U3O8", 80.7, "Mlb U3O8", "2019-07-19", "")],
  [("fs_npv_posttax_8pct", 3465, "C$M", "Post-tax NPV8 at US$50/lb"), ("fs_irr_posttax", 52.4, "%", "Post-tax IRR; pre-tax NPV C$5,577M, IRR 64.9%"),
   ("fs_initial_capex", 1299.9, "C$M", "Pre-production capital incl. pre-commitment (C$1,142.0M project pre-production)"), ("fs_mine_life", 11, "years", "11-year mine life, 233.6 Mlb recovered"),
   ("fs_price_assumption", 50, "US$/lb U3O8", "Long-term uranium price")]),
 ("16_pls", 3448, "Fission Uranium (now Paladin Energy) - PLS (Patterson Lake South) Feasibility Study technical report filing release, Saskatchewan (2 Mar 2023)",
  "Feasibility Study Results Release (NI 43-101)", "2023-03-02", "https://www.newswire.ca/news-releases/fission-files-feasibility-study-highlighting-tier-1-economics-for-pls-high-grade-uranium-project-831014418.html", "PLS FS 2023",
  [], [("fs_npv_posttax_8pct", 1204, "C$M", "Post-tax NPV8 C$1.204B"), ("fs_irr_posttax", 27.2, "%", "Post-tax IRR; payback 2.6 years"), ("fs_initial_capex", 1155, "C$M", "Initial capital C$1.155B, 3-year construction"),
       ("fs_mine_life", 10, "years", "10-year mine life, 90.9 Mlb U3O8")]),
 ("17_sisson", 3285, "Northcliff Resources - Sisson Tungsten-Molybdenum Project Feasibility Study Update technical report filing release, New Brunswick (Oct 2026)",
  "Feasibility Study Results Release (NI 43-101)", "2026-10-02", "https://www.miningstockeducation.com/2026/10/northcliff-files-technical-report-for-positive-feasibility-study-update-of-sisson-project/", "Sisson FSU 2026",
  [(W, "Proven+Probable", 276.8, 0.075, "% WO3", 16.1, "Mmtu WO3", "2026-09-23", "0.023% Mo; LOM production 16.1 M MTU WO3, 113.5 Mlb Mo")],
  [("fs_npv_posttax_8pct", 6915, "C$M", "Post-tax NPV8 at forecast European APT/concentrate prices"), ("fs_irr_posttax", 49.8, "%", "Post-tax IRR; payback 1.6 years"),
   ("fs_initial_capex", 1528, "C$M", "Initial capital; LOM sustaining C$571M")]),
 ("18_nico", 3542, "Micon International for Fortune Minerals - NICO Cobalt-Gold-Bismuth-Copper Project Feasibility Study NI 43-101, Northwest Territories (effective 2 Apr 2014): Item 1 Summary and Item 25",
  "NI 43-101 Technical Report (summary sections)", "2014-04-02", "https://minedocs.com/12/Nico_Feasibility_2014.pdf", "NICO FS 2014",
  [(AU, "Proven+Probable", 32.5, 0.96, "g/t Au", None, None, "2014-04-02", "Open pit reserve; 0.11% Co, 0.14% Bi, 0.04% Cu (plus 0.58 Mt underground)")],
  [("fs_npv_posttax_7pct", 224, "C$M", "Post-tax NPV7 base case; post-tax IRR 15.1%"), ("fs_mine_life", 20, "years", "Approximately 20-year productive mine life")]),
 ("19_marathon", 3379, "Generation Mining - Marathon Copper-Palladium Project Feasibility Study Report Update results release, Ontario (Mar 2025; Ausenco, effective 1 Nov 2024)",
  "Feasibility Study Results Release (NI 43-101)", "2025-03-27", "https://www.nasdaq.com/press-release/generation-mining-announces-feasibility-study-report-update-marathon-copper-palladium", "Marathon FSU 2025",
  [(PD, "Proven", 115.5, 0.66, "g/t Pd", 2434, "koz Pd", "2024-11-01", "0.22% Cu"), (PD, "Probable", 12.7, 0.47, "g/t Pd", 193, "koz Pd", "2024-11-01", "0.20% Cu; P+P 128.3 Mt at 0.64 g/t Pd, 0.21% Cu")],
  [("fs_npv_posttax_6pct", 1070, "C$M", "After-tax NPV6 at 3-year trailing prices; IRR 28%"), ("fs_irr_posttax", 28, "%", "After-tax IRR; payback 1.9 years"), ("fs_initial_capex", 992, "C$M", "Initial capital"),
   ("fs_mine_life", 12.5, "years", "Mine life 12.5 years"), ("fs_aisc", 2.05, "US$/lb CuEq", "LOM AISC US$2.05/lb CuEq (US$781/oz PdEq)")]),
 ("20_casino", 3536, "M3 Engineering for Western Copper and Gold - Casino Project NI 43-101F1 Technical Report Feasibility Study, Yukon (effective 13 Jun 2022; SEC 6-K exhibit): Item 1 Summary and Items 25-26",
  "NI 43-101 Technical Report (summary sections)", "2022-06-13", "https://www.sec.gov/Archives/edgar/data/1364125/000127956922001314/ex991.htm", "Casino FS 2022",
  [(CU, "Proven", 140.1, 0.31, "% Cu", None, None, "2022-06-13", "Mill reserve; 0.39 g/t Au, 0.024% Mo"), (CU, "Probable", 1076.9, 0.17, "% Cu", None, None, "2022-06-13", "Mill reserve; 0.19 g/t Au, 0.021% Mo; mill P+P 1,217.1 Mt at 0.19% Cu, 0.22 g/t Au"),
   (AU, "Proven+Probable", 209.6, 0.265, "g/t Au", None, None, "2022-06-13", "Heap leach reserve; 1.95 g/t Ag, 0.036% Cu")],
  [("fs_npv_posttax_8pct", 2334, "C$M", "After-tax NPV8; pre-tax C$3,473M"), ("fs_irr_posttax", 18.1, "%", "After-tax IRR; pre-tax 21.2%; payback 3.3 years"),
   ("fs_initial_capex", 3617, "C$M", "Total initial capital; sustaining C$751M")]),
]


def embed(texts):
    for attempt in range(4):
        try:
            r = requests.post("https://api.voyageai.com/v1/embeddings", headers={"Authorization": f"Bearer {ENV['VOYAGE_API_KEY']}"},
                              json={"input": texts, "model": "voyage-3-large", "input_type": "document"}, timeout=180)
            r.raise_for_status()
            return [d["embedding"] for d in r.json()["data"]]
        except Exception as e:
            print("embed retry", attempt, e, file=sys.stderr); time.sleep(3 + 3 * attempt)
    raise RuntimeError("embedding failed")


def chunks_of(text, label):
    page, out, buf, start = 1, [], [], None
    for tok in re.split(r"(\[page \d+\])", text):
        m = re.fullmatch(r"\[page (\d+)\]", tok)
        if m: page = int(m.group(1)); continue
        for w in tok.split():
            if start is None: start = page
            buf.append(w)
            if len(buf) >= TARGET:
                out.append((start, " ".join(buf))); buf = buf[-OVERLAP:]; start = page
    if len(buf) > OVERLAP or not out: out.append((start or 1, " ".join(buf)))
    return [(p, f"[{label}] {t}") for p, t in out]


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT count(*) FROM docs.documents WHERE created_by = %s", (TAG,))
assert c.fetchone()[0] == 0 or DRY, "already loaded - delete the tag's rows first"
tot_c = tot_r = tot_f = 0
for folder, pid, title, dtype, pdate, url, label, res, facts in P:
    c.execute("SELECT occurrence_id, jurisdiction_id, company_id FROM core.projects WHERE project_id = %s", (pid,))
    occ, jur, comp = c.fetchone()
    path = f"{ROOT}/{folder}/summary.txt"
    text = re.sub(r"[ \t]+", " ", open(path, encoding="utf-8").read())
    ch = chunks_of(text, label)
    if DRY:
        print(f"DRY {folder:22s} chunks={len(ch):3d} res={len(res)} facts={len(facts)} occ={occ}"); tot_c += len(ch); continue
    vecs = []
    for i in range(0, len(ch), 16):
        vecs += embed([x[1] for x in ch[i:i + 16]]); time.sleep(0.2)
    c.execute("""INSERT INTO docs.documents (title, domain, document_type, company_id, project_id, occurrence_id, jurisdiction_id, publication_date, source_url,
                 file_path, page_count, language, is_active, created_by) VALUES (%s,'TECHNICAL_REPORT',%s,%s,%s,%s,%s,%s,%s,%s,NULL,'en',true,%s) RETURNING document_id""",
              (title, dtype[:50], comp, pid, occ, jur, pdate, url, path.replace("/", "\\"), TAG))
    did = c.fetchone()[0]
    for idx, ((pg, txt), v) in enumerate(zip(ch, vecs)):
        c.execute("""INSERT INTO docs.document_chunks (document_id, domain, chunk_index, page_number, section_heading, content, token_count, embedding,
                     embedding_model, embedding_version, section_type, company_id, project_id, occurrence_id, jurisdiction_id)
                     VALUES (%s,'TECHNICAL_REPORT',%s,%s,NULL,%s,%s,%s::vector,'voyage-3-large',%s,'BODY',%s,%s,%s,%s)""",
                  (did, idx, pg, txt, len(txt.split()), "[" + ",".join(f"{x:.6f}" for x in v) + "]", VERSION, comp, pid, occ, jur))
    for (cid, cls, t, gr, gu, cm, cmu, eff, note) in res:
        c.execute("""INSERT INTO core.resource_estimates (occurrence_id, commodity_id, classification, reporting_standard, effective_date, tonnage, tonnage_unit,
                     grade, grade_unit, contained_metal, contained_metal_unit, competent_person, source_document_id, is_active, created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,'Mt',%s,%s,%s,%s,%s,%s,true,%s)""", (occ, cid, cls, NI, eff, t, gr, gu, cm, cmu, note or None, did, TAG))
        tot_r += 1
    study = re.sub(r"\s*:.*$", "", title)
    for (ft, num, unit, txt) in facts:
        c.execute("""INSERT INTO docs.extracted_facts (document_id, occurrence_id, project_id, company_id, fact_type, fact_value_text, fact_value_numeric, fact_value_unit,
                     fact_data, extraction_confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'HIGH')""",
                  (did, occ, pid, comp, ft, txt, num, unit, json.dumps({"study": study, "source": label, "loaded_by": TAG})))
        tot_f += 1
    c.execute("""INSERT INTO docs.extracted_facts (document_id, occurrence_id, project_id, company_id, fact_type, fact_value_text, fact_data, extraction_confidence)
                 VALUES (%s,%s,%s,%s,'full_report_reference',%s,%s,'HIGH')""", (did, occ, pid, comp, url, json.dumps({"study": study, "loaded_by": TAG})))
    tot_f += 1
    g.commit(); tot_c += len(ch)
    print(f"OK doc {did} {folder}: {len(ch)} chunks, {len(res)} resource rows, {len(facts) + 1} facts", flush=True)
print("TOTAL chunks", tot_c, "resource rows", tot_r, "facts", tot_f)
g.close()
