"""
build_co2_database.py - Builds co2_database.xlsx from BR18 Tabel 7 (Danish generic LCA data,
the same generic data used in LCAbyg).

Source data: tabel7.csv + lcabyg_tabel7_map.json from https://github.com/ocni-dtu/table7 (src/ folder),
version 2025 (published 2025-07-01). Put both files next to this script and run:
    python build_co2_database.py

Every factor is converted to kgCO2e per m3, so carbon.py only multiplies volume x factor.
To add a material: add a row to SELECTION (Tabel 7 ID + the thickness if the product is per m2).
"""

import csv
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent

# category used by carbon.py  ->  Tabel 7 ID, extra info
SELECTION = [
    # category,                         table7_id, thickness_m (only for per-m2 products), rebar_kg_per_m3, needs_cross_section, note
    ("Concrete C20/25",                 "#B1425", None, 100, "no",  "Ready-mix C20/25 SCC. Unreinforced: rebar added separately"),
    ("Concrete C25/30",                 "#B1433", None, 100, "no",  "Ready-mix C25/30. Unreinforced: rebar added separately"),
    ("Concrete C30/37",                 "#B1477", None, 100, "no",  "Ready-mix C30/37. Unreinforced: rebar added separately"),
    ("Concrete C35/45",                 "#B1441", None, 100, "no",  "Ready-mix C35/45 CEM I. Unreinforced: rebar added separately"),
    ("Concrete C40/50",                 "#B1461", None, 100, "no",  "Ready-mix C40/50 CEM I. Unreinforced: rebar added separately"),
    ("Concrete C45/55",                 "#B1469", None, 100, "no",  "Ready-mix C45/55. Unreinforced: rebar added separately"),
    ("Concrete (class not specified)",  "#B1433", None, 100, "no",  "ASSUMPTION: no strength class in the IFC -> C25/30 used"),
    ("Precast concrete wall 20 cm",     "#B1389", 0.20, 0,   "no",  "Precast wall element, 5-15 kg rebar/m2 included. Per m2 / 0.20 m"),
    ("Precast hollow-core slab 22 cm",  "#B1346", 0.22, 0,   "no",  "Huldaek 22 cm. Per m2 / 0.22 m = per m3 of GROSS slab volume"),
    ("Precast hollow-core slab 32 cm",  "#B1350", 0.32, 0,   "no",  "Huldaek 32 cm. Per m2 / 0.32 m = per m3 of GROSS slab volume"),
    ("Reinforcement steel",             "#D1590", None, 0,   "no",  "Also used for the rebar inside in-situ concrete"),
    ("Structural steel",                "#D1591", None, 0,   "yes", "Rolled profiles (HEA, IPE...). Needs CrossSection_m2, not width x height"),
    ("Structural steel welded",         "#D1592", None, 0,   "yes", "Welded built-up profiles"),
    ("Structural steel hollow section", "#D1593", None, 0,   "yes", "RHS / SHS / CHS tubes"),
    ("Light steel profiles",            "#D1594", None, 0,   "yes", "Thin-walled studs and light profiles"),
    ("Glulam",                          "#B1339", None, 0,   "no",  "Biogenic carbon: negative A1-A3, released in C3 (incineration)"),
    ("CLT",                             "#B1318", None, 0,   "no",  "Biogenic carbon: negative A1-A3, released in C3 (incineration)"),
    ("Solid timber",                    "#B1370", None, 0,   "no",  "Planed pine/spruce. Biogenic carbon: negative A1-A3, released in C3"),
    ("Brick",                           "#D1507", None, 0,   "no",  "Red brick. Yellow/other colours: #D1508 (higher)"),
    ("Sand-lime brick",                 "#D1511", None, 0,   "no",  "Kalksandsten"),
    ("Aerated concrete",                "#D1512", None, 0,   "no",  "Porebeton / gasbeton"),
    ("Lightweight aggregate block",     "#B1358", None, 0,   "no",  "Letklinkerblok, massiv"),
    ("Concrete block",                  "#G0330", None, 0,   "no",  "Betonmursten"),
]

