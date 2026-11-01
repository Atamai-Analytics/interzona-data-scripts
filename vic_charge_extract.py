#!/usr/bin/env python3
"""Extract analytical charge weights per Victoria analytical package from the
GSV method descriptions carried in AssayMapping.xlsx (Sheet2).

Rules (conservative - anything uncertain is left out and reported):
  * only weights written as a number + g/gm/gms/gram(s)/mg/kg inside a method description
  * ranges ("50-100g", "10-30g", "3 - 5kg") -> the LOWER bound (this is a *minimum* weight field)
  * skip uncertain ("50 g?"), field-collection and whole-sample-preparation phrases
  * weight is taken from the descriptions of every mapped row of the package, weighted
    by analysis count; if rows disagree the package is reported as AMBIGUOUS and not applied
Output: vic_charge_candidates.json (package_code -> detail)
"""
import json, re, sys, collections
sp = sys.argv[1]
recs = json.load(open(sp + '/vic_mapping.json', encoding='utf-8'))
NUM = r'(\d+(?:\.\d+)?)'
UNIT = r'(kg|gms?|grams?|mg|g)\b'
rng = re.compile(NUM + r'\s?(?:-|to)\s?' + NUM + r'\s?' + UNIT, re.I)
one = re.compile(r'(?<![\w.])' + NUM + r'\s?' + UNIT, re.I)
SKIP = re.compile(r'entire sample|collected|pick and shovel|dispersed in distilled|\?\s*$|50 g\?|volume made|dilut\w+ \d+\s?mg to|dilution', re.I)

def to_g(v, u):
    u = u.lower()
    v = float(v)
    return v * 1000 if u == 'kg' else v / 1000 if u == 'mg' else v

def weights_in(desc):
    out = []
    for part in [p.strip() for p in desc.split(' | ')]:
        if not part or SKIP.search(part):
            continue
        m = rng.search(part)
        if m:
            out.append((to_g(m.group(1), m.group(3)), part)); continue
        m = one.search(part)
        if m:
            out.append((to_g(m.group(1), m.group(2)), part))
    return out

pk = collections.defaultdict(lambda: {'rows': [], 'name': None, 'package_id': None})
for r in recs:
    d = pk[r['package_code']]
    d['name'] = r['package_name']; d['package_id'] = r['package_id']
    d['rows'].append({'lab': r['laboratory_names'], 'codes': r['method_codes'], 'desc': r['method_descriptions'], 'n': int(float(r['count'] or 0))})

res = {}
for code, d in pk.items():
    per_row = []
    for row in d['rows']:
        w = weights_in(row['desc'])
        per_row.append({'weights': sorted({x for x, _ in w}), 'phrases': [p for _, p in w], **row})
    allw = collections.Counter()
    nrows_with = 0
    for pr in per_row:
        if pr['weights']:
            nrows_with += 1
            for x in pr['weights']: allw[x] += pr['n']
    distinct = sorted(allw)
    if not distinct:
        status, weight = 'NONE', None
    elif len(distinct) == 1 and nrows_with == len(per_row):
        status, weight = 'CLEAR', distinct[0]
    elif len(distinct) == 1:
        status, weight = 'PARTIAL', distinct[0]          # some mapped rows state it, others silent
    else:
        status, weight = 'AMBIGUOUS', None
    res[code] = {'package_id': d['package_id'], 'name': d['name'], 'status': status, 'weight_g': weight,
                 'weights_seen_g': distinct, 'rows': per_row}
json.dump(res, open(sp + '/vic_charge_candidates.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
c = collections.Counter(v['status'] for v in res.values())
print(dict(c), "of", len(res), "packages")
