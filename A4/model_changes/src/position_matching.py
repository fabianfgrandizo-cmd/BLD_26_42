"""
REFERENCE implementation kept for comparison (Team 42, position matching). Team 40's code is main.py.
Teams may copy CONN_ALIGN and _pairs_by_position from here.

model_changes - Team 40: which elements change between the existing and a proposed model

Course template (Working Together / node-comply-template):
  analyse(model, existing) -> JSON-compatible dict. One primary 'C' function: COMP_VERSIONS.
  Importing this file does not open models or write files.

  CAPT_ELEMENTS   one row per wall / slab / column / beam of a model (+ section, LoadBearing,
                  position and size)
  CAPT_SECTION    profile name or width x height of a beam or column
  CAPT_GEOMETRY   centre and bounding-box size of every element, in world coordinates (m)
  CONN_SECTION    the "section key" that makes two elements the same kind
  CONN_ALIGN      finds how the proposed model is moved / rotated against the existing one
                  (models exported from different Revit files use different coordinates)
  COMP_SIGNATURE  what counts as "different" between two versions of one element
  COMP_GEOMETRY   same test for two elements matched by position (names differ between authors)
  COMP_VERSIONS   PRIMARY: new / removed / changed / unchanged - matched by GlobalId first,
                  then by position for the rest
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

import numpy as np
import pandas as pd

from model_changes.src.ifc_to_excel import extract_elements   # our A3 tutorial code

MIN_SHARED_IDS = 0.3        # below this share of matching GlobalIds: warning (if position fails too)
POSITION_TOLERANCE = 0.3    # m: two elements closer than this (after alignment) are the same element
MIN_ALIGNED = 0.5           # share of anchor elements that must line up for a trusted alignment
GROUP_KEYS = ["Status", "IfcClass", "Material", "SectionKey"]
GROUP_COLUMNS = ["GlobalId", "Status", "IfcClass", "Material", "TypeName", "Count",
                 "Length_m", "Area_m2", "Volume_m3", "ElementsWithoutVolume"]
ELEMENT_COLUMNS = ["GroupId", "GlobalId", "Status", "Change", "MatchedBy", "IfcClass", "Name",
                   "Material", "SectionKey", "Storey", "LoadBearing", "Length_m", "Area_m2",
                   "Volume_m3", "VolumeSource"]
GEOMETRY_COLUMNS = ["CX", "CY", "CZ", "DX", "DY", "DZ"]


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


def CAPT_GEOMETRY(model, elements):
    """Centre (CX, CY, CZ) and bounding-box size (DX, DY, DZ) in metres, world coordinates,
    for the given elements. Elements whose geometry can't be built are left out."""
    import multiprocessing
    import ifcopenshell.geom
    rows = {}
    if not elements:
        return pd.DataFrame(columns=GEOMETRY_COLUMNS)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    iterator = ifcopenshell.geom.iterator(settings, model, multiprocessing.cpu_count(), include=elements)
    if iterator.initialize():
        while True:
            shape = iterator.get()
            v = np.array(shape.geometry.verts).reshape(-1, 3)
            if len(v):
                lo, hi = v.min(0), v.max(0)
                rows[shape.guid] = [*((lo + hi) / 2), *(hi - lo)]
            if not iterator.next():
                break
    return pd.DataFrame.from_dict(rows, orient="index", columns=GEOMETRY_COLUMNS)


def CAPT_LOADBEARING(element):
    """LoadBearing from any Pset_...Common (True / False), or None if the model doesn't say."""
    import ifcopenshell.util.element as uel
    for name, props in uel.get_psets(element).items():
        if name.endswith("Common") and props.get("LoadBearing") is not None:
            return bool(props["LoadBearing"])
    return None


def CAPT_ELEMENTS(model):
    """One row per wall, slab, column and beam, quantities in m / m2 / m3, plus Section,
    SectionKey, LoadBearing, and position / size (CX..DZ). The model is not modified."""
    import ifcopenshell.util.unit as uunit
    df = extract_elements(model)
    if df.empty:
        return df
    scale = uunit.calculate_unit_scale(model, "LENGTHUNIT")
    elements = [model.by_guid(g) for g in df["GlobalId"]]
    df["Section"] = [CAPT_SECTION(e, scale) for e in elements]
    df["LoadBearing"] = [CAPT_LOADBEARING(e) for e in elements]
    df["IfcClass"] = df["IfcClass"].replace({"IfcWallStandardCase": "IfcWall"})
    df = df.join(CAPT_GEOMETRY(model, elements), on="GlobalId")
    df["SectionKey"] = df.apply(CONN_SECTION, axis=1)
    return df


