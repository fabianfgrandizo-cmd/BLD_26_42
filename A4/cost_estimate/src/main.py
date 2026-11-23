"""
cost_estimate - Team 41: cost of the changed elements   (TEMPLATE, to be completed by Team 41)

Course template (Working Together / node-comply-template):
  analyse(groups) -> JSON-compatible dict. This analysis receives a DATASET (Team 40's groups),
  not a model. One primary 'C' function: CALC_COST.
  Importing this file does not open models or write files.

  CAPT_GROUPS     Team 40's groups (list of dicts, DataFrame, or their Excel file)
  CAPT_PRICES     data/cost_database.xlsx, sheet "Prices" (EMPTY until Team 41 fills it)
  CONN_MATERIAL   material name -> category: Team 42's filter, so cost and CO2 use the same categories
  CALC_COST       PRIMARY: quantity x unit price (new -> construction, removed -> demolition)
  CHEK_COST       groups without a cost, and why
  COMM_COST       summary table
  COMM_EXCEL      add the COST_* sheets to Team 40's Excel file

CONTRACT with runall.py (keep it):
  analyse(groups) returns {"groups": [{"GlobalId", "CostCategory", "Cost_DKK", "CostProblem"}, ...],
                           "total_new_DKK": float, "total_removed_DKK": float, ...}

Run alone (from the A4 folder):
  python -m cost_estimate.src.main results/changes_variantA.xlsx
"""

import json
import sys
from pathlib import Path

import pandas as pd

from embodied_carbon.src.main import CAPT_CO2DATA, CONN_MATERIAL, COMM_SHEETS   # Team 42

HERE = Path(__file__).resolve().parents[1]            # the cost_estimate folder
COST_DATABASE = HERE / "data" / "cost_database.xlsx"
UNIT_TO_COLUMN = {"m3": "Volume_m3", "m2": "Area_m2", "m": "Length_m", "pcs": "Count"}
REQUIRED = ["GlobalId", "Status", "Material", "Count", "Length_m", "Area_m2", "Volume_m3"]
RESULT_COLUMNS = ["GlobalId", "CostCategory", "Cost_DKK", "CostProblem"]


def records(df):
    """DataFrame -> list of dicts with JSON-safe values (NaN -> None)."""
    return json.loads(df.to_json(orient="records"))


# ===================================================================== CAPT
def CAPT_GROUPS(source, sheet="Groups"):
    """source: Team 40's groups as a list of dicts or DataFrame, or the path to their Excel file."""
    if isinstance(source, (str, Path)):
        df = pd.read_excel(source, sheet_name=sheet)
    else:
        df = pd.DataFrame(source).copy()
    for col in REQUIRED:
        if col not in df.columns:
            df[col] = None
    return df


def CAPT_PRICES(path=COST_DATABASE):
    """Price list: one row per category with unit, price_DKK_per_unit, demolition_DKK_per_unit."""
    return pd.read_excel(path, sheet_name="Prices").set_index("category")


# ===================================================================== CALC
def CALC_COST(groups, prices, rules, unit_to_column=UNIT_TO_COLUMN):
    """PRIMARY FUNCTION. Cost in DKK per group = quantity (in the price's unit) x unit price.
    Returns GlobalId, CostCategory, Cost_DKK (None if not possible) and CostProblem."""
    rows = []
    for _, g in groups.iterrows():
        category, why = CONN_MATERIAL(g["Material"], rules)
        cost, problem = None, None
        if category is None:
            problem = why
        elif category not in prices.index:
            problem = f"category '{category}' not in cost_database"
        else:
            p = prices.loc[category]
            removed = g["Status"] == "removed"
            price = p["demolition_DKK_per_unit"] if removed else p["price_DKK_per_unit"]
            column = unit_to_column.get(str(p["unit"]).strip())
            qty = g[column] if column in g and pd.notna(g[column]) else None
            if pd.isna(price):
                problem = f"no {'demolition ' if removed else ''}price for '{category}'"
            elif qty is None or qty == 0:
                problem = f"no quantity in {p['unit']}"
            else:
                cost = qty * price
        rows.append({"GlobalId": g["GlobalId"], "CostCategory": category,
                     "Cost_DKK": round(cost, 0) if cost is not None else None, "CostProblem": problem})
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


# ===================================================================== CHEK
def CHEK_COST(result):
    """Groups without a cost, with the reason."""
    return result[result["CostProblem"].notna()]


# ===================================================================== COMM
def COMM_COST(groups, result, problems):
    """Summary table: construction, demolition and total DKK."""
    merged = groups[["GlobalId", "Status"]].merge(result, on="GlobalId")
    totals = merged.groupby("Status")["Cost_DKK"].sum()
    return pd.DataFrame({
        "Item": ["New elements - construction DKK", "Removed elements - demolition DKK",
                 "TOTAL DKK", "Groups with problems"],
        "Value": [totals.get("new", 0), totals.get("removed", 0), totals.sum(), len(problems)]})


def COMM_EXCEL(result, xlsx_path):
    """Adds COST_Summary, COST_Groups and COST_Problems to Team 40's Excel file."""
    groups = pd.DataFrame(result["groups"], columns=RESULT_COLUMNS)
    COMM_SHEETS(xlsx_path, {"COST_Summary": pd.DataFrame(result["summary"]),
                            "COST_Groups": groups,
                            "COST_Problems": groups[groups["CostProblem"].notna()]},
                header_colour="8A5A00")


# ===================================================================== analyse
def analyse(groups, database=COST_DATABASE):
    """groups: Team 40's result["groups"] (list of dicts), a DataFrame or their Excel file.
    Returns a JSON-compatible dict: total_new_DKK, total_removed_DKK, groups, summary."""
    table = CAPT_GROUPS(groups)
    prices = CAPT_PRICES(database)
    rules, _ = CAPT_CO2DATA()
    result = CALC_COST(table, prices, rules)
    problems = CHEK_COST(result)
    summary = COMM_COST(table, result, problems)
    merged = table[["GlobalId", "Status"]].merge(result, on="GlobalId")
    totals = merged.groupby("Status")["Cost_DKK"].sum()
    return {"total_new_DKK": float(totals.get("new", 0)),
            "total_removed_DKK": float(totals.get("removed", 0)),
            "groups": records(result), "summary": records(summary)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python -m cost_estimate.src.main results/changes_variantA.xlsx")
    res = analyse(sys.argv[1])
    COMM_EXCEL(res, sys.argv[1])
    print(pd.DataFrame(res["groups"], columns=RESULT_COLUMNS).to_string(index=False))
