"""Map Mineral Resources Tasmania lithology names (free text, e.g. 'mudstone, carbonaceous', 'granitic-rock (granitoid)') to geochem.lithology codes.

Order: (1) exact dictionary name; (2) curated synonym; (3) the base name before a comma or bracket, by name or synonym; (4) keyword rules;
(5) no match -> None (the loader stores UNKNOWN). The MRT text itself is always kept verbatim in lithology_observations.lithology_local.
map_lithology(text, by_name) -> (code or None, how) where how is exact / synonym / base / keyword / none.
"""
import re

# curated: MRT name (lower case) -> geochem.lithology code
SYN = {
    "dolerite": "DIABASE", "dolerite, granophyric": "DIABASE", "metadolerite": "METDOL", "quartzite": "QUARTZITE_METAMORPHIC",
    "quartz (vein)": "QUARTZ_VEIN", "vein": "HYDUND", "carbonate (vein)": "CARBONATE_VEIN", "pyrite (vein)": "HYDUND", "hematite (vein)": "HYDUND",
    "volcaniclastic sedimentary rock": "VOLCANICLAST", "volcaniclastic-igneous-rock and tephra": "VOLCANICLAST",
    "volcaniclastic-sedimentary-rock and sediment": "VOLCANICLAST", "volcaniclastic sedimentary rock or sediment": "VOLCANICLAST",
    "volcaniclastic-sediment": "VOLCANICLAST", "fragmental igneous rock": "VOLCANICLAST", "pyroclastic rocks": "VOLCANICLAST",
    "tephra (pyroclastic sediment)": "TEPHRA", "pyroclastics, felsic": "FELVOL", "pyroclastics, mafic": "MAFUND",
    "granitic-rock (granitoid)": "GRANITE", "microgranite": "GRANITE", "granite, porphyritic": "GRPOR", "granite, granophyric": "GRNPH",
    "pegmatitic granite": "PEGMATITE", "pegmatite (undiff)": "PEGMATITE", "aplites (granitic)": "APLITE", "monzogranite (adamellite)": "MZGR",
    "alkali-feldspar-granite": "ALKFGR", "alkali-feldspar-syenite": "SYENITE", "syenitic-rock": "SYENITE", "quartz-monzonite": "QUARTZ_MONZONITE",
    "quartz-diorite": "QZDIO", "quartz-gabbro": "QZGAB", "dioritic-rock": "DIORITE", "microdiorite": "DIORITE", "microgranodiorite": "GRANODIORITE",
    "gabbroic-rock": "GABBRO", "hornblende-gabbro": "GABBRO", "olivine-gabbro": "GABBRO", "orthopyroxene-gabbro": "GABBRO", "gabbro (ss)": "GABBRO",
    "orthopyroxenite": "PYROXENITE", "ultramafic-rock (xdcgr)": "ULMFUND", "ultramafitic-rock (xdfgnr)": "ULMFUND", "metaultramafic-rock": "METAULTRAMAF",
    "meta-ultramafitite": "METAULTRAMAF", "serpentinite (ultramafic)": "SERPENTINITE", "serpentinite (undiff)": "SERPENTINITE", "talc-rock": "TALC_ROCK",
    "lava (undifferentiated)": "EXTR_VOLC_UND", "volcanic rock": "VOLUND", "igneous rock": "IGNUND", "crystalline-igneous-rock": "IGNUND",
    "crystalline-igneous-rock [normal]": "IGNUND", "crystalline-igneous-rock [exotic]": "IGNUND", "crystalline-igneous rock, normal-cgnd": "IGNUND",
    "glassy-igneous-rock": "VOLC_GLASS", "meta-igneous rock": "METAIGNEOUS", "porphyry": "PORUND", "basaltic-rock": "BASALT", "basaltic-andesite": "ANDESITE",
    "basalt, tholeiitic": "BASALT_THOLEIITIC", "basalt, alkaline": "BASALT_ALKALINE", "basalt, olivine": "OLIVINE_THOL", "andesitic-rock": "ANDESITE",
    "dacitic-rock": "DACITE", "rhyolitic-rock": "RHYOLITE", "trachytic-rock": "TRACHYTE", "mugearite": "TRABAS", "benmoreite": "TRAAND",
    "shoshonite": "TRABAS", "boninite": "MAFUND", "mafite": "MAFUND", "metamafite": "METAMAFITE", "metabasalt": "METBAS", "metagabbro": "METGAB",
    "metagabbroic-rock": "METGAB", "metadioritic-rock": "METDIO", "metagranite": "META_GRANITE", "metagranodiorite": "META_GRANODIORITE",
    "metafelsite": "METAFELSITE", "metavolcanic": "METAVOLC", "metavolcaniclastic-rock": "METAVOLC", "metamorphosed tuff": "META_TUFF",
    "picrite": "PICBAS", "hyaloclastite": "BRECCIA_VOLCANIC", "autobreccia": "BRECCIA_VOLCANIC", "pyroclastic-breccia": "BRECCIA_VOLCANIC",
    "tuffaceous-breccia": "BRECCIA_VOLCANIC", "volcaniclastic-sedimentary breccia": "BRECCIA_VOLCANIC", "fault-breccia": "FLTBX",
    "metamorphic-fault breccia": "FLTBX", "fault-gouge": "FAULT_GOUGE", "cataclastic-rock": "CATACLASITE", "mylonitic-rock": "MYLONITE",
    "protomylonite": "MYLONITE", "ultramylonite": "MYLONITE", "melange": "TECTONITE", "mechanically broken and reconstituted rock": "CATACLASITE",
    "migmatitic rock": "MIGMATITE", "granofels (granulite)": "GRANOFELS", "calcsilicate-rock": "CALCSILICATE", "epidosite": "EPIDOTITE",
    "ophicalcite": "MARBLE", "metacarbonate-rock": "METACARB", "hydrothermal and metasomatic-rocks": "HYDUND", "silicified rock": "ALTERATION_SILICIFICATION",
    "listwanite": "ALTERATION_CARBONATE",
    "wacke": "GREYWACKE", "wacke, lithic": "GREYWACKE", "wacke, quartz": "QZGW", "metawacke": "METAGRAYWACKE", "metaquartz-wacke": "METAGRAYWACKE",
    "arenite, quartz": "QUARTZ_ARENITE", "arenite, lithic": "LITHAR", "arenite, feldspathic": "ARKAR", "arenite, siliciclastic": "SANDSTONE",
    "metaquartz-arenite": "METAQUARTZITE", "meta-arenite": "METAR", "psammite": "META_SANDSTONE", "metasandstone": "META_SANDSTONE",
    "metasiltstone": "META_SILTSTONE", "metamudstone": "META_MUDSTONE", "metaconglomerate": "META_CONGLOMERATE", "metasediments": "METASED",
    "metasedimentary rock (siliciclastic)": "METASED", "metasiliceous rocks": "METASED", "metahybrid sedimentary rocks": "METASED",
    "metamorphic rocks and metasediments": "METUND", "metamorphic rocks with unknown protolith": "METUND", "calcareous pelite": "PELITE",
    "semipelite, calcareous": "PELITE", "hybrid sedimentary rocks": "SEDUND", "sedimentary rocks (siliciclastic)": "CLASED",
    "sediment and sedimentary rock (siliciclastic)": "CLASED", "sediment and sedimentary rock": "SEDUND", "sediments (undifferentiated)": "SEDUND",
    "rock and sediment  (undiff.)": "UNKNOWN", "rock (undifferentiated)": "UNKNOWN", "diamictite": "TILLITE", "tuffaceous-siltstone": "SILTSTONE",
    "tuffaceous-sandstone": "SANDSTONE", "tuffaceous-sedimentary-rock": "VOLCANICLAST", "carbonate sediments and carbonate sedimentary rock": "LIMESTONE",
    "argillaceous (muddy) limestone/cementstone/calcilutite": "LIMESTONE", "aeolianite": "CALCARENITE", "magnesite-stone": "METACARB",
    "serpentine-dolomite": "DOLOMITE", "talc-dolomite": "DOLOMITE", "iron-sediment": "IRONSTONE", "phosphate-gravel": "PHOSPHORITE",
    "phosphatic sediments and phosphorites": "PHOSPHORITE", "oilshale": "OIL_SHALE", "coal shale": "SHALE", "bituminous deposit": "COAL",
    "jasper": "CHERT", "silcrete": "REGOLITH", "weathered rock": "WEATHERED", "palaeosoil (undifferentiated)": "SOIL", "superficial deposit": "REGOLITH",
    "boulder(s) (undifferentiated)": "GRAVEL", "mud": "CLAY", "peat": "SOIL", "organic": "SOIL", "loam": "SOIL", "clay loam": "SOIL", "sandy loam": "SOIL",
    "clay (soil)": "SOIL", "sand (soil)": "SOIL", "soil - undifferentiated": "SOIL", "clays": "CLAY", "heavy mineral sands": "SAND", "bauxite": "LATERITE",
    "mineralisation": "MINUND", "sulphide ore": "SULFIDE_ORE", "iron ore": "OXIDE_ORE", "metallic ores:": "MINUND",
    "nephelinite": "MAFUND", "melilitic-rock": "MAFUND", "basanitic-foidite": "BASANITE", "phonolitic-tephrite": "PHON", "spessartite": "LAMPROPHYRE",
    "monchiquite": "LAMPROPHYRE", "sediments and sedimentary rocks rich in organic matter": "SEDUND", "sedimentary-rock rich in organic matter": "SEDUND",
    "slag": "ARTIFICIAL_FILL", "fill": "ARTIFICIAL_FILL", "miscellaneous mine products": "ARTIFICIAL_FILL", "bricks": "ARTIFICIAL_FILL",
    "concretes": "ARTIFICIAL_FILL", "construction material": "ARTIFICIAL_FILL", "asbestos filter": "ARTIFICIAL_FILL", "silica flour": "ARTIFICIAL_FILL",
}

