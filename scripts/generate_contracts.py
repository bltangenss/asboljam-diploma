"""Reconstruct explicit data/design handoff files from this implementation.

The supplied archive contained CSVs and a dictionary, not the original manifest
or design token/screen JSON files. Generated provenance states this distinction.
Run again after changing importer schemas, UI copy or styles.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(relative: str, value: dict) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def importer_constants() -> dict:
    """Read constant declarations without importing/starting the application."""
    source = (ROOT / "apps/api/importing.py").read_text(encoding="utf-8")
    parsed = ast.parse(source)
    wanted = {"SCHEMAS", "KEYS", "IGNORED", "FK", "INT_FIELDS", "DECIMAL_FIELDS", "FLAGS"}
    result = {}
    for item in parsed.body:
        if not isinstance(item, ast.Assign) or not isinstance(item.targets[0], ast.Name):
            continue
        name = item.targets[0].id
        if name not in wanted:
            continue
        if name in {"INT_FIELDS", "DECIMAL_FIELDS"}:
            result[name] = set(ast.literal_eval(item.value.args[0].func.value).split())
        else:
            result[name] = ast.literal_eval(item.value)
    if result.keys() != wanted:
        raise ValueError("Importer constants changed; review the contract generator")
    return result


def data_manifest() -> dict:
    constants = importer_constants()
    dictionary_path = ROOT / "data/raw/data_dictionary.csv"
    with dictionary_path.open(encoding="utf-8-sig", newline="") as handle:
        dictionary = {(row["file"], row["field"]): row for row in csv.DictReader(handle)}
    files = {}
    for kind, columns in constants["SCHEMAS"].items():
        path = ROOT / "data/raw" / (kind + ".csv")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            source_fields = reader.fieldnames
            row_count = sum(1 for _ in reader)
        required = columns.split()
        discarded = sorted(constants["IGNORED"].get(kind, set()))
        if set(source_fields) != set(required + discarded):
            raise ValueError(f"Unexpected source/header mapping for {kind}")
        fields = {}
        for field in source_fields:
            info = dictionary.get((path.name, field), {})
            ignored = field in discarded
            if field.endswith("_id"):
                storage_type = "string_identifier"
            elif field in constants["INT_FIELDS"]:
                storage_type = "integer"
            elif field in constants["DECIMAL_FIELDS"]:
                storage_type = "decimal_string"
            elif field in {"date", "snapshot_date", "expiry_date"}:
                storage_type = "iso_date_string"
            else:
                storage_type = "string"
            if ignored:
                training_use = "forbidden_generator_parameter"
            elif kind == "daily_sales" and field == "units_sold":
                training_use = "observed_sales_target_and_strictly_past_lags"
            elif kind == "daily_sales" and field in {"date", "meal_id", "branch_id"}:
                training_use = "date_or_entity_key"
            else:
                training_use = "not_used_by_current_forecasting_features"
            field_schema = {
                "source_dtype": info.get("dtype", "object"), "source_role": info.get("role", "input"),
                "description_kk": info.get("description_kk", ""),
                "required": not ignored, "storage_type": None if ignored else storage_type,
                "import_policy": "accepted_but_discarded" if ignored else "retained",
                "source_to_storage": None if ignored else f"operational_records.data.{field}",
                "training_use": training_use,
            }
            if field.endswith("_id"):
                field_schema["pattern"] = "^[A-Za-z0-9_-]{1,64}$"
            if field in constants["FLAGS"]:
                field_schema["enum"] = [0, 1]
            if field == "unit":
                field_schema["enum"] = ["kg", "L"]
            if field == "data_origin":
                field_schema["enum"] = ["SYNTHETIC", "REAL"]
                field_schema["origin_policy"] = "Must match the tenant's exclusive origin; REAL requires an operator-registered source."
            if field == "yield_factor":
                field_schema.update({"exclusive_minimum": "0", "maximum": "1"})
            if field in {"pack_qty", "net_qty_per_portion"}:
                field_schema["exclusive_minimum"] = "0"
            if field in constants["INT_FIELDS"] and field not in constants["FLAGS"]:
                field_schema.update({"minimum": 0, "maximum": 6 if field == "weekday" else 1000000000})
            if field in constants["DECIMAL_FIELDS"]:
                field_schema["absolute_maximum"] = "1000000000000"
                if field != "temperature_forecast_c":
                    field_schema["minimum"] = "0"
            fields[field] = field_schema
        references = [{"field": field, "target_file": target + ".csv", "target_field": field}
                      for field, target in constants["FK"].items() if field in required and kind != target]
        files[path.name] = {
            "kind": kind, "source_path": "data/raw/" + path.name,
            "sha256": sha(path), "source_rows": row_count,
            "required_columns": required, "optional_discarded_columns": discarded,
            "allowed_columns": required + discarded, "additional_columns": "reject",
            "primary_key": constants["KEYS"][kind], "foreign_keys": references,
            "storage": {"table": "operational_records", "organization_id": "authenticated_user.organization_id",
                        "branch_id": "source branch_id when present; never inferred from UI selection"},
            "fields": fields,
        }
    return {
        "schema_version": "1.0", "data_origin": "SYNTHETIC",
        "provenance": {
            "status": "reconstructed_during_implementation_not_supplied_original",
            "basis": ["actual supplied CSV headers", "data/raw/data_dictionary.csv", "implemented importer validation"],
            "generator": "scripts/generate_contracts.py",
            "dictionary_sha256": sha(dictionary_path), "importer_sha256": sha(ROOT / "apps/api/importing.py"),
            "notice": "This file was reconstructed explicitly; no original contracts/data_manifest.json was included in the supplied materials.",
        },
        "encoding": ["UTF-8", "UTF-8 BOM"], "separator": ",", "decimal_separator": ".",
        "date_format": "YYYY-MM-DD", "identifier_policy": "Keep source IDs as strings; no synthetic ID remapping.",
        "import": {"default_mode": "append", "all_or_nothing": True,
                   "origin_policy": {"synthetic_only": "SYNTHETIC", "real_only": "REAL"},
                   "real_source_required": ["source_id", "mapping_version", "branch_id", "authorization_reference", "purpose"],
                   "real_usage_modes": {"pilot": "PILOT", "test_fixture": "TEST"},
                   "real_source_registration": "Operator-only, empty unconfigured organization, known timezone and KZT; immutable versioned registration does not independently verify consent.",
                   "real_date_policy": "Sales must precede current business day; inventory snapshots cannot be future-dated. Forecast origin is explicit and closed, target=origin+1.",
                   "real_inventory_policy": "Exact target-date snapshot; every required recipe ingredient needs an explicit quantity, including factual zero. Same-date expiry is usable; eligible offer lead time is zero.",
                   "same_file_duplicate_keys": "rejected", "existing_identical_rows": "unchanged_no_duplicate_insert",
                   "existing_changed_rows": "explicit_correction_required",
                   "correction_kinds": ["daily_sales", "calendar", "inventory_lots"],
                   "correction_requires": ["reason", "existing_keys", "unchanged_preview_hash_and_revision"],
                   "hash_scope": "received UTF-8 CSV text; claimed original hash remains unverified",
                   "canonical_hash_version": "canonical-v1", "commit_replay": "immutable receipt, no duplicate operational writes",
                   "record_history": "append-only revisions; existing legacy source batches remain unknown",
                   "preview_required": True, "default_max_bytes": 20971520, "default_max_rows": 250000,
                   "accepted_upload_type": "CSV", "blank_is_not_zero": True},
        "scenario": {"historical_sales_end": "2025-12-31", "forecast_target": "2026-01-01",
                     "inventory_snapshot": "2026-01-01", "snapshot_position": "before target-day operations"},
        "cross_field_rules": [
            "daily_sales.units_sold <= available_portions",
            "daily_sales.is_open == 0 implies units_sold == 0",
            "supplier_offers.min_packs <= max_packs",
            "inventory_lots.unit == ingredients.unit",
            "calendar.weekday matches the ISO date (Monday=0)",
            "Canonical CSV retains one recipe_version per organization; dated branch/meal recipe activations are separate explicit audited commands",
            "When any selected meal has a dated recipe, every forecast meal needs an effective complete activation; captured per-row yield applies once",
            "An opened stock journal must reconcile with the exact target-date count before procurement; movements on the target day are excluded from its opening",
            "Foreign keys, duplicate keys, branch access and user role are rechecked on commit",
            "Serialized natural key must fit the shared SQLite/PostgreSQL VARCHAR(255) boundary",
            "Inventory expiry_date < target is excluded; equality is usable under the demo convention",
            "Procurement chooses the exact target-date inventory snapshot; stale stock is not silently current",
            "Gross requirement = sum(portions * net_qty_per_portion / yield_factor), once",
            "Line cost = integer packs * pack_qty * unit_cost_kzt",
            "Offer lead_time_days overrides supplier descriptive default; only zero-day offers are eligible",
        ],
        "forbidden_training_sources": ["oracle_do_not_train.csv", "research_only/**",
                                       "branches.demand_multiplier", "meals.base_daily_demand",
                                       "latent_demand_ORACLE_ONLY (scripts/generate_kz_demo.py --oracle)"],
        "operational_import_order": list(constants["SCHEMAS"]), "files": files,
        "demo_datasets": demo_datasets(constants),
    }


def demo_datasets(constants: dict) -> list:
    """Both shipped SYNTHETIC datasets must fit the same importer schemas."""
    roles = {
        "data/raw": "Supplied diploma research dataset; default of seed(), tests and scripts/run_research.py.",
        "data/kz": "Kazakhstan (Qyzylorda) product demo generated by scripts/generate_kz_demo.py; "
                   "default of scripts/seed_demo.py and DEMO_DATASET.",
    }
    result = []
    for relative, role in roles.items():
        files = {}
        for kind, columns in constants["SCHEMAS"].items():
            path = ROOT / relative / (kind + ".csv")
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fields = set(reader.fieldnames or [])
                rows = sum(1 for _ in reader)
            required = set(columns.split())
            if not required <= fields <= required | set(constants["IGNORED"].get(kind, set())):
                raise ValueError(f"{relative}/{path.name} does not fit the importer schema")
            files[path.name] = {"sha256": sha(path), "rows": rows}
        result.append({"path": relative, "role": role, "files": files})
    return result


def design_tokens() -> dict:
    path = ROOT / "apps/web/src/style.css"
    # theme.css is loaded last (apps/web/src/main.tsx) and completes the base tokens and components.
    css = path.read_text(encoding="utf-8") + "\n" + (ROOT / "apps/web/src/theme.css").read_text(encoding="utf-8")
    # Merge repeated top-level selectors in cascade order. Media rules are
    # inventoried separately; they must not overwrite the desktop base tokens.
    cleaned = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules, depth, selector_start, body_start, selector = [], 0, 0, 0, ""
    for index, character in enumerate(cleaned):
        if character == "{":
            if depth == 0:
                selector = cleaned[selector_start:index].strip()
                body_start = index + 1
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                if not selector.startswith("@"):
                    rules.append((selector.split(","), cleaned[body_start:index]))
                selector_start = index + 1
    def declarations(selector):
        values = {}
        for selectors, body in rules:
            if selector in [value.strip() for value in selectors]:
                values.update({key.strip(): value.strip() for part in body.split(";") if ":" in part
                               for key, value in [part.split(":", 1)]})
        if not values:
            raise ValueError(f"Missing style selector {selector}")
        return values
    base = declarations(":root")
    primary, danger, warning, info = (declarations(selector)
                                      for selector in (".primary", ".alert.danger", ".alert.warning", ".alert.info"))
    spacing = set()
    for declaration in re.findall(r"(?:padding(?:-[a-z]+)?|margin(?:-[a-z]+)?|gap):([^;}]+)", css):
        spacing.update(re.findall(r"(?<![-\d.])(?:\d+(?:\.\d+)?)px", declaration))
    observed_fonts = sorted(set(re.findall(r"font-size:(\d+)px", css)), key=int)
    return {
        "schema_version": "1.0",
        "provenance": {"status": "extracted_from_implemented_css_not_supplied_original",
                       "source": "apps/web/src/style.css", "sha256": sha(path),
                       "additional_styles": [{"source": str(p.relative_to(ROOT)).replace('\\', '/'), "sha256": sha(p)} for p in sorted((ROOT / "apps/web/src").glob('*.css')) if p != path],
                       "generator": "scripts/generate_contracts.py",
                       "notice": "Handoff snapshot of actual CSS. Original token JSON was not supplied; this is not a claim of completed accessibility certification."},
        "color": {
            "background": base["background"], "surface": base["--surface"], "text": base["color"],
            "primary": base["--action"], "muted": base["--muted"], "border": base["--border"],
            "shell": base["--shell"], "canvas": base["--canvas"], "accent": base["--accent"],
            "primary_text": primary["color"], "focus_ring": "#7541df",
            "danger": {"background": danger["background"], "text": danger["color"], "border": danger["border-color"]},
            "warning": {"background": warning["background"], "text": warning["color"], "border": warning["border-color"]},
            "information": {"background": info["background"], "text": info["color"], "border": info["border-color"]},
            "all_observed_hex_values": sorted(set(re.findall(r"#[0-9a-fA-F]{3,8}\b", css))),
        },
        "typography": {"font_family": base["font-family"], "base_size": base["font-size"],
                       "h1": declarations("h1"), "h2": declarations("h2"),
                       "table_size": declarations("table")["font-size"],
                       "observed_pixel_sizes": [size + "px" for size in observed_fonts],
                       "observed_sizes_notice": "Literal CSS values include superseded declarations and media queries; they are not effective minimum text sizes.",
                       "extraction_scope": "Top-level selector cascade, with media queries inventoried separately.",
                       "observed_weights": sorted(set(re.findall(r"font-weight:(\d+)", css)), key=int),
                       "numerals": "tabular-nums", "bundled_font_files": False},
        "spacing": {"observed_values": sorted(spacing, key=lambda value: float(value[:-2])),
                    "desktop_content_padding": declarations(".content")["padding"],
                    "panel_heading_padding": declarations(".panel-heading")["padding"]},
        "radius": {"button": declarations(".button")["border-radius"],
                   "metric": declarations(".metric").get("border-radius", "0"),
                   "next_action": declarations(".next-action")["border-radius"],
                   "panel": declarations(".panel")["border-radius"],
                   "dialog": declarations("dialog")["border-radius"]},
        "layout": {"sidebar_default": declarations(".sidebar")["width"],
                   "topbar_min_height": declarations(".topbar")["min-height"],
                   "content_max_width": declarations(".content")["max-width"],
                   "table_overflow": declarations(".table-scroll")["overflow"]},
        "responsive": {
            "media_queries": re.findall(r"@media\(([^)]+)\)", css),
            "desktop_wide_min": "1600px", "desktop_compact_max": "1200px",
            "tablet_max": "1023px", "mobile_max": "767px",
            "mobile_navigation": "sidebar drawer and fixed bottom navigation with safe-area inset",
            "mobile_tables": "horizontal overflow; columns retain readable width",
            "review_viewports": [{"width": width, "height": height} for width, height in
                                 ((360, 800), (390, 844), (768, 1024), (1280, 800), (1440, 900), (1600, 1000))],
        },
        "motion": {"reduced_motion": "@media(prefers-reduced-motion:reduce) disables animation and transition",
                   "button_transition": declarations(".button")["transition"],
                   "spinner": declarations(".spinner")["animation"]},
    }


def screen_map() -> dict:
    operations = ["admin", "manager", "analyst"]
    common = ["loading", "empty", "API_error", "offline_notice", "forbidden"]
    definitions = [
        ("login", "/login", "App.tsx:Login", "Кіру", ["unauthenticated"],
         ["POST /session/login", "GET /session/me"], ["email", "password", "show_password", "locale"],
         ["idle", "submitting", "invalid_credentials", "API_error"]),
        ("dashboard", "/dashboard", "Dashboard.tsx:Dashboard", "Бүгін", operations,
         ["GET /dashboard"], ["branch", "calculation_day", "source_and_usage", "priority_tasks", "actionable_warnings", "daily_plan", "current_purchase", "secondary_sales_analytics", "disclosed_plan_history"], common),
        ("data", "/data", "DataWorkspace.tsx", "Деректер және талдау", operations + ["warehouse"],
         [], ["add_sales", "add_counted_stock", "explicit_correction", "sales_review", "analysis", "reference_import_help"], common),
        ("sales", "/sales", "DataPages.tsx:Sales", "Сатылым", operations,
         ["GET /sales", "GET /meals", "GET /exports/daily_sales"], ["date_range", "meal", "pagination", "CSV_export"], common),
        ("imports", "/imports", "Imports.tsx", "Дерек импорттау", operations + ["warehouse"],
         ["POST /imports/preview", "POST /imports/{id}/commit", "GET /imports", "GET /imports/{id}"],
         ["CSV_file", "kind", "source", "received_text_hash", "counts", "preview_sample", "history", "correction_reason", "before_after", "correction_acknowledgement", "commit"],
         common + ["validation_errors", "partial_scan", "preview_ready", "committed", "identical_replay", "duplicate_conflict", "stale_correction", "recover_commit_status", "batch_deep_link"]),
        ("forecasts", "/forecasts", "Planning.tsx:Forecasts", "Күн жоспары", operations,
         ["GET /forecasts", "POST /forecasts", "GET /runs/{id}", "GET /runs"], ["model", "one_day_target", "calculate", "run_history", "resume_run", "history_pagination"],
         common + ["queued", "running", "failed", "succeeded", "heartbeat_unknown", "heartbeat_delayed", "retry_same_job_status"]),
        ("forecast_detail", "/forecasts/:id", "Planning.tsx:Forecasts", "Болжам нәтижесі", operations,
         ["GET /forecasts/{id}", "GET /sales", "GET /production-plans", "GET /production-plans/{id}", "POST /production-plans"], ["forecast_vs_integer_cooking_portions", "explicit_ceiling_suggestion", "variant_name_and_reason", "immutable_saved_variants", "dated_actual_history_chart", "meal_selector", "one_day_prediction_and_real_quantiles", "metrics", "model_card", "create_procurement"],
         common + ["baseline_without_intervals", "quantile_prediction", "empty_draft_is_not_zero", "save_pending", "uncertain_save_retry_same_key", "stale_source_blocks_new_variant", "dirty_navigation_requires_explicit_discard", "pending_or_uncertain_navigation_blocked"]),
        ("procurement", "/procurement", "Planning.tsx:Procurement", "Сатып алу", operations,
         ["GET /plans", "GET /forecasts", "GET /production-plans", "GET /production-plans/{id}", "POST /procurement", "GET /runs/{id}", "GET /runs"],
         ["forecast", "optional_saved_cooking_variant", "budget", "point_or_quantile_strategy_for_forecasts_only", "calculate", "run_history", "resume_run", "history_pagination"], common + ["queued", "running", "failed", "succeeded", "heartbeat_unknown", "heartbeat_delayed", "retry_same_job_status", "invalid_manual_basis_never_silently_falls_back"]),
        ("plan_detail", "/procurement/:id", "Planning.tsx:Procurement", "Сатып алу жоспары", operations,
         ["GET /plans/{id}", "POST /plans/{id}/approve", "POST /plans/{id}/reject", "GET /plans/{id}/export"],
         ["requirements", "supplier_lines", "shortage_warning", "version", "decision_reason", "shortage_acknowledgement", "frozen_stock_and_recipe_basis", "frozen_manual_portions_when_selected"],
         common + ["ready", "approved", "rejected", "shortage", "approval_dialog", "stale_version", "idempotency_conflict"]),
        ("inventory", "/inventory", "DataPages.tsx:Reference", "Қалдықтар", operations + ["warehouse"],
         ["GET /inventory", "GET /stock/catalog", "GET /stock/ledger", "POST /stock/open/preview", "POST /stock/open", "POST /stock/movements/preview", "POST /stock/movements", "GET /stock/movements", "GET /stock/reconciliation", "POST /stock/recipe-requirements", "GET /stock/recipes", "POST /stock/recipes/preview", "POST /stock/recipes", "GET /stock/count-anchors", "POST /stock/count-anchors/preview", "POST /stock/count-anchors"],
         ["snapshot_date", "lot", "expiry", "quantity", "unit", "explicit_opening", "document_preview", "receipt", "waste", "adjustment", "recipe_usage_with_lot_allocation", "reversal", "dated_recipe_activation", "history_pagination", "count_reconciliation", "immutable_count_anchor", "count_anchor_differences_acknowledgement", "period_scoped_stock_basis"],
         common + ["expired", "expiring_soon", "journal_not_open", "preview", "posting", "uncertain_retry_same_key", "stale_preview", "version_conflict", "source_duplicate", "baseline_changed", "missing_count_unknown", "count_anchor_resolves_old_baseline", "count_anchor_source_change_blocked"]),
        ("recipes", "/recipes", "DataPages.tsx:Reference", "Рецепттер", operations,
         ["GET /recipes"], ["meal", "ingredient", "net_qty_per_portion", "yield_factor", "recipe_version"], common),
        ("suppliers", "/suppliers", "DataPages.tsx:Reference", "Жеткізушілер", operations,
         ["GET /suppliers"], ["pack_qty", "unit_cost_kzt", "min_packs", "max_packs", "lead_time_days"], common),
        ("reports", "/reports", "DataPages.tsx:Reports", "Есептер", operations,
         ["GET /forecasts"], ["forecast_run_list", "link_to_run_metrics"], common),
        ("settings", "/settings", "DataPages.tsx:Reference", "Баптаулар", operations + ["warehouse"],
         ["GET /settings", "POST /account/password"],
         ["organization", "timezone", "currency", "data_policy", "tenant_status", "locale", "role", "branch_access", "current_password", "new_password", "password_confirmation"],
         common + ["organization_read_only", "unknown_metadata", "password_change_pending", "password_validation_error", "password_changed_requires_login"]),
        ("audit", "/audit", "DataPages.tsx:Reference", "Аудит журналы", operations,
         ["GET /audit"], ["actor", "time", "action", "entity", "reason"], common),
    ]
    return {
        "schema_version": "1.0",
        "provenance": {"status": "reconstructed_from_implemented_routes_not_supplied_original",
                       "source": "apps/web/src/App.tsx", "generator": "scripts/generate_contracts.py",
                       "notice": "Route/state inventory is implementation handoff, not a claim every viewport/state has an end-to-end test."},
        "shared_context": {"locales": ["kk", "ru"], "default_locale": "kk", "currency": "KZT",
                           "branch_scoped": True, "data_origin": "Server data_context: exclusive SYNTHETIC or REAL; usage DEMO/PILOT/TEST", "scenario_date": "2026-01-01 for fixed synthetic demo only",
                           "last_sales_date": "2025-12-31", "no_silent_mock_fallback": True,
                           "scenario_scope": "Supplied synthetic source only; never a date assigned to empty organizations",
                           "workspace_gate": {"component": "apps/web/src/Onboarding.tsx",
                               "states": ["settings_loading", "settings_error", "data_policy_unconfigured", "no_authorized_branches", "first_branch_import"],
                               "branch_default": None, "unknown_metadata": None,
                               "refresh_after_branch_commit": ["session/me", "settings", "branches"]}},
        "navigation": {"desktop": "five task groups with contextual secondary navigation", "mobile": "drawer and bottom bar",
                       "primary_routes": ["/dashboard", "/forecasts", "/inventory", "/procurement", "/data"],
                       "groups": {"forecasts": ["forecasts", "recipes"], "procurement": ["procurement", "suppliers"], "data": ["data", "sales", "imports", "reports"], "settings": ["settings", "audit"]},
                       "stock_tasks": ["balance", "receipt", "consumption", "reconciliation", "history", "recipes"],
                       "daily_flow": "Today -> forecast -> optional explicit saved cooking variant -> same-branch stock review -> procurement -> explicit human decision",
                       "forecast_limit": "Observed-sales estimate stays unchanged; user saves immutable named cooking variants with integer portions and reason, without posting stock",
                       "production_editor_guard": {"voluntary_transitions": ["menu", "branch", "logout", "back_forward"],
                           "dirty": "explicit discard or stay", "pending_or_uncertain": "stay and resolve original command",
                           "security": "forced session revocation clears editor regardless of guard",
                           "lifetime": "memory only; beforeunload warns but cannot guarantee recovery after forced close",
                           "history_fallback": "without an exact index for an old unmanaged entry, restore URL consistency by disclosed replacement; managed entries retain forward history"},
                       "mobile_primary_routes": ["/dashboard", "/forecasts", "/procurement", "/inventory"],
                       "root_route": "/dashboard", "unknown_route": "settings fallback in current app"},
        "role_rules": {"approval": ["admin", "manager"], "forecast_and_procurement": ["admin", "manager"],
                       "production_plan_save": ["admin", "manager"], "production_plan_read_api": operations + ["warehouse"],
                       "forecast_and_procurement_read": operations,
                       "operational_import": ["admin", "manager"], "analyst_access": "read_only_with_operational_CSV_templates",
                       "reference_import": ["admin"], "warehouse_import": ["inventory_lots"],
                       "own_password_change": operations + ["warehouse"],
                       "stock_receipt_waste_recipe_usage": ["admin", "manager", "warehouse"],
                       "stock_adjustment_reversal_recipe_activation": ["admin", "manager"],
                       "scope_enforcement": "API enforces role, organization and branch on every request"},
        "screens": [{"id": identifier, "route": route, "component": "apps/web/src/" + component,
                     "title_kk": title, "read_roles": roles, "api": endpoints,
                     "controls_and_data": controls, "states": states}
                    for identifier, route, component, title, roles, endpoints, controls, states in definitions],
        "known_scope": ["One-day forecasting only", "No actual supplier dispatch", "Settings organization view is read-only",
                        "InputProvenance.tsx shows derived freshness and scoped source batch links; historical results stay immutable, stale/unknown ready plans require recomputation before approval",
                        "Forecast chart compares 28 dated actual observations with a separate one-day target; baselines have no fabricated uncertainty interval",
                        "Reports links to stored run metrics; reproducible research CSVs are under artifacts/research"],
    }


def main() -> None:
    write("contracts/data_manifest.json", data_manifest())
    write("design/tokens.json", design_tokens())
    write("design/screens.json", screen_map())
    shared = (ROOT / "apps/web/src/shared.tsx").read_text(encoding="utf-8")
    pairs = re.findall(r"(\w+):\['([^']*)','([^']*)'\]", shared)
    if pairs:
        stock = (ROOT / "apps/web/src/stockCopy.ts").read_text(encoding="utf-8")
        stock_pairs = re.findall(r"(\w+):\['([^']*)','([^']*)'\]", stock)
        write("design/copy.kk.json", {**{key: kk for key, kk, _ in pairs}, **{'stock.' + key: kk for key, kk, _ in stock_pairs}})
        write("design/copy.ru.json", {**{key: ru for key, _, ru in pairs}, **{'stock.' + key: ru for key, _, ru in stock_pairs}})
    print("Reconstructed data manifest, actual CSS tokens, route/state map and implemented UI copy.")


if __name__ == "__main__":
    main()
