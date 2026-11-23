"""
model_changes - Team 40: which elements change between the existing and a proposed model

Course template (Working Together / node-comply-template):
  analyse(model, existing) -> JSON-compatible dict. One primary 'C' function: COMP_VERSIONS.
  Importing this file does not open models or write files.

  CAPT_ELEMENTS   one row per wall / slab / column / beam of a model (+ its section)
  CAPT_SECTION    profile name or width x height of a beam or column
  CONN_SECTION    the "section key" that makes two elements the same kind
  COMP_SIGNATURE  what counts as "different" between two versions of one element
  COMP_VERSIONS   PRIMARY: new / removed / changed / unchanged, by GlobalId
  CALC_GROUPS     group similar elements: count, total length, area and volume
  CHEK_CHANGES    warnings: few matching GlobalIds, elements without volume or material
  COMM_EXCEL      write Groups / Elements / Info sheets (for people who don't open IFC)

Run alone (from the A4 folder):
  python -m model_changes.src.main existing.ifc proposed.ifc [changes.xlsx]
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from model_changes.src.ifc_to_excel import extract_elements   # our A3 tutorial code

MIN_SHARED_IDS = 0.3        # below this share of matching GlobalIds: warning
GROUP_KEYS = ["Status", "IfcClass", "Material", "SectionKey"]
GROUP_COLUMNS = ["GlobalId", "Status", "IfcClass", "Material", "TypeName", "Count",
                 "Length_m", "Area_m2", "Volume_m3", "ElementsWithoutVolume"]
ELEMENT_COLUMNS = ["GroupId", "GlobalId", "Status", "Change", "IfcClass", "Name", "Material",
                   "SectionKey", "Storey", "Length_m", "Area_m2", "Volume_m3", "VolumeSource"]


def records(df):
    """DataFrame -> list of dicts with JSON-safe values (NaN -> None)."""
    return json.loads(df.to_json(orient="records"))


# ===================================================================== CAPT
def CAPT_SECTION(element, length_scale):
    """Profile name, or 'width x height' in mm, of a beam or column (None if not found)."""
    profiles = []

    def walk(item):
        if item.is_a("IfcMappedItem"):
            for i in item.MappingSource.MappedRepresentation.Items:
                walk(i)
        elif item.is_a("IfcSweptAreaSolid"):
            profiles.append(item.SweptArea)
        elif item.is_a("IfcBooleanResult"):
            walk(item.FirstOperand)

    if element.Representation:
        for rep in element.Representation.Representations:
            for item in rep.Items:
                walk(item)
    for p in profiles:
        if p.ProfileName:
            return p.ProfileName
        mm = length_scale * 1000
        if p.is_a("IfcRectangleProfileDef"):
            return f"{p.XDim * mm:.0f}x{p.YDim * mm:.0f}"
        if p.is_a("IfcIShapeProfileDef"):
            return f"I {p.OverallWidth * mm:.0f}x{p.OverallDepth * mm:.0f}"
        if p.is_a("IfcCircleProfileDef"):
            return f"D{2 * p.Radius * mm:.0f}"
    return None


def CAPT_ELEMENTS(model):
    """One row per wall, slab, column and beam, quantities in m / m2 / m3, plus Section and
    SectionKey. model: an opened ifcopenshell file (it is not modified)."""
    import ifcopenshell.util.unit as uunit
    df = extract_elements(model)
    if df.empty:
        return df
    scale = uunit.calculate_unit_scale(model, "LENGTHUNIT")
    df["Section"] = [CAPT_SECTION(model.by_guid(g), scale) for g in df["GlobalId"]]
    df["SectionKey"] = df.apply(CONN_SECTION, axis=1)
    df["IfcClass"] = df["IfcClass"].replace({"IfcWallStandardCase": "IfcWall"})
    return df


# ===================================================================== CONN
def CONN_SECTION(row):
    """What makes two elements 'the same kind': wall/slab thickness, or beam/column section."""
    if row["IfcClass"] in ("IfcWall", "IfcWallStandardCase", "IfcSlab"):
        t = row["Thickness_m"]
        if pd.isna(t) and pd.notna(row["Volume_m3"]) and pd.notna(row["Area_m2"]) and row["Area_m2"]:
            t = row["Volume_m3"] / row["Area_m2"]
        return f"t={t * 1000:.0f} mm" if pd.notna(t) else "thickness unknown"
    if pd.notna(row["Section"]):
        return row["Section"]
    if pd.notna(row["Volume_m3"]) and pd.notna(row["Length_m"]) and row["Length_m"]:
        return f"A={row['Volume_m3'] / row['Length_m']:.4f} m2"
    return "section unknown"


# ===================================================================== COMP
def COMP_SIGNATURE(row):
    """If any of these differ between two versions of an element, it has changed."""
    r = lambda x, n: round(x, n) if pd.notna(x) else None
    return (row["IfcClass"], row["Material"], row["SectionKey"],
            r(row["Volume_m3"], 3), r(row["Length_m"], 2), r(row["Area_m2"], 2))


def COMP_VERSIONS(existing, proposed):
    """PRIMARY FUNCTION. Compares two element tables (from CAPT_ELEMENTS) by GlobalId.
    Returns (changes, n_unchanged, shared_share):
      only in proposed -> Status new      only in existing -> Status removed
      in both, different signature -> old version removed + new version new
      in both, same signature -> left out (counted in n_unchanged)"""
    old = existing.set_index("GlobalId")
    new = proposed.set_index("GlobalId")
    shared = old.index.intersection(new.index)

    rows = []
    for gid in new.index.difference(old.index):
        rows.append({**new.loc[gid].to_dict(), "GlobalId": gid, "Status": "new", "Change": "added"})
    for gid in old.index.difference(new.index):
        rows.append({**old.loc[gid].to_dict(), "GlobalId": gid, "Status": "removed", "Change": "deleted"})
    n_unchanged = 0
    for gid in shared:
        if COMP_SIGNATURE(old.loc[gid]) == COMP_SIGNATURE(new.loc[gid]):
            n_unchanged += 1
            continue
        rows.append({**old.loc[gid].to_dict(), "GlobalId": gid, "Status": "removed", "Change": "changed (old version)"})
        rows.append({**new.loc[gid].to_dict(), "GlobalId": gid, "Status": "new", "Change": "changed (new version)"})
    return pd.DataFrame(rows), n_unchanged, len(shared) / max(len(old), 1)


# ===================================================================== CALC
def CALC_GROUPS(changes, keys=GROUP_KEYS):
    """Groups changed elements with the same Status, class, material and section.
    Returns (groups, changes). A group's volume is empty if any of its elements has none."""
    if changes.empty:
        return pd.DataFrame(columns=GROUP_COLUMNS), pd.DataFrame(columns=ELEMENT_COLUMNS)
    changes = changes.copy()
    changes["Material"] = changes["Material"].fillna("NO MATERIAL")
    groups = (changes.groupby(keys, dropna=False)
                     .agg(Count=("GlobalId", "count"),
                          Length_m=("Length_m", "sum"),
                          Area_m2=("Area_m2", "sum"),
                          Volume_m3=("Volume_m3", lambda v: v.sum(min_count=len(v))),
                          ElementsWithoutVolume=("Volume_m3", lambda v: int(v.isna().sum())))
                     .round(4).reset_index())
    groups.insert(0, "GroupId", [f"G{i + 1:03d}" for i in range(len(groups))])
    group_of = groups.set_index(keys)["GroupId"]
    changes["GroupId"] = [group_of[tuple(r[k] for k in keys)] for _, r in changes.iterrows()]
    groups = groups.rename(columns={"SectionKey": "TypeName", "GroupId": "GlobalId"})
    return groups[GROUP_COLUMNS], changes[ELEMENT_COLUMNS]