# (pattern, code): applied in order after the name / synonym / base steps
RULES = [
    (r"\bore\b", "MINUND"), (r"^asbestos", "MINUND"), (r"^lime-", "LIMESTONE"), (r"^dolomite-", "DOLOMITE"), (r"^coal\b", "COAL"),
    (r"tuff", "TUFF"), (r"^volcaniclastic", "VOLCANICLAST"), (r"schist", "SCHIST"), (r"^sandstone", "SANDSTONE"), (r"^siltstone", "SILTSTONE"),
    (r"^mudstone", "MUDSTONE"), (r"^limestone", "LIMESTONE"), (r"^conglomerate", "CONGLOMERATE"), (r"^clay", "CLAY"), (r"^sand\b", "SAND"),
    (r"^gravel", "GRAVEL"), (r"^porphyry", "PORUND"), (r"^basalt", "BASALT"), (r"^andesite", "ANDESITE"), (r"^pelite", "PELITE"), (r"^chert", "CHERT"),
    (r"^phyllite", "PHYLLITE"), (r"^breccia", "BRECCIA_SEDIMENTARY"), (r"^meta", "METUND"), (r"^granite", "GRANITE"),
]


def map_lithology(text, by_name):
    t = (text or "").strip()
    if not t:
        return None, "none"
    k = re.sub(r"\s+", " ", t.lower())
    if k in by_name: return by_name[k], "exact"
    if k in SYN: return SYN[k], "synonym"
    for base in (k.split(",")[0].strip(), k.split("(")[0].strip()):
        if base and base in by_name: return by_name[base], "base"
        if base and base in SYN: return SYN[base], "base"
    for pat, code in RULES:
        if re.search(pat, k): return code, "keyword"
    return None, "none"
