# Changelog

## 2026-11-25 (night) – delivery

- New `README.md` for the A4 hand-in (about the tool, Advanced Building Design, IDS, who wrote
  what); the previous technical README is now `docs/TECHNICAL.md`.
- New `information_requirements.ids` (IDS 1.0): material on structural elements, IsExternal on
  walls, positive NetVolume. Passes on B308X, 26-06 and 26-09. `ifctester` added to requirements.

## 2026-11-25 (evening) – Team 41 cost part integrated

- **Effect for all teams:** `cost_estimate/` is now Team 41's code and price list
  (BLD_26_41, commit ded1735): 18 construction and 17 removal rates (DKK, Danish public
  references, all marked unverified; sources in the Sources / Rate_basis sheets and
  `PRICE_GUIDE.md`). Steel categories and CLT removal have no price yet (reported, never 0).
- Only Team 41's own files were taken (cost_estimate/, tests/test_cost.py, examples/,
  PRICE_GUIDE.md); their repo's older copies of runall.py, embodied_carbon and project_report
  were not used.
- Real models: 26-06 ≈ 30.7 M DKK (18/165 groups without price), 26-09 ≈ 7.3 M DKK
  (47/154). `test_missing_data_is_reported_not_zero` updated now that prices exist (28 tests OK).

## 2026-11-25 – Team 40 code integrated

- **Effect for all teams:** `model_changes/src/main.py` is now Team 40's code (quantity
  equivalence matching). The earlier version is kept as `model_changes/src/position_matching.py`.
- `runall.py`: new `CONN_TEAM40` calls Team 40 with only the options it accepts and fills
  `existing_model`, `proposed_model`, `shared_ids`, `warnings` when missing.
- `project_report`: elements Team 40 returns as `review` (incomplete data) now appear in the
  Manual review sheet instead of disappearing (before: the test models gave 0 kgCO2e and "Complete").
- Tests: CO2 / cost / report checked on the reference matching; new `test_team40_contract`
  checks Team 40's code through the runner (11 tests).
- Open points for Team 40: see `TEAM40_REVIEW.md`.

## 2026-11-23 (evening) – models read from a folder

- **Effect for all teams:** no more file paths in `settings.py`. Put the IFC files in `models/`;
  the one whose name contains `EXISTING_MODEL_NAME` ("B308X") is the existing building, the
  others are proposed versions (`CAPT_MODELS` in `runall.py`). Clear errors if the original is
  missing, ambiguous, or there are no proposed versions.
- `python runall.py <folder> [--existing TEXT]` and `python runall.py existing.ifc a.ifc ...` still work.
- Console totals now say how many groups have no CO2 / no price (totals count only known values).

## 2026-11-23 (afternoon) – tested with the course models

- **Effect for all teams:** existing and proposed models from different Revit files now work.
  `model_changes` aligns the models automatically (`CONN_ALIGN`) and matches elements by
  position when GlobalIds don't match (B308 vs the structural models: 0 shared GlobalIds).
- Elements marked `LoadBearing = False` are left out (setting `LOAD_BEARING_ONLY`), so
  partitions in the architectural model are not counted as demolished.
- Wall / slab thickness from volume ÷ area or geometry: Revit's Qto "Width" of a slab is its
  plan width (gave "t=64440 mm").
- `embodied_carbon`: multi-layer materials split by layer thickness; non-structural layers
  (insulation, membranes, air, finishes) count as 0; concrete strength in MPa recognised;
  profiles with the same material repeated treated as one material; a rule order bug fixed
  ("Concrete_Painted" was read as paint).
- New settings `LOAD_BEARING_ONLY`, `POSITION_TOLERANCE_M`; new test models D (re-exported) and
  F (moved 120 m); 9 tests.

## 2026-11-23

- Restructured A4 to the course node-comply-template: shared `settings.py` and `runall.py` at
  the A4 root; one folder per analysis (`model_changes`, `embodied_carbon`, `cost_estimate`,
  `project_report`) with `src/main.py` and its own `results/`.
- Every `analyse()` now returns JSON-compatible data; each run is saved as a new
  `run-…/result.json` and earlier runs are kept.
- `runall.py` extended for our tool: opens the existing model once and every proposed model, and
  passes Team 40's groups to Teams 42 and 41. **Effect for the teams:** Teams 42 and 41 receive
  `changes["groups"]` (a list of dicts) instead of an Excel path.
- Functions renamed to the course convention TYPE_ELEMENT (e.g. `COMP_VERSIONS`, `CALC_CO2`,
  `CALC_COST`), one primary "C" function per analysis, all inputs as arguments.
- Fixed: two identical models crashed the CO₂ and cost step; they now give 0 kgCO₂e and
  `Complete = yes`.
- A failing model (e.g. MEP without structure) is reported as FAILED and the run exits with an
  error; no substitute zero is written.
- Added `tests/test_tool.py` (7 tests, `python -m unittest discover -s tests`).

## 2026-11-16

- Team 40 output format (sheet `Groups`) agreed; CO₂ database built from BR18 Tabel 7 (2025);
  cost template and manual review sheet added.
