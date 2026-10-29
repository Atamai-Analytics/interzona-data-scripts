"""Dry run: build every row the EU CRMA strategic-projects load would write to interzona_cm. Writes nothing to the DB.

usage: python -P -E crma_dryrun.py <scratchpad_dir>
Outputs <scratchpad>/dryrun/*.csv (one per target table) + site_decisions.csv + report.txt
"""
import csv, json, os, re, sys
from collections import Counter

base = sys.argv[1]
out_dir = os.path.join(base, 'dryrun')
os.makedirs(out_dir, exist_ok=True)
TAG = 'migration_eu_crma_20261029'
SRC = 'EU_CRMA_STRATEGIC_PROJECTS'

# --- lookups (from core.jurisdictions / core.commodities / core.companies, queried 2026-10-29) ---
JURIS = {'Belgium': 778, 'Brazil': 789, 'Bulgaria': 780, 'Canada': 796, 'Czechia': 814, 'Estonia': 822,
         'Finland': 828, 'France': 833, 'Germany': 815, 'Greece': 846, 'Greenland': 841, 'Italy': 867,
         'Kazakhstan': 882, 'Lithuania': 890, 'Madagascar': 899, 'Malawi': 913, 'Namibia': 917,
         'Netherlands': 923, 'New Caledonia': 918, 'Norway': 924, 'Poland': 936, 'Portugal': 941,
         'Romania': 946, 'Serbia': 947, 'Slovakia': 959, 'South Africa': 1004, 'Spain': 826, 'Sweden': 954,
         'Ukraine': 987, 'United Kingdom': 835, 'UK': 835, 'Zambia': 1005}
# material string (lower, qualifier stripped) -> (commodity_id, commodities-array name)
MATERIAL = {'copper': (1106, 'Cu'), 'lithium': (1089, 'Li'), 'nickel': (1107, 'Ni'), 'cobalt': (1105, 'Co'),
            'graphite': (994, 'Graphite'), 'manganese': (1112, 'Mn'), 'platinum group metals': (1126, 'PGE'),
            'bauxite/alumina/aluminium': (1078, 'Al'), 'rare earth elements for permanent magnets': (1123, 'REE'),
            'rare earth elements for magnets': (1123, 'REE'), 'tungsten': (1103, 'W'), 'germanium': (1145, 'Ge'),
            'magnesium metal': (1090, 'Mg'), 'titanium metal': (1113, 'Ti'), 'boron': (1144, 'B'),
            'gallium': (1084, 'Ga'), 'silicon metal': (1147, 'Si')}
COMPANY = {'umicore': 34, 'rio tinto': 32, 'sibanye-stillwater': 33}
ASSET_TYPE = {'extraction': 'MINE', 'processing': 'PROCESSING', 'recycling': 'RECYCLING',
              'substitution': 'SUBSTITUTION', 'integrated: extraction and processing': 'MINE',
              'integrated: processing and recycling': 'PROCESSING'}
ROUND = {('EU', '2025'): ('2025-03-25', 'C(2025) 1904'), ('non-EU', '2025'): ('2025-06-04', 'C(2025) 3491'),
         ('EU', '2026'): ('2026-10-09', 'C(2026) 8051')}

# multi-site projects: per-site (name suffix, country, is_deposit) - from the factsheets / EC map
SITES = {
    3: [('Cinovec deposit', 'Czechia', True), ('processing plant', 'Czechia', False)],
    6: [('site 1', 'Finland', True), ('site 2', 'Finland', True), ('Kokkola chemical plant', 'Finland', False)],
    11: [('Lacq', 'France', False), ('Lyon area', 'France', False)],
    12: [('Beauvoir mine', 'France', True), ('Montlucon conversion plant', 'France', False)],
    13: [('site 1', 'France', False), ('site 2', 'France', False)],
    19: [('Germany site', 'Germany', False), ('France site (main)', 'France', False), ('Namibia site', 'Namibia', False)],
    23: [('bauxite mines', 'Greece', True), ('Agios Nikolaos alumina plant', 'Greece', False)],
    45: [('Malmberget', 'Sweden', True), ('Per Geijer', 'Sweden', True), ('Lulea Industrial Park', 'Sweden', False)],
    76: [('Italy site', 'Italy', False), ('Poland site', 'Poland', False), ('France site', 'France', False),
         ('UK site', 'United Kingdom', False)],
    99: [('Amitsoq', 'Greenland', True), ('Norgraph plant', 'Norway', False)],
}
PRIMARY_SITE = {19: 1}  # 'France (main location)'

