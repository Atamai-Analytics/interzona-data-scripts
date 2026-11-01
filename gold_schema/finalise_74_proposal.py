"""Turns facilities_placement_proposal_74.csv into the file the loader reads for the 74 never-loaded facilities:
  * four placements whose town text is really a COUNTY name (the lookup picked a same-named village elsewhere in the state) are put back to UNPLACED with a note;
  * writes facilities_placement_proposal_74_final.csv (use with PROP_IN=...)."""
import pandas as pd

SRC = r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal_74.csv"
OUT = r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal_74_final.csv"
COUNTY_NOT_TOWN = {
    "Harley Dome Plant": "'Grant, UT' is probably Grand County (Harley Dome, near Cisco); lookup picked Grant village in Salt Lake Co.",
    "Jayhawk Plant": "'Grant, KS' is Grant County (SW Kansas gas field); lookup picked a village in Lincoln Co.",
    "Ulysses Plant": "'Grant, KS' is Grant County (Ulysses); lookup picked a village in Lincoln Co.",
    "Kentucky-Illinois Project": "'Crittenden and Livingston, KY' are counties; lookup picked a village in Grant Co.",
}
p = pd.read_csv(SRC, dtype=str, encoding="utf-8-sig").fillna("")
for name, why in COUNTY_NOT_TOWN.items():
    m = p["name"] == name
    assert m.sum() == 1, name
    p.loc[m, ["action", "lat", "lon", "position_accuracy"]] = ["UNPLACED", "", "", ""]
    p.loc[m, "review_candidate"] = "NOT PLACED: " + why
p.to_csv(OUT, index=False, encoding="utf-8-sig")
print(p["action"].value_counts().to_string())