# ===================================================================== CONN
def CONN_SECTION(row):
    """What makes two elements 'the same kind': wall/slab thickness, or beam/column section.
    Thickness = volume / area (works for any orientation); else the smallest bounding-box size.
    (Revit's Qto 'Width' of a slab is its plan width, not its thickness, so it is not trusted.)"""
    if row["IfcClass"] in ("IfcWall", "IfcWallStandardCase", "IfcSlab"):
        t = None
        if pd.notna(row["Volume_m3"]) and pd.notna(row["Area_m2"]) and row["Area_m2"]:
            t = row["Volume_m3"] / row["Area_m2"]
        if (t is None or t > 2.0) and pd.notna(row.get("DX")):
            t = min(row["DX"], row["DY"], row["DZ"])
        if (t is None or t > 2.0) and pd.notna(row["Thickness_m"]) and row["Thickness_m"] <= 2.0:
            t = row["Thickness_m"]
        return f"t={t * 1000:.0f} mm" if t is not None and pd.notna(t) else "thickness unknown"
    if pd.notna(row["Section"]):
        return row["Section"]
    if pd.notna(row["Volume_m3"]) and pd.notna(row["Length_m"]) and row["Length_m"]:
        return f"A={row['Volume_m3'] / row['Length_m']:.4f} m2"
    return "section unknown"


def _anchors(df):
    """Points used to align two models: columns if there are enough, else all elements."""
    df = df.dropna(subset=["CX"])
    cols = df[df["IfcClass"] == "IfcColumn"]
    use = cols if len(cols) >= 5 else df
    return use[["CX", "CY", "CZ"]].to_numpy(float)


def _rotate(xy, angle):
    r = np.radians(angle)
    return xy @ np.array([[np.cos(r), -np.sin(r)], [np.sin(r), np.cos(r)]]).T


def CONN_ALIGN(existing, proposed, tolerance=POSITION_TOLERANCE):
    """How to move the proposed model onto the existing one: plan rotation (0/90/180/270),
    plan shift and vertical shift, plus the share of anchor elements that line up.
    Returns {"rotation", "shift", "aligned_share"}; aligned_share 0 = could not align."""
    A, P = _anchors(existing), _anchors(proposed)
    if len(A) < 3 or len(P) < 3:
        return {"rotation": 0, "shift": [0.0, 0.0, 0.0], "aligned_share": 0.0}
    best = None
    for angle in (0, 90, 180, 270):
        Q = _rotate(P[:, :2], angle)
        t = (A[:, :2].min(0) + A[:, :2].max(0)) / 2 - (Q.min(0) + Q.max(0)) / 2   # box centres
        for _ in range(15):                                   # refine: median offset of neighbours
            d = np.sqrt(((A[:, None, :2] - (Q + t)[None]) ** 2).sum(-1))
            j = d.argmin(1)
            ok = d[np.arange(len(A)), j] < 2.0
            if ok.sum() < 3:
                break
            t = t + np.median(A[ok, :2] - (Q + t)[j[ok]], 0)
        d = np.sqrt(((A[:, None, :2] - (Q + t)[None]) ** 2).sum(-1))
        share = float((d.min(1) < tolerance).mean())
        if best is None or share > best[0]:
            best = (share, angle, t, d)
    share, angle, t, d = best
    # vertical shift: the most common height difference between elements that line up in plan
    i, j = np.nonzero(d < tolerance)
    dz = 0.0
    if len(i):
        diffs = A[i, 2] - P[j, 2]
        bins = np.round(diffs, 1)
        values, counts = np.unique(bins, return_counts=True)
        mode = values[counts.argmax()]
        dz = float(np.median(diffs[np.abs(diffs - mode) <= 0.1]))
    return {"rotation": int(angle), "shift": [round(float(t[0]), 3), round(float(t[1]), 3), round(dz, 3)],
            "aligned_share": round(share, 3)}


def CONN_APPLY_ALIGN(df, align):
    """Proposed element positions moved into the existing model's coordinates."""
    df = df.copy()
    if df.empty or align["aligned_share"] == 0:
        return df
    xy = _rotate(df[["CX", "CY"]].to_numpy(float), align["rotation"]) + np.array(align["shift"][:2])
    df["CX"], df["CY"] = xy[:, 0], xy[:, 1]
    df["CZ"] = df["CZ"] + align["shift"][2]
    if align["rotation"] in (90, 270):
        df["DX"], df["DY"] = df["DY"].copy(), df["DX"].copy()
    return df


# ===================================================================== COMP
def COMP_SIGNATURE(row):
    """If any of these differ between two versions of an element, it has changed."""
    r = lambda x, n: round(x, n) if pd.notna(x) else None
    return (row["IfcClass"], row["Material"], row["SectionKey"],
            r(row["Volume_m3"], 3), r(row["Length_m"], 2), r(row["Area_m2"], 2))


