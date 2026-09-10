# Emit SQL to apply the 204 HIGH mineral translations + 21 descriptors, then relink deposit_mineralogy.
import csv, os
O = os.path.dirname(os.path.abspath(__file__))
TAG = "claude_mineraltrans_20260910"

rows = list(csv.DictReader(open(os.path.join(O, "mineral_translation_candidates_ar.csv"), encoding="utf-8")))
apply = [r for r in rows if r["confidence"] == "HIGH" or r["category"] == "descriptor"]
print(f"{len(apply)} rows to apply ({sum(1 for r in apply if r['confidence']=='HIGH')} HIGH species + "
      f"{sum(1 for r in apply if r['category']=='descriptor')} descriptors)")

def q(s):
    return "'" + s.replace("'", "''") + "'"

WORD = {
    "oxidos": "oxides", "oxido": "oxide", "hidroxidos": "hydroxides", "hidroxido": "hydroxide",
    "carbonatos": "carbonates", "carbonato": "carbonate", "sulfosales": "sulfosalts",
    "sulfosal": "sulfosalt", "sulfuros": "sulfides", "sulfuro": "sulfide", "sulfatos": "sulfates",
    "sulfotelururos": "sulfotellurides", "silicatos": "silicates", "arcillas": "clays",
    "arcilla": "clay", "minerales": "minerals", "mineral": "mineral", "nativo": "native",
    "nativa": "native", "complejos": "complex", "especular": "specular", "hematita": "hematite",
    "grupo": "group", "del": "of the", "de": "of", "la": "the", "y": "and", "oro": "gold",
    "cuarzo": "quartz", "cobre": "copper", "hierro": "iron", "plata": "silver", "plomo": "lead",
    "bismuto": "bismuth", "manganeso": "manganese", "cobalto": "cobalt", "niquel": "nickel",
    "uranio": "uranium", "estano": "tin", "titanio": "titanium", "antimonio": "antimony",
    "cu": "copper", "fe": "iron", "mn": "manganese", "bi": "bismuth", "ni": "nickel",
    "co": "cobalt", "ag": "silver", "sn": "tin", "u": "uranium", "pt": "platinum", "ti": "titanium",
}
def descr_english(src):
    import re, unicodedata
    s = unicodedata.normalize("NFKD", src).encode("ascii", "ignore").decode().lower()
    toks = re.split(r"[\s-]+", s.strip())
    out = [WORD.get(t, t) for t in toks if t]
    return " ".join(out)

vals = []
for r in apply:
    src = r["source_text"].strip().lower()
    eng = r["proposed_english"].strip()
    mid = r["mineral_id"].strip()
    cat = "descriptor" if r["category"] == "descriptor" else "species"
    mid_sql = mid if mid else "NULL"
    if not eng and cat == "descriptor":
        eng = descr_english(src)
    eng_sql = q(eng) if eng else "NULL"
    note = q(f"auto: {r['method']}; {r['n_rows']} deposit_mineralogy rows")
    vals.append(f"  ({q(src)}, {eng_sql}, {mid_sql}, {q(cat)}, {note}, '{TAG}')")

sql = f"""-- Apply 204 HIGH + 21 descriptor Spanish->English mineral translations, then relink.
-- criticialmineralsexp, 2026-09-10. Reversible via created_by = '{TAG}'.
BEGIN;

-- backup the rows deposit_mineralogy relink will touch
CREATE TABLE deposit_mineralogy_bak_mineraltrans_20260910 AS
SELECT deposit_mineralogy_id, depositid, mineral_name_local, mineral_id
FROM deposit_mineralogy WHERE mineral_id IS NULL;

-- 1. new translation entries (skip any exact source_text already present)
INSERT INTO mineral_name_translations (source_text, english_text, mineral_id, category, notes, created_by)
VALUES
{",".join(chr(10) + v for v in vals)}
ON CONFLICT (source_text) DO NOTHING;

-- 2. relink deposit_mineralogy.mineral_id from the translation table
--    (covers the new entries AND ~39 pre-existing translated-but-unlinked names)
WITH upd AS (
  UPDATE deposit_mineralogy dm
  SET mineral_id = t.mineral_id
  FROM mineral_name_translations t
  WHERE dm.mineral_id IS NULL
    AND t.mineral_id IS NOT NULL
    AND lower(btrim(dm.mineral_name_local)) = lower(t.source_text)
  RETURNING dm.deposit_mineralogy_id, dm.depositid
)
SELECT count(*) AS deposit_mineralogy_rows_linked,
       count(DISTINCT depositid) AS deposits_affected
FROM upd;

-- summary
SELECT 'mineral_name_translations added' k, count(*)::text v
  FROM mineral_name_translations WHERE created_by = '{TAG}'
UNION ALL SELECT 'deposit_mineralogy still unlinked (all)',
  count(*)::text FROM deposit_mineralogy WHERE mineral_id IS NULL
UNION ALL SELECT 'deposit_mineralogy still unlinked (SEGEMAR)',
  count(*)::text FROM deposit_mineralogy dm
  JOIN deposits d ON d.depositid = dm.depositid
  JOIN locations l ON l.locationid = d.locationid
  WHERE dm.mineral_id IS NULL AND l.datasource LIKE 'Argentine%';

COMMIT;
"""
open(os.path.join(O, "apply_mineral_translations.sql"), "w", encoding="utf-8").write(sql)
print("wrote apply_mineral_translations.sql")
