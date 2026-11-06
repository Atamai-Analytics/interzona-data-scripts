"""One-off 2026-11-06: re-derive fact_data->>'study' for the Canadian report facts (docs 415-434) with the loader's new study_name rule, so
studies whose date sat after the title's colon (docs 415, 425) carry it. Only rows whose value changes are updated. --apply to write.
Uses the same admin connection as canada_report_load.py."""
import os, re, sys, psycopg2

GS = r"C:\Users\dean\claude_lithosurfer\lithosurfer-work\gold_schema"
src = open(os.path.join(GS, "canada_report_load.py"), encoding="utf-8").read()
ns = {"re": re}
exec(src[src.index("def study_name"):src.index("def embed(texts):")], ns)
study_name = ns["study_name"]

ENV = {}
for f in (os.path.join(GS, "..", ".env"), r"C:\Users\dean\critical-minerals-ai\.env.local"):
    if os.path.exists(f):
        for l in open(f, encoding="utf-8"):
            l = l.strip()
            if l and not l.startswith("#") and "=" in l:
                k, v = l.split("=", 1); ENV.setdefault(k.strip(), v.strip())
conn = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                        user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
cur = conn.cursor()
cur.execute("""SELECT f.extracted_fact_id, f.fact_data->>'study', d.title FROM docs.extracted_facts f JOIN docs.documents d USING (document_id)
               WHERE f.document_id BETWEEN 415 AND 434 AND f.fact_data ? 'study'""")
changes = [(fid, old, study_name(title)) for fid, old, title in cur.fetchall() if study_name(title) != old]
for fid, old, new in changes[:4]:
    print(fid, "|", old, "->", new)
print("rows changing:", len(changes), "| distinct new values:", sorted({c[2] for c in changes}))
if "--apply" in sys.argv:
    for fid, old, new in changes:
        cur.execute("UPDATE docs.extracted_facts SET fact_data = jsonb_set(fact_data, '{study}', to_jsonb(%s::text)) WHERE extracted_fact_id = %s", (new, fid))
    conn.commit(); print("committed")
conn.close()
