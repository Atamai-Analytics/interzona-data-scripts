"""CDoGS sample-type mapping shared by the overlap check and the loader: CDoGS SampleType name -> (gold sample type, broad medium) or None (left out).
Left out: water and lake-water samples, soil gas, vegetation (twigs, bark, seaweed, plants), public-health soils and untyped ('Null') samples."""

KEEP = {
    "NGR lake sediment grab sample": ("SED_LAKE", "lake"), "Lake sediments": ("SED_LAKE", "lake"),
    "NGR bulk stream sediment": ("SED_STREAM", "stream"), "Stream sediments": ("SED_STREAM", "stream"),
    "Heavy Mineral Concentrate (Stream)": ("SED_HMC", "hmc"),
    "Till": ("TILL_SAMPLE", "till"), "Basal till": ("TILL_BASAL", "till"), "Lodgement till": ("TILL_BASAL", "till"),
    "Ablation till": ("TILL_ABLATION", "till"), "Deformation till": ("TILL_SAMPLE", "till"), "Melt-out till": ("TILL_SAMPLE", "till"),
    "Colluviated till": ("TILL_SAMPLE", "till"), "Diamicton": ("TILL_SAMPLE", "till"), "Glacial/waterlaid": ("TILL_SAMPLE", "till"),
    "Rock (surface)": ("ROCK_SAMPLE", "rock"), "Whole": ("ROCK_SAMPLE", "rock"), "Gossan": ("ROCK_SELECT", "rock"), "Weathered bedrock": ("ROCK_SAMPLE", "rock"),
    "Limestone": ("ROCK_SAMPLE", "rock"), "Shale": ("ROCK_SAMPLE", "rock"), "Drill Core": ("CORE_SAMPLE", "rock"),
    "A-horizon soil": ("SOIL_A", "soil"), "B-horizon soil": ("SOIL_B", "soil"), "C-horizon soil": ("SOIL_C", "soil"), "Soil": ("SOIL_SAMPLE", "soil"),
    "Humus": ("SOIL_SAMPLE", "soil"),
}
for name in ["Sediment", "Sand", "Esker", "Glaciolacustrine", "Glaciofluvial", "Sand and gravel", "Colluvium", "Silt and Clay", "Pebbly sand",
             "Glaciomarine / lacustrine", "Fine sand", "Ice-contact sand", "Alluvium", "Beach sand", "Eolian", "Peat", "Organics"]:
    KEEP[name] = ("SEDIMENT_SAMPLE", "sediment")

# broad medium of the gold sample types already loaded, for the overlap check
GOLD_MEDIUM = {"SED_LAKE": "lake", "SED_STREAM": "stream", "SED_STREAM_FINE": "stream", "SED_HMC": "hmc", "TILL_SAMPLE": "till", "TILL_BASAL": "till",
               "TILL_ABLATION": "till", "TILL_GLACIAL": "till", "SOIL_A": "soil", "SOIL_B": "soil", "SOIL_C": "soil", "SOIL_SAMPLE": "soil",
               "SEDIMENT_SAMPLE": "sediment", "ROCK_SAMPLE": "rock", "ROCK_OUTCROP": "rock", "ROCK_FLOAT": "rock", "ROCK_SELECT": "rock",
               "ROCK_GRAB": "rock", "CORE_SAMPLE": "rock"}

# CDoGS organisations whose surveys are federal (Geological Survey of Canada divisions, Agriculture Canada, CIRNAC / AANDC mining recorders,
# Canada-Nunavut Geoscience Office); provincial-agency, company and US surveys are left out
FEDERAL_ORGS = {1, 2, 3, 5, 9, 11, 14, 15, 21, 22, 23, 24, 25, 29, 31, 35, 38}
