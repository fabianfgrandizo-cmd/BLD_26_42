"""
runall.py - shared runner (course node-comply-template, extended for our tool)

Run from the A4 folder:
    python runall.py                                   # every .ifc in models/ (settings.py)
    python runall.py other_folder                      # every .ifc in another folder
    python runall.py other_folder --existing B308X     # ... and say which file is the original
    python runall.py existing.ifc variantA.ifc [variantB.ifc ...]   # exact files

Differences from the course template, because our tool compares models and the teams build
on each other:
  * it opens TWO OR MORE models: the existing building once, then every proposed version
    (they may come from different Revit files: model_changes then aligns them and matches
    elements by position);
  * the analyses are a chain, not independent: Team 40's groups are passed to Teams 42 and 41,
    and the manager's report receives all three results.
Everything else follows the template: each analysis has analyse(...) in <name>/src/main.py,
returns JSON-compatible data, and every run is saved as
<name>/results/<variant>/run-<UTC-time>-<suffix>/result.json without overwriting earlier runs.

For people who don't open IFC or JSON, it also writes Excel files to results/:
    results/changes_<variant>.xlsx    Team 40 sheets + CO2_* sheets + COST_* sheets
    results/project_results.xlsx      Overview, Manual review, one sheet per variant (grows)
"""

import argparse
import inspect
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from settings import MODELS_FOLDER, EXISTING_MODEL_NAME, LOAD_BEARING_ONLY, POSITION_TOLERANCE_M
from model_changes.src.main import CAPT_ELEMENTS, analyse as compare_versions, COMM_EXCEL as excel_changes
from embodied_carbon.src.main import analyse as calculate_carbon, COMM_EXCEL as excel_carbon
from cost_estimate.src.main import analyse as calculate_cost, COMM_EXCEL as excel_cost
from project_report.src.main import analyse as build_report, COMM_WORKBOOK

ROOT = Path(__file__).resolve().parent


def save_result(result, results_dir):
    # Reject unsupported values before creating a run folder.   (unchanged from the template)
    content = json.dumps(result, indent=2, allow_nan=False)
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(tempfile.mkdtemp(prefix=f"run-{timestamp}-", dir=results_dir))
    output = run_dir / "result.json"
    output.write_text(content + "\n", encoding="utf-8")
    return output


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def CAPT_MODELS(folder, existing_name=EXISTING_MODEL_NAME):
    """Finds the models in a folder: the .ifc whose name contains existing_name is the existing
    building, every other .ifc is a proposed version (sorted by name)."""
    folder = resolve(folder)
    if not folder.is_dir():
        raise ValueError(f"Models folder not found: {folder}  (create it or change MODELS_FOLDER in settings.py)")
    files = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".ifc")
    existing = [f for f in files if existing_name.lower() in f.name.lower()]
    if not existing:
        raise ValueError(f"No .ifc with '{existing_name}' in its name in {folder}. Found: "
                         f"{', '.join(f.name for f in files) or 'no .ifc files'}  "
                         "(change EXISTING_MODEL_NAME in settings.py or use --existing)")
    if len(existing) > 1:
        raise ValueError(f"More than one file contains '{existing_name}': "
                         f"{', '.join(f.name for f in existing)}  (use a more exact EXISTING_MODEL_NAME)")
    proposed = [f for f in files if f != existing[0]]
    if not proposed:
        raise ValueError(f"Only the existing model {existing[0].name} is in {folder}: add proposed versions")
    return existing[0], proposed


def CONN_TEAM40(model, existing_elements, names):
    """Calls Team 40's analyse() with only the options it accepts and fills the keys the other
    teams need if Team 40 does not return them, so Team 40 can change its code freely."""
    options = {"load_bearing_only": LOAD_BEARING_ONLY, "tolerance": POSITION_TOLERANCE_M}
    accepted = inspect.signature(compare_versions).parameters
    changes = compare_versions(model, existing_elements, names=names,
                               **{k: v for k, v in options.items() if k in accepted})
    if "groups" not in changes:
        raise ValueError("Team 40 analyse() returned no 'groups'")
    changes.setdefault("existing_model", names[0])
    changes.setdefault("proposed_model", names[1])
    changes.setdefault("warnings", [])
    skipped = [r.get("Value") for r in changes.get("info", []) if "to review" in str(r.get("Item"))]
    if skipped:                                         # e.g. walls Team 40 leaves out of scope
        changes["warnings"] = list(changes["warnings"]) + [
            f"Team 40 left {len(skipped)} element(s) out of the comparison (see Info sheet)"]
    if "shared_ids" not in changes:                       # documented in Team 40's Info list
        info = {row.get("Item"): row.get("Value") for row in changes.get("info", [])}
        text = str(info.get("Shared GlobalIds", "0")).rstrip("%")
        try:
            changes["shared_ids"] = float(text) / 100
        except ValueError:
            changes["shared_ids"] = 0.0
    return changes


