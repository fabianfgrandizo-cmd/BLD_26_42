"""
embodied_carbon - Team 42: embodied CO2 of the changed elements

Course template (Working Together / node-comply-template):
  analyse(groups) -> JSON-compatible dict. This analysis receives a DATASET (Team 40's groups),
  not a model ("other functions may accept datasets instead"). One primary 'C' function: CALC_CO2.
  Importing this file does not open models or write files.

  CAPT_GROUPS     Team 40's groups (list of dicts, DataFrame, or their Excel file)
  CAPT_CO2DATA    data/co2_database.xlsx: material rules + CO2 factors per m3 (BR18 Tabel 7 2025)
  CONN_NAME       normalise a material name ("Stål S355" -> "stal s355")
  CONN_MATERIAL   material name -> category with the rules (the material filter)
  CALC_VOLUME     volume in m3 of a group (Team 40 gives it; fallbacks if not)
  CALC_FACTOR     kgCO2e per m3 for a category and status (new / removed), rebar included
  CALC_CO2        PRIMARY: kgCO2e for every group
  CHEK_CO2        groups that could not be calculated, and why
  COMM_CO2        summary tables
  COMM_SHEETS     add / replace sheets in an existing Excel file, keeping the others
  COMM_EXCEL      add the CO2_* sheets to Team 40's Excel file

Run alone (from the A4 folder):
  python -m embodied_carbon.src.main results/changes_variantA.xlsx
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[1]            # the embodied_carbon folder
CO2_DATABASE = HERE / "data" / "co2_database.xlsx"
TEAM40_SHEET = "Groups"

# Columns we use from Team 40 -> their name in Team 40's table. If they rename one, change it here.
COLUMNS = {
    "GlobalId": "GlobalId", "IfcClass": "IfcClass", "TypeName": "TypeName",
    "Material": "Material", "Status": "Status", "Count": "Count",
    "Length_m": "Length_m", "Area_m2": "Area_m2", "Volume_m3": "Volume_m3",
    # optional, only used when Volume_m3 is missing:
    "Width_m": "Width_m", "Height_m": "Height_m", "Thickness_m": "Thickness_m",
    "CrossSection_m2": "CrossSection_m2",
}

# New elements: whole life cycle A1-A3 + C3-C4 (as BR18 / LCAbyg). Keeps timber fair: its
# negative A1-A3 (stored biogenic carbon) is released again in C3.
# Removed elements: only C3-C4 (they are demolished now).
INCLUDE_END_OF_LIFE_FOR_NEW = True


def records(df):
    """DataFrame -> list of dicts with JSON-safe values (NaN -> None)."""
    return json.loads(df.to_json(orient="records"))


# ===================================================================== CAPT
def CAPT_GROUPS(source, sheet=TEAM40_SHEET, columns=COLUMNS):
    """source: Team 40's groups as a list of dicts or DataFrame, or the path to their Excel file.
    Returns a DataFrame with our column names; missing optional columns are empty."""
    if isinstance(source, (str, Path)):
        sheets = pd.ExcelFile(source).sheet_names
        df = pd.read_excel(source, sheet_name=sheet if sheet in sheets else 0)
    else:
        df = pd.DataFrame(source).copy()
    df = df.rename(columns={v: k for k, v in columns.items()})
    for col in columns:
        if col not in df.columns:
            df[col] = None
    df["Status"] = df["Status"].fillna("new").astype(str).str.lower().str.strip()
    return df[list(columns)]


def CAPT_CO2DATA(path=CO2_DATABASE):
    """Returns (rules, factors): the material filter rules and the CO2 factors per category."""
    rules = pd.read_excel(path, sheet_name="Rules")
    factors = pd.read_excel(path, sheet_name="Factors").set_index("category")
    return rules, factors


# ===================================================================== CONN
def CONN_NAME(text):
    """'Stål S355 – Beton C30/37' -> 'stal s355 beton c30/37' (lowercase, no accents)."""
    text = str(text).lower()
    text = text.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9/|.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def CONN_MATERIAL(material, rules):
    """The material filter: raw IFC material name -> (category or None, rule used / reason).
    rules: table with columns 'pattern' (regular expression) and 'category'; first match wins."""
    if material is None or pd.isna(material) or str(material).strip() in ("", "NO MATERIAL"):
        return None, "no material"
    if "|" in str(material):
        return None, "multi-layer material - split per layer first"
    name = CONN_NAME(material)
    for _, rule in rules.iterrows():
        if re.search(rule["pattern"], name):
            return rule["category"], rule["pattern"]
    return None, "no rule matches"


# ===================================================================== CALC
def CALC_VOLUME(row):
    """Volume in m3 of one group. Returns (volume or None, method)."""
    def ok(*cols):
        return all(pd.notna(row[c]) and row[c] != "" for c in cols)

    if ok("Volume_m3"):
        return float(row["Volume_m3"]), "given"
    if ok("CrossSection_m2", "Length_m"):
        return row["CrossSection_m2"] * row["Length_m"], "section x length"
    if ok("Area_m2", "Thickness_m"):
        return row["Area_m2"] * row["Thickness_m"], "area x thickness"
    if ok("Length_m", "Width_m", "Height_m"):
        return row["Length_m"] * row["Width_m"] * row["Height_m"], "length x width x height"
    return None, "missing volume"


def CALC_FACTOR(category, status, factors, end_of_life_for_new=INCLUDE_END_OF_LIFE_FOR_NEW):
    """kgCO2e per m3 for a category. status 'removed' -> C3-C4; otherwise A1-A3 (+ C3-C4).
    Adds rebar_kg_per_m3 x reinforcement steel where the category has it."""
    f = factors.loc[category]
    rebar_kg = f["rebar_kg_per_m3"] if pd.notna(f["rebar_kg_per_m3"]) else 0
    r = factors.loc["Reinforcement steel"]
    rebar_a = r["A1A3_kgCO2e_m3"] / r["density_kg_m3"]          # per kg of rebar
    rebar_c = r["C3C4_kgCO2e_m3"] / r["density_kg_m3"]
    if status == "removed":
        return f["C3C4_kgCO2e_m3"] + rebar_kg * rebar_c
    value = f["A1A3_kgCO2e_m3"] + rebar_kg * rebar_a
    if end_of_life_for_new:
        value += f["C3C4_kgCO2e_m3"] + rebar_kg * rebar_c
    return value


def CALC_CO2(groups, rules, factors):
    """PRIMARY FUNCTION. kgCO2e for every group = volume (m3) x factor (kgCO2e/m3).
    Returns the groups with Category, MatchedBy, VolumeMethod and kgCO2e (None if not possible)."""
    out = []
    for _, row in groups.iterrows():
        category, rule = CONN_MATERIAL(row["Material"], rules)
        volume, method = CALC_VOLUME(row)
        # an I-profile is not width x height: steel needs a real volume or cross-section
        if category and factors.loc[category].get("needs_cross_section") == "yes" \
                and method == "length x width x height":
            volume, method = None, "steel profile - needs CrossSection_m2"
        if row["Status"] == "existing" or category is None or volume is None:
            kg = None
        else:
            kg = volume * CALC_FACTOR(category, row["Status"], factors)
        out.append({**row.to_dict(), "Category": category, "MatchedBy": rule,
                    "Volume_m3": volume, "VolumeMethod": method, "kgCO2e": kg})
    columns = list(groups.columns) + ["Category", "MatchedBy", "VolumeMethod", "kgCO2e"]
    return pd.DataFrame(out, columns=columns)


# ===================================================================== CHEK
def CHEK_CO2(result, factors):
    """Returns (problems, unverified): groups without kgCO2e and why, and the categories
    whose factor is not marked verified in the database."""
    rows = []
    for _, r in result.iterrows():
        if r["Status"] == "existing":
            continue
        if pd.isna(r["Category"]):
            rows.append((r["GlobalId"], r["IfcClass"], r["Material"], r["MatchedBy"]))
        elif pd.isna(r["Volume_m3"]):
            rows.append((r["GlobalId"], r["IfcClass"], r["Material"], r["VolumeMethod"]))
    problems = pd.DataFrame(rows, columns=["GlobalId", "IfcClass", "Material", "Problem"])
    used = result["Category"].dropna().unique()
    unverified = [c for c in used if not str(factors.loc[c, "verified"]).lower().startswith("yes")]
    return problems, unverified


# ===================================================================== COMM
def COMM_CO2(result, problems, unverified):
    """Returns (summary, by_type) tables."""
    calc = result.dropna(subset=["kgCO2e"])
    totals = calc.groupby("Status")["kgCO2e"].sum()
    by_type = (calc.groupby(["Status", "IfcClass", "Category"])
                   .agg(Groups=("GlobalId", "count"), Volume_m3=("Volume_m3", "sum"),
                        kgCO2e=("kgCO2e", "sum"))
                   .round(2).reset_index())
    summary = pd.DataFrame({
        "Item": ["New elements (A1-A3 + C3-C4)", "Removed elements - demolition (C3-C4)",
                 "TOTAL kgCO2e", "Groups calculated", "Groups with problems",
                 "Categories using UNVERIFIED factors"],
        "Value": [round(totals.get("new", 0), 1), round(totals.get("removed", 0), 1),
                  round(calc["kgCO2e"].sum(), 1), len(calc), len(problems),
                  ", ".join(unverified) or "none"],
    }).astype({"Value": str})
    return summary, by_type


def COMM_SHEETS(xlsx_path, sheets, header_colour="5B2C83"):
    """Adds or replaces sheets in an EXISTING Excel file and keeps all its other sheets.
    sheets: {"SheetName": DataFrame}."""
    from openpyxl.styles import Font, PatternFill
    with pd.ExcelWriter(xlsx_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
            ws = w.sheets[name]
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor=header_colour)
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 45)


def COMM_EXCEL(result, xlsx_path):
    """Adds CO2_Summary, CO2_ByType, CO2_Groups and CO2_Problems to Team 40's Excel file."""
    detail = pd.DataFrame(result["groups"])
    if len(detail):
        detail = detail[["GlobalId", "Status", "IfcClass", "TypeName", "Material", "Category",
                         "Volume_m3", "VolumeMethod", "kgCO2e"]]
    COMM_SHEETS(xlsx_path, {"CO2_Summary": pd.DataFrame(result["summary"]),
                            "CO2_ByType": pd.DataFrame(result["by_type"]),
                            "CO2_Groups": detail,
                            "CO2_Problems": pd.DataFrame(result["problems"],
                                                         columns=["GlobalId", "IfcClass", "Material", "Problem"])})