RULES = [
    # pattern on normalised name (lowercase, no accents, ae/oe/aa), category, example. FIRST MATCH WINS.
    (r"huldaek|hollow ?core", "Precast hollow-core slab 22 cm", "Huldæk 22; Hollow core slab (CHECK thickness!)"),
    (r"vaegelement|precast wall|betonelement", "Precast concrete wall 20 cm", "Betonvægelement (CHECK thickness!)"),
    (r"porebeton|gasbeton|aerated|aircrete|\bytong\b|\bh ?h\b", "Aerated concrete", "Porebeton; Aircrete; H+H"),
    (r"letklinker|leca|lightweight aggregate", "Lightweight aggregate block", "Letklinkerblok; Leca"),
    (r"letbeton|lightweight concrete", "Aerated concrete", "Letbeton (ASSUMPTION: aerated)"),
    (r"concrete block|betonblok|betonmursten|betonsten", "Concrete block", "Masonry - Concrete Block"),
    (r"kalksand|sand lime", "Sand-lime brick", "stone_sand-lime; Kalksandsten"),
    (r"tegl|mursten|brick", "Brick", "Tegl (mursten); Masonry - Brick"),
    (r"armering|rebar|reinforcing bar|reinforcement", "Reinforcement steel", "Armeringsstål"),
    (r"\b(rhs|shs|chs)\b|hollow section|\btube\b|roerprofil", "Structural steel hollow section", "RHS 100x100x5; Rørprofil"),
    (r"svejst|welded", "Structural steel welded", "Svejst profil"),
    (r"metal stud|light steel|let stal|tyndplade|stalskelet", "Light steel profiles", "Metal - Stud Layer"),
    (r"\b(stal|staal|steel)\b|\bs ?(235|275|355|460)\b|\b\d{3} mpa\b|\b(hea|heb|hem|ipe|upe|unp)\b", "Structural steel", "Stål S355; Steel - 345 MPa; HEA200"),
    (r"limtrae|glulam|\bgl ?\d{2}", "Glulam", "Limtræ GL30"),
    (r"\bclt\b|krydslam|cross laminated", "CLT", "CLT panel"),
    (r"trae|timber|wood|spruce|\bgran\b|\bfyr\b|pine|\bc ?(14|16|18|24|30)\b(?!/)", "Solid timber", "wood_spruce_beam; Konstruktionstræ C24"),
    (r"c ?20/25", "Concrete C20/25", "Beton C20/25"),
    (r"c ?25/30", "Concrete C25/30", "Beton - C25/30, in-situ"),
    (r"c ?30/37", "Concrete C30/37", "Concrete C30/37"),
    (r"c ?35/45", "Concrete C35/45", "Beton C35/45"),
    (r"c ?40/50", "Concrete C40/50", "Beton C40/50"),
    (r"c ?45/55", "Concrete C45/55", "Beton C45/55"),
    (r"(beton|concrete).*\b20 ?mpa", "Concrete C20/25", "Concrete - 20 MPa (cylinder strength)"),
    (r"(beton|concrete).*\b25 ?mpa", "Concrete C25/30", "Concrete - 25 MPa"),
    (r"(beton|concrete).*\b30 ?mpa", "Concrete C30/37", "Concrete - 30 MPa"),
    (r"(beton|concrete).*\b35 ?mpa", "Concrete C35/45", "Precast Concrete - 35 MPa"),
    (r"(beton|concrete).*\b40 ?mpa", "Concrete C40/50", "Concrete - 40 MPa"),
    (r"(beton|concrete).*\b45 ?mpa", "Concrete C45/55", "Concrete - 45 MPa"),
    (r"beton|concrete|cast in place|in situ", "Concrete (class not specified)", "M_Concrete-Cast-in-Place Concrete"),
    # LAST: layers that are not structure (checked only if no structural material matched above)
    (r"insulat|isolering|mineral ?wool|rockwool|glasswool|\bbatt\b|membrane|roofing felt|\bfelt\b|vapou?r|"
     r"\bair\b|gypsum|\bgips\b|plasterboard|\bplaster\b|covering|finish|paint|\btile|carpet|acoustic",
     "Not counted (non-structural layer)", "Insulation; Roofing felt; Air space; Plasterboard; Floor covering"),
]


def num(x):
    return float(x) if x not in ("", "-", None) else 0.0


