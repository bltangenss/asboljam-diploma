"""Offline, explicitly mapped aggregate POS CSV preparation; no API or DB writes.

REAL output requires a separately registered tenant source and API preview/commit.
Unknown source columns are refused instead of dropping possible personal/oracle data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_OUTPUT = ROOT / ".cache" / "enterprise-adapter"
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 250000
MAX_ERRORS = 100
SCHEMAS = {
    "daily_sales": "date branch_id meal_id units_sold available_portions stockout_flag is_open promo price_kzt data_origin".split(),
    "inventory_lots": "branch_id ingredient_id lot_id snapshot_date expiry_date on_hand_qty unit data_origin".split(),
}
KEYS = {
    "daily_sales": ("date", "branch_id", "meal_id"),
    "inventory_lots": ("branch_id", "ingredient_id", "lot_id", "snapshot_date"),
}
INT_FIELDS = {"units_sold", "available_portions", "stockout_flag", "is_open", "promo"}
FLAGS = {"stockout_flag", "is_open", "promo"}
DATE_FIELDS = {"date", "snapshot_date", "expiry_date"}
DECIMAL_FIELDS = {"price_kzt", "on_hand_qty"}
FORBIDDEN_HEADERS = re.compile(
    r"oracle|research[_\W]*only|latent|demand[_\W]*multiplier|base[_\W]*daily[_\W]*demand|"
    r"customer|client|guest|cashier|employee|staff|person|first[_\W]*name|last[_\W]*name|"
    r"full[_\W]*name|email|e[_\W]*mail|phone|mobile|address|passport|loyalty|payment|card|"
    r"operator|contact|account|iban|password|secret|token|(?:^|[_\W])(name|user|login|имя|аты)(?:$|[_\W])|"
    r"клиент|покупател|гост[ья]|кассир|сотрудник|персонал|фамили|отчеств|телефон|почт|адрес|"
    r"жеке|телефон|мекенжай|сатып[_\W]*алушы|(?:^|[_\W])(iin|ssn|pan|фио|иин|жсн)(?:$|[_\W])",
    re.IGNORECASE,
)
PII_VALUE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+|\+\d[\d\s().-]{8,}|\b\d{12,}\b")
SETTINGS = {"mapping_version", "kind", "declared_data_origin", "declared_sales_unit", "declared_currency", "date_format", "decimal_separator", "delimiter", "columns"}


class AdapterError(ValueError):
    """Public messages contain no source values or paths."""


def _problem(row: int, field: str, code: str) -> dict:
    return {"row_number": row, "field": field, "code": code}


def _configuration(mapping: dict) -> tuple[str, dict, str]:
    if not isinstance(mapping, dict) or set(mapping) - SETTINGS:
        raise AdapterError("Mapping must be an object with only documented keys.")
    if mapping.get("mapping_version") != "1" or not isinstance(mapping.get("kind"), str) or mapping["kind"] not in SCHEMAS:
        raise AdapterError("Unsupported mapping_version or kind.")
    kind, columns = mapping["kind"], mapping.get("columns")
    if any(field in mapping and mapping[field] != expected
           for field, expected in (("declared_sales_unit", "portion"), ("declared_currency", "KZT"))):
        raise AdapterError("Unit and currency declarations must use documented values.")
    if kind == "daily_sales" and (mapping.get("declared_sales_unit") != "portion" or mapping.get("declared_currency") != "KZT"):
        raise AdapterError("Sales require explicit portion and KZT declarations; unit/currency conversion is unsupported.")
    required = set(SCHEMAS[kind]) - {"data_origin"}
    if not isinstance(columns, dict) or set(columns) - set(SCHEMAS[kind]) or required - set(columns):
        raise AdapterError("Every operational field must map to an actual source column; constants are unsupported.")
    if any(not isinstance(value, str) or not value or len(value) > 128 for value in columns.values()):
        raise AdapterError("Source column names must be nonempty strings of at most 128 characters.")
    if len(set(columns.values())) != len(columns) or any(FORBIDDEN_HEADERS.search(value) for value in columns.values()):
        raise AdapterError("Duplicate, personal or oracle source column mappings are refused.")
    origin = mapping.get("declared_data_origin")
    if not isinstance(origin, str) or origin not in {"REAL", "SYNTHETIC"}:
        raise AdapterError("declared_data_origin must explicitly be REAL or SYNTHETIC.")
    if mapping.get("delimiter", ",") not in (",", ";", "\t"):
        raise AdapterError("Only comma, semicolon or tab delimiters are supported.")
    if mapping.get("decimal_separator", ".") not in (".", ","):
        raise AdapterError("decimal_separator must be a period or comma.")
    if mapping.get("date_format", "%Y-%m-%d") not in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        raise AdapterError("Only the documented date-only formats are supported; timestamps need an explicit upstream business-date policy.")
    return kind, columns, origin


def _value(field: str, value: str, mapping: dict) -> str:
    if not value or len(value) > 255:
        raise ValueError("MISSING_OR_OVERSIZED_VALUE")
    if PII_VALUE.search(value):
        raise ValueError("POSSIBLE_PERSONAL_DATA")
    if field.endswith("_id"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("INVALID_IDENTIFIER")
    elif field in DATE_FIELDS:
        date_format = mapping.get("date_format", "%Y-%m-%d")
        parsed = datetime.strptime(value, date_format)
        if parsed.strftime(date_format) != value:
            raise ValueError("INVALID_DATE")
        value = parsed.date().isoformat()
    elif field in INT_FIELDS:
        if not re.fullmatch(r"\d+", value) or int(value) > 1000000000:
            raise ValueError("INVALID_INTEGER")
        if field in FLAGS and int(value) not in {0, 1}:
            raise ValueError("INVALID_FLAG")
        value = str(int(value))
    elif field in DECIMAL_FIELDS:
        separator = mapping.get("decimal_separator", ".")
        pattern = r"\d+(?:\.\d+)?" if separator == "." else r"\d+(?:,\d+)?"
        if not re.fullmatch(pattern, value):
            raise ValueError("INVALID_DECIMAL")
        quantity = Decimal(value.replace(",", "."))
        if not quantity.is_finite() or not 0 <= quantity <= Decimal("1000000000000"):
            raise ValueError("INVALID_DECIMAL")
        value = format(quantity, "f")
    elif field == "unit" and value not in {"kg", "L"}:
        raise ValueError("UNSUPPORTED_UNIT")
    elif field == "data_origin" and value != mapping["declared_data_origin"]:
        raise ValueError("ORIGIN_CONFLICT")
    return value


def adapt(source: bytes, mapping: dict) -> tuple[list[dict], dict]:
    """Return canonical rows and a non-sensitive report. Invalid input returns no rows."""
    kind, columns, origin = _configuration(mapping)
    quality = {
        "rows_seen": 0,
        "rows_checked": 0,
        "scan_complete": False,
        "stop_reason": None,
        "aggregate_basis": "valid_rows",
        "valid_rows": 0,
        "missing_values": 0,
        "duplicate_key_rows": 0,
        "units": [],
        "distinct_branch_count": 0,
        "distinct_entity_count": 0,
        "stockout_rows": 0,
        "promo_rows": 0,
        "closed_rows": 0,
        "reference_check": {
            "status": "not_run",
            "reason": "Canonical references and organization scope require separate application preview and commit.",
        },
    }
    report = {
        "adapter_version": "1", "kind": kind, "data_origin": origin,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "mapping_sha256": hashlib.sha256(json.dumps(mapping, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
        "origin_evidence": "source_column_and_operator_declaration" if "data_origin" in columns else "operator_declaration_only",
        "declared_sales_unit": mapping.get("declared_sales_unit"), "declared_currency": mapping.get("declared_currency"),
        "compatibility": "CANONICAL_REAL_REQUIRES_CONFIGURED_SOURCE" if origin == "REAL" else "DEMO_SCHEMA_PREPARED_NOT_IMPORTED",
        "import_performed": False, "foreign_keys_checked": False, "enterprise_compatibility_verified": False,
        "warnings": ["No enterprise connector, source authorization, PII audit, foreign-key or database validation is certified.",
                     "REAL output requires a separately registered source in an eligible organization and application preview/commit; tenant compatibility is not checked here."],
        "source_rows": 0, "output_rows": 0, "valid": False, "errors": [], "quality": quality,
    }
    errors = report["errors"]

    def reject(code: str, row_number: int = 1, field: str = "file") -> tuple[list[dict], dict]:
        errors.append(_problem(row_number, field, code))
        quality["stop_reason"] = code
        return [], report

    def add_error(row_number: int, field: str, code: str) -> None:
        if len(errors) < MAX_ERRORS:
            errors.append(_problem(row_number, field, code))

    if len(source) > MAX_BYTES:
        return reject("FILE_TOO_LARGE")
    try:
        source_text = source.decode("utf-8-sig")
    except UnicodeDecodeError:
        return reject("UTF8_REQUIRED")
    reader = csv.DictReader(io.StringIO(source_text, newline=""), delimiter=mapping.get("delimiter", ","), strict=True)
    rows, seen = [], set()
    branch_ids, entity_ids, units = set(), set(), set()
    try:
        fields = reader.fieldnames or []
        if any(FORBIDDEN_HEADERS.search(field) for field in fields):
            return reject("PERSONAL_OR_ORACLE_COLUMN", field="header")
        if len(fields) != len(set(fields)) or set(fields) != set(columns.values()):
            return reject("UNMAPPED_MISSING_OR_DUPLICATE_COLUMNS", field="header")
        for row_number, raw in enumerate(reader, 2):
            report["source_rows"] += 1
            quality["rows_seen"] += 1
            if report["source_rows"] > MAX_ROWS:
                add_error(row_number, "file", "TOO_MANY_ROWS")
                quality["stop_reason"] = "TOO_MANY_ROWS"
                break
            quality["rows_checked"] += 1
            quality["missing_values"] += sum(
                value is None or not value.strip() for value in (raw.get(name) for name in columns.values())
            )
            if None in raw or any(value is None for value in raw.values()):
                add_error(row_number, "row", "COLUMN_COUNT_MISMATCH")
                if len(errors) >= MAX_ERRORS:
                    quality["stop_reason"] = "ERROR_LIMIT_REACHED"
                    errors.append(_problem(row_number, "file", "ERROR_LIMIT_REACHED"))
                    break
                continue
            row, before = {}, len(errors)
            for field in SCHEMAS[kind]:
                value = origin if field == "data_origin" and field not in columns else raw[columns[field]].strip()
                try:
                    row[field] = _value(field, value, mapping)
                except (ValueError, InvalidOperation) as exc:
                    # strptime can echo a source value; emit allowlisted codes only.
                    code = str(exc)
                    if not re.fullmatch(r"[A-Z_]+", code):
                        code = "INVALID_DATE" if field in DATE_FIELDS else "INVALID_VALUE"
                    add_error(row_number, field, code)
            if len(errors) == before:
                key = tuple(row[field] for field in KEYS[kind])
                if key in seen:
                    quality["duplicate_key_rows"] += 1
                    add_error(row_number, "key", "DUPLICATE_KEY")
                seen.add(key)
                if kind == "daily_sales":
                    if int(row["units_sold"]) > int(row["available_portions"]):
                        add_error(row_number, "units_sold", "SALES_EXCEED_AVAILABLE")
                    if row["is_open"] == "0" and int(row["units_sold"]):
                        add_error(row_number, "is_open", "CLOSED_WITH_SALES")
                if len(errors) == before:
                    quality["valid_rows"] += 1
                    rows.append(row)
                    branch_ids.add(row["branch_id"])
                    entity_ids.add(row["meal_id" if kind == "daily_sales" else "ingredient_id"])
                    units.add("portion" if kind == "daily_sales" else row["unit"])
                    if kind == "daily_sales":
                        quality["stockout_rows"] += int(row["stockout_flag"])
                        quality["promo_rows"] += int(row["promo"])
                        quality["closed_rows"] += int(row["is_open"] == "0")
            if len(errors) >= MAX_ERRORS:
                quality["stop_reason"] = "ERROR_LIMIT_REACHED"
                errors.append(_problem(row_number, "file", "ERROR_LIMIT_REACHED"))
                break
        else:
            quality["scan_complete"] = True
        if not report["source_rows"] and not errors:
            errors.append(_problem(2, "file", "EMPTY_FILE"))
    except csv.Error:
        add_error(max(1, reader.line_num), "file", "INVALID_CSV")
        quality["stop_reason"] = "INVALID_CSV"
    if errors:
        quality["units"] = sorted(units)
        quality["distinct_branch_count"] = len(branch_ids)
        quality["distinct_entity_count"] = len(entity_ids)
        return [], report
    report.update(valid=True, output_rows=len(rows))
    quality["units"] = sorted(units)
    quality["distinct_branch_count"] = len(branch_ids)
    quality["distinct_entity_count"] = len(entity_ids)
    dates = [row["date" if kind == "daily_sales" else "snapshot_date"] for row in rows]
    report.update(date_from=min(dates), date_to=max(dates))
    return rows, report


def write_bundle(rows: list[dict], report: dict, output_dir: Path | None = None) -> Path:
    """Create a new, private ignored output directory. Never overwrite or alter inputs."""
    if not report.get("valid") or not rows or report.get("output_rows") != len(rows):
        raise AdapterError("Only a fully valid, nonempty batch may be written.")
    configured_root = PRIVATE_OUTPUT.absolute()
    safe_root = PRIVATE_OUTPUT.resolve()
    # Refuse symlinks/junctions anywhere in the output-root chain.
    if configured_root != safe_root:
        raise AdapterError("The private output root must not traverse symlinks or junctions.")
    destination = (output_dir or safe_root / uuid.uuid4().hex).absolute()
    resolved = destination.resolve()
    if resolved != destination or not resolved.is_relative_to(safe_root) or resolved == safe_root:
        raise AdapterError("Output must be a new directory inside .cache/enterprise-adapter without symlinks.")
    if destination.exists():
        raise AdapterError("Output already exists; overwriting is refused.")
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    csv_text = io.StringIO(newline="")
    writer = csv.DictWriter(csv_text, fieldnames=SCHEMAS[report["kind"]], lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    payload = csv_text.getvalue().encode("utf-8")
    manifest = dict(report, created_at=datetime.now(timezone.utc).isoformat(),
                    output_sha256=hashlib.sha256(payload).hexdigest(),
                    output_file=report["kind"] + ".csv")
    for filename, content in ((manifest["output_file"], payload),
                              ("provenance.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))):
        with (destination / filename).open("xb") as stream:
            stream.write(content)
        (destination / filename).chmod(0o600)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="UTF-8 aggregate operational CSV; no customer-level exports")
    parser.add_argument("--mapping", required=True, type=Path, help="Explicit JSON mapping and source-origin declaration")
    parser.add_argument("--write", action="store_true", help="Opt in to a new ignored private output bundle; default is dry run")
    parser.add_argument("--output-dir", type=Path, help="New directory under .cache/enterprise-adapter; requires --write")
    args = parser.parse_args(argv)
    try:
        if args.output_dir and not args.write:
            raise AdapterError("--output-dir requires --write; dry run creates no files.")
        source_path = args.source.resolve(strict=True)
        if any(re.search(r"oracle|research[_-]?only|latent", part, re.IGNORECASE) for part in (*args.source.parts, *source_path.parts)):
            raise AdapterError("Research/oracle sources are refused.")
        if source_path.stat().st_size > MAX_BYTES or args.mapping.stat().st_size > 16384:
            raise AdapterError("Source or mapping exceeds its size limit.")
        with source_path.open("rb") as stream:
            payload = stream.read(MAX_BYTES + 1)
        mapping = json.loads(args.mapping.read_text(encoding="utf-8-sig"))
        rows, report = adapt(payload, mapping)
        report["mode"] = "write" if args.write else "dry_run"
        if report["valid"] and args.write:
            destination = write_bundle(rows, report, args.output_dir)
            report["output_directory"] = str(destination.relative_to(ROOT))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 2
    except (AdapterError, OSError, UnicodeError, json.JSONDecodeError):
        # Never echo paths, personal values, connection strings or raw parser errors.
        print(json.dumps({"valid": False, "code": "ADAPTER_INPUT_OR_OUTPUT_REJECTED", "import_performed": False,
                          "message": "Check documented mapping, permitted source, size/encoding and new private output path."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