# ===================================================================== analyse
def analyse(groups, database=CO2_DATABASE):
    """groups: Team 40's result["groups"] (list of dicts), a DataFrame or their Excel file.
    Returns a JSON-compatible dict: new_kgCO2e, removed_kgCO2e, groups, problems, summary,
    by_type, unverified_categories."""
    table = CAPT_GROUPS(groups)
    rules, factors = CAPT_CO2DATA(database)
    result = CALC_CO2(table, rules, factors)
    problems, unverified = CHEK_CO2(result, factors)
    summary, by_type = COMM_CO2(result, problems, unverified)
    totals = result.dropna(subset=["kgCO2e"]).groupby("Status")["kgCO2e"].sum()
    return {"new_kgCO2e": round(float(totals.get("new", 0.0)), 1),
            "removed_kgCO2e": round(float(totals.get("removed", 0.0)), 1),
            "unverified_categories": unverified,
            "groups": records(result), "problems": records(problems),
            "summary": records(summary), "by_type": records(by_type)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python -m embodied_carbon.src.main results/changes_variantA.xlsx")
    res = analyse(sys.argv[1])
    COMM_EXCEL(res, sys.argv[1])
    print(pd.DataFrame(res["summary"]).to_string(index=False))
    print(f"\nCO2 sheets added to {sys.argv[1]}")
