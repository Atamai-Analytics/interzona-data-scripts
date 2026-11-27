"""Company depth, step A (2026-11-27): add the major critical-minerals companies missing from core.companies, fill tickers / HQ /
websites / commodities on important existing ones, store SEC CIKs (core.external_ids, source_system 'SEC_CIK'), and link USGS
ownership rows (core.occurrence_ownership.company_id) where the owner named IS the parent company (normalised name match; subsidiaries,
joint-venture strings and controlling shareholders are NOT linked).

Facts checked 27 Nov 2026 against company sites / SEC EDGAR (some tickers and HQ cities from exchange listings; unconfirmed values left NULL).
Backup: company_depth_backup_<stamp>.csv ; rollback: python company_depth_20261127.py --undo <backup.csv>
Usage: python company_depth_20261127.py [--dry | --undo backup.csv]
"""
import csv, os, re, sys, time, unicodedata, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "company_depth_20261127"
P, ED, = "Producer", "Explorer/Developer"

# name, short, ticker, exchange(s), HQ country, website, type, commodity symbols (first = main), SEC CIK, owner-name aliases
NEW = [
 ("Freeport-McMoRan Inc.", "Freeport", "FCX", "NYSE", "United States", "https://www.fcx.com", P, ["Cu", "Au", "Mo"], 831259, ["freeport mcmoran", "freeport mcmoran copper and gold", "freeport mcmoran copper gold"]),
 ("Southern Copper Corporation", "Southern Copper", "SCCO", "NYSE (also Lima)", "United States", None, P, ["Cu", "Mo", "Zn", "Ag"], 1001838, ["southern copper", "southern peru copper"]),
 ("Corporación Nacional del Cobre de Chile (Codelco)", "Codelco", None, "Not listed (state-owned)", "Chile", "https://www.codelco.com/en", P, ["Cu", "Mo", "Ag", "Au"], None, ["corporacion nacional del cobre", "codelco", "corporacion nacional del cobre de chile"]),
 ("Antofagasta plc", "Antofagasta", "ANTO", "LSE", "United Kingdom", "https://www.antofagasta.co.uk", P, ["Cu", "Au", "Mo"], None, ["antofagasta"]),
 ("First Quantum Minerals Ltd.", "First Quantum", "FM", "TSX", "Canada", "https://www.first-quantum.com", P, ["Cu", "Ni", "Au", "Zn"], None, ["first quantum minerals"]),
 ("Ivanhoe Mines Ltd.", "Ivanhoe Mines", "IVN", "TSX / OTCQX (IVPAF)", "Canada", "https://www.ivanhoemines.com", P, ["Cu", "Zn", "Pt", "Pd", "Ni", "Au"], None, ["ivanhoe mines"]),
 ("Lundin Mining Corporation", "Lundin Mining", "LUN", "TSX / Nasdaq Stockholm (LUMI)", "Canada", "https://lundinmining.com", P, ["Cu", "Au", "Ni", "Zn", "Ag", "Mo"], None, ["lundin mining"]),
 ("Zijin Mining Group Co., Ltd.", "Zijin Mining", "601899", "Shanghai (601899) / Hong Kong (2899)", "China", "https://www.zijinmining.com", P, ["Cu", "Au", "Zn", "Li", "Ag", "Mo"], None, ["zijin mining group", "zijin mining", "zijin mining group company"]),
 ("CMOC Group Limited", "CMOC", "603993", "Shanghai (603993) / Hong Kong (3993)", "China", "https://www.cmoc.com/", P, ["Cu", "Co", "Mo", "W", "Nb", "P"], None, ["china molybdenum", "cmoc group", "cmoc"]),
 ("Jiangxi Ganfeng Lithium Group Co., Ltd.", "Ganfeng Lithium", "002460", "Shenzhen (002460) / Hong Kong (1772)", "China", "https://www.ganfenglithium.com/", P, ["Li"], None, ["jiangxi ganfeng lithium", "ganfeng lithium", "jiangxi ganfeng lithium group"]),
 ("Tianqi Lithium Corporation", "Tianqi Lithium", "002466", "Shenzhen (002466) / Hong Kong (9696)", "China", "https://www.tianqilithium.com/", P, ["Li"], None, ["tianqi lithium", "sichuan tianqi lithium industry"]),
 ("Barrick Mining Corporation", "Barrick", "B", "NYSE (B) / TSX (ABX)", "Canada", "https://www.barrick.com", P, ["Au", "Cu"], 756894, ["barrick gold", "barrick mining"]),
 ("Zhejiang Huayou Cobalt Co., Ltd.", "Huayou Cobalt", "603799", "Shanghai", "China", "https://www.huayou.com/", P, ["Co", "Ni", "Li"], None, ["zhejiang huayou cobalt", "huayou cobalt"]),
 ("Jinchuan Group Co., Ltd.", "Jinchuan Group", None, "Not listed (state-owned parent)", "China", None, P, ["Ni", "Cu", "Co", "Pt", "Pd"], None, ["jinchuan group", "jinchuan"]),
 ("Jinchuan Group International Resources Co. Ltd", "Jinchuan International", "2362", "Hong Kong", "China", None, P, ["Cu", "Co"], None, ["jinchuan group international resources"]),
 ("Shenghe Resources Holding Co., Ltd.", "Shenghe Resources", "600392", "Shanghai", "China", None, P, ["REE"], None, ["shenghe resources holding"]),
 ("IGO Limited", "IGO", "IGO", "ASX", "Australia", "https://www.igo.com.au/", P, ["Ni", "Li"], None, ["igo"]),
 ("Mineral Resources Limited", "MinRes", "MIN", "ASX", "Australia", "https://www.mineralresources.com.au/", P, ["Fe", "Li"], None, ["mineral resources"]),
 ("Nickel Industries Limited", "Nickel Industries", "NIC", "ASX", "Australia", "https://www.nickelindustries.com/", P, ["Ni"], None, ["nickel industries"]),
 ("Boliden AB", "Boliden", "BOL", "Nasdaq Stockholm", "Sweden", "https://www.boliden.com/", P, ["Zn", "Cu", "Pb", "Ni", "Au", "Ag"], None, ["boliden"]),
 ("Jiangxi Copper Company Limited", "Jiangxi Copper", "600362", "Shanghai (600362) / Hong Kong (0358)", "China", "https://www.jxcc.com/", P, ["Cu", "Au", "Ag", "Pb", "Zn"], None, ["jiangxi copper"]),
 ("Sumitomo Metal Mining Co., Ltd.", "Sumitomo Metal Mining", "5713", "Tokyo", "Japan", "https://www.smm.co.jp/en/", P, ["Cu", "Ni", "Au"], None, ["sumitomo metal mining"]),
 ("PT Trimegah Bangun Persada Tbk (Harita Nickel)", "Harita Nickel", "NCKL", "Indonesia (IDX)", "Indonesia", "https://www.tbpnickel.com/", P, ["Ni", "Co"], None, ["trimegah bangun persada"]),
 ("PT Vale Indonesia Tbk", "Vale Indonesia", "INCO", "Indonesia (IDX)", "Indonesia", None, P, ["Ni"], None, ["vale indonesia"]),
 ("La Générale des Carrières et des Mines (Gécamines)", "Gécamines", None, "Not listed (state-owned)", "Congo, Democratic Republic of the", "https://www.gecamines.cd/", P, ["Cu", "Co", "Zn"], None, ["la generale des carrieres et des mines", "societe generale des carrieres et des mines", "gecamines"]),
 ("China Rare Earth Group Co., Ltd.", "China Rare Earth Group", None, "Not listed (central state-owned group)", "China", None, P, ["REE"], None, ["china rare earth group"]),
 ("China Rare Earth Resources and Technology Co., Ltd.", "China Rare Earth Resources and Technology", "000831", "Shenzhen", "China", None, P, ["REE"], None, ["china rare earth resources and technology"]),
 ("Lithium Americas Corp.", "Lithium Americas", "LAC", "NYSE / TSX", "Canada", "https://www.lithiumamericas.com", ED, ["Li"], 1966983, ["lithium americas"]),
 ("Sigma Lithium Corporation", "Sigma Lithium", "SGML", "Nasdaq / TSXV / ASX (SAU)", "Canada", "https://sigmalithiumcorp.com/", P, ["Li"], 1848309, ["sigma lithium"]),
 ("Standard Lithium Ltd.", "Standard Lithium", "SLI", "NYSE American / TSXV", "Canada", "https://standardlithium.com", ED, ["Li", "Br"], 1537137, ["standard lithium"]),
 ("ioneer Ltd", "ioneer", "INR", "ASX / Nasdaq ADS (IONR)", "Australia", "https://www.ioneer.com", ED, ["Li", "B"], 1896084, ["ioneer"]),
 ("USA Rare Earth, Inc.", "USA Rare Earth", "USAR", "Nasdaq", "United States", "https://www.usare.com/", ED, ["REE"], 1970622, ["usa rare earth"]),
 ("Perpetua Resources Corp.", "Perpetua", "PPTA", "Nasdaq / TSX", "United States", None, ED, ["Au", "Sb", "Ag"], 1526243, ["perpetua resources"]),
 ("Almonty Industries Inc.", "Almonty", "ALM", "Nasdaq", "Canada", "https://www.almonty.com", P, ["W", "Mo"], 1670061, ["almonty industries"]),
 ("Graphite One Inc.", "Graphite One", "GPH", "TSXV / OTCQX (GPHOF)", "Canada", None, ED, ["Graphite"], None, ["graphite one"]),
 ("Westwater Resources, Inc.", "Westwater", "WWR", "NYSE American", "United States", None, ED, ["Graphite"], 839470, ["westwater resources"]),
 ("Largo Inc.", "Largo", "LGO", "Nasdaq / TSX", "Canada", "https://www.largoinc.com", P, ["V", "Ti"], 1400438, ["largo", "largo resources"]),
 ("AMG Critical Materials N.V.", "AMG", "AMG", "Euronext Amsterdam", "Netherlands", "https://www.amg-nv.com", P, ["Li", "V", "Ta", "Nb", "Si"], None, ["amg critical materials", "amg critical minerals", "amg advanced metallurgical group"]),
 ("Jupiter Mines Limited", "Jupiter Mines", "JMS", "ASX", "Australia", "https://www.jupitermines.com", P, ["Mn"], None, ["jupiter mines"]),
 ("MMC Norilsk Nickel (Nornickel)", "Nornickel", "GMKN", "Moscow Exchange", "Russian Federation", "https://www.nornickel.com", P, ["Ni", "Pd", "Pt", "Cu", "Co", "Rh"], None, ["mmc norilsk nickel", "norilsk nickel"]),
 ("Valterra Platinum Limited", "Valterra Platinum", "VAL", "JSE / LSE (VALT)", "South Africa", "https://www.valterraplatinum.com/", P, ["Pt", "Pd", "Rh"], None, ["anglo american platinum", "valterra platinum"]),
 ("Northam Platinum Holdings Limited", "Northam Platinum", "NPH", "JSE", "South Africa", "https://www.northam.co.za/", P, ["Pt", "Pd", "Rh", "Au"], None, ["northam platinum", "northam platinum holdings"]),
 ("Anglo American plc", "Anglo American", "AAL", "LSE / JSE (AGL)", "United Kingdom", "https://www.angloamerican.com/", P, ["Cu", "Fe", "Ni"], None, ["anglo american"]),
 ("Companhia Brasileira de Metalurgia e Mineração (CBMM)", "CBMM", None, "Not listed (private)", "Brazil", "https://cbmm.com/", P, ["Nb"], None, ["companhia brasileira de metalurgia e mineracao", "cbmm"]),
]
# existing company_id: (new name or None, short, ticker, exchange, HQ, type, commodities, CIK, aliases)
EXISTING = {
 "BHP Group Limited": (None, "BHP", "BHP", "ASX / LSE / NYSE (ADR) / JSE (BHG)", "Australia", P, ["Cu", "Fe", "Ni"], 811809, ["bhp group", "bhp billiton", "bhp"]),
 "Vale S.A.": (None, "Vale", "VALE3", "B3 (VALE3) / NYSE (VALE)", "Brazil", P, ["Fe", "Ni", "Cu"], 917851, ["vale"]),
 "Teck Resources Limited": (None, "Teck", "TECK.B", "TSX (TECK.B) / NYSE (TECK)", "Canada", P, ["Cu", "Zn", "Ge"], 886986, ["teck resources", "teck cominco"]),
 "Newmont Corporation": (None, "Newmont", "NEM", "NYSE / TSX (NGT) / ASX", "United States", P, ["Au", "Cu", "Ag", "Zn", "Pb"], 1164727, ["newmont", "newmont mining"]),
 "Hudbay Minerals Inc.": (None, "Hudbay", "HBM", "TSX / NYSE", "Canada", P, ["Cu", "Au", "Zn", "Ag", "Mo"], 1322422, ["hudbay minerals"]),
 "Nutrien Ltd.": (None, "Nutrien", "NTR", "TSX / NYSE", "Canada", P, ["K", "P"], 1725964, ["nutrien"]),
 "The Mosaic Company": (None, "Mosaic", "MOS", "NYSE", "United States", P, ["P", "K"], 1285785, ["mosaic", "the mosaic"]),
 "Uranium Energy Corp": (None, "UEC", "UEC", "NYSE American", "United States", ED, ["U", "Ti", "V"], 1334933, ["uranium energy"]),
 "NexGen Energy Ltd.": (None, "NexGen", "NXE", "TSX / NYSE / ASX (NXG)", "Canada", ED, ["U"], 1698535, ["nexgen energy"]),
 "Denison Mines Corp.": (None, "Denison", "DML", "TSX (DML) / NYSE American (DNN)", "Canada", ED, ["U"], 1063259, ["denison mines"]),
 "Nouveau Monde Graphite Inc.": (None, "NMG", "NOU", "TSX (NOU) / NYSE (NMG)", "Canada", ED, ["Graphite"], 1649752, ["nouveau monde graphite"]),
 "Northern Graphite Corporation": (None, "Northern Graphite", "NGC", "TSXV", "Canada", P, ["Graphite"], None, ["northern graphite"]),
 "Taseko Mines Limited": ("Trekor Metals Limited", "Trekor Metals (formerly Taseko Mines)", "TKO", "TSX / NYSE American (TGB) / LSE", "Canada", P, ["Cu", "Mo", "Au"], 878518, ["taseko mines", "trekor metals"]),
 "MMG Limited": (None, "MMG", "1208", "Hong Kong", None, P, ["Cu", "Zn"], None, ["mmg"]),
 "Ferroglobe PLC": (None, "Ferroglobe", "GSM", "Nasdaq", "United Kingdom", P, ["Si", "Mn"], 1639877, ["ferroglobe"]),
 "Alcoa Corporation": (None, None, None, None, None, None, [], 1675149, ["alcoa"]),
}
# CIKs for companies that already have hand-extracted financials (used by the EDGAR step)
CIK_ONLY = {"Albemarle Corporation": 915913, "MP Materials Corp.": 1801368, "Energy Fuels Inc.": 1385849, "Cameco Corporation": 1009001,
            "Rio Tinto Group": 863064, "Sociedad Quimica y Minera de Chile S.A.": 909037, "Sibanye-Stillwater Limited": 1786909,
            "Elevra Lithium": 1739016, "NioCorp Developments Ltd.": 1512228, "Tronox Holdings plc": 1530804}

