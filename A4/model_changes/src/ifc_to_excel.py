"""
ifc_to_excel.py  -  From IFC to a shareable Excel file with Python
A3 tutorial - Group 42

Reads the structural elements of an IFC model (walls, slabs, columns, beams)
and writes them to an Excel file that anyone can open, filter and share.

Usage:
    python ifc_to_excel.py path/to/model.ifc
    python ifc_to_excel.py path/to/model.ifc  output.xlsx

Requirements:
    pip install ifcopenshell pandas openpyxl
"""

import sys
from datetime import datetime
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel
import ifcopenshell.util.shape as ushape
import ifcopenshell.util.unit as uunit
import pandas as pd

# ---------------------------------------------------------------------
# STEP 0 - Settings: which IFC classes do we want in the Excel file?
# ---------------------------------------------------------------------
CLASSES = ["IfcWall", "IfcSlab", "IfcColumn", "IfcBeam"]

# Quantity names differ per class, so we try them in order of preference
QTO_KEYS = {
    "Length_m":    ["Length"],
    "Area_m2":     ["NetSideArea", "NetArea", "GrossSideArea", "GrossArea"],
    "CrossSection_m2": ["CrossSectionArea"],
    "Thickness_m": ["Width", "Depth"],
    "Volume_m3":   ["NetVolume", "GrossVolume"],
}


# ---------------------------------------------------------------------
# STEP 1 - Unit scales
# IFC values are stored in the model's own units. A model can use mm for
# lengths and m3 for volumes at the same time, so we read each scale.
# ---------------------------------------------------------------------
def get_unit_scales(model):
    return {
        "Length_m":    uunit.calculate_unit_scale(model, "LENGTHUNIT"),
        "Thickness_m": uunit.calculate_unit_scale(model, "LENGTHUNIT"),
        "Area_m2":     uunit.calculate_unit_scale(model, "AREAUNIT"),
        "CrossSection_m2": uunit.calculate_unit_scale(model, "AREAUNIT"),
        "Volume_m3":   uunit.calculate_unit_scale(model, "VOLUMEUNIT"),
    }


# ---------------------------------------------------------------------
# STEP 2 - Helper functions to read information from one element
# ---------------------------------------------------------------------
def get_material_name(element):
    """Returns a readable material name, also for layered walls/slabs."""
    material = uel.get_material(element, should_skip_usage=True)
    if material is None:
        return None
    if material.is_a("IfcMaterial"):
        return material.Name
    if material.is_a("IfcMaterialLayerSet"):
        return " | ".join(f"{l.Material.Name} ({l.LayerThickness:g})"
                          for l in material.MaterialLayers if l.Material)
    if material.is_a("IfcMaterialConstituentSet"):
        return " | ".join(c.Material.Name for c in material.MaterialConstituents or [] if c.Material)
    if material.is_a("IfcMaterialProfileSet"):
        return " | ".join(p.Material.Name for p in material.MaterialProfiles if p.Material)
    if material.is_a("IfcMaterialList"):
        return " | ".join(m.Name for m in material.Materials)
    return getattr(material, "Name", None)


def get_quantities(element, scales):
    """Reads Qto_ quantity sets and converts them to metres."""
    qtos = uel.get_psets(element, qtos_only=True)
    result = {}
    for column, keys in QTO_KEYS.items():
        value = None
        for qto in qtos.values():
            for key in keys:
                if qto.get(key) is not None:
                    value = qto[key]
                    break
            if value is not None:
                break
        result[column] = round(value * scales[column], 4) if value is not None else None
    return result


def volume_from_geometry(element):
    """Fallback when the model has no quantity sets: compute volume from 3D shape.
    ifcopenshell.geom returns geometry in metres, so no unit scale is needed."""
    try:
        shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), element)
        return round(ushape.get_volume(shape.geometry), 4)
    except Exception:
        return None


# ---------------------------------------------------------------------
# STEP 3 - Loop over the model: one row per element
# ---------------------------------------------------------------------
def extract_elements(model):
    scales = get_unit_scales(model)
    rows = []
    for ifc_class in CLASSES:
        for element in model.by_type(ifc_class):
            element_type = uel.get_type(element)
            storey = uel.get_container(element)
            row = {
                "GlobalId": element.GlobalId,
                "IfcClass": element.is_a(),
                "Name": element.Name,
                "TypeName": element_type.Name if element_type else None,
                "Storey": storey.Name if storey else None,
                "Material": get_material_name(element),
            }
            row.update(get_quantities(element, scales))

            row["VolumeSource"] = "Qto" if row["Volume_m3"] is not None else None
            if row["Volume_m3"] is None:
                row["Volume_m3"] = volume_from_geometry(element)
                if row["Volume_m3"] is not None:
                    row["VolumeSource"] = "Geometry"
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# STEP 4 - Write the Excel file (3 sheets) and make it easy to read
# ---------------------------------------------------------------------
def write_excel(df, ifc_path, xlsx_path):
    summary = (df.groupby(["IfcClass", "Material"], dropna=False)
                 .agg(Count=("GlobalId", "count"),
                      Total_Volume_m3=("Volume_m3", "sum"),
                      Total_Area_m2=("Area_m2", "sum"))
                 .round(3).reset_index())

    info = pd.DataFrame({
        "Field": ["Source IFC", "Created", "Elements exported", "Classes", "Units"],
        "Value": [Path(ifc_path).name, datetime.now().strftime("%Y-%m-%d %H:%M"),
                  len(df), ", ".join(CLASSES), "m, m2, m3 (converted from model units)"],
    })

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Elements", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)
        info.to_excel(writer, sheet_name="Info", index=False)

        # Formatting with openpyxl: bold header, filters, frozen header, column widths
        from openpyxl.styles import Font, PatternFill
        for sheet in writer.sheets.values():
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F4E79")
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in column)
                sheet.column_dimensions[column[0].column_letter].width = min(width + 2, 50)


# ---------------------------------------------------------------------
# STEP 5 - Run
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python ifc_to_excel.py model.ifc [output.xlsx]")
    ifc_path = sys.argv[1]
    xlsx_path = sys.argv[2] if len(sys.argv) > 2 else Path(ifc_path).with_suffix(".xlsx").name

    model = ifcopenshell.open(ifc_path)
    df = extract_elements(model)
    if df.empty:
        sys.exit(f"No {', '.join(CLASSES)} found in {ifc_path} - is this a structural/architectural model?")
    write_excel(df, ifc_path, xlsx_path)

    print(f"{len(df)} elements exported to {xlsx_path}")
    print(df.groupby("IfcClass").size().to_string())
    missing = df[df["Material"].isna() | df["Volume_m3"].isna()]
    if len(missing):
        print(f"Warning: {len(missing)} elements without material or volume - check the Excel file")
