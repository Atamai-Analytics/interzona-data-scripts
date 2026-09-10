# Build name-based crosswalks: DB deposit_types -> LDepositType, DB commodities -> LCommodity.
import json, csv, re, difflib, sys

def norm(s):
    s = s.lower().strip()
    s = s.replace('-', ' ').replace('(', ' ').replace(')', ' ').replace('/', ' ')
    s = s.replace('–', ' ').replace('−', ' ').replace('+', ' ')
    s = s.replace('±', ' ').replace(',', ' ').replace('&', ' ')
    # drop bracketed abbreviations like (LS) (HS) (IS) (VMS) and trailing "± X" qualifiers
    s = re.sub(r'\b(ls|hs|is)\b', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    # common token equivalences
    s = s.replace('goldsilver', 'gold silver').replace('silvergold', 'silver gold')
    s = s.replace('zinclead', 'zinc lead').replace('leadzinc', 'lead zinc')
    s = s.replace('alkalicalcic', 'alkali calcic')
    s = s.replace('kyanit ', 'kyanite ')
    return s.strip()

def load_ref(name):
    return json.load(open(f'ref_{name}.json', encoding='utf-8'))

def match(dbname, ref, extra_aliases=None):
    aliases = {norm(r['name']): r for r in ref}
    n = norm(dbname)
    if extra_aliases and dbname in extra_aliases:
        want = extra_aliases[dbname]
        for r in ref:
            if r['name'] == want:
                return r, 'MANUAL'
    if n in aliases:
        return aliases[n], 'EXACT'
    # token-set equality
    nt = set(n.split())
    for r in ref:
        if set(norm(r['name']).split()) == nt:
            return r, 'TOKENSET'
    # fuzzy
    cand = difflib.get_close_matches(n, list(aliases), n=1, cutoff=0.82)
    if cand:
        return aliases[cand[0]], 'FUZZY'
    return None, 'NONE'

# ---- deposit types ----
ldt = load_ref('LDepositType')
DT_ALIASES = {
  # DB Hofstra name -> exact LDepositType.name (verified against ref_LDepositType.json)
  'Intermediate-sulfidation epithermal silver-gold': 'Intermediate-sulfidation (IS) epithermal silvergold ± Zn, Pb, Cu, Sn, Mn',
  'Low-sulfidation epithermal gold-silver': 'Low-sulfidation (LS) epithermal goldsilver',
  'High-sulfidation epithermal silver-gold': 'High-sulfidation (HS) epithermal silver-gold ± Cu',
  'Greisen tin': 'Greisen tin ±W-Mo',
  'Greisen tungsten-molybdenum': 'Greisen tungsten-molybdenum ±Bi',
  'Sediment-hosted copper': 'Sediment-hosted copper ± Co',
  'Porphyry copper-gold': 'Porphyry copper ± gold',
  'Skarn gold': 'Skarn gold ± copper ± tungsten',
  'Skarn tungsten': 'Skarn tungsten ± Mo',
  'Skarn zinc-lead-silver': 'Skarn zinc-lead-silver',
  'Epizonal orogenic antimony': 'Epizonal orogenic antimony ± gold',
  'Lacustrine zeolite': 'Lacustrine zeolite (± Li, B)',
  'Oolitic iron formation': 'Oolitic iron formation',
  'Heavy mineral sands': 'Heavy mineral sands',
  'U-M intrusion nickel-copper-PGE': 'U-M intrusion nickel-copper-PGE',
  'U-M layered intrusion iron-titanium-vanadium': 'U-M layered intrusion iron-titanium-vanadium',
}
rows = list(csv.DictReader(open('db_deposit_types_used.csv', encoding='utf-8')))
with open('xwalk_deposit_type.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['db_deposit_type_id','db_deposit_type_name','n_deposits','ls_deposit_type_id','ls_deposit_type_name','match'])
    miss = 0
    for r in rows:
        m, how = match(r['deposit_type_name'], ldt, DT_ALIASES)
        if not m: miss += 1
        w.writerow([r['deposit_type_id'], r['deposit_type_name'], r['n_deposits'],
                    m['id'] if m else '', m['name'] if m else '', how])
print(f'deposit_type: {len(rows)} rows, {miss} unmatched', file=sys.stderr)

# ---- commodities ----
lc = load_ref('LCommodity')
CM_ALIASES = {
  'Sand and Gravel': 'Sand And Gravel', 'Crushed Rock': 'Crushed Stone', 'Silica Sand': 'Silica',
  'Soda Ash': 'Soda Ash', 'Phosphate Rock': 'Phosphate', 'REE': 'Rare Earth Elements',
  'PGE': 'Platinum Group Elements', 'ThO2': 'Thorium', 'MgCO3': 'Magnesite', 'Baryte': 'Barite',
  'Greenstone': 'Dimension Stone', 'Crushed Stone': 'Crushed Stone',
}
SYMBOL2NAME = {'Pb':'Lead','Cu':'Copper','Ag':'Silver','Au':'Gold','Zn':'Zinc','W':'Tungsten','Fe':'Iron',
  'Mn':'Manganese','Ba':'Barium','Li':'Lithium','Mo':'Molybdenum','Sn':'Tin','U':'Uranium','Bi':'Bismuth',
  'Sb':'Antimony','V':'Vanadium','Ni':'Nickel','F':'Fluorine','As':'Arsenic','S':'Sulfur','Cr':'Chromium',
  'Nb':'Niobium','Th':'Thorium','Ta':'Tantalum','K':'Potassium','Co':'Cobalt','Ti':'Titanium','Se':'Selenium',
  'Pt':'Platinum','Zr':'Zirconium','B':'Boron','Hg':'Mercury','In':'Indium','Al':'Aluminium','Cs':'Caesium',
  'REE':'Rare Earth Elements','PGE':'Platinum Group Elements'}
rows = list(csv.DictReader(open('db_commodities_used.csv', encoding='utf-8')))
with open('xwalk_commodity.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['db_commodity_id','db_commodity_name','db_symbol','n','ls_commodity_id','ls_commodity_name','match'])
    miss = 0
    for r in rows:
        m, how = match(r['commodity_name'], lc, CM_ALIASES)
        if not m and r['commodity_symbol'] in SYMBOL2NAME:
            m, how = match(SYMBOL2NAME[r['commodity_symbol']], lc)
            if m: how = 'SYMBOL'
        if not m and r['commodity_name'] in SYMBOL2NAME:
            m, how = match(SYMBOL2NAME[r['commodity_name']], lc)
            if m: how = 'SYMBOL'
        if not m: miss += 1
        w.writerow([r['commodity_id'], r['commodity_name'], r['commodity_symbol'], r['n'],
                    m['id'] if m else '', m['name'] if m else '', how])
print(f'commodity: {len(rows)} rows, {miss} unmatched', file=sys.stderr)