SUFFIX = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "sa", "nv", "ab", "ag", "tbk", "pao", "pjsc", "jsc", "llc", "the", "pt", "s", "a"}
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("<null>", "")
    s = re.sub(r"\([^)]*\)", " ", s)                 # drop bracketed abbreviations / parents / shares
    w = re.sub(r"[^a-z0-9]+", " ", s).split()
    while w and w[-1] in SUFFIX: w.pop()
    while w and w[0] in {"the", "pt", "pao"}: w.pop(0)
    return " ".join(w)

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
        if r["kind"] == "own": c.execute("UPDATE core.occurrence_ownership SET company_id = NULL WHERE ownership_id = %s AND company_id = %s", (int(r["id"]), int(r["new"])))
        elif r["kind"] == "co": c.execute(f"UPDATE core.companies SET {r['field']} = %s, modified_by = NULL, modified_date = NULL WHERE company_id = %s", (r["old"] or None, int(r["id"])))
    c.execute("DELETE FROM core.external_ids WHERE created_by = %s", (TAG,))
    c.execute("DELETE FROM core.company_commodities WHERE created_by = %s", (TAG,))
    c.execute("DELETE FROM core.companies WHERE created_by = %s", (TAG,))
    g.commit(); print("undone", len(rows), "backup rows"); sys.exit()