def to_per_m3(row, thickness):
    """Convert a Tabel 7 value (per declared unit) to per m3. Returns (factor, explanation)."""
    unit, fu = row["Deklareret enhed (FU)"], num(row["Deklareret faktor (FU)"])
    mass, mass_unit = num(row["Masse faktor"]), row["Masse enhed"]
    if unit == "m³":
        return 1 / fu, "declared per m3"
    if unit == "ton" and mass_unit == "kg/m³":
        return mass / 1000 / fu, f"per ton x {mass:g} kg/m3 / 1000"
    if unit == "kg" and mass_unit == "kg/m³":
        return mass / fu, f"per kg x {mass:g} kg/m3"
    if unit == "m²" and thickness:
        return 1 / (fu * thickness), f"per m2 / {thickness} m thickness"
    raise ValueError(f"Cannot convert {row['Sorterings ID']} ({unit}, {mass_unit}) to m3")


def density(row, thickness):
    mass, mass_unit = num(row["Masse faktor"]), row["Masse enhed"]
    if mass_unit == "kg/m³":
        return mass
    if mass_unit == "kg/m²" and thickness:
        return mass / thickness
    return None


def build(csv_path=HERE / "tabel7.csv", map_path=HERE / "lcabyg_tabel7_map.json", out=HERE / "co2_database.xlsx"):
    table7 = {r["Sorterings ID"]: r for r in csv.DictReader(open(csv_path, encoding="utf-8"))}
    lcabyg_ids = json.load(open(map_path, encoding="utf-8"))

    rows = []
    for category, tid, thickness, rebar, cross, note in SELECTION:
        r = table7[tid]
        k, how = to_per_m3(r, thickness)
        a = num(r["Global Opvarmning, modul A1-A3"]) * k
        c3 = num(r["Global Opvarmning, modul C3"]) * k
        c4 = num(r["Global Opvarmning, modul C4"]) * k
        rows.append({
            "category": category,
            "A1A3_kgCO2e_m3": round(a, 2),
            "C3C4_kgCO2e_m3": round(c3 + c4, 2),
            "density_kg_m3": round(density(r, thickness), 1) if density(r, thickness) else None,
            "rebar_kg_per_m3": rebar,
            "needs_cross_section": cross,
            "table7_id": tid,
            "lcabyg_id": lcabyg_ids.get(tid),
            "table7_name_dk": r["Navn DK"],
            "table7_value": f"A1-A3 {r['Global Opvarmning, modul A1-A3']} / C3 {r['Global Opvarmning, modul C3']} / "
                            f"C4 {r['Global Opvarmning, modul C4']} per {r['Deklareret faktor (FU)']} {r['Deklareret enhed (FU)']}",
            "conversion": how,
            "data_type": r["Data type"],
            "note": note,
            "verified": "yes - BR18 Tabel 7 (2025)",
            "source_url": r["Url (link)"],
        })
    factors = pd.DataFrame(rows)
    rules = pd.DataFrame(RULES, columns=["pattern", "category", "example"])
    readme = pd.DataFrame({"How to use this file": [
        "Factors: kgCO2e per m3 for each category, from BR18 Tabel 7 version 2025 (Danish generic data, also used in LCAbyg).",
        "Source: github.com/ocni-dtu/table7 -> src/tabel7.csv. lcabyg_id = the same product's ID in LCAbyg.",
        "A1A3 = production. C3C4 = waste processing + disposal (end of life). Module D is NOT included.",
        "Biogenic carbon (timber): A1-A3 is negative because the wood stores CO2; it is released again in C3. Always use A1-A3 + C3-C4 together for timber.",
        "In-situ concrete in Tabel 7 is UNREINFORCED. carbon.py adds rebar_kg_per_m3 x Reinforcement steel. 100 kg/m3 is an ASSUMPTION - agree on it.",
        "Rules: the material filter. Checked top to bottom, the FIRST match wins. Patterns are regular expressions on the normalised name (lowercase, no accents, ae/oe/aa).",
        "A material that matches no rule appears in the report sheet 'Problems'. Add a rule here and run again.",
        "To add a product from Tabel 7: add it to SELECTION in build_co2_database.py and run the script again.",
    ]})
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        readme.to_excel(w, sheet_name="README", index=False)
        factors.to_excel(w, sheet_name="Factors", index=False)
        rules.to_excel(w, sheet_name="Rules", index=False)
        from openpyxl.styles import Font, PatternFill
        for ws in w.sheets.values():
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="5B2C83")
            ws.freeze_panes = "B2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 60)
    return factors


if __name__ == "__main__":
    f = build()
    print(f[["category", "table7_id", "A1A3_kgCO2e_m3", "C3C4_kgCO2e_m3", "conversion"]].to_string(index=False))