def COMP_GEOMETRY(old, new, section_tolerance=0.02, length_tolerance=0.10, min_length_tolerance=0.5):
    """For two elements matched by POSITION (often from different authors, so names and the
    level a column is modelled to differ). Bounding-box sizes sorted small -> large:
      walls / slabs:   thickness (smallest size) +-2 cm; length and width +-10 % or 0.5 m
      columns / beams: cross-section (two smaller sizes) +-2 cm; length +-10 % or 0.5 m"""
    if old["IfcClass"] != new["IfcClass"]:
        return False
    so = sorted(float(old[k]) for k in ("DX", "DY", "DZ"))
    sn = sorted(float(new[k]) for k in ("DX", "DY", "DZ"))
    n_section = 1 if old["IfcClass"] in ("IfcWall", "IfcSlab") else 2
    if any(abs(a - b) > section_tolerance for a, b in zip(so[:n_section], sn[:n_section])):
        return False
    return all(abs(a - b) <= max(length_tolerance * max(a, b), min_length_tolerance)
               for a, b in zip(so[n_section:], sn[n_section:]))


def _pairs_by_position(old, new, tolerance):
    """One-to-one pairs (old GlobalId, new GlobalId) of the same class. Two elements are the same
    element when their centres are closer than `tolerance` IN PLAN and they share the same height
    range (overlap >= 50 % of the shorter one, or centres at the same height): authors model
    columns to different levels, so the 3D centre alone is not reliable. Closest pairs first."""
    pairs = []
    for cls in set(old["IfcClass"]) & set(new["IfcClass"]):
        a = old[(old["IfcClass"] == cls) & old["CX"].notna()]
        b = new[(new["IfcClass"] == cls) & new["CX"].notna()]
        if a.empty or b.empty:
            continue
        A, B = a[["CX", "CY", "CZ", "DZ"]].to_numpy(float), b[["CX", "CY", "CZ", "DZ"]].to_numpy(float)
        plan = np.sqrt(((A[:, None, :2] - B[None, :, :2]) ** 2).sum(-1))
        lo = np.maximum((A[:, 2] - A[:, 3] / 2)[:, None], (B[:, 2] - B[:, 3] / 2)[None])
        hi = np.minimum((A[:, 2] + A[:, 3] / 2)[:, None], (B[:, 2] + B[:, 3] / 2)[None])
        shorter = np.maximum(np.minimum(A[:, 3][:, None], B[:, 3][None]), 1e-6)
        dz = np.abs(A[:, 2][:, None] - B[:, 2][None])
        same_height = ((hi - lo) / shorter >= 0.5) | (dz < tolerance)
        cost = np.where((plan < tolerance) & same_height, plan + 0.1 * dz, np.inf)
        used_a, used_b = set(), set()
        for k in np.argsort(cost, axis=None):
            i, j = divmod(int(k), cost.shape[1])
            if not np.isfinite(cost[i, j]):
                break
            if i in used_a or j in used_b:
                continue
            used_a.add(i), used_b.add(j)
            pairs.append((a["GlobalId"].iloc[i], b["GlobalId"].iloc[j]))
    return pairs