c.execute("SELECT commodity_symbol, commodity_id FROM core.commodities WHERE is_active AND parent_commodity_id IS NULL AND commodity_symbol IS NOT NULL")
SYM = dict(c.fetchall()); SYM["Graphite"] = 994
def jid(country):
    if not country: return None
    c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND (name = %s OR name ILIKE %s) ORDER BY (name = %s) DESC LIMIT 1", (country, country, country))
    r = c.fetchone(); assert r, country; return r[0]
c.execute("SELECT company_id, name FROM core.companies WHERE is_active")
byname = {n: i for i, n in c.fetchall()}
allnorm = {}
for n, i in byname.items(): allnorm.setdefault(norm(n), []).append(i)
for x in NEW:
    assert x[0] not in byname, f"already exists: {x[0]}"
    for s in x[7]: assert s in SYM, (x[0], s)
for n in list(EXISTING) + list(CIK_ONLY): assert n in byname, f"missing existing: {n}"

# ownership candidates: active rows not yet linked, owner name normalised
c.execute("SELECT ownership_id, owner_name FROM core.occurrence_ownership WHERE is_active AND company_id IS NULL")
own = [(i, n, norm(n)) for i, n in c.fetchall()]
alias_to = {}
for x in NEW:
    for a in x[9]: alias_to.setdefault(a, set()).add(("new", x[0]))
