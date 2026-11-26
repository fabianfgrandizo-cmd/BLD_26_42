"""Behaviour and integration checks; synthetic prices never enter the real database."""
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from cost_estimate.src import main as cost
from embodied_carbon.src.main import CAPT_CO2DATA, CONN_MATERIAL

ROOT = Path(__file__).resolve().parents[1]


class CostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules, _ = CAPT_CO2DATA()

    def setUp(self):
        self.group = {"GlobalId": "G002", "Status": "new", "IfcClass": "IfcWall",
                      "Material": "Concrete C30/37", "TypeName": "t=200 mm", "Count": 1,
                      "Length_m": 3.8, "Area_m2": 14.6565, "Volume_m3": 2.9313,
                      "ElementsWithoutVolume": 0}
        self.price = {"category": "Concrete C30/37", "unit": "m3", "price_DKK_per_unit": 2000,
                      "demolition_DKK_per_unit": 300, "source": "SYNTHETIC TEST ONLY", "verified": "no"}

    def calculate(self, group=None, price=None):
        return cost.CALC_COST(cost.CAPT_GROUPS([self.group if group is None else group]),
                              pd.DataFrame([self.price if price is None else price]).set_index("category"),
                              self.rules).iloc[0]

    def empty_prices(self):
        """Keep missing-price tests independent of the editable production rates."""
        prices = cost.CAPT_PRICES().copy()
        prices[["price_DKK_per_unit", "demolition_DKK_per_unit"]] = None
        return prices

    def test_expected_concrete_cost(self):
        row = self.calculate()
        self.assertEqual(row.Cost_DKK, 5863.0)
        self.assertIsNone(row.CostProblem)

    def test_demolition_uses_separate_price(self):
        row = self.calculate({**self.group, "Status": "removed"})
        self.assertEqual(row.Cost_DKK, 879.0)

    def test_all_supported_units_use_group_totals(self):
        for unit, column in cost.UNIT_TO_COLUMN.items():
            with self.subTest(unit=unit):
                row = self.calculate(price={**self.price, "unit": unit})
                self.assertEqual(row.Cost_DKK, round(self.group[column] * 2000))

    def test_missing_invalid_and_zero_prices(self):
        for value in [None, "", "not a price", -1, float("inf"), True]:
            with self.subTest(value=value):
                row = self.calculate(price={**self.price, "price_DKK_per_unit": value})
                self.assertIsNone(row.Cost_DKK)
                self.assertTrue(row.CostProblem)
        self.assertEqual(self.calculate(price={**self.price, "price_DKK_per_unit": 0}).Cost_DKK, 0)

    def test_missing_or_invalid_quantities_never_become_zero_cost(self):
        for value in [None, "", 0, -1, "invalid", float("inf"), True]:
            with self.subTest(value=value):
                row = self.calculate({**self.group, "Volume_m3": value})
                self.assertIsNone(row.Cost_DKK)
                self.assertEqual(row.CostProblem, "no quantity in m3")

    def test_material_filter_is_shared(self):
        for material in ["NO MATERIAL", "mystery", "Concrete | Wood", "wood_spruce_beam", "Stål S355"]:
            with self.subTest(material=material):
                row = self.calculate({**self.group, "Material": material})
                category, reason = CONN_MATERIAL(material, self.rules)
                self.assertEqual(row.CostCategory, category)
                if category is None:
                    self.assertEqual(row.CostProblem, reason)
                    self.assertIsNone(row.Cost_DKK)

    def test_unknown_category_and_duplicate_price(self):
        row = self.calculate(price={**self.price, "category": "Other"})
        self.assertEqual(row.CostProblem, "category 'Concrete C30/37' not in cost_database")
        prices = pd.DataFrame([self.price, self.price]).set_index("category")
        row = cost.CALC_COST(cost.CAPT_GROUPS([self.group]), prices, self.rules).iloc[0]
        self.assertEqual(row.CostProblem, "duplicate prices for 'Concrete C30/37'")

    def test_invalid_status_and_unit(self):
        self.assertTrue(self.calculate({**self.group, "Status": "existing"}).CostProblem)
        self.assertEqual(self.calculate(price={**self.price, "unit": "kg"}).CostProblem,
                         "unsupported unit 'kg'")

    def test_material_section_conflict_and_partial_volume(self):
        row = self.calculate({**self.group, "TypeName": "Flatsteeel 60mmx20mm S235"})
        self.assertIsNone(row.Cost_DKK)
        self.assertIn("material/section conflict", row.CostProblem)
        self.assertIsNone(self.calculate({**self.group, "ElementsWithoutVolume": 1}).Cost_DKK)

    def test_price_schema_is_exactly_the_shared_six_columns(self):
        expected = ["unit", "price_DKK_per_unit", "demolition_DKK_per_unit", "source", "verified"]
        self.assertEqual(cost.CAPT_PRICES().columns.tolist(), expected)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wrong_schema.xlsx"
            pd.DataFrame([{**self.price, "extra_column": "not allowed"}]).to_excel(
                path, sheet_name="Prices", index=False)
            with self.assertRaisesRegex(ValueError, "exactly these columns"):
                cost.CAPT_PRICES(path)

    def test_duplicate_or_missing_ids_rejected(self):
        for groups in [[self.group, self.group], [{**self.group, "GlobalId": None}]]:
            with self.assertRaises(ValueError):
                cost.CAPT_GROUPS(groups)

    def test_empty_input_needs_no_database(self):
        with patch.object(cost, "CAPT_CO2DATA", side_effect=AssertionError("not needed")):
            result = cost.analyse([], database="does-not-exist.xlsx")
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["total_new_DKK"], 0.0)
        self.assertEqual(result["total_removed_DKK"], 0.0)
        json.dumps(result, allow_nan=False)

    def test_analyse_contract_and_no_input_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "test_prices.xlsx"
            pd.DataFrame([self.price]).to_excel(database, sheet_name="Prices", index=False)
            source = ROOT / "examples/changes_example.xlsx"
            before = hashlib.sha256(source.read_bytes()).digest()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = cost.analyse(source, database=database)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)
            self.assertEqual([r["GlobalId"] for r in result["groups"]], ["G001", "G002", "G003"])
            self.assertEqual(result["total_new_DKK"], 5863)
            self.assertEqual(result["total_removed_DKK"], 0)
            self.assertEqual(result["groups"][1]["Cost_DKK"], 5863)
            self.assertIsNone(result["groups"][0]["Cost_DKK"])
            self.assertEqual(set(result), {"groups", "summary", "total_new_DKK", "total_removed_DKK"})
            for group in result["groups"]:
                self.assertEqual(set(group), {"GlobalId", "CostCategory", "Cost_DKK", "CostProblem"})
            json.dumps(result, allow_nan=False)

    def test_excel_preservation_and_repeated_write(self):
        with tempfile.TemporaryDirectory() as folder:
            source = ROOT / "examples/changes_example.xlsx"
            target = Path(folder) / "copy.xlsx"
            shutil.copy2(source, target)
            with pd.ExcelFile(source) as book:
                keep = {name: pd.read_excel(book, sheet_name=name)
                        for name in book.sheet_names if not name.startswith("COST_")}
            with patch.object(cost, "CAPT_PRICES", return_value=self.empty_prices()):
                result = cost.analyse(target)
            cost.COMM_EXCEL(result, target)
            cost.COMM_EXCEL(result, target)
            with pd.ExcelFile(target) as book:
                for name, frame in keep.items():
                    pd.testing.assert_frame_equal(frame, pd.read_excel(book, sheet_name=name))
                self.assertEqual(len(pd.read_excel(book, sheet_name="COST_Groups")), 3)
                self.assertEqual(len(pd.read_excel(book, sheet_name="COST_Problems")), 3)

    def test_real_team40_files_preserve_order_and_json_contract(self):
        for source in sorted((ROOT / "examples/team40").glob("*.xlsx")):
            with self.subTest(source=source.name):
                groups = pd.read_excel(source, sheet_name="Groups")
                with patch.object(cost, "CAPT_PRICES", return_value=self.empty_prices()):
                    result = cost.analyse(groups)
                self.assertEqual([r["GlobalId"] for r in result["groups"]], groups.GlobalId.tolist())
                self.assertTrue(all(r["Cost_DKK"] is None and r["CostProblem"] for r in result["groups"]))
                json.dumps(result, allow_nan=False)

    def test_module_command_writes_only_cost_sheets_to_working_copy(self):
        source = ROOT / "examples/changes_example.xlsx"
        before = hashlib.sha256(source.read_bytes()).digest()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "working_copy.xlsx"
            shutil.copy2(source, target)
            subprocess.run([sys.executable, "-m", "cost_estimate.src.main", str(target)],
                           cwd=ROOT, check=True, capture_output=True, text=True)
            with pd.ExcelFile(source) as original, pd.ExcelFile(target) as output:
                for name in original.sheet_names:
                    if not name.startswith("COST_"):
                        pd.testing.assert_frame_equal(pd.read_excel(original, sheet_name=name),
                                                      pd.read_excel(output, sheet_name=name))
                groups = pd.read_excel(output, sheet_name="COST_Groups")
                self.assertEqual(groups.columns.tolist(), cost.RESULT_COLUMNS)
                self.assertEqual(len(groups), 3)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)

    def test_import_does_not_read_data_or_write_results(self):
        program = """
from unittest.mock import patch
import pandas as pd
import embodied_carbon.src.main as carbon
with patch.object(pd, 'read_excel', side_effect=AssertionError('read on import')), \\
     patch.object(pd, 'ExcelWriter', side_effect=AssertionError('write on import')), \\
     patch.object(carbon, 'CAPT_CO2DATA', side_effect=AssertionError('classify on import')):
    import cost_estimate.src.main
"""
        result = subprocess.run([sys.executable, "-c", program], cwd=ROOT,
                                check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
