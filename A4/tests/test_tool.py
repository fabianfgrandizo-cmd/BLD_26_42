"""
Tests for the A4 tool. Run from the A4 folder:
    python -m unittest discover -s tests

Test models (tests/models) are made from the public buildingSMART sample 'Building-Structural.ifc':
  variantA  1 wall deleted, 1 wall changed to concrete, 3 beams added
  variantB  2 walls deleted, 3 timber beams changed to steel
  variantC  2 beams with an unknown material, 1 wall without material
  variantD  same building re-exported (all GlobalIds new) + 1 wall deleted -> matched by position
  variantE  identical copy (no changes)
  variantF  as D, and the whole model moved 120 m / -45 m / +3 m -> found by CONN_ALIGN
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "tests" / "models"
sys.path.insert(0, str(ROOT))

import ifcopenshell  # noqa: E402

# Known results are checked with the reference matching (position_matching.py), so the CO2, cost and
# report parts are tested on a fixed input; Team 40's own main.py is checked by test_team40_contract.
from model_changes.src.position_matching import CAPT_ELEMENTS, analyse as compare_versions  # noqa: E402
from embodied_carbon.src.main import CONN_MATERIAL, CAPT_CO2DATA, analyse as calculate_carbon  # noqa: E402
from cost_estimate.src.main import analyse as calculate_cost  # noqa: E402

EXPECTED = {   # variant: (kgCO2e total, groups without CO2, GlobalIds match)
    "variantA_concrete_wall": (1452.2, 0, True),
    "variantB_steel_beams": (2854.3, 0, True),
    "variantC_problems": (148.1, 2, True),
    "variantD_reexported": (140.0, 0, False),     # only the deleted wall, found by position
    "variantE_identical": (0.0, 0, True),
    "variantF_moved": (140.0, 0, False),          # same as D after alignment
}


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.existing = CAPT_ELEMENTS(ifcopenshell.open(str(MODELS / "existing.ifc")))

    def run_chain(self, variant):
        changes = compare_versions(ifcopenshell.open(str(MODELS / f"{variant}.ifc")), self.existing)
        return changes, calculate_carbon(changes["groups"]), calculate_cost(changes["groups"])

    def test_known_results(self):
        for variant, (kg, n_problems, ids_match) in EXPECTED.items():
            with self.subTest(variant=variant):
                changes, carbon, cost = self.run_chain(variant)
                self.assertAlmostEqual(carbon["new_kgCO2e"] + carbon["removed_kgCO2e"], kg, delta=0.2)
                self.assertEqual(len(carbon["problems"]), n_problems)
                self.assertEqual(changes["shared_ids"] >= 0.3, ids_match)
                expect_warning = variant in ("variantC_problems", "variantD_reexported", "variantF_moved")
                self.assertEqual(bool(changes["warnings"]), expect_warning)

    def test_results_are_json_compatible(self):
        for result in self.run_chain("variantC_problems"):
            json.dumps(result, allow_nan=False)            # raises if not JSON-compatible

    def test_cost_contract(self):
        _, _, cost = self.run_chain("variantA_concrete_wall")
        self.assertTrue({"GlobalId", "Cost_DKK", "CostProblem"} <= set(cost["groups"][0]))
        self.assertIn("total_new_DKK", cost)

    def test_missing_data_is_reported_not_zero(self):
        _, carbon, cost = self.run_chain("variantC_problems")
        missing = [g for g in carbon["groups"] if g["kgCO2e"] is None]
        self.assertEqual(len(missing), 2)
        for g in cost["groups"]:                          # no price -> reason given, never 0
            self.assertTrue(g["Cost_DKK"] is not None or g["CostProblem"])
        no_category = [g for g in carbon["groups"] if g["Category"] is None]
        costs = {g["GlobalId"]: g for g in cost["groups"]}
        self.assertTrue(all(costs[g["GlobalId"]]["Cost_DKK"] is None for g in no_category))

    def test_alignment_finds_the_shift(self):
        changes = compare_versions(ifcopenshell.open(str(MODELS / "variantF_moved.ifc")), self.existing)
        self.assertEqual(changes["alignment"]["rotation"], 0)
        for got, expected in zip(changes["alignment"]["shift"], [-120.0, 45.0, -3.0]):
            self.assertAlmostEqual(got, expected, delta=0.01)
        self.assertEqual(changes["match_stats"]["by_position"], 9)

    def test_layers_split_by_thickness(self):
        from embodied_carbon.src.main import CONN_LAYERS
        layers, _ = CONN_LAYERS("Brick (100) | Insulation (100) | Concrete (200)")
        self.assertEqual([round(s, 2) for _, s in layers], [0.25, 0.25, 0.5])
        self.assertEqual(CONN_LAYERS("Steel | Steel | Steel")[0], [("Steel", 1.0)])

    def test_material_filter(self):
        rules, _ = CAPT_CO2DATA()
        self.assertEqual(CONN_MATERIAL("Stål S355", rules)[0], "Structural steel")
        self.assertEqual(CONN_MATERIAL("Limtræ GL30", rules)[0], "Glulam")
        self.assertEqual(CONN_MATERIAL("Concrete C30/37", rules)[0], "Concrete C30/37")
        self.assertEqual(CONN_MATERIAL("Concrete - Precast Concrete - 35 MPa", rules)[0], "Concrete C35/45")
        self.assertEqual(CONN_MATERIAL("Misc. Air Layers - Air Space", rules)[0], "Not counted (non-structural layer)")

    def test_import_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
                    "import model_changes.src.main, embodied_carbon.src.main, "
                    "cost_estimate.src.main, project_report.src.main, runall")
            process = subprocess.run([sys.executable, "-c", code], cwd=directory,
                                     capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, "")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_runner_writes_new_run_folders_and_excel(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / "runall.py"), str(MODELS / "existing.ifc"),
                       str(MODELS / "variantA_concrete_wall.ifc"), "--results-dir", directory]
            for _ in range(2):
                process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
            runs = list(Path(directory).glob("embodied_carbon/variantA_concrete_wall/run-*/result.json"))
            self.assertEqual(len(runs), 2)                    # earlier runs are not overwritten
            self.assertTrue((Path(directory) / "project_results.xlsx").is_file())
            self.assertTrue((Path(directory) / "changes_variantA_concrete_wall.xlsx").is_file())

    def test_models_folder(self):
        from runall import CAPT_MODELS
        existing, proposed = CAPT_MODELS(MODELS, "existing")
        self.assertEqual(existing.name, "existing.ifc")
        self.assertEqual(len(proposed), 6)
        self.assertNotIn(existing, proposed)
        with self.assertRaises(ValueError):
            CAPT_MODELS(MODELS, "variant")              # more than one possible original
        with self.assertRaises(ValueError):
            CAPT_MODELS(MODELS, "B308X")                # no original in the folder

    def test_team40_contract(self):
        """Team 40's main.py, called the way runall.py calls it: whatever its matching method,
        the other teams must get groups in the agreed format and nothing may disappear."""
        import runall
        from model_changes.src import main as team40
        from project_report.src.main import analyse as build_report
        existing = team40.CAPT_ELEMENTS(ifcopenshell.open(str(MODELS / "existing.ifc")))
        model = ifcopenshell.open(str(MODELS / "variantA_concrete_wall.ifc"))
        changes = runall.CONN_TEAM40(model, existing, ("existing.ifc", "variantA_concrete_wall.ifc"))
        json.dumps(changes, allow_nan=False)
        for key in ["groups", "existing_model", "proposed_model", "shared_ids", "warnings"]:
            self.assertIn(key, changes)
        for g in changes["groups"]:
            self.assertTrue({"GlobalId", "Status", "IfcClass", "Material", "TypeName", "Count",
                             "Volume_m3"} <= set(g))
            self.assertIn(g["Status"], ("new", "removed"))
        report = build_report(changes, calculate_carbon(changes["groups"]),
                              calculate_cost(changes["groups"]), "variantA_concrete_wall")
        rows = len(changes["groups"]) + len(changes.get("review") or [])
        self.assertEqual(len(report["table"]), rows)            # review elements are not lost
        if changes.get("review"):
            self.assertNotEqual(report["overview"]["Complete"], "yes")


if __name__ == "__main__":
    unittest.main()
