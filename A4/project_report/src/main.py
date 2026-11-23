"""
project_report - Manager: one table per variant (quantities + CO2 + cost) and the shared
results workbook that grows with every run.

Course template (Working Together / node-comply-template):
  analyse(changes, carbon, cost) -> JSON-compatible dict. This analysis receives the DATASETS
  returned by the three teams. Importing this file does not open models or write files.

  CONN_TEAMS      join Team 40, 42 and 41 results on the group ID
  CALC_OVERVIEW   totals per variant
  CHEK_COMPLETE   is every group calculated? (Complete = yes / NO)
  COMM_WORKBOOK   update results/project_results.xlsx: Overview, Manual review, one sheet per variant
"""

import json
import re
from datetime import datetime

import pandas as pd

FIXED_SHEETS = {"Overview", "Manual review"}
MANUAL_COLUMNS = ["Manual_kgCO2e", "Manual_Cost_DKK", "Checked_by", "Comment"]
GROUP_KEY = ["Variant", "Status", "IfcClass", "Material", "TypeName"]
TABLE_COLUMNS = ["Variant", "GroupId", "Status", "IfcClass", "Material", "TypeName", "Count",
                 "Length_m", "Area_m2", "Volume_m3", "Category", "kgCO2e", "Cost_DKK",
                 "CO2Problem", "CostProblem"]


def records(df):
    return json.loads(df.to_json(orient="records"))


# ===================================================================== CONN
def CONN_TEAMS(changes, carbon, cost, variant):
    """One row per group: Team 40 quantities + Team 42 kgCO2e + Team 41 DKK, with the reasons."""
    q = pd.DataFrame(changes["groups"], columns=["GlobalId", "Status", "IfcClass", "Material", "TypeName",
                                                 "Count", "Length_m", "Area_m2", "Volume_m3"])
    c = pd.DataFrame(carbon["groups"], columns=["GlobalId", "Category", "kgCO2e", "MatchedBy", "VolumeMethod"])
    k = pd.DataFrame(cost["groups"], columns=["GlobalId", "Cost_DKK", "CostProblem"])
    table = q.merge(c, on="GlobalId", how="left").merge(k, on="GlobalId", how="left")
    no_co2 = table["kgCO2e"].isna()
    table["CO2Problem"] = None
    table.loc[no_co2 & table["Category"].isna(), "CO2Problem"] = table["MatchedBy"]
    table.loc[no_co2 & table["Category"].notna(), "CO2Problem"] = table["VolumeMethod"]
    table = table.rename(columns={"GlobalId": "GroupId"})
    table["kgCO2e"] = pd.to_numeric(table["kgCO2e"]).round(1)
    table.insert(0, "Variant", variant)
    return table[TABLE_COLUMNS]


# ===================================================================== CHEK
def CHEK_COMPLETE(table):
    return "yes" if table[["CO2Problem", "CostProblem"]].isna().all().all() else "NO - see Manual review"


# ===================================================================== CALC
def CALC_OVERVIEW(table, changes, carbon, cost, variant):
    new, rem = table["Status"] == "new", table["Status"] == "removed"
    return {
        "Variant": variant,
        "Proposed file": changes["proposed_model"],
        "Existing file": changes["existing_model"],
        "Run": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Groups new": int(new.sum()), "Groups removed": int(rem.sum()),
        "Volume new m3": round(float(table.loc[new, "Volume_m3"].sum()), 2),
        "Volume removed m3": round(float(table.loc[rem, "Volume_m3"].sum()), 2),
        "kgCO2e new (A1-A3+C3-C4)": carbon["new_kgCO2e"],
        "kgCO2e demolition (C3-C4)": carbon["removed_kgCO2e"],
        "kgCO2e TOTAL": round(carbon["new_kgCO2e"] + carbon["removed_kgCO2e"], 1),
        "Cost new DKK": round(cost["total_new_DKK"]),
        "Cost demolition DKK": round(cost["total_removed_DKK"]),
        "Cost TOTAL DKK": round(cost["total_new_DKK"] + cost["total_removed_DKK"]),
        "Complete": CHEK_COMPLETE(table),
        "Groups without CO2": int(table["CO2Problem"].notna().sum()),
        "Groups without cost": int(table["CostProblem"].notna().sum()),
        "Shared GlobalIds": f"{changes['shared_ids']:.0%}",
        "Warnings": " | ".join(changes["warnings"]) or "none",
    }


