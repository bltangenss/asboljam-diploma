"""All fixtures are fabricated, even tests exercising the REAL provenance branch."""
import contextlib
import ast
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import adapt_pos_csv as adapter


def mapping(kind="daily_sales", origin="REAL"):
    return {"mapping_version": "1", "kind": kind, "declared_data_origin": origin,
            **({"declared_sales_unit": "portion", "declared_currency": "KZT"} if kind == "daily_sales" else {}),
            "columns": {field: field for field in adapter.SCHEMAS[kind]}}


def sales(**changes):
    return dict(date="2025-12-31", branch_id="001", meal_id="0009", units_sold="7",
                available_portions="12", stockout_flag="0", is_open="1", promo="0",
                price_kzt="1250.10", data_origin="REAL", **changes)


def stock():
    return dict(branch_id="001", ingredient_id="I9", lot_id="LOT_01", snapshot_date="2026-01-01",
                expiry_date="2026-01-02", on_hand_qty="1.250", unit="kg", data_origin="REAL")


def payload(*rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


class PosAdapterTests(unittest.TestCase):
    def test_canonical_columns_match_the_actual_importer_contract(self):
        tree = ast.parse((adapter.ROOT / "apps/api/importing.py").read_text(encoding="utf-8"))
        declaration = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SCHEMAS" for target in node.targets))
        schemas = ast.literal_eval(declaration.value)
        for kind, fields in adapter.SCHEMAS.items():
            self.assertEqual(fields, schemas[kind].split())

    def test_real_provenance_ids_and_decimal_are_preserved(self):
        raw = payload(sales())
        rows, report = adapter.adapt(raw, mapping())
        self.assertTrue(report["valid"])
        self.assertEqual(rows[0]["branch_id"], "001")
        self.assertEqual(rows[0]["price_kzt"], "1250.10")
        self.assertEqual(rows[0]["data_origin"], "REAL")
        self.assertEqual(report["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["compatibility"], "CANONICAL_REAL_IMPORT_UNSUPPORTED")
        self.assertFalse(report["foreign_keys_checked"])
        self.assertFalse(report["enterprise_compatibility_verified"])
        self.assertFalse(report["import_performed"])

    def test_origin_conflict_never_relabels_real_as_synthetic(self):
        rows, report = adapter.adapt(payload(sales()), mapping(origin="SYNTHETIC"))
        self.assertEqual(rows, [])
        self.assertIn("ORIGIN_CONFLICT", [error["code"] for error in report["errors"]])
        synthetic = sales(); synthetic["data_origin"] = "SYNTHETIC"
        rows, report = adapter.adapt(payload(synthetic), mapping(origin="SYNTHETIC"))
        self.assertEqual(rows[0]["data_origin"], "SYNTHETIC")
        self.assertEqual(report["compatibility"], "DEMO_SCHEMA_PREPARED_NOT_IMPORTED")

    def test_explicit_declaration_is_not_claimed_as_verified_origin(self):
        row = sales(); row.pop("data_origin")
        config = mapping(); config["columns"].pop("data_origin")
        rows, report = adapter.adapt(payload(row), config)
        self.assertEqual(rows[0]["data_origin"], "REAL")
        self.assertEqual(report["origin_evidence"], "operator_declaration_only")
        # A real source origin column cannot silently be ignored.
        self.assertFalse(adapter.adapt(payload(sales()), config)[1]["valid"])

    def test_unmapped_personal_or_oracle_columns_are_refused_not_dropped(self):
        for field in ("customer_email", "name", "operator_id", "account", "oracle_demand", "latent_demand_ORACLE_ONLY", "research_only", "demand_multiplier", "unknown_column"):
            with self.subTest(field=field):
                row = sales(); row[field] = "DO_NOT_PRINT_THIS"
                rows, report = adapter.adapt(payload(row), mapping())
                self.assertFalse(report["valid"])
                self.assertEqual(rows, [])
                self.assertNotIn("DO_NOT_PRINT_THIS", json.dumps(report))

    def test_personal_mapping_and_values_are_refused_without_echo(self):
        config = mapping(); config["columns"]["meal_id"] = "customer_id"
        with self.assertRaises(adapter.AdapterError):
            adapter.adapt(payload(sales()), config)
        for value in ("example.person@example.invalid", "+7 (777) 111-22-33", "123456789012"):
            row = sales(); row["meal_id"] = value
            rows, report = adapter.adapt(payload(row), mapping())
            self.assertEqual(rows, [])
            self.assertNotIn(value, json.dumps(report))
            self.assertEqual(report["errors"][0]["code"], "POSSIBLE_PERSONAL_DATA")

    def test_missing_facts_cannot_be_inferred_from_sales(self):
        config = mapping(); config["columns"].pop("available_portions")
        with self.assertRaises(adapter.AdapterError):
            adapter.adapt(payload(sales()), config)

    def test_sales_require_explicit_portions_and_kzt_no_conversion(self):
        for field, value in (("declared_currency", "USD"), ("declared_sales_unit", "kg"), ("declared_sales_unit", None)):
            config = mapping(); config[field] = value
            with self.subTest(field=field), self.assertRaises(adapter.AdapterError):
                adapter.adapt(payload(sales()), config)

    def test_malformed_row_errors_are_bounded_and_atomic(self):
        raw = payload(sales()).splitlines()[0] + b"\n" + b"missing,cells\n" * 5
        with patch.object(adapter, "MAX_ERRORS", 2):
            rows, report = adapter.adapt(raw, mapping())
        self.assertEqual(rows, [])
        self.assertEqual(len(report["errors"]), 3)
        self.assertEqual(report["errors"][-1]["code"], "ERROR_LIMIT_REACHED")

    def test_explicit_date_decimal_locale_and_column_mapping(self):
        row = sales(); row["date"] = "31.12.2025"; row["price_kzt"] = "1250,10"
        config = mapping(); config.update(date_format="%d.%m.%Y", decimal_separator=",", delimiter=";")
        config["columns"] = {field: "pos_" + field for field in row}
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=list(config["columns"].values()), delimiter=";")
        writer.writeheader(); writer.writerow({"pos_" + field: value for field, value in row.items()})
        rows, report = adapter.adapt(buf.getvalue().encode(), config)
        self.assertTrue(report["valid"])
        self.assertEqual(rows[0]["date"], "2025-12-31")
        self.assertEqual(rows[0]["price_kzt"], "1250.10")

    def test_invalid_numbers_dates_flags_and_cross_field_rules(self):
        cases = [("units_sold", "7.5"), ("units_sold", "-1"), ("units_sold", "13"),
                 ("is_open", "0"), ("promo", "2"), ("price_kzt", "NaN"),
                 ("price_kzt", "=1+1"), ("date", "2025-02-30"), ("date", "2025-12-31T00:00:00")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                row = sales(); row[field] = value
                self.assertFalse(adapter.adapt(payload(row), mapping())[1]["valid"])

    def test_supported_stock_unit_and_exact_quantity_no_implicit_conversion(self):
        rows, report = adapter.adapt(payload(stock()), mapping("inventory_lots"))
        self.assertTrue(report["valid"])
        self.assertEqual(rows[0]["on_hand_qty"], "1.250")
        for unit in ("g", "ml", "pcs", "кг"):
            row = stock(); row["unit"] = unit
            rows, report = adapter.adapt(payload(row), mapping("inventory_lots"))
            self.assertEqual(rows, [])
            self.assertEqual(report["errors"][0]["code"], "UNSUPPORTED_UNIT")

    def test_duplicate_or_invalid_batch_returns_no_partial_rows(self):
        rows, report = adapter.adapt(payload(sales(), sales()), mapping())
        self.assertEqual(rows, [])
        self.assertEqual(report["output_rows"], 0)
        self.assertEqual(report["errors"][0]["code"], "DUPLICATE_KEY")
        bad = sales(); bad["meal_id"] = "another"; bad["price_kzt"] = ""
        self.assertEqual(adapter.adapt(payload(sales(), bad), mapping())[0], [])

    def test_malformed_empty_encoding_size_and_row_limit(self):
        for raw in (b"\xff", b"", payload(sales()).splitlines()[0] + b"\n", payload(sales()) + b'"unterminated'):
            with self.subTest(raw=raw[:12]):
                self.assertFalse(adapter.adapt(raw, mapping())[1]["valid"])
        with patch.object(adapter, "MAX_BYTES", 4):
            self.assertEqual(adapter.adapt(payload(sales()), mapping())[1]["errors"][0]["code"], "FILE_TOO_LARGE")
        with patch.object(adapter, "MAX_ROWS", 1):
            other = sales(); other["meal_id"] = "other"
            self.assertEqual(adapter.adapt(payload(sales(), other), mapping())[0], [])

    def test_invalid_configuration_types_fail_cleanly(self):
        for field, value in (("kind", []), ("declared_data_origin", []), ("delimiter", {}), ("date_format", []), ("decimal_separator", [])):
            config = mapping(); config[field] = value
            with self.subTest(field=field), self.assertRaises(adapter.AdapterError):
                adapter.adapt(payload(sales()), config)

    def test_cli_dry_run_does_not_create_output_or_expose_source_values(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); source = base / "sales.csv"; config = base / "mapping.json"
            source.write_bytes(payload(sales())); config.write_text(json.dumps(mapping()), encoding="utf-8")
            stdout = io.StringIO()
            with patch.object(adapter, "PRIVATE_OUTPUT", base / "private"), contextlib.redirect_stdout(stdout):
                self.assertEqual(adapter.main(["--source", str(source), "--mapping", str(config)]), 0)
            self.assertFalse((base / "private").exists())
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["mode"], "dry_run")
            self.assertNotIn("1250.10", stdout.getvalue())

    def test_write_bundle_is_private_verified_and_never_overwritten(self):
        rows, report = adapter.adapt(payload(sales()), mapping())
        with tempfile.TemporaryDirectory() as temp, patch.object(adapter, "PRIVATE_OUTPUT", Path(temp) / "private"):
            destination = adapter.write_bundle(rows, report)
            output = (destination / "daily_sales.csv").read_bytes()
            provenance = json.loads((destination / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["output_sha256"], hashlib.sha256(output).hexdigest())
            self.assertIn(b",REAL\n", output)
            self.assertEqual(list(csv.DictReader(io.StringIO(output.decode())))[0]["branch_id"], "001")
            with self.assertRaises(adapter.AdapterError):
                adapter.write_bundle(rows, report, destination)
            self.assertEqual((destination / "daily_sales.csv").read_bytes(), output)

    def test_output_escape_invalid_batches_and_symlink_targets_are_refused(self):
        rows, report = adapter.adapt(payload(sales()), mapping())
        with tempfile.TemporaryDirectory() as temp, patch.object(adapter, "PRIVATE_OUTPUT", Path(temp) / "private"):
            outside = Path(temp) / "tracked"
            with self.assertRaises(adapter.AdapterError):
                adapter.write_bundle(rows, report, outside)
            self.assertFalse(outside.exists())
            with self.assertRaises(adapter.AdapterError):
                adapter.write_bundle([], dict(report, valid=False))
            # Deterministically exercise the same resolved-path mismatch as a junction.
            with patch.object(Path, "resolve", return_value=Path(temp) / "elsewhere"), self.assertRaises(adapter.AdapterError):
                adapter.write_bundle(rows, report)

    def test_oracle_source_path_and_output_without_write_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); source = base / "oracle_do_not_train.csv"; config = base / "mapping.json"
            source.write_bytes(payload(sales())); config.write_text(json.dumps(mapping()), encoding="utf-8")
            for extra in ([], ["--output-dir", str(base / "out")]):
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(adapter.main(["--source", str(source), "--mapping", str(config), *extra]), 2)
                self.assertNotIn(str(source), stdout.getvalue())
            self.assertFalse((base / "out").exists())


if __name__ == "__main__":
    unittest.main()
