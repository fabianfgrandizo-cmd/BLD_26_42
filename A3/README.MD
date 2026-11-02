# A3 – From IFC to Excel: sharing BIM data with Python

## Summary

**Title:** Export IFC structural elements to a shareable Excel file

**Summary:** Learn to read walls, slabs, columns and beams from any IFC model with IfcOpenShell, convert their quantities to SI units, and write a formatted Excel file that non-BIM colleagues can open, filter and share.

| | |
|---|---|
| **Group** | 42 |
| **Focus area** | Build (BLD) |
| **Role / level** | Manager, level [1–2] |
| **BIM use** | Quantity take-off / data exchange between tools |
| **Video** |/// [YouTube link] ///|

**Contents**

1. [What is this tool?](#1-what-is-this-tool)
2. [How the script is built](#2-how-the-script-is-built)
3. [Getting started](#3-getting-started)
4. [Learn the basics in 5 steps](#4-learn-the-basics-in-5-steps)
5. [Demonstration: the full script](#5-demonstration-the-full-script)
6. [Limitations](#6-limitations)

---

## 1. What is this tool?

A Python script, **`ifc_to_excel.py`**, that opens an IFC model, collects the
structural elements (walls, slabs, columns, beams) and writes them to an
**Excel file**: one row per element, with its type, storey, material and
quantities in metres.

Most people on a project never open an IFC file, but everybody opens Excel. With
this file, cost estimators, LCA consultants or other tools can use the model data
directly. In our course project, three teams pass data to each other this way:
structure, cost and CO₂.

## 2. How the script is built

The script uses three free Python libraries:

| Library | What it is | What we use it for |
|---|---|---|
| **IfcOpenShell** | Open-source library to read, write and analyse IFC files. It is the same engine that runs inside **Bonsai** (Blender) | Open the model, find the elements, read materials and quantities, calculate volumes from geometry |
| **pandas** | The standard Python library for tables (rows and columns) | Hold the elements as a table, group them, write them to Excel |
| **openpyxl** | Library to create and format Excel files | Bold header, filters, frozen first row, column widths |

## 3. Getting started

We assume Python is already installed.

### 3.1 Open a terminal in your project folder
Put `ifc_to_excel.py` and the test models (see 3.3) in one folder, then open a
terminal **inside that folder**:

- **VS Code** (easiest): *File → Open Folder…* → select the folder → *Terminal → New Terminal*.
- **Windows**: open the folder in File Explorer, click the address bar, type `cmd` and press Enter.
- **Mac**: right-click the folder in Finder → *New Terminal at Folder*.

### 3.2 Install the libraries with pip
`pip` is Python's package installer. In the terminal, type:

```bash
pip install ifcopenshell pandas openpyxl
```

> On Mac you may need `pip3` instead of `pip`.

### 3.3 Get the test models
We use two small **public** sample models published by **buildingSMART
International**, the organisation that maintains the IFC standard. They are free,
so you get exactly our results.

- Repository: [buildingSMART/Sample-Test-Files](https://github.com/buildingSMART/Sample-Test-Files)
- Folder: `IFC 4.0.2.1 (IFC 4 ADD2 TC1)/Simple-Scene/`
- Files: `Building-Architecture.ifc` and `Building-Structural.ifc`

| Model | What it contains |
|---|---|
| `Building-Architecture.ifc` | 4 walls, 3 slabs (floor + 2 roof slabs) |
| `Building-Structural.ifc` | 4 walls, 6 timber beams, 1 footing |

## 4. Learn the basics in 5 steps

Before the full script, here is the core of IfcOpenShell in a few lines. Save
this as `basics.py` in the same folder and run it in the terminal with
`python basics.py`.

**Step 1 – Open the model**
```python
import ifcopenshell
import ifcopenshell.util.element as uel
import pandas as pd

model = ifcopenshell.open("Building-Architecture.ifc")
print(model.schema)          # IFC4
```

**Step 2 – Get all elements of one class**
```python
walls = model.by_type("IfcWall")
print(len(walls))            # 4
```

**Step 3 – Read the attributes of one element**
```python
wall = walls[0]
print(wall.GlobalId, wall.Name)
# 1AQAupaRP1txwK1AGiN61V house - outer wall - house right front
```
`GlobalId` is the unique ID of the element – it never changes, so it is the key
to link your Excel rows back to the model.

**Step 4 – Read material and quantities**
```python
print(uel.get_material(wall).Name)
# stone_sand-lime

print(uel.get_psets(wall, qtos_only=True))
# {'Qto_WallBaseQuantities': {'NetVolume': 1.269, 'Width': 200.0,
#                             'Length': 1800.0, 'NetSideArea': 6.346, ...}}
```
Look closely: **Width 200 and Length 1800** – these are millimetres, while the
volume is in m³. Remember this, it comes back in the demonstration.

**Step 5 – Write a table to Excel**
```python
rows = [{"GlobalId": w.GlobalId, "Name": w.Name} for w in walls]
pd.DataFrame(rows).to_excel("walls.xlsx", index=False)
```
Open `walls.xlsx` – four rows, one per wall. That is the whole idea; the full
script adds more columns, units, error handling and formatting.

## 5. Demonstration: the full script

### Run it
```bash
python ifc_to_excel.py Building-Architecture.ifc
```

```
7 elements exported to Building-Architecture.xlsx
IfcClass
IfcSlab    3
IfcWall    4
```

The Excel file has three sheets:

| Sheet | Content |
|---|---|
| `Elements` | One row per element: GlobalId, class, name, type, storey, material, length, area, thickness, cross-section, volume, volume source |
| `Summary` | Count, total volume and area grouped by class and material |
| `Info` | Source file, date, classes exported, units |

`Summary` sheet for `Building-Architecture.ifc`:

| IfcClass | Material | Count | Total volume (m³) | Total area (m²) |
|---|---|---|---|---|
| IfcSlab | composite_element_roof | 2 | 16.084 | 53.613 |
| IfcSlab | concrete_reinforced_in-situ | 1 | 6.438 | 25.750 |
| IfcWall | gypsum_fiber-board_panel | 1 | 0.165 | 6.863 |
| IfcWall | stone_sand-lime | 3 | 7.286 | 36.429 |

### How it works

**Step 0 – Choose the classes**
```python
CLASSES = ["IfcWall", "IfcSlab", "IfcColumn", "IfcBeam"]
```
`model.by_type("IfcWall")` also returns subclasses (e.g. `IfcWallStandardCase`
in older IFC2x3 files), so you do not need to list them.

**Step 1 – Unit scales: never assume units**

*Finding 1 – the model mixes units.* As we saw in the basics, lengths are stored
in **millimetres** but volumes in **cubic metres**, in the same file. So the
script asks the model for each unit:

```python
uunit.calculate_unit_scale(model, "LENGTHUNIT")   # 0.001 -> mm to m
uunit.calculate_unit_scale(model, "VOLUMEUNIT")   # 1.0   -> already m3
```
Every quantity is multiplied by its own scale, so the Excel file is always in
m, m² and m³: the wall becomes 1.8 m long and 0.2 m thick, not 1800 and 200.

**Step 2 – Read each element**

Type (`get_type`), storey (`get_container`), material (`get_material`, also
layered materials) and quantities (`get_psets(..., qtos_only=True)`).
Quantity names differ per class (`NetSideArea` for walls, `NetArea` for slabs,
`CrossSectionArea` for beams), so the script tries a list of names in order
(`QTO_KEYS`).

**Step 3 – No quantities? Use the geometry**

*Finding 2 – the footing has no quantities.* In `Building-Structural.ifc` the
walls and beams have `Qto_` sets, but the footing does not. Add `"IfcFooting"`
to `CLASSES` and run the script on the structural model. The script then
calculates the volume from the 3D shape:

```python
shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), element)
ushape.get_volume(shape.geometry)       # always in metres
```
The footing gets **3.69 m³**, with `VolumeSource = Geometry`. To check the
method, we deleted all quantity sets from the structural model and ran it again:
the geometry gave exactly the same volumes as the modelled ones (walls
11.008 m³, beams 0.494 m³).

> Keep a column like `VolumeSource`: whoever uses your Excel file must know
> whether a number was modelled or calculated.

**Step 4 – Layered materials**

The sample models use one material per element. Real walls are often layered
(brick + insulation + plasterboard). The script writes each layer with its
thickness in one cell, e.g. `Masonry - Brick (0.092) | Insulation - Rigid (0.05)`.
For cost or CO₂ this matters: each layer has its own volume
(`wall area × layer thickness`).

**Step 5 – Write and format the Excel file**
```python
with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="Elements", index=False)
    summary.to_excel(writer, sheet_name="Summary", index=False)
    info.to_excel(writer, sheet_name="Info", index=False)
```
Then openpyxl formats every sheet: bold coloured header, frozen first row,
filters and column widths. The file is ready to send.

### Using your own model
Use an **architectural or structural** model. MEP models (ventilation, plumbing,
electrical) usually contain no walls or slabs, and the script will tell you:

```
No IfcWall, IfcSlab, IfcColumn, IfcBeam found in model.ifc
- is this a structural/architectural model?
```

## 6. Limitations

- Layered materials are written as one text; the volume is not split per layer.
- Geometry-based volume needs valid solid geometry and is slower on large models.
- Only the first matching quantity per element is used.
- MEP models will usually return no elements.
