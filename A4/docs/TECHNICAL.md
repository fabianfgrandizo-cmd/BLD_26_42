# A4 – Renovation changes → quantities, embodied CO₂ and cost

Compares an **existing** IFC model with one or more **proposed** (renovated) versions and reports,
for every version: the **quantities** of the elements that change, their **embodied CO₂**
(Danish generic data, BR18 Tabel 7 – the same data used in LCAbyg), their **cost**, and
**everything that could not be calculated**, so it can be finished by hand.

Built on the course template [Working Together](https://github.com/timmcginley/41934/blob/main/Activities/workingTogether.md)
and the week 11 starter [node-comply-template](https://github.com/timmcginley/node-comply-template).

## Folder structure

```text
A4/
  settings.py              models folder and which file is the existing building
  models/                  put your IFC files here (not uploaded to GitHub)
  runall.py                shared runner: opens the models, runs every analysis, saves results
  requirements.txt
  CHANGELOG.md
  model_changes/           Team 40 – which elements change, grouped
    src/main.py              analyse(model, existing)
    src/ifc_to_excel.py      reads one IFC (our A3 tutorial)
    results/<variant>/run-…/result.json
  embodied_carbon/         Team 42 – embodied CO₂
    src/main.py              analyse(groups)
    data/co2_database.xlsx   CO₂ factors per m³ + material filter rules (BR18 Tabel 7, 2025)
    data/build_co2_database.py, tabel7.csv, lcabyg_tabel7_map.json
    results/<variant>/run-…/result.json
  cost_estimate/           Team 41 – cost (TEMPLATE, to be completed by Team 41)
    src/main.py              analyse(groups)
    data/cost_database.xlsx  prices per category – EMPTY, Team 41 fills it
    results/<variant>/run-…/result.json
  project_report/          Manager – one table per variant + the shared workbook
    src/main.py              analyse(changes, carbon, cost)
    results/<variant>/run-…/result.json
  results/                 Excel files for people who don't open IFC or JSON
    changes_<variant>.xlsx     Team 40 sheets + CO2_* + COST_* sheets
    project_results.xlsx       Overview, Manual review, one sheet per variant (grows)
  tests/                   test_tool.py + small test models
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Put **all** the IFC files you want to compare in the `models/` folder: the existing building
and every proposed version. The file whose name contains `B308X` is the existing building;
every other `.ifc` is a proposed version. To change that, edit `settings.py`:

```python
MODELS_FOLDER = r"models"          # or a full path, e.g. r"C:\Models"
EXISTING_MODEL_NAME = "B308X"      # text in the file name of the original building
```

To compare other models, just add or remove files in the folder; no code changes.

Two more options in `settings.py`: `LOAD_BEARING_ONLY = True` leaves out elements marked
`LoadBearing = False` (partitions in an architectural model), and `POSITION_TOLERANCE_M = 0.3`
is how close two elements must be to count as the same element when matched by position.

IFC models are **not** uploaded to GitHub (`.gitignore`).

## Run

```powershell
.\.venv\Scripts\python.exe runall.py
```

Other ways for one run: another folder `python runall.py C:\Models --existing B308X`, or exact
files `python runall.py existing.ifc variantA.ifc variantB.ifc` (first = existing).
Run **`runall.py`**, not the `main.py` files: each `main.py` defines an analysis, the runner loads
the models, calls them in order and saves the results.

Every run writes a new `run-<UTC-time>-<suffix>/result.json` per analysis and per variant;
earlier runs are never overwritten. It also updates the Excel files in `results/`.
A model that fails (e.g. an MEP model without walls) is reported as FAILED, never as zero.

## How the analyses connect

The course template runs independent analyses on one model. Our tool compares models and the
teams build on each other, so `runall.py` is extended in two ways only:

1. it opens the existing model once and every proposed model;
2. it passes results along: Team 40's `groups` go to Teams 42 and 41, and all three go to the report.

```python
changes = compare_versions(proposed_model, existing_elements)   # Team 40  -> {"groups": [...], ...}
carbon  = calculate_carbon(changes["groups"])                     # Team 42  -> {"new_kgCO2e": ..., ...}
cost    = calculate_cost(changes["groups"])                       # Team 41  -> {"total_new_DKK": ..., ...}
report  = build_report(changes, carbon, cost, variant)            # Manager
```

### How elements are matched between the existing and a proposed model

`model_changes/src/main.py` is **Team 40's code** (BLD_26_40, 2026-11-25). It matches by
**quantity equivalence**: an existing and a proposed element are the same if they have the same
class, material name and section and the same length / area / volume (10 mm, 1 %), without
GlobalIds or coordinates. Unmatched elements are `new` or `removed`; elements with incomplete
data are returned as `review` and appear in the Manual review sheet. Scope: beams, columns,
slabs and **exterior** walls (by name / `IsExternal`).

`model_changes/src/position_matching.py` is the earlier **reference** version (matching by
GlobalId, then by position after automatic alignment). It is used by the tests and can be
copied from (`CONN_ALIGN`, `_pairs_by_position`).

`runall.py` calls Team 40 through `CONN_TEAM40`, which passes only the options `analyse()`
accepts and fills the keys the other teams need, so Team 40 can change its code freely.

## Functions (named TYPE_ELEMENT, one primary "C" function per analysis)

Every function gets what it needs as arguments, so other groups can copy single functions.

**model_changes (Team 40)** – see the comments in `model_changes/src/main.py`
(`CAPT_ELEMENTS`, `CAPT_QUANTITY`, `CAPT_SECTION`, `COMP_VERSIONS`, `CALC_GROUPS`,
`CALC_NET_QUANTITIES`, `analyse`, `COMM_EXCEL`).

**cost_estimate (Team 41)** – primary **`CALC_COST`**: price per unit from
`cost_estimate/data/cost_database.xlsx` (same categories as the CO2 database) × the matching
quantity (m3 / m2 / m / pcs). How prices were chosen and their sources: `PRICE_GUIDE.md`.

**embodied_carbon (Team 42)** – primary **`CALC_CO2`**

| Function | What it does |
|---|---|
| `CAPT_GROUPS(source)`, `CAPT_CO2DATA()` | Team 40's groups; rules + factors from `data/co2_database.xlsx` |
| `CONN_NAME(text)`, `CONN_MATERIAL(material, rules)` | Material filter: raw IFC name → category (handles Stål, Limtræ, Beton…, "35 MPa" → C35/45) |
| `CONN_LAYERS(material)` | Multi-layer materials: volume split by layer thickness. Insulation, membranes, air and finishes are "Not counted (non-structural layer)"; every other layer must be classified, else kgCO₂e is left empty and the reason names the layer |
| `CALC_VOLUME(row)`, `CALC_FACTOR(category, status, factors)` | m³; kgCO₂e/m³ – new: A1-A3 + C3-C4, removed: C3-C4, rebar added to in-situ concrete |
| **`CALC_CO2(groups, rules, factors)`** | kgCO₂e = volume × factor per group |
| `CHEK_CO2(result, factors)` | Groups without kgCO₂e and why; unverified factors |
| `COMM_CO2`, `COMM_SHEETS`, `COMM_EXCEL` | Summary tables; add sheets to an Excel file keeping the others |

**cost_estimate (Team 41, template)** – primary **`CALC_COST`**

| Function | What it does |
|---|---|
| `CAPT_GROUPS(source)`, `CAPT_PRICES()` | Team 40's groups; `data/cost_database.xlsx` sheet `Prices` |
| `CONN_MATERIAL` | Team 42's filter, so cost and CO₂ use the same categories |
| **`CALC_COST(groups, prices, rules)`** | Quantity × unit price; new → construction, removed → demolition; `unit` m3 / m2 / m / pcs picks the quantity |
| `CHEK_COST(result)`, `COMM_COST`, `COMM_EXCEL` | Groups without cost; summary; COST_* sheets |

Contract with `runall.py`: `analyse(groups)` returns `{"groups": [{"GlobalId", "CostCategory", "Cost_DKK", "CostProblem"}…], "total_new_DKK", "total_removed_DKK", …}`.

**project_report (Manager)**: `CONN_TEAMS`, `CALC_OVERVIEW`, `CHEK_COMPLETE`, `COMM_WORKBOOK`.

## Reuse a function or run one analysis alone

From the A4 folder:

```python
from embodied_carbon.src.main import CAPT_CO2DATA, CONN_MATERIAL
rules, _ = CAPT_CO2DATA()
CONN_MATERIAL("Stål S355", rules)        # ('Structural steel', ...)
```

```powershell
python -m model_changes.src.position_matching existing.ifc variantA.ifc changes.xlsx   # reference version
python -m embodied_carbon.src.main changes.xlsx      # adds the CO2_* sheets
python -m cost_estimate.src.main changes.xlsx        # adds the COST_* sheets
```

Importing a module does not open a model or write files.

## The Excel results

`results/project_results.xlsx`:

| Sheet | Content |
|---|---|
| `Overview` | One row per variant: quantities, kgCO₂e, cost, values typed by hand, `Complete` (yes / NO), warnings, ranked by CO₂ |
| `Manual review` | Every group that could not be calculated and why, with columns `Manual_kgCO2e`, `Manual_Cost_DKK`, `Checked_by`, `Comment` – kept between runs and added to the totals |
| `<variant>` | One sheet per variant: quantities + kgCO₂e + cost per group |

⚠ Only compare variants with `Complete = yes`: a variant with missing groups looks better than it is.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

9 tests: known results on six test variants (including a re-exported model with new GlobalIds
and a model moved 120 m), automatic alignment, layer splitting, JSON-compatible results, the
cost contract, missing data reported (never zero), the material filter, import without side
effects, and new run folders on every run.

## Tested with the course models

Existing: `B308X_2.ifc` (whole building, IFC4X3). Proposed: `26-03-d-struc.ifc` (IFC4X3) and
`26-06-d-str.ifc` (IFC4), structural models from other Revit files – 0 shared GlobalIds,
different coordinates (shifts of ~270 m and ~6300 m found automatically, no rotation).

| Proposed | Matched by position | Unchanged | Changed | Added | Removed | New kgCO₂e |
|---|---|---|---|---|---|---|
| 26-03 | 172 | 90 | 82 | 364 | 49 | ≈ 798 t |
| 26-06 | 174 | 145 | 29 | 597 | 47 | ≈ 454 t |

Run time ≈ 15 s for both. The volumes come from geometry (the structural models have no
quantity sets) and have **not yet been checked against a Revit material take-off**.

## Known limitations (found in testing)

| Limitation | Effect | Seen in |
|---|---|---|
| **Authors model the same existing element differently** | A column that is 200x200 in B308 and 200x240 in a structural model counts as changed (removed + new); a column split per storey in one model and continuous in the other leaves extra "new" pieces | 26-03: 43 columns typed "Ex…" end up as new |
| **Generic template materials** (`DTU_Default_Floor_Construction`, `<Unnamed>`, `IN_Heavy Weight_120mm`) | No category → no CO₂; they go to Manual review with the layer named | B308 slabs; 26-03 columns |
| **Material change with the same geometry, between different files** | Not detected: position pairs are compared on geometry only, because names differ between authors | – |
| **Precast and hollow-core elements** | Classified as concrete with 100 kg rebar/m³ unless named "huldæk / hollow core": probably overestimated | 26-03 "Precast-Hollow" beams |
| **Volumes from geometry** | Correct for solids, but not checked against Revit take-offs; hollow-core voids may not be modelled | 26-03, 26-06 |
| **Only walls, slabs, columns, beams** | Footings, members, stairs… ignored | – |
| **CO₂ assumptions** | 100 kg rebar/m³ in in-situ concrete; concrete without class → C25/30; module D not included | – |
| **Prices not filled yet** | Every group shows "no price" until Team 41 fills `cost_database.xlsx` | All variants |
| **Incomplete variants rank too well** | Compare only `Complete = yes` (or after the Manual review) | – |