def COMP_VERSIONS(existing, proposed, align=None, tolerance=POSITION_TOLERANCE):
    """PRIMARY FUNCTION. Compares two element tables (from CAPT_ELEMENTS).
    1. Match by GlobalId (same Revit file).  2. Match the rest by position, after CONN_ALIGN
    (different files / coordinates).  Then:
      only in proposed -> new         only in existing -> removed
      matched, different -> old version removed + new version new
      matched, the same  -> left out (unchanged)
    Returns (changes, stats) - stats: counts per kind of match."""
    old = existing.set_index("GlobalId", drop=False)
    new = proposed.set_index("GlobalId", drop=False)
    by_id = list(old.index.intersection(new.index))
    pairs = [(g, g, "GlobalId") for g in by_id]
    if align is not None and align["aligned_share"] > 0:
        rest_old = old.drop(index=by_id)
        rest_new = CONN_APPLY_ALIGN(new.drop(index=by_id), align)
        pairs += [(a, b, "Position") for a, b in _pairs_by_position(rest_old, rest_new, tolerance)]
    matched_old = {a for a, _, _ in pairs}
    matched_new = {b for _, b, _ in pairs}

    rows, n_unchanged = [], 0
    for gid in new.index.difference(list(matched_new)):
        rows.append({**new.loc[gid].to_dict(), "Status": "new", "Change": "added", "MatchedBy": None})
    for gid in old.index.difference(list(matched_old)):
        rows.append({**old.loc[gid].to_dict(), "Status": "removed", "Change": "deleted", "MatchedBy": None})
    for a, b, how in pairs:
        same = (COMP_SIGNATURE(old.loc[a]) == COMP_SIGNATURE(new.loc[b]) if how == "GlobalId"
                else COMP_GEOMETRY(old.loc[a], new.loc[b]))
        if same:
            n_unchanged += 1
            continue
        rows.append({**old.loc[a].to_dict(), "Status": "removed", "Change": "changed (old version)", "MatchedBy": how})
        rows.append({**new.loc[b].to_dict(), "Status": "new", "Change": "changed (new version)", "MatchedBy": how})
    stats = {"by_globalid": len(by_id), "by_position": len(pairs) - len(by_id),
             "unchanged": n_unchanged, "shared_ids": len(by_id) / max(len(old), 1)}
    return pd.DataFrame(rows), stats


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
def CHEK_CHANGES(groups, stats, align, minimum=MIN_SHARED_IDS, min_aligned=MIN_ALIGNED):
    """List of warnings (text). Empty list = nothing suspicious."""
    warnings = []
    if stats["shared_ids"] < minimum and align["aligned_share"] < min_aligned:
        warnings.append(f"Only {stats['shared_ids']:.0%} of GlobalIds match and the models could not be "
                        f"aligned by position ({align['aligned_share']:.0%} of anchor elements line up): "
                        "most elements show as removed + new.")
    elif stats["by_position"]:
        warnings.append(f"{stats['by_position']} elements matched by POSITION (different files): "
                        f"rotation {align['rotation']}°, shift {align['shift']} m, "
                        f"{align['aligned_share']:.0%} of anchor elements line up. Check the result.")
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
def analyse(model, existing, names=("existing", "proposed"), load_bearing_only=True,
            tolerance=POSITION_TOLERANCE):
    """model: the PROPOSED model (opened ifcopenshell file), as in the course template.
    existing: the existing model (opened file) or its element table from CAPT_ELEMENTS
              (the runner reads the existing model once for all variants).
    load_bearing_only: leave out elements marked LoadBearing = False (e.g. partitions in an
              architectural model, when the proposed model is structural only).
    Returns a JSON-compatible dict: groups, elements, info, shared_ids, alignment, warnings."""
    old = existing if isinstance(existing, pd.DataFrame) else CAPT_ELEMENTS(existing)
    new = CAPT_ELEMENTS(model)
    if old.empty or new.empty:
        raise ValueError("A model has no walls, slabs, columns or beams (MEP model?).")
    if load_bearing_only:
        excluded = int((old["LoadBearing"] == False).sum() + (new["LoadBearing"] == False).sum())  # noqa: E712
        old = old[old["LoadBearing"] != False]                                                      # noqa: E712
        new = new[new["LoadBearing"] != False]                                                      # noqa: E712
    else:
        excluded = 0
    shared = len(set(old["GlobalId"]) & set(new["GlobalId"])) / max(len(old), 1)
    align = CONN_ALIGN(old, new, tolerance) if shared < 0.99 else {"rotation": 0, "shift": [0.0, 0.0, 0.0], "aligned_share": 1.0}
    changes, stats = COMP_VERSIONS(old, new, align, tolerance)
    groups, changes = CALC_GROUPS(changes)
    warnings = CHEK_CHANGES(groups, stats, align)

    status = changes.groupby("Change").size() if len(changes) else pd.Series(dtype=int)
    info = pd.DataFrame({"Field": ["Existing model", "Proposed model", "Created",
                                   "Elements existing / proposed", "Left out (LoadBearing = False)",
                                   "Shared GlobalIds", "Matched by GlobalId", "Matched by position",
                                   "Alignment (rotation, shift m, share lined up)",
                                   "Unchanged (left out)", "Added", "Deleted", "Changed",
                                   "Groups", "Warnings"],
                         "Value": [names[0], names[1], datetime.now().strftime("%Y-%m-%d %H:%M"),
                                   f"{len(old)} / {len(new)}", excluded, f"{shared:.0%}",
                                   stats["by_globalid"], stats["by_position"],
                                   f"{align['rotation']}°, {align['shift']}, {align['aligned_share']:.0%}",
                                   stats["unchanged"], int(status.get("added", 0)),
                                   int(status.get("deleted", 0)), int(status.get("changed (new version)", 0)),
                                   len(groups), " | ".join(warnings) or "none"]}).astype(str)
    return {"existing_model": names[0], "proposed_model": names[1],
            "shared_ids": round(shared, 4), "alignment": align, "match_stats": stats,
            "warnings": warnings,
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
