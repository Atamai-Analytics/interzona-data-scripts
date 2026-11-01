"""Parse SGU strat_p classes (code + Swedish text) into numeric age ranges and propose a gold stratigraphic_age_reference match.  Review output only."""
import csv, re, collections, os, sys, json
import psycopg2
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def lines(path):
    with open(path, "rb") as fb:
        for raw in fb:
            try: yield raw.decode("utf-8")
            except UnicodeDecodeError: yield raw.decode("cp1252", errors="replace")


NA = ("", "NA")
classes = {}; samples = collections.defaultdict(set)
for x in csv.DictReader(lines(r"D:\CriticalMineralsDB\Sweden\bergartskemi.csv")):
    c = x["strat_p"].strip(); t = x["strat_p_tx"].strip()
    if c == "0" or t in NA: continue
    classes[c] = t; samples[c].add(x["bergartskemi_id"])
NUM = r"(\d+(?:[.,]\d+)?)"


def parse(t):
    s = t.replace("Ga", " Ga")
    m = re.search(NUM + r"\s*[-–]\s*" + NUM, s)
    if m:
        a, b = (float(m.group(i).replace(",", ".")) * 1000 for i in (1, 2)); return max(a, b), min(a, b)
    m = re.search(r"([<>])\s*(?:ca\s*)?" + NUM, s)
    if m:
        v = float(m.group(2).replace(",", ".")) * 1000
        return (None, v) if m.group(1) == ">" and False else ((4000.0, v) if m.group(1) == ">" else (v, 0.0))
    m = re.search(r"ca\s*" + NUM + r"\s*Ga", s)
    if m:
        v = float(m.group(1).replace(",", ".")) * 1000; return v, v
    return None, None


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("""SELECT stratigraphic_age_id, age_name, age_start_ma, age_end_ma FROM geochem.stratigraphic_age_reference
 WHERE is_active AND age_start_ma IS NOT NULL AND age_type IN ('EON','ERA','PERIOD','EPOCH') AND is_official""")
REF = c.fetchall()
c.execute("SELECT sample_number FROM geochem.samples WHERE source_system='SWEDEN_SGU_LITHOGEOCHEMISTRY'")
IN_GOLD = {r[0] for r in c.fetchall()}
out = []
for code, t in sorted(classes.items(), key=lambda kv: -len(samples[kv[0]])):
    a, b = parse(t)
    best = None
    if a is not None:
        cand = [(r[2] - r[3], r) for r in REF if float(r[2]) >= a - 1e-6 and float(r[3]) <= b + 1e-6]
        best = min(cand)[1][1] if cand else None
    n = len(samples[code] & IN_GOLD)
    out.append((code, t, a, b, best, n))
tot = sum(o[5] for o in out)
print("classes", len(out), "samples", tot)
for o in out: print(f"{o[0]:>4} n={o[5]:>5} {str(o[2])[:7]:>7}-{str(o[3])[:7]:<7} -> {o[4]} | {o[1][:70]}")
json.dump(out, open("sgu_strat_p_map_draft.json", "w", encoding="utf-8"), ensure_ascii=False)
byref = collections.Counter()
for o in out: byref[o[4]] += o[5]
print(byref.most_common())