# (project index, site index) -> (occurrence_id, decision, reason). Everything not listed = NEW
LINKS = {
    (2, 0): (426311, 'LINK', 'Chvaletice tailings, same site'),
    (3, 0): (325354, 'LINK', 'Cinovec deposit (Sn-W-Li)'),
    (5, 0): (3880, 'LINK', 'Sakatti, 0.3 km, same name'),
    (7, 0): (3878, 'LINK', 'Kolmisoppi is a Talvivaara/Terrafame deposit'),
    (15, 0): (474857, 'LINK', 'Sandouville = former SLN Le Havre nickel refinery'),
    (27, 0): (529868, 'LINK', 'Portovesme smelter'),
    (33, 0): (515877, 'LINK', 'Neves-Corvo'),
    (34, 0): (325151, 'LINK', 'Baia de Fier graphite'),
    (43, 0): (488000, 'LINK', 'Atlantic Copper Huelva smelter'),
    (45, 0): (403100, 'LINK', 'Malmberget Mine'),
    (49, 0): (488356, 'LINK', 'Georgi Damyanov = Aurubis Pirdop smelter'),
    (54, 0): (447396, 'LINK', 'Sokli'),
    (66, 0): (570036, 'LINK', 'Aurubis Luenen smelter'),
    (89, 0): (467533, 'LINK', 'Slovalco Ziar nad Hronom smelter'),
    (92, 0): (508294, 'LINK', 'Viscaria (by name; EC point is 6 km off)'),
    (95, 0): (339176, 'LINK', 'Dumont Nickel Mine'),
    (99, 0): (3736, 'LINK', 'Amitsoq Graphite Mine, 0.0 km'),
    (104, 0): (322551, 'LINK', 'Hemerdon Mine (Tungsten West)'),
    (105, 0): (3805, 'LINK', 'Zandkopsdrift (Frontier Rare Earths)'),
    # plausible but needs a human look
    (0, 0): (446949, 'REVIEW', 'Umicore Olen site? (Olen Smelter, Co-Cu) - GePETO is Ge refining at Olen'),
    (1, 0): (446949, 'REVIEW', 'Umicore Olen site? same as GePETO'),
    (39, 0): (354257, 'REVIEW', 'La Parrilla W-Sn, 19 km apart'),
    (48, 0): (447100, 'REVIEW', 'Umicore Hoboken plant? 2.2 km'),
    (51, 0): (529199, 'REVIEW', 'Kokkola Co-Ni refinery (Umicore Kokkola?)'),
    (85, 0): (475155, 'REVIEW', 'Borralha W; existing points 14-15 km off the EC point'),
    (94, 0): (447422, 'REVIEW', 'SLN Doniambo smelter, 1.7 km'),
}
# near-miss candidates deliberately kept NEW (for the review list)
NOT_LINKED = {
    (52, 0): 'Vuonos Mine 1.9 km - Hautalampi is a separate deposit',
    (68, 0): 'Cinovec 0.7 km - Zinnwald is the German side, separate project/promoter',
    (97, 0): 'Chambishi RLE plant 0.5 km - Kobaloni is a new cobalt plant',
    (45, 1): 'Kirunavaara 3.2 km - Per Geijer is a separate deposit',
    (10, 0): 'Kokkola refinery ~6 km - Jervois builds a new refinery',
    (32, 0): 'Minal tungsten 4.7 km - unrelated',
    (72, 0): 'Porto Marghera Zn - different plant in the same industrial zone',
    (73, 0): 'Porto Marghera Zn - different plant in the same industrial zone',
    (81, 0): 'Rotterdam/Pernis plants - different',
}


def norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def split_materials(s):
    parts = [p.strip() for p in re.split(r',(?![^()]*\))', s) if p.strip()]
    out = []
    for p in parts:
        key = re.sub(r'\s*\(.*?\)', '', p.lower()).strip()
        out.append((p, MATERIAL.get(key)))
    return out


def countries(s):
    s = s.replace('(main location)', '')
    return [c.strip() for c in re.split(r',| and ', s) if c.strip()]


rows = list(csv.DictReader(open(os.path.join(base, 'crma_projects_merged.csv'), encoding='utf-8-sig')))
problems = []
occ_new, occ_link, projects, ownership, designations, documents, ext_ids, occ_comms, decisions = ([] for _ in range(9))