for n, v in EXISTING.items():
    for a in v[8]: alias_to.setdefault(a, set()).add(("old", n))
amb = {a: t for a, t in alias_to.items() if len(t) > 1}
assert not amb, amb
links = [(i, n, next(iter(alias_to[k]))) for i, n, k in own if k in alias_to]
from collections import Counter
cnt = Counter(t[1] for _, _, t in links)
print(f"{len(NEW)} new companies, {len(EXISTING)} existing to fill, {len(CIK_ONLY)} CIK-only; {len(links)} ownership rows to link")
for k, v in cnt.most_common(): print(f"  {v:4d}  {k}")
names = Counter((t[1], n) for _, n, t in links)
print("matched owner names:"); [print(f"   {k[0][:30]:30} <- {k[1]} ({v})") for k, v in sorted(names.items())]
if DRY: sys.exit("dry run")

backup = os.path.join(HERE, f"company_depth_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
bw = csv.writer(open(backup, "w", newline="", encoding="utf-8")); bw.writerow(["kind", "id", "field", "old", "new"])
ids = {}
def commods(cid, syms):
    for k, s in enumerate(syms):
        c.execute("SELECT 1 FROM core.company_commodities WHERE company_id = %s AND commodity_id = %s AND is_active", (cid, SYM[s]))
        if not c.fetchone():
            c.execute("INSERT INTO core.company_commodities (company_id, commodity_id, commodity_role, is_active, created_by, created_date) VALUES (%s,%s,%s,true,%s,now())",
                      (cid, SYM[s], "PRIMARY" if k == 0 else "SECONDARY", TAG))
def cik(cid, v):
    if v:
        c.execute("SELECT 1 FROM core.external_ids WHERE entity_type = 'company' AND entity_id = %s AND source_system = 'SEC_CIK'", (cid,))
        if not c.fetchone():
            c.execute("INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by, created_date) VALUES ('company',%s,'SEC_CIK',%s,'EXACT',%s,now())", (cid, str(v), TAG))
for (name, short, tick, exch, hq, web, typ, syms, ck, _al) in NEW:
    c.execute("""INSERT INTO core.companies (name, short_name, ticker, exchange, hq_jurisdiction_id, company_type, primary_commodity_id, website, is_active, created_by, created_date)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true,%s,now()) RETURNING company_id""",
              (name, short, tick, exch, jid(hq), typ, SYM[syms[0]] if len(syms) == 1 else None, web, TAG))
    cid = c.fetchone()[0]; ids[name] = cid; commods(cid, syms); cik(cid, ck)
for n, (newname, short, tick, exch, hq, typ, syms, ck, _al) in EXISTING.items():
    cid = byname[n]; ids[n] = cid
    c.execute("SELECT name, short_name, ticker, exchange, hq_jurisdiction_id, company_type, primary_commodity_id FROM core.companies WHERE company_id = %s", (cid,))
    cur = dict(zip(["name", "short_name", "ticker", "exchange", "hq_jurisdiction_id", "company_type", "primary_commodity_id"], c.fetchone()))
    want = {"short_name": short, "ticker": tick, "exchange": exch, "hq_jurisdiction_id": jid(hq), "company_type": typ,
            "primary_commodity_id": SYM[syms[0]] if len(syms) == 1 else None}
    if newname: want["name"] = newname
    for f, v in want.items():
        if v is not None and (cur[f] is None or f == "name"):
            bw.writerow(["co", cid, f, cur[f] if cur[f] is not None else "", v])
            c.execute(f"UPDATE core.companies SET {f} = %s, modified_by = %s, modified_date = now() WHERE company_id = %s", (v, TAG, cid))
    commods(cid, syms); cik(cid, ck)
for n, ck in CIK_ONLY.items(): cik(byname[n], ck)
for i, n, (kind, key) in links:
    cid = ids[key]
    bw.writerow(["own", i, "company_id", "", cid])
    c.execute("UPDATE core.occurrence_ownership SET company_id = %s WHERE ownership_id = %s AND company_id IS NULL", (cid, i))
g.commit(); print("done; backup", backup)
