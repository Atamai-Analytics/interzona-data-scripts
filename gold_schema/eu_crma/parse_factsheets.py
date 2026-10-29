"""Parse Windows-OCR line dumps of CRMA strategic-project factsheets and merge with the EC table JSON + map GeoJSON.

usage: python -P -E parse_factsheets.py <scratchpad_dir>
"""
import csv, glob, json, os, re, sys
from collections import defaultdict

base = sys.argv[1]
COL_SPLIT = 900          # px at 220 dpi: left text column < 900 <= right info panel
LABELS = {
    'project name': 'fs_name', 'project type': 'fs_type', 'strategic raw material': 'fs_materials',
    'strategic raw materials': 'fs_materials', 'project promoter': 'fs_promoter', 'project country': 'fs_country',
    'location': 'fs_location', 'estimated starting date of production': 'fs_start_production',
    'unfc classification': 'fs_unfc', 'website of the strategic project': 'fs_website', 'production': 'fs_production',
}


def lines_of(path):
    rows = []
    for l in open(path, encoding='utf-8-sig'):
        p = l.rstrip('\n').split('\t')
        if len(p) == 3 and p[1].lstrip('-').isdigit():
            rows.append((int(p[0]), int(p[1]), p[2].strip()))
    return rows


def merge_rows(rows):
    """Join fragments on the same visual line (justified text is split by OCR)."""
    rows = sorted(rows, key=lambda r: (r[1], r[0]))
    out = []
    for x, y, t in rows:
        if out and abs(out[-1][1] - y) <= 12:
            out[-1] = (out[-1][0], out[-1][1], out[-1][2] + ' ' + t)
        else:
            out.append((x, y, t))
    return out


def join_text(parts):
    s = ' '.join(parts)
    s = re.sub(r'(\w)- (\w)', r'\1\2', s)       # de-hyphenate line wraps
    return re.sub(r'\s+', ' ', s).strip()


def fix_unfc(s):
    # OCR confuses 1/l/I and 0/O in codes like E1.1 // F1.1 // G1
    def fix(m):
        return m.group(1) + m.group(2).replace('l', '1').replace('I', '1').replace('O', '0').replace('i', '1')
    return re.sub(r'\b([EFG])([0-9lIiO.]+)', fix, s.replace('EI', 'E1').replace('FI', 'F1').replace('GI', 'G1'))


def parse(path):
    rows = lines_of(path)
    left = merge_rows([r for r in rows if r[0] < COL_SPLIT])
    right = merge_rows([r for r in rows if r[0] >= COL_SPLIT])
    rec = {'fs_description': '', 'fs_benefit': '', 'fs_benefit_heading': ''}

    # left column: title, description, benefit
    sec, buf = None, defaultdict(list)
    for i, (x, y, t) in enumerate(left):
        lt = t.lower()
        if lt.startswith('strategic project') and 'fs_title' not in rec:
            rec['fs_title'] = left[i + 1][2] if i + 1 < len(left) else ''
            continue
        if re.search(r'escription of (the )?project', lt):
            sec = 'fs_description'; continue
        if lt.startswith('benefit for'):
            sec = 'fs_benefit'; rec['fs_benefit_heading'] = t; continue
        if re.match(r'^[©O0] ?european union', lt) or lt.startswith('reuse of this document'):
            sec = None; continue
        if sec:
            buf[sec].append(t)
    for k, v in buf.items():
        rec[k] = join_text(v)
    # "Benefit for the EU and New" + "Zealand" style headings wrap onto the body; keep as-is, flagged by heading

    # right column: label / value pairs; OCR sometimes glues a label onto the previous value line
    label_re = re.compile(r'(' + '|'.join(sorted((re.escape(k) for k in LABELS), key=len, reverse=True)) + r')\s*:?',
                          re.I)
    pieces = []
    for x, y, t in right:
        pos = 0
        for m in label_re.finditer(t):
            if m.group(0).endswith(':') or m.end() == len(t) or m.group(1).lower() == 'unfc classification':
                if t[pos:m.start()].strip():
                    pieces.append(t[pos:m.start()].strip())
                pieces.append(m.group(1) + ':')
                pos = m.end()
        if t[pos:].strip():
            pieces.append(t[pos:].strip())
    cur, vals = None, defaultdict(list)
    for t in pieces:
        lt = t.lower().rstrip(':').strip()
        if t.endswith(':') and lt in LABELS:
            cur = LABELS[lt]; continue
        if lt.startswith('luxembourg') or lt.startswith('pdf isbn') or lt.startswith('print isbn'):
            if lt.startswith('pdf isbn'):
                m = re.search(r'doi:\s*(\S+)', t)
                rec['fs_doi'] = m.group(1) if m else ''
            cur = None; continue
        if cur:
            vals[cur].append(t)
    for k, v in vals.items():
        rec[k] = join_text(v) if k != 'fs_website' else ' '.join(v).replace(' ', '')
    if 'fs_unfc' in rec:
        rec['fs_unfc'] = fix_unfc(rec['fs_unfc'])
    return rec


def norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


# EC table rows
projects = []
for fn, scope in (('crma_eu.json', 'EU'), ('crma_noneu.json', 'non-EU')):
    for r in json.load(open(os.path.join(base, fn), encoding='utf-8')):
        projects.append({'scope': scope, 'year': r.get('Year') or 2025, 'name': r['Name'].strip(),
                         'type': r['Type'].strip(), 'promoter': r['Promoter'].strip(), 'country': r['Country'].strip(),
                         'materials': r['Strategic raw materials'].strip(), 'factsheet_id': r.get('Factsheet') or ''})

# map points, joined by normalised name
pts = defaultdict(list)
for f in json.load(open(os.path.join(base, 'crma_all.geojson'), encoding='utf-8'))['features']:
    lon, lat = f['geometry']['coordinates'][:2]
    pts[norm(f['properties']['name'])].append((lat, lon))

# UNFC values the OCR dropped, read off the factsheet images by eye
UNFC_OVERRIDES = {
    'a284150d-2641-11f0-8a44-01aa75ed71a1': 'E2 // F2.1 // G2',              # Las Navas
    'e3a3b52b-65e8-11f0-bf4e-01aa75ed71a1': 'E2; F2.1; G2',                  # Kobaloni Energy Zambia
    '404b8c19-91e0-11f0-97c8-01aa75ed71a1': 'E2,F2,G2/ E2,F2,G1',            # Greenland Graphite / Norgraph
    '6b3fd70c-65e4-11f0-bf4e-01aa75ed71a1': 'E1 // F1 // G2',                # Sao Miguel Paulista
}
# map points that are named per site rather than per project
POINT_ALIASES = {norm('Greenland Graphite a/s and Norgraph a/s'): ['greenlandgraphiteas', 'norgraphas']}

# fs_location / fs_production only ever came from a value-chain graphic, not the info panel - not kept
fs_keys = ['fs_title', 'fs_name', 'fs_type', 'fs_materials', 'fs_promoter', 'fs_country',
           'fs_start_production', 'fs_unfc', 'fs_website', 'fs_doi', 'fs_benefit_heading',
           'fs_description', 'fs_benefit']
unmatched_pts = set(pts)
for p in projects:
    p['factsheet_url'] = (f"https://op.europa.eu/en/publication-detail/-/publication/{p['factsheet_id']}/language-en"
                          if p['factsheet_id'] else '')
    fs = parse(os.path.join(base, 'fs_ocr', p['factsheet_id'] + '.tsv')) if p['factsheet_id'] else {}
    if p['factsheet_id'] in UNFC_OVERRIDES:
        fs['fs_unfc'] = UNFC_OVERRIDES[p['factsheet_id']]
    for k in fs_keys:
        p[k] = fs.get(k, '')
    keys = POINT_ALIASES.get(norm(p['name']), [norm(p['name'])])
    p_pts = [pt for k in keys for pt in pts.get(k, [])]
    p['points'] = json.dumps(p_pts)
    p['n_points'] = len(p_pts)
    unmatched_pts.difference_update(keys)

out = os.path.join(base, 'crma_projects_merged.csv')
with open(out, 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.DictWriter(fh, fieldnames=list(projects[0].keys()))
    w.writeheader(); w.writerows(projects)
print('projects', len(projects), 'with factsheet', sum(1 for p in projects if p['factsheet_id']),
      'with coords', sum(1 for p in projects if p['n_points']))
print('unmatched map names', sorted(unmatched_pts))
print('wrote', out)