for i, r in enumerate(rows):
    year = str(r['year'])
    approval_date, decision_ref = ROUND[(r['scope'], year)]
    mats = split_materials(r['materials'])
    for raw, m in mats:
        if not m:
            problems.append(f'{i} {r["name"]}: unmapped material {raw!r}')
    mats = [(raw, m) for raw, m in mats if m]
    comm_ids = list(dict.fromkeys(m[0] for _, m in mats))
    comm_names = list(dict.fromkeys(m[1] for _, m in mats))
    ctry = countries(r['country'])
    for c in ctry:
        if c not in JURIS:
            problems.append(f'{i} {r["name"]}: unmapped country {c!r}')
    proj_juris = JURIS.get(ctry[0])
    ttype = r['type'].strip().lower()
    company_id = next((v for k, v in COMPANY.items() if k in r['promoter'].lower()), None)
    pts = json.loads(r['points'])
    sites = SITES.get(i) or [('', ctry[0], 'extraction' in ttype)]
    if len(sites) != len(pts):
        problems.append(f'{i} {r["name"]}: {len(pts)} map points but {len(sites)} site definitions')
    proj_key = f'{r["scope"]}-{year}-{norm(r["name"])[:60]}'

    site_refs = []
    for j, (lat, lon) in enumerate(pts):
        suffix, s_ctry, is_dep = sites[j] if j < len(sites) else (f'site {j + 1}', ctry[0], False)
        ext_key = f'{proj_key}#{j}'
        link = LINKS.get((i, j))
        if link:
            occ_id, decision, reason = link
            occ_link.append({'proj_idx': i, 'site_idx': j, 'occurrence_id': occ_id, 'decision': decision,
                             'set_project_id': 'yes, if NULL', 'add_commodities': ','.join(comm_names)})
            site_refs.append(f'occ:{occ_id}')
        else:
            decision, reason, occ_id = 'NEW', NOT_LINKED.get((i, j), ''), None
            name = r['name'] if not suffix else f'{r["name"]} - {suffix}'
            comments = ' | '.join(filter(None, [
                f'EU CRMA strategic project ({r["scope"]}, approved {approval_date}, Commission Decision {decision_ref})',
                f'Project type (as published): {r["type"]}',
                f'Promoter (as published): {r["promoter"]}',
                f'Strategic raw materials (as published): {r["materials"]}',
                'POSITION IS APPROXIMATE (REGIONAL): the EC map states project locations are based on regional scale',
                f'Factsheet: {r["factsheet_url"]}' if r['factsheet_url'] else '',
                f'Source: European Commission, Selected strategic projects under the CRMA. Load tag {TAG}']))
            occ_new.append({'tmp_key': ext_key, 'name': name, 'is_deposit': is_dep, 'lat': lat, 'lon': lon,
                            'jurisdiction_id': JURIS[s_ctry], 'company_id': company_id or '',
                            'status': 'DEVELOPMENT', 'workings_type': '' if is_dep else (
                                'Recycling plant' if 'recycl' in ttype else 'Processing plant'),
                            'position_accuracy': 'REGIONAL', 'commodities': '{' + ','.join(comm_names) + '}',
                            'comments': comments, 'created_by': TAG})
            for k, cid in enumerate(comm_ids):
                occ_comms.append({'occurrence': ext_key, 'commodity_id': cid,
                                  'commodity_role': 'PRIMARY' if k == 0 else 'SECONDARY', 'created_by': TAG})
            ext_ids.append({'entity_type': 'OCCURRENCE', 'entity': ext_key, 'source_system': SRC,
                            'source_id': ext_key, 'match_confidence': 'EXACT', 'created_by': TAG})
            site_refs.append(f'new:{ext_key}')
        decisions.append({'proj_idx': i, 'site_idx': j, 'project': r['name'], 'type': r['type'],
                          'promoter': r['promoter'], 'site': suffix, 'lat': lat, 'lon': lon,
                          'decision': decision, 'occurrence_id': occ_id or '', 'reason': reason})

    prim = PRIMARY_SITE.get(i, 0)
    projects.append({'tmp_key': proj_key, 'name': r['name'], 'company_id': company_id or '',
                     'jurisdiction_id': proj_juris, 'status': 'DEVELOPMENT',
                     'primary_commodity_id': comm_ids[0] if comm_ids else '',
                     'occurrence': site_refs[prim] if site_refs else '',
                     'asset_type': ASSET_TYPE[ttype], 'description': r['fs_description'],
                     'source_document': f'doc:{r["factsheet_id"]}' if r['factsheet_id'] else '',
                     'created_by': TAG})
    ownership.append({'project': proj_key, 'company_id': company_id or '', 'owner_name': r['promoter'],
                      'share_pct': '', 'as_of_year': year,
                      'source_document': f'doc:{r["factsheet_id"]}' if r['factsheet_id'] else '', 'created_by': TAG})
    designations.append({'project': proj_key, 'programme': 'EU_CRMA_STRATEGIC_PROJECT', 'scope': r['scope'],
                         'approval_date': approval_date, 'decision_ref': decision_ref,
                         'value_chain_stage': r['type'], 'materials_as_published': r['materials'],
                         'promoter_as_published': r['promoter'], 'promoter_factsheet': r['fs_promoter'],
                         'countries_as_published': r['country'], 'unfc_classification': r['fs_unfc'],
                         'est_start_production': r['fs_start_production'], 'website': r['fs_website'],
                         'eu_benefit': r['fs_benefit'], 'factsheet_doi': r['fs_doi'],
                         'factsheet_url': r['factsheet_url'], 'created_by': TAG})
    ext_ids.append({'entity_type': 'PROJECT', 'entity': proj_key, 'source_system': SRC, 'source_id': proj_key,
                    'match_confidence': 'EXACT', 'created_by': TAG})
    if r['factsheet_id']:
        documents.append({'tmp_key': f'doc:{r["factsheet_id"]}',
                          'title': f'Strategic project factsheet: {r["fs_title"] or r["name"]}',
                          'domain': 'POLICY', 'document_type': 'Factsheet', 'company_id': company_id or '',
                          'project': proj_key, 'commodity_id': comm_ids[0] if comm_ids else '',
                          'jurisdiction_id': proj_juris, 'publication_date': '',
                          'source_url': r['factsheet_url'], 'page_count': 1, 'language': 'en', 'created_by': TAG})

