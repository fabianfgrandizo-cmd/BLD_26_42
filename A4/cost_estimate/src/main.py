"""Team 41: preliminary construction and removal costs for Team 40 groups.

The shared runner calls analyse(groups), then COMM_EXCEL(result, path).
Neither importing this module nor analyse() writes files or opens IFC models.
Run independently from A4: python -m cost_estimate.src.main changes.xlsx
"""

import json
import sys
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font

from embodied_carbon.src.main import CAPT_CO2DATA, CONN_MATERIAL, COMM_SHEETS

HERE = Path(__file__).resolve().parents[1]
COST_DATABASE = HERE / "data" / "cost_database.xlsx"
UNIT_TO_COLUMN = {"m3": "Volume_m3", "m2": "Area_m2", "m": "Length_m", "pcs": "Count"}
REQUIRED = ["GlobalId", "Status", "Material", "Count", "Length_m", "Area_m2", "Volume_m3"]
RESULT_COLUMNS = ["GlobalId", "CostCategory", "Cost_DKK", "CostProblem"]
DETAIL_COLUMNS = [
    "GlobalId", "Status", "IfcClass", "Material", "TypeName", "CostCategory",
    "CostUnit", "CostQuantity", "UnitPrice_DKK", "Cost_DKK", "CostProblem",
    "CostSource", "PriceVerified", "MatchedBy", "CostWarning",
]


def COMM_RECORDS(df):
    """Return JSON-compatible records, including None for missing values."""
    return json.loads(df.to_json(orient="records", double_precision=15))


# ===================================================================== CAPT
def CAPT_GROUPS(source, sheet="Groups"):
    """Read a list, DataFrame or Excel Groups sheet without changing the input."""
    table = (pd.read_excel(source, sheet_name=sheet, dtype={"GlobalId": str})
             if isinstance(source, (str, Path)) else pd.DataFrame(source).copy())
    for column in REQUIRED:
        if column not in table:
            table[column] = None
    if not table.empty:
        if table["GlobalId"].isna().any() or table["GlobalId"].astype(str).str.strip().eq("").any():
            raise ValueError("Every group must have a non-empty GlobalId.")
        table["GlobalId"] = table["GlobalId"].astype(str)
        if table["GlobalId"].duplicated().any():
            raise ValueError("Duplicate GlobalIds: group IDs must be unique within a variant.")
    return table.reset_index(drop=True)


def CAPT_PRICES(path=COST_DATABASE):
    """Read category prices. Ambiguous duplicate categories are rejected per group."""
    prices = pd.read_excel(path, sheet_name="Prices")
    required = ["category", "unit", "price_DKK_per_unit", "demolition_DKK_per_unit", "source", "verified"]
    if list(prices.columns) != required:
        raise ValueError("Prices must have exactly these columns, in order: " + ", ".join(required))
    return prices.set_index("category")


# ===================================================================== CHEK
def CHEK_NUMBER(value):
    """Return a finite number, or None for blanks, text, booleans and infinity."""
    if pd.api.types.is_bool(value) or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) and number not in (float("inf"), -float("inf")) else None


# ===================================================================== CALC
def CALC_COST(groups, prices, rules, unit_to_column=UNIT_TO_COLUMN):
    """PRIMARY C function: quantity times construction or demolition unit price.

    Keep one record per input group, in order. Unresolved costs remain None.
    Detailed values stay internal; analyse() returns the four shared group keys.
    """
    rows = []
    for _, group in groups.iterrows():
        category, reason = CONN_MATERIAL(group["Material"], rules)
        status = group["Status"]
        row = {column: None for column in DETAIL_COLUMNS}
        row.update({column: group.get(column) for column in
                    ["GlobalId", "Status", "IfcClass", "Material", "TypeName"]})
        row.update(CostCategory=category, MatchedBy=reason)
        problem = None
        if pd.isna(status) or status not in ("new", "removed"):
            problem = "invalid status - expected new or removed"
        elif category is None:
            problem = reason
        elif category not in prices.index:
            problem = f"category '{category}' not in cost_database"
        elif isinstance(prices.loc[category], pd.DataFrame):
            problem = f"duplicate prices for '{category}'"
        else:
            price_row = prices.loc[category]
            unit = str(price_row["unit"]).strip()
            removed = status == "removed"
            price_name = "demolition_DKK_per_unit" if removed else "price_DKK_per_unit"
            raw_price = price_row[price_name]
            price = CHEK_NUMBER(raw_price)
            column = unit_to_column.get(unit)
            quantity = CHEK_NUMBER(group.get(column)) if column else None
            row.update(CostUnit=unit, CostQuantity=quantity, UnitPrice_DKK=price,
                       CostSource=price_row.get("source"), PriceVerified=price_row.get("verified"))
            section = str(group.get("TypeName", "")).lower()
            steel_section = any(marker in section for marker in
                                ("steel", "s235", "s275", "s355", "hea", "heb", "hem", "ipe", "ipn", "upn"))
            if "concrete" in str(category).lower() and steel_section:
                problem = "material/section conflict - verify with Team 40"
            elif unit not in unit_to_column:
                problem = f"unsupported unit '{unit}'"
            elif pd.isna(raw_price) or str(raw_price).strip() == "":
                problem = f"no {'demolition ' if removed else ''}price for '{category}'"
            elif price is None or price < 0:
                problem = f"invalid {'demolition ' if removed else ''}price for '{category}'"
            elif quantity is None or quantity <= 0:
                problem = f"no quantity in {unit}"
            elif unit == "m3" and (CHEK_NUMBER(group.get("ElementsWithoutVolume")) or 0) > 0:
                problem = "incomplete volume - some elements lack volume"
            else:
                amount = price * quantity
                if CHEK_NUMBER(amount) is None:
                    problem = "cost exceeds numeric range"
                else:
                    row["Cost_DKK"] = float(round(amount))
                    warnings = []
                    if str(price_row.get("verified", "")).strip().lower() != "yes":
                        warnings.append("price not verified")
                    if pd.isna(price_row.get("source")) or not str(price_row.get("source", "")).strip():
                        warnings.append("price source missing")
                    row["CostWarning"] = "; ".join(warnings) or None
        row["CostProblem"] = problem
        rows.append(row)
    return pd.DataFrame(rows, columns=DETAIL_COLUMNS)


