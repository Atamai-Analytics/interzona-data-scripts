"""WA deposit extract - Step 2b: union-find clustering over the auto-merge edges.

Reads nodes.csv + edges.csv (from 02_edges.sql), assigns every staging row to a
cluster, and writes:
  cluster_assignment.csv   staging_id, cluster_id
  cluster_report.txt       human summary (size distribution, cross-source mix)
"""
import csv, collections, io, sys

HERE = "wa_deposit_extract/staging/"

nodes = {}
with io.open(HERE + "nodes.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        r["staging_id"] = int(r["staging_id"])
        r["latitude"] = float(r["latitude"]); r["longitude"] = float(r["longitude"])
        nodes[r["staging_id"]] = r

parent = {sid: sid for sid in nodes}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: parent[max(ra, rb)] = min(ra, rb)

n_edges = 0
with io.open(HERE + "edges.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if not r.get("a"):
            continue
        union(int(r["a"]), int(r["b"])); n_edges += 1

comp = collections.defaultdict(list)
for sid in nodes:
    comp[find(sid)].append(sid)

# stable cluster ids: 1..N ordered by min staging_id
clusters = sorted(comp.values(), key=min)
assign = {}
with io.open(HERE + "cluster_assignment.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f); w.writerow(["staging_id", "cluster_id"])
    for i, members in enumerate(clusters, 1):
        for sid in members:
            assign[sid] = i
            w.writerow([sid, i])

# ---- report -------------------------------------------------------------
sizes = collections.Counter(len(m) for m in clusters)
multi = [m for m in clusters if len(m) > 1]
src_of = lambda sid: nodes[sid]["wa_source"]

def bbox_m(members):
    import math
    lats = [nodes[s]["latitude"] for s in members]
    lons = [nodes[s]["longitude"] for s in members]
    dlat = (max(lats) - min(lats)) * 111_000
    dlon = (max(lons) - min(lons)) * 111_000 * math.cos(math.radians(sum(lats) / len(lats)))
    return (dlat ** 2 + dlon ** 2) ** 0.5

out = []
out.append("WA deposit dedup - cluster report")
out.append("=" * 50)
out.append("staging rows in ...... %d" % len(nodes))
out.append("auto-merge edges ..... %d" % n_edges)
out.append("clusters ............. %d" % len(clusters))
out.append("  single-row ........ %d" % sum(1 for m in clusters if len(m) == 1))
out.append("  multi-row ......... %d" % len(multi))
out.append("rows collapsed away .. %d" % (len(nodes) - len(clusters)))
out.append("")
out.append("cluster size distribution:")
for sz in sorted(sizes):
    out.append("  %2d rows : %4d clusters" % (sz, sizes[sz]))
out.append("")
spread = [(bbox_m(m), m) for m in multi]
spread.sort(reverse=True)
out.append("widest multi-row clusters (member coordinate spread):")
for d, m in spread[:15]:
    names = " / ".join(sorted({nodes[s]["site_name"] for s in m}))
    srcs = ",".join(sorted({src_of(s) for s in m}))
    out.append("  %6.0f m  [%s]  %s" % (d, srcs, names[:90]))
out.append("")
mix = collections.Counter()
for m in multi:
    mix[tuple(sorted({src_of(s) for s in m}))] += 1
out.append("multi-row cluster source combinations:")
for combo, c in mix.most_common():
    out.append("  %4d  %s" % (c, " + ".join(combo)))

rep = "\n".join(out)
with io.open(HERE + "cluster_report.txt", "w", encoding="utf-8") as f:
    f.write(rep + "\n")
print(rep)

# ---- review_pairs_open.csv: drop pairs now resolved (co-clustered) -------
try:
    with io.open(HERE + "review_pairs.csv", encoding="utf-8") as f, \
         io.open(HERE + "review_pairs_open.csv", "w", encoding="utf-8", newline="") as g:
        rd = csv.reader(f); wr = csv.writer(g)
        header = next(rd); wr.writerow(header)
        kept = 0
        for row in rd:
            a, b = int(row[1]), int(row[2])
            if assign.get(a) != assign.get(b):
                wr.writerow(row); kept += 1
    print("\nreview_pairs_open.csv: %d unresolved pairs" % kept)
except FileNotFoundError:
    pass