# ===================================================================== analyse
def analyse(changes, carbon, cost, variant):
    """changes / carbon / cost: the dicts returned by the three teams' analyse()."""
    table = CONN_TEAMS(changes, carbon, cost, variant)
    return {"overview": CALC_OVERVIEW(table, changes, carbon, cost, variant), "table": records(table)}


# ===================================================================== COMM
def _sheet_name(variant):
    name = re.sub(r"[\[\]:*?/\\]", "_", variant)[:31]
    return name + "_" if name in FIXED_SHEETS else name


def _read(path, sheet):
    if path.exists() and sheet in pd.ExcelFile(path).sheet_names:
        return pd.read_excel(path, sheet_name=sheet)
    return pd.DataFrame()


def COMM_WORKBOOK(report, xlsx_path):
    """Updates the shared results workbook. Only this variant's sheet and rows are replaced;
    values typed by hand in 'Manual review' are kept and added to the totals."""
    variant, overview = report["overview"]["Variant"], dict(report["overview"])
    table = pd.DataFrame(report["table"], columns=TABLE_COLUMNS)

    old = _read(xlsx_path, "Manual review")
    todo = table[table["CO2Problem"].notna() | table["CostProblem"].notna()].copy()
    for col in MANUAL_COLUMNS:
        todo[col] = None
    if not old.empty:
        typed = old[old["Variant"] == variant].dropna(subset=MANUAL_COLUMNS, how="all")
        if not typed.empty:
            todo = todo.drop(columns=MANUAL_COLUMNS).merge(
                typed[GROUP_KEY + MANUAL_COLUMNS], on=GROUP_KEY, how="left")
        old = old[old["Variant"] != variant]
    review = pd.concat([old, todo], ignore_index=True)

    overview["kgCO2e manual"] = round(pd.to_numeric(todo["Manual_kgCO2e"], errors="coerce").sum(), 1)
    overview["Cost manual DKK"] = round(pd.to_numeric(todo["Manual_Cost_DKK"], errors="coerce").sum())
    overview["kgCO2e TOTAL incl. manual"] = overview["kgCO2e TOTAL"] + overview["kgCO2e manual"]
    overview["Cost TOTAL incl. manual DKK"] = overview["Cost TOTAL DKK"] + overview["Cost manual DKK"]

    ov = _read(xlsx_path, "Overview")
    if not ov.empty:
        ov = ov[ov["Variant"] != variant].drop(columns=["Rank CO2"], errors="ignore")
    ov = pd.concat([ov, pd.DataFrame([overview])], ignore_index=True).sort_values("kgCO2e TOTAL incl. manual")
    ov.insert(0, "Rank CO2", range(1, len(ov) + 1))

    from openpyxl.styles import Font, PatternFill
    sheets = {"Overview": ov, "Manual review": review, _sheet_name(variant): table}
    exists = xlsx_path.exists()
    with pd.ExcelWriter(xlsx_path, engine="openpyxl", mode="a" if exists else "w",
                        **({"if_sheet_exists": "replace"} if exists else {})) as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
            ws = w.sheets[name]
            colour = "C00000" if name == "Manual review" else "1F4E79"
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor=colour)
            ws.freeze_panes = "B2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 40)
        book = w.book
        for i, name in enumerate(["Overview", "Manual review"]):
            book.move_sheet(name, offset=i - book.sheetnames.index(name))
    return ov
