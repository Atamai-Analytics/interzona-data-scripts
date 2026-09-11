"""WA fossil age -> stratigraphic_age_reference matcher.
Standalone dev/debug pass: read distinct reported_age strings, resolve each to
a stratigraphic_age_id, print unmatched / low-confidence ones for review.
"""
import csv, json, re, collections

ref = list(csv.DictReader(open("wa_fossil_extract/build/stratigraphic_age_reference.csv", encoding="utf-8")))
for r in ref:
    r["age_start_ma"] = float(r["age_start_ma"]) if r["age_start_ma"] else None
    r["age_end_ma"] = float(r["age_end_ma"]) if r["age_end_ma"] else None

canon = {}                      # lowercase age_name -> row   (skips RANGE "_" names)
range_lookup = {}                # frozenset({base1,base2}) -> row
range_by_name = {}               # "a_b" lowercase -> row (direct, for crosswalk targets)
for r in ref:
    name = r["age_name"]
    if r["age_type"] == "RANGE" and "_" in name:
        a, b = name.split("_", 1)
        range_lookup[frozenset({a.lower(), b.lower()})] = r
        range_by_name[name.lower()] = r
    else:
        canon[name.lower()] = r

# alias Early<->Lower / Late<->Upper so a reference row filed under one spelling
# ("Upper Jurassic") is also matched by source text using the other ("Late Jurassic")
_ALIAS = {"early": "lower", "lower": "early", "late": "upper", "upper": "late"}
for name in list(canon):
    w = name.split(" ", 1)
    if len(w) == 2 and w[0] in _ALIAS:
        alias = f"{_ALIAS[w[0]]} {w[1]}"
        canon.setdefault(alias, canon[name])

# known source typos -> corrected word (applied to the raw text before matching)
TYPO_FIX = {"eocone": "eocene", "mississppian": "mississippian"}

MOD = ("earliest", "latest", "uppermost", "lowermost", "early", "late", "middle", "upper", "lower")
SWAP = {"early": "lower", "late": "upper", "earliest": "lower", "latest": "upper",
        "uppermost": "upper", "lowermost": "lower"}

def strip_mod(name):
    w = name.split()
    if w and w[0].lower() in MOD:
        return " ".join(w[1:]), w[0].lower()
    return name, None

def base_lookup(name):
    """Resolve a single chronostrat phrase (already lowercase) to a ref row, trying
    the literal name, the modifier-swapped name (late<->upper, early<->lower), then
    the bare base unit with no modifier."""
    name = name.strip()
    if name in canon:
        return canon[name], "exact"
    base, mod = strip_mod(name)
    if mod:
        swapped = SWAP.get(mod)
        if swapped and f"{swapped} {base}" in canon:
            return canon[f"{swapped} {base}"], "modifier-swap"
        if base in canon:
            return canon[base], "base-fallback"
    return None, None

# regional / provincial stage & informal-unit synonyms not present as their own
# stratigraphic_age_reference row (WA Cenozoic benthic-foram stages, Mississippian
# provincial stages, etc.) -> a phrase base_lookup can resolve.
CROSSWALK = {
    "zemorrian": "oligocene",
    "kummerian": "oligocene",
    "refugian": "eocene_oligocene",       # tried as a range pair below
    "narizian": "eocene",
    "ulatisian": "eocene",
    "penutian": "eocene",
    "bulitian": "eocene",
    "domengine": "eocene",
    "fultonian": "mississippian",
    "ravenian": "mississippian",
    "chesterian": "mississippian",
    "meramecian": "mississippian",
    "wolfcampian": "permian",
    "hueco": "permian",
    "berriasian": "early cretaceous",
    "hauterivian": "early cretaceous",
}

UNCERTAIN_RE = re.compile(r"probably|possibly|\bor younger\b|\bor older\b|as young as|questionable|\?", re.I)
# canonical names sorted longest-first so "late jurassic" matches before "jurassic"
ALL_NAMES = sorted(set(canon) | set(CROSSWALK), key=len, reverse=True)
NAME_RE = {n: re.compile(r"\b" + re.escape(n) + r"\b", re.I) for n in ALL_NAMES}

def find_mentions(text):
    t = text.lower()
    hits = []
    for n in ALL_NAMES:
        if NAME_RE[n].search(t):
            hits.append(n)
    # drop names that are pure substrings of a longer hit already covering the same span
    # (e.g. "jurassic" when "late jurassic" already matched) -- simple heuristic: if a
    # shorter hit's tokens are a trailing subset of a longer hit, drop the shorter one.
    keep = []
    for n in hits:
        if any(n != m and n in m for m in hits):
            continue
        keep.append(n)
    return keep

def resolve(raw):
    confidence = "UNCERTAIN" if UNCERTAIN_RE.search(raw) else "MEDIUM"
    text = raw.lower()
    for typo, fix in TYPO_FIX.items():
        text = re.sub(r"\b" + typo + r"\b", fix, text)
    mentions = find_mentions(text)

    # crosswalk terms resolve to a target name (possibly a direct "a_b" range key)
    resolved_mentions = []
    for m in mentions:
        target = CROSSWALK.get(m, m)
        if target in range_by_name:
            return range_by_name[target], "crosswalk-range", "UNCERTAIN", mentions
        resolved_mentions.append(target)

    bases = set()
    for m in resolved_mentions:
        b, _ = strip_mod(m)
        bases.add(b)

    # two-unit range?
    if len(bases) >= 2:
        for a in bases:
            for b in bases:
                if a >= b: continue
                key = frozenset({a, b})
                if key in range_lookup:
                    return range_lookup[key], "range", "UNCERTAIN", mentions
        # no direct range row -- fall through to best single match below

    # prefer the most specific (smallest span) resolved single mention
    best, how = None, None
    for m in resolved_mentions:
        row, method = base_lookup(m)
        if row is None:
            continue
        span = (row["age_start_ma"] - row["age_end_ma"]) if row["age_start_ma"] and row["age_end_ma"] else 1e9
        if best is None or span < best[0]:
            best = (span, row); how = method
    if best:
        return best[1], how, confidence, mentions
    return None, None, confidence, mentions

if __name__ == "__main__":
    rows = list(csv.DictReader(open("wa_fossil_extract/build/wa_fossil_age.csv", encoding="utf-8")))
    distinct = collections.Counter(r["reported_age"] for r in rows)
    unresolved = []
    method_count = collections.Counter()
    for txt, n in distinct.most_common():
        row, how, conf, mentions = resolve(txt)
        method_count[how] += n
        if row is None:
            unresolved.append((n, txt, mentions))
    print("distinct strings:", len(distinct), " total rows:", sum(distinct.values()))
    print("method counts (rows):", dict(method_count))
    print(f"\nUNRESOLVED: {sum(x[0] for x in unresolved)} rows across {len(unresolved)} distinct strings")
    for n, txt, mentions in sorted(unresolved, key=lambda x: -x[0]):
        print(f"  {n:3d}  {txt!r}  mentions={mentions}")
