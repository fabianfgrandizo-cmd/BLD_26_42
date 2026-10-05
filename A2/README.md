# A2 — Carbon Footprint Comparison Use Case

## A2a. About Your Group
- **Group coding level (total):** 2
- **Focus area:** Build
- **Role:** Manager

---

## A2b. Identify Claim
Comparison: measure the carbon footprint of the added walls and columns in the different versions of the transformed Building 308.

### Building
- **ID:** #2601

### Claim
> TODO: quote the exact sentence or figure from the #2601 report, with page number.
> Example form: "The transformed building adds X kg CO2e from new load-bearing and non-load-bearing walls and columns."

### Purpose of Checking This Claim
The main purpose of the tool is to calculate the carbon footprint of the walls and columns added in each transformed version of the building, so the versions can be ranked from lowest to highest footprint. The second function is to quantify those added elements per version.

- **Walls:** quantity, load-bearing or not, material layers, dimensions, location (storey).
- **Columns:** quantity, material, dimensions, location (storey).

All elements use GWP factors from the **LCAbyg database** (generic data compliant with EN 15804+A2), so every version is measured against the same source.

---

## A2c. Use Case

### How Would You Check This Claim?
1. Identify the carbon footprint claim in the report and the model versions it refers to.
2. Load the original IFC model and each transformed version with **ifcOpenShell**.
3. Detect the added walls and columns by comparing `GlobalId` values between the original and each version.
4. Extract quantities (volume, area) and materials for the added elements.
5. Map each IFC material to an entry in the **LCAbyg database** and calculate: volume x density x GWP factor.
6. Analysts each develop a Python script for one part (walls, columns, material mapping).
7. Manager integrates all results into a single platform and compares the versions against each other and against the claim.

### What Phase?
Design phase, before tender (Build focus area).

At this stage the structural and wall systems can still be changed. Comparing the carbon footprint of the versions here lets the team choose the lowest-impact buildable option before quantities and materials are locked into the tender documents.

### What Information Does This Claim Rely On?
- Geometry and quantities of walls and columns (volume, area, thickness, length, height)
- Material assignment of each element, including wall layers
- Load-bearing status of walls (`Pset_WallCommon.LoadBearing`)
- A stable identifier per element across model versions (`GlobalId`)
- GWP factors and densities per material (external: LCAbyg)

See Analyst groups for details.

### What BIM Purpose Is Required?
**Analyse** (extract, compare and compute), then **Communicate** (report the ranking to stakeholders).

### Closest BIM Use Case
**Sustainability analysis (LCA / embodied carbon)** — TODO: replace with the matching number and name from the course use case list.

### BPMN Diagram

![](./flow.svg)
[View Flow_Diagram (file)](./flow.svg)

## A2d. Scope the Use Case
![](./scope.svg)
[View Scope (file)](./scope.svg)

The new tool covers three steps of the flow: detecting added elements between versions, mapping materials to LCAbyg, and calculating and comparing the footprint. Reading the IFC files and reporting use existing tools (ifcOpenShell, plotting libraries).

## A2e. Tool Idea

### Overview
Python-based **carbon footprint comparison tool** using ifcOpenShell.

### Core Function
Automatically detect the walls and columns added in each version of an IFC model relative to the original, extract their dimensions, volumes and materials, combine them with LCAbyg GWP factors, and calculate the carbon footprint per element, per element type and per version.

### Features
- Compares two or more model versions against one original
- Separates load-bearing walls, non-load-bearing walls and columns
- Integrates results from multiple analyst scripts
- Visualises the comparison and creates a report
- Flags elements with missing material or quantity data instead of silently skipping them
- Supports **OpenBIM** principles of interoperability, collaboration and traceability

### Business Value
- Automates the carbon footprint of any added element in any model version
- Gives a like-for-like basis for choosing between design options
- Improves accuracy and efficiency compared with manual take-off

### Societal Value
- Supports lower embodied carbon in building transformations
- Promotes transparency through OpenBIM standards and a public database

## A2f. Information Requirements

### Information to Extract
| Category | IFC Class | Data Needed | Where in IFC |
|-----------|------------|--------------|--------------|
| Columns | `IfcColumn` | Quantity, material, dimensions, volume | `Qto_ColumnBaseQuantities`, `IfcRelAssociatesMaterial` |
| Walls | `IfcWall` (and `IfcWallStandardCase` in IFC2x3) | Load-bearing status, area, volume, material layers and thicknesses | `Pset_WallCommon`, `Qto_WallBaseQuantities`, `IfcMaterialLayerSet` |
| Identity | all | Match elements between versions | `GlobalId` |
| Location | all | Storey | `IfcRelContainedInSpatialStructure` |

### Is It in the Model?
Partly.
- Geometry, materials and identifiers: yes.
- Base quantities: only if exported; otherwise computed from geometry.
- GWP factors and densities: no, these come from LCAbyg.

### Access via ifcOpenShell?
YES. Properties and quantities via `ifcopenshell.util.element`, geometry-based volumes via `ifcopenshell.geom` when base quantities are missing. A manual mapping table links IFC material names to LCAbyg entries.
