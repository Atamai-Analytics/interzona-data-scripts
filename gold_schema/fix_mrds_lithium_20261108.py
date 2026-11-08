"""Add lithium (SECONDARY commodity) to 5 old USGS MRDS records that are known lithium deposits, each with a cited source.

Found 2026-11-08 by matching the deposits named in library doc 444 to core.occurrences (see memory lithium-gap-fill). MRDS (stopped 2011) lists
these as tin, boron/potash or salt only. Each change appends a dated note with the source to comments; log fix_mrds_lithium_<ts>.csv for rollback
(delete the occurrence_commodities rows created_by TAG and remove the appended note).
Usage: python fix_mrds_lithium_20261108.py [--dry]
"""
import csv, os, sys, datetime
import psycopg2

DRY = "--dry" in sys.argv
TAG = "fix_mrds_lithium_20261108"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")

FIX = {
    378282: ("Uis Mine", "Andrada Mining, 'Mineral Resource Update at Uis' (RNS, 6 Feb 2025): V1V2 petalite pegmatite on ML 134, about 0.79% Li2O; https://www.lse.co.uk/rns/mineral-resource-update-at-uis-expkiziuwqcr4da.html"),
    447411: ("Uis Tin Mine", "Andrada Mining, 'Mineral Resource Update at Uis' (RNS, 6 Feb 2025): V1V2 petalite pegmatite on ML 134, about 0.79% Li2O; https://www.lse.co.uk/rns/mineral-resource-update-at-uis-expkiziuwqcr4da.html"),
    378288: ("Kamativi Mine", "Kamativi reopened as a lithium (spodumene) mine; spodumene processing plant commissioned April 2024 (Mining Index Zimbabwe / ZBC News); https://www.miningindex.co.zw/?p=25890"),
    396703: ("Zhabuye Salt Lake", "Tibet Mineral Development (000762.SZ) 10,000 t/y battery-grade lithium carbonate line at Zhabuye salt lake, commercial production from September 2025 (SMM); https://news.metal.com/en/newscontent/102829881"),
    576217: ("Qaidam Basin", "Qarhan salt lake brines (Qaidam Basin) are processed for lithium carbonate: Qinghai Salt Lake Industry 20,000 t/y battery-grade plant at full load June 2022 (Yicai Global); https://yicaiglobal.com/news/china-qinghai-salt-lake-jumps-as-new-lithium-carbonate-factory-comes-online"),
}

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT commodity_id FROM core.commodities WHERE commodity_symbol = 'Li'"); LI = c.fetchone()[0]
logrows = []
for oid, (name, src) in FIX.items():
    c.execute("SELECT name, is_active, commodities FROM core.occurrences WHERE occurrence_id = %s", (oid,))
    nm, act, coms = c.fetchone()
    assert nm == name and act, (oid, nm, act)
    if "Li" in (coms or []): print("already Li", oid); continue
    c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,'SECONDARY',true,%s)", (oid, LI, TAG))
    note = f"Lithium added 2026-11-08 (not in MRDS): {src}"
    c.execute("UPDATE core.occurrences SET comments = concat_ws('; ', comments, %s), modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (note, TAG, oid))
    c.execute("SELECT commodities FROM core.occurrences WHERE occurrence_id = %s", (oid,))
    logrows.append((oid, name, coms, c.fetchone()[0], note))
    print(oid, name, coms, "->", logrows[-1][3])
path = os.path.join(HERE, f"fix_mrds_lithium_{datetime.datetime.now():%Y%m%d_%H%M%S}{'_DRY' if DRY else ''}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["occurrence_id", "name", "commodities_before", "commodities_after", "note_appended"]); w.writerows(logrows)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED", path)
