"""Shared grouping of HS 6-digit product codes into commodities (OUR grouping, not a published classification).
Used by load_baci_minerals.py; the same rules as load_oecd_export_restrictions.py plus the two downstream codes kept from BACI
(850511 permanent magnets, 850760 lithium-ion batteries). Mixed HS groups keep a published-style name, e.g. 'Niobium, tantalum, vanadium (ores)'.
"""

HEADING = {
    "2502": "Pyrite", "2504": "Graphite", "2505": "Natural sands", "2507": "Kaolin", "2508": "Clays (bentonite etc.)", "2510": "Phosphate rock",
    "2511": "Barite", "2512": "Diatomite", "2513": "Pumice and natural abrasives", "2519": "Magnesium (magnesite)", "2520": "Gypsum",
    "2521": "Limestone flux", "2522": "Lime", "2526": "Talc", "2528": "Boron (natural borates)", "2530": "Other minerals (mica, vermiculite etc.)",
    "2601": "Iron ore", "2602": "Manganese", "2603": "Copper", "2604": "Nickel", "2605": "Cobalt", "2606": "Aluminium (bauxite)", "2607": "Lead",
    "2608": "Zinc", "2609": "Tin", "2610": "Chromium", "2611": "Tungsten", "2612": "Uranium and thorium", "2613": "Molybdenum", "2614": "Titanium",
    "2616": "Precious metals (ores)", "2618": "Iron and steel slag", "2619": "Iron and steel slag", "2620": "Metal-bearing ash and residues",
    "2621": "Metal-bearing ash and residues", "2701": "Coal", "2704": "Coke", "2809": "Phosphate rock", "2810": "Boron (natural borates)",
    "2817": "Zinc", "2818": "Aluminium (bauxite)", "2819": "Chromium", "2820": "Manganese", "2821": "Iron ore", "2822": "Cobalt",
    "2823": "Titanium", "2824": "Lead", "2826": "Fluorspar", "2835": "Phosphate rock", "2840": "Boron (natural borates)",
    "2843": "Precious metals (compounds)", "2846": "Rare earths", "2852": "Mercury", "3104": "Potash", "4403": "Wood", "4407": "Wood",
    "7102": "Diamonds", "7105": "Diamonds", "7106": "Silver", "7107": "Silver", "7108": "Gold", "7109": "Gold", "7110": "Platinum-group metals",
    "7111": "Platinum-group metals", "7112": "Precious metals (waste and scrap)", "7201": "Pig iron", "7202": "Ferroalloys",
    "7203": "Iron (direct-reduced)", "7204": "Iron and steel scrap", "7205": "Iron powders",
    "8101": "Tungsten", "8102": "Molybdenum", "8103": "Tantalum", "8104": "Magnesium", "8105": "Cobalt", "8106": "Bismuth", "8107": "Cadmium",
    "8108": "Titanium", "8109": "Zirconium", "8110": "Antimony", "8111": "Manganese", "8113": "Cermets",
}
CODE = {
    "261510": "Zirconium", "261590": "Niobium, tantalum, vanadium (ores)", "261710": "Antimony", "261790": "Other ores",
    "252910": "Feldspar", "252921": "Fluorspar", "252922": "Fluorspar", "252930": "Leucite, nepheline",
    "280519": "Alkali and alkaline-earth metals (incl. lithium metal)", "280530": "Rare earths", "280540": "Mercury",
    "282520": "Lithium", "282530": "Vanadium", "282540": "Nickel", "282550": "Copper", "282560": "Germanium", "282570": "Molybdenum",
    "282580": "Antimony", "283691": "Lithium", "283692": "Strontium", "283324": "Nickel", "283325": "Copper",
    "811212": "Beryllium", "811213": "Beryllium", "811219": "Beryllium", "811221": "Chromium", "811222": "Chromium", "811229": "Chromium",
    "811251": "Thallium", "811252": "Thallium", "811259": "Thallium",
    "811292": "Germanium, gallium, indium, vanadium, niobium, hafnium, rhenium (grouped)",
    "811299": "Germanium, gallium, indium, vanadium, niobium, hafnium, rhenium (grouped)",
    "850511": "Permanent magnets (metal, incl. rare-earth magnets)", "850760": "Lithium-ion batteries",
}
CHAPTER = {"72": "Iron and steel", "74": "Copper", "75": "Nickel", "76": "Aluminium", "78": "Lead", "79": "Zinc", "80": "Tin"}
KEYWORDS = [("lithium", "Lithium"), ("cobalt", "Cobalt"), ("nickel", "Nickel"), ("copper", "Copper"), ("zinc", "Zinc"), ("lead", "Lead"),
            ("mangan", "Manganese"), ("chrom", "Chromium"), ("molybd", "Molybdenum"), ("tungst", "Tungsten"), ("vanad", "Vanadium"),
            ("german", "Germanium"), ("gallium", "Gallium"), ("indium", "Indium"), ("antimon", "Antimony"), ("titan", "Titanium"),
            ("zircon", "Zirconium"), ("tantal", "Tantalum"), ("niob", "Niobium"), ("rare-earth", "Rare earths"), ("cerium", "Rare earths"),
            ("silicon", "Silicon"), ("selen", "Selenium"), ("tellur", "Tellurium"), ("arsen", "Arsenic"), ("boron", "Boron (natural borates)"),
            ("mercur", "Mercury"), ("stront", "Strontium"), ("magnes", "Magnesium"), ("alumin", "Aluminium (bauxite)"), ("iron", "Iron ore"),
            ("phosph", "Phosphate rock"), ("fluor", "Fluorspar"), ("barium", "Barite")]


def commodity(hs6, desc=""):
    if hs6 in CODE: return CODE[hs6]
    if hs6[:4] in HEADING: return HEADING[hs6[:4]]
    if hs6[:2] in CHAPTER: return CHAPTER[hs6[:2]]
    d = (desc or "").lower()
    for k, v in KEYWORDS:
        if k in d: return v
    return "Other inorganic chemicals"


# Products kept from BACI (agreed with the user 2026-11-11): minerals and metals, not finished steel or other manufactures.
KEEP_HEADINGS = {"2502", "2504", "2510", "2511", "2519", "2526", "2528", "2529", "2530", "2804", "2805", "2818", "2822", "2825", "2826", "2833",
                 "2836", "2841", "2846", "2849", "7106", "7107", "7108", "7109", "7110", "7111", "7112", "7201", "7202", "7203", "7204", "7205",
                 "7401", "7402", "7403", "7404", "7405", "7501", "7502", "7503", "7601", "7602", "7801", "7802", "7901", "7902", "7903",
                 "8001", "8002"}
KEEP_CHAPTERS = {"26", "81"}
KEEP_CODES = {"850511", "850760"}


def keep(hs6):
    return hs6 in KEEP_CODES or hs6[:2] in KEEP_CHAPTERS or hs6[:4] in KEEP_HEADINGS
