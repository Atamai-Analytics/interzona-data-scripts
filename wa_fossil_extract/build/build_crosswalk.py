"""WA fossil age -> stratigraphic_age_reference: emit the resolved crosswalk CSV
for \\copy into a staging table, keyed on the verbatim reported_age string."""
import csv, collections
import importlib.util
spec = importlib.util.spec_from_file_location("pa", "wa_fossil_extract/build/parse_ages.py")
pa = importlib.util.module_from_spec(spec); spec.loader.exec_module(pa)

rows = list(csv.DictReader(open("wa_fossil_extract/build/wa_fossil_age.csv", encoding="utf-8")))
distinct = sorted(set(r["reported_age"] for r in rows))

out = []
method_count = collections.Counter()
for txt in distinct:
    row, how, conf, mentions = pa.resolve(txt)
    method_count[how] += 1
    out.append({
        "reported_age": txt,
        "stratigraphic_age_id": row["stratigraphic_age_id"],
        "matched_age_name": row["age_name"],
        "confidence_level": conf,
        "match_method": how,
    })

with open("wa_fossil_extract/build/crosswalk_reported_age.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["reported_age", "stratigraphic_age_id", "matched_age_name", "confidence_level", "match_method"])
    w.writeheader()
    for o in out: w.writerow(o)

print(f"{len(out)} distinct reported_age strings resolved -> crosswalk_reported_age.csv")
print("method mix:", dict(method_count))
print("confidence mix:", collections.Counter(o["confidence_level"] for o in out))