# ===================================================================== CHEK
def CHEK_CHANGES(groups, shared_share, minimum=MIN_SHARED_IDS):
    """List of warnings (text). Empty list = nothing suspicious."""
    warnings = []
    if shared_share < minimum:
        warnings.append(f"Only {shared_share:.0%} of GlobalIds match: models probably exported "
                        "separately, almost everything shows as removed + new.")
    n = int(pd.to_numeric(groups["ElementsWithoutVolume"]).sum()) if len(groups) else 0
    if n:
        warnings.append(f"{n} elements have no volume (no quantities and no usable geometry).")
    n = int((groups["Material"] == "NO MATERIAL").sum()) if len(groups) else 0
    if n:
        warnings.append(f"{n} groups have NO MATERIAL.")
    return warnings


# ===================================================================== COMM
def COMM_EXCEL(result, xlsx_path):
    """Writes the Excel file for people who don't open IFC: Groups (input for Teams 41 and 42),
    Elements and Info."""
    from openpyxl.styles import Font, PatternFill
    sheets = {"Groups": pd.DataFrame(result["groups"], columns=GROUP_COLUMNS),
              "Elements": pd.DataFrame(result["elements"], columns=ELEMENT_COLUMNS),
              "Info": pd.DataFrame(result["info"])}
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
            ws = w.sheets[name]
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="555555")
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 45)