def run_variant(existing_elements, existing_name, proposed_path, results_dir=None):
    """Runs the four analyses for one proposed model and saves their results."""
    import ifcopenshell
    variant = proposed_path.stem
    model = ifcopenshell.open(str(proposed_path))                  # opened for reading only
    out = lambda name: (ROOT / name / "results" if results_dir is None else Path(results_dir) / name) / variant

    changes = CONN_TEAM40(model, existing_elements, (existing_name, proposed_path.name))
    carbon = calculate_carbon(changes["groups"])                     # Team 42 receives Team 40's data
    cost = calculate_cost(changes["groups"])                         # Team 41 receives Team 40's data
    report = build_report(changes, carbon, cost, variant)

    for name, result in [("model_changes", changes), ("embodied_carbon", carbon),
                         ("cost_estimate", cost), ("project_report", report)]:
        print(f"  {name}: Result saved to: {save_result(result, out(name)).resolve()}")

    excel_dir = ROOT / "results" if results_dir is None else Path(results_dir)
    excel_dir.mkdir(parents=True, exist_ok=True)
    xlsx = excel_dir / f"changes_{variant}.xlsx"
    excel_changes(changes, xlsx)
    excel_carbon(carbon, xlsx)
    excel_cost(cost, xlsx)
    COMM_WORKBOOK(report, excel_dir / "project_results.xlsx")
    return report["overview"]


def main():
    parser = argparse.ArgumentParser(description="Compare an existing IFC with proposed versions.")
    parser.add_argument("models", nargs="*", type=Path,
                        help="a folder with the models, or existing.ifc followed by proposed .ifc files "
                             "(default: MODELS_FOLDER in settings.py)")
    parser.add_argument("--existing", default=EXISTING_MODEL_NAME,
                        help="text in the file name of the existing model (folder mode)")
    parser.add_argument("--results-dir", type=Path,
                        help="Optional output root; writes <root>/<analysis-name>/<variant>/run-.../result.json")
    args = parser.parse_args()

    if len(args.models) >= 2:                                       # exact files
        existing, proposed = resolve(args.models[0]), [resolve(p) for p in args.models[1:]]
        for path in [existing, *proposed]:
            if not path.is_file():
                parser.error(f"IFC file not found: {path}")
    else:                                                           # a folder
        folder = args.models[0] if args.models else MODELS_FOLDER
        try:
            existing, proposed = CAPT_MODELS(folder, args.existing)
        except ValueError as error:
            parser.error(str(error))
        print(f"Models in {resolve(folder)}: existing = {existing.name}, "
              f"proposed = {', '.join(p.name for p in proposed)}")

    import ifcopenshell
    print(f"Reading existing model {existing.name} ...")
    existing_elements = CAPT_ELEMENTS(ifcopenshell.open(str(existing)))   # read once for all variants

    failed = []
    for path in proposed:
        print(f"-> {path.stem}")
        try:
            ov = run_variant(existing_elements, existing.name, path, args.results_dir)
        except Exception as error:               # an error is reported, never turned into a zero
            print(f"  FAILED: {error}")
            failed.append(path.name)
            continue
        print(f"  {ov['kgCO2e TOTAL']} kgCO2e ({ov['Groups without CO2']} groups without CO2), "
              f"{ov['Cost TOTAL DKK']} DKK ({ov['Groups without cost']} groups without price), "
              f"Complete: {ov['Complete']}")   # totals count only the groups that have a value
        if ov["Warnings"] != "none":
            print(f"  WARNING: {ov['Warnings']}")

    if failed:
        sys.exit(f"\nFailed variants (no results written for them): {', '.join(failed)}")
    print(f"\nExcel results in {ROOT / 'results' if args.results_dir is None else args.results_dir}")


if __name__ == "__main__":
    main()