data_source = [{'source_system': SRC, 'publisher': 'European Commission, DG Internal Market, Industry, Entrepreneurship and SMEs',
                'dataset_name': 'Selected strategic projects under the Critical Raw Materials Act (EU lists 2025 and 2026, non-EU list 2025): project table, map locations and project factsheets; obtained 2026-10-28',
                'licence': 'CC BY 4.0 (stated on the factsheets); Commission reuse policy (Decision 2011/833/EU) for the web table',
                'attribution_required': True, 'attribution_text': '(c) European Union, 2025-2026',
                'caveats': 'Locations are regional-scale (EC map disclaimer). Factsheet text extracted by OCR from image-only PDFs.',
                'evidence_location': 'https://single-market-economy.ec.europa.eu/sectors/raw-materials/areas-specific-interest/critical-raw-materials/strategic-projects-under-crma/selected-projects_en',
                'evidence_date': '2026-10-28', 'is_loaded': True, 'created_by': TAG}]

DDL = '''CREATE TABLE core.project_designations (
  project_designation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id integer NOT NULL REFERENCES core.projects(project_id),
  programme varchar(60) NOT NULL,          -- e.g. EU_CRMA_STRATEGIC_PROJECT
  scope varchar(20),                       -- EU / non-EU
  approval_date date,
  decision_ref text,
  value_chain_stage text,
  materials_as_published text,
  promoter_as_published text,
  promoter_factsheet text,
  countries_as_published text,
  unfc_classification text,
  est_start_production text,               -- mostly a year; some dates/quarters as published
  website text,
  eu_benefit text,
  factsheet_doi text,
  factsheet_url text,
  source_document_id bigint REFERENCES docs.documents(document_id),
  is_active boolean NOT NULL DEFAULT true,
  created_by varchar(100) NOT NULL DEFAULT CURRENT_USER,
  created_date timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, programme)
);'''


def dump(name, data):
    if not data:
        return
    with open(os.path.join(out_dir, name + '.csv'), 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
        w.writeheader(); w.writerows(data)


for name, data in [('data_sources', data_source), ('documents', documents), ('occurrences_new', occ_new),
                   ('occurrences_linked', occ_link), ('occurrence_commodities', occ_comms),
                   ('projects', projects), ('project_ownership', ownership),
                   ('project_designations', designations), ('external_ids', ext_ids),
                   ('site_decisions', decisions)]:
    dump(name, data)
open(os.path.join(out_dir, 'project_designations_ddl.sql'), 'w').write(DDL)

# --- checks ---
for o in occ_new:
    if len(o['workings_type']) > 50 or len(o['status']) > 50 or len(o['position_accuracy']) > 20:
        problems.append(f'length: {o["name"]}')
for p in projects:
    if not p['primary_commodity_id']:
        problems.append(f'no commodity: {p["name"]}')
    if not p['jurisdiction_id']:
        problems.append(f'no jurisdiction: {p["name"]}')
keys = Counter(e['source_id'] for e in ext_ids)
problems += [f'duplicate external id {k}' for k, v in keys.items() if v > 1]

rep = [f'projects {len(projects)}', f'project_ownership {len(ownership)} (company_id set: {sum(1 for o in ownership if o["company_id"])})',
       f'project_designations {len(designations)}', f'documents {len(documents)}',
       f'sites {len(decisions)}: ' + str(dict(Counter(d["decision"] for d in decisions))),
       f'occurrences_new {len(occ_new)} (deposits {sum(1 for o in occ_new if o["is_deposit"])})',
       f'occurrences_linked {len(occ_link)}', f'occurrence_commodities {len(occ_comms)}',
       f'external_ids {len(ext_ids)}', 'asset_type ' + str(dict(Counter(p["asset_type"] for p in projects))),
       f'problems {len(problems)}'] + problems
open(os.path.join(out_dir, 'report.txt'), 'w', encoding='utf-8').write('\n'.join(rep))
print('\n'.join(rep))