def CHEK_COST(result):
    """Return unresolved groups with their short, human-readable reasons."""
    return result.loc[result["CostProblem"].notna()].copy()


# ===================================================================== COMM
def COMM_COST(groups, result, problems):
    """Summarise calculated costs and state whether outstanding groups remain."""
    amounts = pd.to_numeric(result["Cost_DKK"], errors="coerce")
    new = float(amounts.where(result["Status"].eq("new")).sum())
    removed = float(amounts.where(result["Status"].eq("removed")).sum())
    return pd.DataFrame([
        {"Item": "New elements - construction DKK (calculated only)", "Value": new},
        {"Item": "Removed elements - demolition DKK (calculated only)", "Value": removed},
        {"Item": "TOTAL DKK (calculated only)", "Value": new + removed},
        {"Item": "Groups received", "Value": len(groups)},
        {"Item": "Groups calculated", "Value": int(amounts.notna().sum())},
        {"Item": "Groups with problems", "Value": len(problems)},
        {"Item": "Groups with price warnings", "Value": int(result["CostWarning"].notna().sum())},
        {"Item": "Valuation coverage", "Value": "PARTIAL - see COST_Problems" if len(problems) else "All received groups valued"},
        {"Item": "Scope", "Value": "Preliminary costs for unmatched quantities; not verified site activities or a full project budget."},
    ])


def COMM_EXCEL(result, xlsx_path):
    """Append/replace COST_* sheets using Team 42's helper; retain other sheets."""
    groups = pd.DataFrame(result["groups"], columns=RESULT_COLUMNS)
    COMM_SHEETS(xlsx_path, {
        "COST_Summary": pd.DataFrame(result["summary"]),
        "COST_Groups": groups,
        "COST_Problems": CHEK_COST(groups),
    }, header_colour="8A5A00")
    COMM_FORMAT(xlsx_path, ["COST_Summary", "COST_Groups", "COST_Problems"])


def COMM_FORMAT(xlsx_path, sheet_names):
    """Fit and wrap only our output sheets, using pandas' openpyxl writer."""
    with pd.ExcelWriter(xlsx_path, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
        for name in sheet_names:
            sheet = writer.book[name]
            sheet.sheet_view.showGridLines = False
            sheet.freeze_panes = "B2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.columns:
                header = str(cells[0].value or "")
                width = sheet.column_dimensions[cells[0].column_letter].width
                for cell in cells:
                    cell.alignment = Alignment(wrap_text=True, vertical="center",
                                               horizontal="center" if cell.row == 1 else
                                               "right" if isinstance(cell.value, (int, float)) else "left")
                    cell.font = Font(name="Arial", size=10, bold=cell.row == 1,
                                     color="FFFFFF" if cell.row == 1 else "222222")
                    if cell.row > 1 and isinstance(cell.value, (int, float)):
                        cell.number_format = ("#,##0" if "DKK" in header or cell.value == int(cell.value)
                                              else "0.000000")
                    lines = max(1, (len(str(cell.value or "")) + int(width) - 1) // max(1, int(width)))
                    height = max(30 if cell.row == 1 else 20, lines * 15)
                    sheet.row_dimensions[cell.row].height = max(sheet.row_dimensions[cell.row].height or 0, height)


def analyse(groups, database=COST_DATABASE):
    """Return JSON-compatible costs and totals; never print, write or open IFCs."""
    table = CAPT_GROUPS(groups)
    if table.empty:
        result = pd.DataFrame(columns=DETAIL_COLUMNS)
    else:
        prices = CAPT_PRICES(database)
        rules, _ = CAPT_CO2DATA()
        result = CALC_COST(table, prices, rules)
    problems = CHEK_COST(result)
    summary = COMM_COST(table, result, problems)
    amounts = pd.to_numeric(result["Cost_DKK"], errors="coerce")
    return {
        "total_new_DKK": float(amounts.where(result["Status"].eq("new")).sum()),
        "total_removed_DKK": float(amounts.where(result["Status"].eq("removed")).sum()),
        "groups": COMM_RECORDS(result[RESULT_COLUMNS]), "summary": COMM_RECORDS(summary),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m cost_estimate.src.main changes.xlsx")
    res = analyse(sys.argv[1])
    COMM_EXCEL(res, sys.argv[1])
    print(pd.DataFrame(res["groups"], columns=RESULT_COLUMNS).to_string(index=False))
