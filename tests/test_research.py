"""Research provenance boundary checks do not fit models or run MILP."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_research


class ResearchOriginTests(unittest.TestCase):
    def files(self, directory, changed=None, origin="SYNTHETIC", second=False):
        for name in run_research.INPUTS:
            with (directory / (name + ".csv")).open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["branch_id", "data_origin"])
                writer.writeheader()
                if name == changed and origin is None:
                    continue
                writer.writerow({"branch_id": "B1", "data_origin": "SYNTHETIC" if name != changed or second else origin})
                if name == changed and second:
                    writer.writerow({"branch_id": "B1", "data_origin": origin})

    def test_each_real_input_is_refused_before_computation_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in run_research.INPUTS:
                with self.subTest(name=name):
                    self.files(directory, changed=name, origin="REAL")
                    output = directory / "artifacts"
                    with patch.object(run_research, "forecast") as compute, self.assertRaisesRegex(ValueError, "explicitly SYNTHETIC"):
                        run_research.run(directory, output)
                    compute.assert_not_called()
                    self.assertFalse(output.exists())

    def test_mixed_missing_and_empty_origins_are_not_silently_relabelled(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for origin, second in (("REAL", True), ("", False), ("synthetic", False), (None, False)):
                with self.subTest(origin=origin, second=second):
                    self.files(directory, changed="inventory_lots", origin=origin, second=second)
                    output = directory / "artifacts"
                    with patch.object(run_research, "forecast") as compute, self.assertRaisesRegex(ValueError, "explicitly SYNTHETIC"):
                        run_research.run(directory, output)
                    compute.assert_not_called()
                    self.assertFalse(output.exists())

    def test_synthetic_preflight_reaches_computation_without_fitting(self):
        class StopBeforeModelFit(Exception):
            pass
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.files(directory)
            with patch.object(run_research, "forecast", side_effect=StopBeforeModelFit) as compute, self.assertRaises(StopBeforeModelFit):
                run_research.run(directory, directory / "artifacts")
            compute.assert_called_once()
            self.assertEqual(compute.call_args.args[1:], ("B1", "2025-12-31", "seasonal_naive_7"))
            self.assertEqual(list((directory / "artifacts").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