# ===================================================================== analyse
def analyse(model, existing, names=("existing", "proposed")):
    """model: the PROPOSED model (opened ifcopenshell file), as in the course template.
    existing: the existing model (opened file) or its element table from CAPT_ELEMENTS
              (the runner reads the existing model once for all variants).
    Returns a JSON-compatible dict: groups, elements, info, shared_ids, warnings."""
    old = existing if isinstance(existing, pd.DataFrame) else CAPT_ELEMENTS(existing)
    new = CAPT_ELEMENTS(model)
    if old.empty or new.empty:
        raise ValueError("A model has no walls, slabs, columns or beams (MEP model?).")
    changes, n_unchanged, share = COMP_VERSIONS(old, new)
    groups, changes = CALC_GROUPS(changes)
    warnings = CHEK_CHANGES(groups, share)

    status = changes.groupby("Change").size() if len(changes) else pd.Series(dtype=int)
    info = pd.DataFrame({"Field": ["Existing model", "Proposed model", "Created",
                                   "Elements existing / proposed", "Shared GlobalIds",
                                   "Unchanged (left out)", "Added", "Deleted", "Changed",
                                   "Groups", "Warnings"],
                         "Value": [names[0], names[1], datetime.now().strftime("%Y-%m-%d %H:%M"),
                                   f"{len(old)} / {len(new)}", f"{share:.0%}", n_unchanged,
                                   int(status.get("added", 0)), int(status.get("deleted", 0)),
                                   int(status.get("changed (new version)", 0)), len(groups),
                                   " | ".join(warnings) or "none"]}).astype(str)
    return {"existing_model": names[0], "proposed_model": names[1],
            "shared_ids": round(share, 4), "warnings": warnings,
            "groups": records(groups), "elements": records(changes), "info": records(info)}


if __name__ == "__main__":
    import ifcopenshell
    if len(sys.argv) < 3:
        sys.exit("Usage: python -m model_changes.src.main existing.ifc proposed.ifc [changes.xlsx]")
    out = sys.argv[3] if len(sys.argv) > 3 else "changes.xlsx"
    res = analyse(ifcopenshell.open(sys.argv[2]), ifcopenshell.open(sys.argv[1]),
                  names=(Path(sys.argv[1]).name, Path(sys.argv[2]).name))
    COMM_EXCEL(res, out)
    print(pd.DataFrame(res["info"]).to_string(index=False))
    print("\n" + pd.DataFrame(res["groups"], columns=GROUP_COLUMNS).to_string(index=False))
    print(f"\nWritten to {out}")
