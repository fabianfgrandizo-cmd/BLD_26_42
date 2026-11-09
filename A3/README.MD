# A3 – IFC Pset Explanation: reading an IFC line and its Psets
 
## Summary
 
**Title:** Understand what one line of an IFC file says, and where an element's properties live
 
**Summary:** An animated 3D explainer walks through every part of an `IFCWALL` line, then its property sets (Psets) and quantities (Qto). A short exam tests it, and a small IfcOpenShell script does the same on any real model.
 
| | |
|---|---|
| **Group** | 42 |
| **Focus area** | Build (BLD) |
| **Role / level** | Manager, level [1–2] |
| **BIM use** | Model understanding / data exchange (IFC literacy) |
| **Video** | [IFC Pset Explanation – animated explainer + exam](https://claude.ai/artifact/BNkHnKbPTG77vm8PDANVRy) |
 
**Contents**
 
1. [What is this tool?](#1-what-is-this-tool)
2. [How the tool is built](#2-how-the-tool-is-built)
3. [Getting started](#3-getting-started)
4. [Learn the basics in 5 steps](#4-learn-the-basics-in-5-steps)
5. [Demonstration](#5-demonstration)
6. [Limitations](#6-limitations)
---
 
## 1. What is this tool?
 
Every BIM tool (cost, LCA, clash, viewers) reads lines of text like this one:
 
```
#158=IFCWALL('1AQAupaRP1txwK1AGiN61V',#1,'house - outer wall - house right front','A solid outer wall, ...','solidwall',#167,#179,'454425.1027891.979946.932083.920023',$);
```
 
The tool teaches you to read it:
 
- **IFC Pset Explanation** (web page): a cartoon 3D wall explains its line attribute by attribute, then its Psets and Qto. An exam follows: rebuild two IFC lines by drag-and-drop, plus 12 quick questions.
- **`ifc_line_explainer.py`** (Python): prints any element of a real model with every attribute labelled, plus its Psets and quantities.
## 2. How the tool is built
 
| Part | Built with | What it does |
|---|---|---|
| Explainer + exam | One HTML page + **three.js** | 22 animated scenes, 2 drag-and-drop levels (`IFCWALL`, `IFCPROPERTYSET`), 12 questions |
| `ifc_line_explainer.py` | **IfcOpenShell** (the engine inside Bonsai/Blender) | Labels each attribute of one element, lists its Psets/Qtos and converts units |
 
## 3. Getting started
 
**Explainer:** open the Video link above and press **▶ Watch the explainer** (about 4 minutes). Drag the scene to rotate it. The dots under the video jump between scenes. **Go to the exam →** opens the test.
 
**Script:** with Python installed, open a terminal in the script's folder and run:
 
```bash
pip install ifcopenshell
```
 
**Test models:** the public buildingSMART samples in [Sample-Test-Files](https://github.com/buildingSMART/Sample-Test-Files), folder `IFC 4.0.2.1 (IFC 4 ADD2 TC1)/Simple-Scene/`, file `Building-Architecture.ifc`.
 
## 4. Learn the basics in 5 steps
 
**Step 1 – One element = one line**
```python
import ifcopenshell
import ifcopenshell.util.element as uel
 
model = ifcopenshell.open("Building-Architecture.ifc")
wall = model.by_type("IfcWall")[0]
print(wall)   # #158=IfcWall('1AQAupaRP1txwK1AGiN61V',#1,...,$)
```
`#158` is the instance ID (local to this file). `IFCWALL` is the class. The values in brackets are attributes, always in the schema's order.
 
**Step 2 – The nine attributes of `IfcWall` (IFC4)**
 
| # | Attribute | Value in #158 |
|---|---|---|
| 1 | GlobalId | `'1AQAupaRP1txwK1AGiN61V'` (stable ID) |
| 2 | OwnerHistory | `#1` |
| 3 | Name | `'house - outer wall - …'` |
| 4 | Description | `'A solid outer wall, …'` |
| 5 | ObjectType | `'solidwall'` |
| 6 | ObjectPlacement | `#167` (where it is) |
| 7 | Representation | `#179` (3D shape) |
| 8 | Tag | `'454425.1027891…'` |
| 9 | PredefinedType | `$` |
 
**Step 3 – Five kinds of value:** `'…'` text · `#n` reference to another line · `$` empty · `.XXX.` enumeration · `(…)` list.
 
**Step 4 – Properties live in other lines.** An `IFCRELDEFINESBYPROPERTIES` glues a set to the wall:
```python
print(wall.IsDefinedBy[0])
# #166=IfcRelDefinesByProperties('1l9T...',#1,$,$,(#158),#165)
```
Read it as: "set `#165` applies to `(#158)`".
 
**Step 5 – Read the sets**
```python
print(uel.get_psets(wall))
# {'Qto_WallBaseQuantities': {'NetVolume': 1.269, 'Width': 200.0, 'Length': 1800.0, 'NetSideArea': 6.346}}
```
A **Pset** holds descriptive properties (`IsExternal`, `LoadBearing`, `FireRating`…). A **Qto** holds measurements. The prefixes `Pset_` and `Qto_` are reserved for buildingSMART, so custom sets need their own prefix (e.g. `DTU_CostCarbon`).
 
## 5. Demonstration
 
```bash
python ifc_line_explainer.py Building-Architecture.ifc 53
```
```
#53=IfcSlab('3zR0BOEcLADRKln4HYporH',#1,'floor',...,$)
 9  PredefinedType   $   empty (optional, no value)
PredefinedType is $ on the occurrence; resolved from its type: FLOOR
 
  Pset_SlabCommon  [IfcPropertySet, #58, from Occurrence]
    IsExternal       True     (IfcBoolean)
    LoadBearing      False    (IfcBoolean)
    FireRating       REI30    (IfcLabel)
    AcousticRating   29dB Rw  (IfcLabel)
  Qto_SlabBaseQuantities  [IfcElementQuantity, #65, from Occurrence]
    NetVolume        6.4375  -> 6.438 m³
    Depth            250     -> 0.250 m
  Pset_SlabCommon  [IfcPropertySet, #52, from Type #48]
    FireRating       REI60    (IfcLabel)
```
 
**What we found in the real model**
 
1. **The walls have no `Pset_WallCommon`**, only quantities. Check which sets exist before you build on them.
2. **`$` is not always unknown.** `PredefinedType` is `$` on the element but set on its type (`.SOLIDWALL.`, `.FLOOR.`).
3. **The same Pset can appear twice.** The floor's type says `REI60` and the floor itself says `REI30`. The occurrence wins.
4. **Units are mixed.** Width `200` is mm, but NetVolume `1.269` is m³. Always apply the unit scale.
5. **Text values vary.** `'29dB Rw'` here, `'Rw 52 dB'` in the video. Normalise text before filtering.
## 6. Limitations
 
- The video animates walls only. Other classes follow the same pattern with their own Psets.
- Attribute names follow IFC4. In IFC2x3, for example, `IfcWall` has no `PredefinedType`.
- The script shows one element at a time and expands only single-value properties.
- Exam progress is not saved when the page is reloaded.
  
