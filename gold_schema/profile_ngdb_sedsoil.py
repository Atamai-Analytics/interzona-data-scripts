"""Profile the USGS NGDB sediment and soil CSV releases (D:/CriticalMineralsDB/USA/ngdbsed, ngdbsoil) before loading."""
import csv, collections, sys
R = "D:/CriticalMineralsDB/USA/"
for ds in ("ngdbsed", "ngdbsoil"):
    print("=" * 20, ds)
    m = collections.Counter(); prep = collections.Counter(); country = collections.Counter(); nolatlon = 0; n = 0; prec = collections.Counter()
    with open(R + ds + "/main.csv", encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            n += 1
            m[(r["sample_source"], r["primary_class"], r["specific_name"])] += 1
            prep[r["prep"][:40]] += 1; country[r["country"]] += 1; prec[r["coord_prec_est"]] += 1
            if not r["lat_wgs84"] or not r["long_wgs84"]: nolatlon += 1
    print("samples", n, "no lat/lon", nolatlon); print("countries", country.most_common(6)); print("coord precision", prec.most_common(8))
    print("source/class/name", m.most_common(25)); print("prep", prep.most_common(10))
    meth = collections.Counter(); qual = collections.Counter(); unit = collections.Counter(); tbl = collections.Counter(); neg = 0; nres = 0; species = collections.Counter()
    with open(R + ds + "/chemistry.csv", encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            nres += 1; meth[r["amethod"]] += 1; qual[r["qualifier"]] += 1; unit[r["unit"]] += 1; tbl[r["tblname"]] += 1; species[r["species"]] += 1
            try:
                if float(r["qvalue"]) < 0: neg += 1
            except ValueError: qual["BADVALUE:" + r["qvalue"][:10]] += 1
    print("results", nres, "negative", neg); print("qualifiers", qual.most_common(15)); print("units", unit.most_common(10))
    print("tables", tbl.most_common(20)); print("methods", len(meth), meth.most_common(60)); print("species", len(species), species.most_common(15))
