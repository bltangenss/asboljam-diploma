"""HTTP-only runtime acceptance against an isolated seeded API and real worker.

Reads DEMO_PASSWORD privately from the environment or --env-file. Creates
synthetic jobs, a sale, and temporary scoped users (deactivated afterward).
No backend imports, worker shortcuts, direct database writes, or secrets in logs.
Database engine/container verification remains a separate deployment check.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import os
import re
import secrets
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]

def timestamp():
    return datetime.now(timezone.utc).isoformat()

class Failure(Exception):
    """Only author-supplied sanitized messages belong in this exception."""

class Report:
    def __init__(self, args):
        self.data = {
            "started_at": timestamp(), "status": "running",
            "api_url": args.api_url, "web_origin": args.web_origin,
            "scope": "External HTTP API and separately running durable worker",
            "database_backend_verified_by_this_script": False,
            "checks": [], "created_records": {},
            "limitations": [
                "Database engine and container health require separate deployment checks.",
                "Cross-organization access not exercised: admin API creates same-organization users only."
            ]
        }

    def check(self, label, success, **facts):
        self.data["checks"].append({"check": label, "passed": bool(success), "at": timestamp(), **facts})
        print(("PASS " if success else "FAIL ") + label, flush=True)
        if not success:
            raise Failure(label)

class Client:
    def __init__(self, args, report):
        self.args, self.report, self.csrf = args, report, None
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, payload=None, *, expected=200, label=None, headers=None, raw=False, record=True):
        request_headers = {"Origin": self.args.web_origin, "Accept": "application/json"}
        if self.csrf:
            request_headers["X-CSRF-Token"] = self.csrf
        request_headers.update(headers or {})
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(self.args.api_url.rstrip("/") + path, data=body, headers=request_headers, method=method)
        try:
            response = self.opener.open(request, timeout=30)
        except HTTPError as error:
            response = error
        except (URLError, TimeoutError, OSError):
            self.report.check(label or method + " " + path, False, failure="network_request_failed")
        with response:
            status = response.status
            result = response.read(10 * 1024 * 1024 + 1)
        if len(result) > 10 * 1024 * 1024:
            raise Failure("HTTP response exceeded verification size limit")
        try:
            result = result.decode("utf-8-sig")
            if not raw:
                result = json.loads(result)
        except (UnicodeError, ValueError):
            raise Failure("HTTP response has invalid text or JSON") from None
        success = status == expected
        if record or not success:
            facts = {"method": method, "endpoint": path, "http_status": status, "expected_status": expected}
            detail = result.get("detail") if isinstance(result, dict) else None
            code = detail.get("code", "") if isinstance(detail, dict) else ""
            if not success and isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,64}", code):
                facts["error_code"] = code
            self.report.check(label or method + " " + path, success, **facts)
        return result

    def login(self, email, password, label):
        result = self.call("POST", "/session/login", {"email": email, "password": password}, label=label)
        csrf = result.get("csrf_token")
        self.report.check(label + " establishes CSRF session", isinstance(csrf, str) and len(csrf) >= 20)
        self.csrf = csrf
        return result

def read_password(path):
    if os.environ.get("DEMO_PASSWORD"):
        return os.environ["DEMO_PASSWORD"]
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        raise Failure("DEMO_PASSWORD unavailable in environment or env file") from None
    for line in content.splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name.strip() == "DEMO_PASSWORD":
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in [chr(34), chr(39)]:
                value = value[1:-1]
            if value:
                return value
    raise Failure("DEMO_PASSWORD unavailable in environment or env file")

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
        raise Failure("API returned invalid resource identifier")
    return value

def wait_job(client, queued, kind):
    run_id = identifier(queued.get("run_id"))
    client.report.check(kind + " enters durable queue", queued.get("status") == "queued", run_id=run_id)
    started, observed = time.monotonic(), []
    while time.monotonic() - started < client.args.timeout:
        run = client.call("GET", "/runs/" + run_id, record=False)
        status = run.get("status")
        if status not in {"queued", "running", "succeeded", "failed"}:
            raise Failure(kind + " returned invalid job status")
        if status not in observed:
            observed.append(status)
        if status == "failed":
            client.report.check(kind + " worker completes", False, run_id=run_id, status=status)
        if status == "succeeded":
            client.report.check(kind + " worker completes", bool(run.get("finished_at")) and run.get("kind") == kind,
                                run_id=run_id, observed_statuses=observed, elapsed_seconds=round(time.monotonic() - started, 2))
            return identifier(run.get("result_id"))
        time.sleep(1)
    client.report.check(kind + " worker completes before timeout", False, timeout_seconds=client.args.timeout)

def scoped_user(admin, role, suffix, created_users):
    password = secrets.token_urlsafe(32)
    email = "runtime-" + role + "-" + suffix + "@asboljam.local"
    user = admin.call("POST", "/users", {"email": email, "password": password, "role": role, "branch_ids": ["1"]},
                      expected=201, label="Create temporary " + role)
    user_id = identifier(user.get("id"))
    created_users.append((user_id, role))
    admin.report.check(role + " is scoped to branch 1", user.get("role") == role and user.get("branch_ids") == ["1"])
    client = Client(admin.args, admin.report)
    client.login(email, password, role + " login")
    return client

def check_import(admin):
    report = admin.report
    latest = admin.call("GET", "/sales?" + urlencode({"branch_id": "1", "meal_id": "1", "limit": 1}), label="Read existing import references")
    report.check("Import uses known branch and meal", latest.get("total", 0) > 0)
    row = latest["items"][0]
    chosen_date = max(date(2026, 1, 4), date.fromisoformat(row["date"]) + timedelta(days=1))
    fields = "date branch_id meal_id units_sold available_portions stockout_flag is_open promo price_kzt data_origin".split()
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fields)
    writer.writeheader()
    writer.writerow({"date": chosen_date.isoformat(), "branch_id": "1", "meal_id": "1", "units_sold": 2,
                     "available_portions": 3, "stockout_flag": 0, "is_open": 1, "promo": 0,
                     "price_kzt": row["price_kzt"], "data_origin": "SYNTHETIC"})
    payload = {"kind": "daily_sales", "csv_text": text.getvalue()}
    preview = admin.call("POST", "/imports/preview", payload, label="Preview valid CSV import")
    report.check("CSV preview validates one row", preview.get("valid") is True and preview.get("row_count") == 1)
    batch_id = identifier(preview.get("id"))
    receipt = admin.call("POST", "/imports/" + batch_id + "/commit", label="Commit valid CSV import")
    query = urlencode({"branch_id": "1", "meal_id": "1", "date_from": chosen_date.isoformat(), "date_to": chosen_date.isoformat()})
    imported = admin.call("GET", "/sales?" + query, label="Read committed sale")
    report.check("Committed sale exists exactly once", imported.get("total") == 1 and imported["items"][0].get("units_sold") == 2)
    replay = admin.call("POST", "/imports/" + batch_id + "/commit", label="Replay committed import")
    report.check("Import replay returns the saved receipt", replay == receipt)
    repeated = admin.call("POST", "/imports/preview", payload, label="Preview identical stored row")
    report.check("Identical stored row is unchanged", repeated.get("valid") is True and
                 repeated.get("counts", {}).get("unchanged") == 1)
    unchanged = admin.call("POST", "/imports/" + identifier(repeated.get("id")) + "/commit", label="Commit unchanged row without duplication")
    report.check("Unchanged import inserts zero rows", unchanged.get("inserted_rows") == 0 and unchanged.get("unchanged_rows") == 1)
    imported = admin.call("GET", "/sales?" + query, label="Check sale after repeat import")
    report.check("Repeated imports preserve exactly one sale", imported.get("total") == 1)
    lines = payload['csv_text'].splitlines(keepends=True)
    invalid = admin.call("POST", "/imports/preview", {**payload, 'csv_text': ''.join(lines + lines[1:])}, label="Preview duplicate keys within one CSV")
    report.check("Duplicate keys within a CSV are rejected", invalid.get("valid") is False and
                 any(error.get("code") == "DUPLICATE_KEY" for error in invalid.get("errors", [])))
    admin.call("POST", "/imports/" + identifier(invalid.get("id")) + "/commit", expected=422, label="Reject invalid duplicate CSV commit")
    report.data["created_records"]["sale"] = {"date": chosen_date.isoformat(), "branch_id": "1", "meal_id": "1", "import_id": batch_id}

def verify(args, report):
    password = read_password(args.env_file)
    admin = Client(args, report)
    Client(args, report).call("GET", "/branches", expected=401, label="Anonymous access is denied")
    health = admin.call("GET", "/health", label="API health")
    report.check("API liveness responds", health == {"status": "ok"})
    ready = admin.call("GET", "/ready", label="API database readiness")
    report.check("API reports supported database schema", ready == {"status": "ready"})
    login = admin.login(args.admin_email, password, "Admin login")
    report.check("Runtime fixture is explicitly synthetic", login.get("data_origin") == "SYNTHETIC" and login.get("usage_mode") == "DEMO")
    report.check("Admin identity has admin role", login.get("user", {}).get("role") == "admin")
    branches = admin.call("GET", "/branches", label="Read seeded branches")
    report.check("Seed includes branches 1 and 2", {"1", "2"}.issubset({row.get("branch_id") for row in branches.get("items", [])}))
    sales = admin.call("GET", "/sales?branch_id=1&limit=2", label="Read branch 1 sales")
    report.check("Sales are populated and scoped", sales.get("total", 0) > 0 and
                 all(row.get("branch_id") == "1" and row.get("data_origin") == "SYNTHETIC" for row in sales.get("items", [])))
    admin.call("POST", "/forecasts", {"branch_id": "1"}, headers={"X-CSRF-Token": "invalid"}, expected=403, label="Mutations reject incorrect CSRF")
    admin.call("POST", "/forecasts", {"branch_id": "1"}, headers={"Origin": "https://invalid.example"}, expected=403, label="Mutations reject untrusted origin")
    queued = admin.call("POST", "/forecasts", {"branch_id": "1", "origin": "2025-12-31", "model": "seasonal_naive_7"},
                        expected=202, label="Queue real seasonal forecast")
    forecast_id = wait_job(admin, queued, "forecast")
    forecast = admin.call("GET", "/forecasts/" + forecast_id, label="Read completed forecast")
    report.check("Forecast has predictions and reproducible snapshot", bool(forecast.get("predictions")) and
                 forecast.get("target_date") == "2026-01-01" and forecast.get("branch_id") == "1" and
                 bool(re.fullmatch(r"[0-9a-f]{64}", forecast.get("input_snapshot_sha256", ""))))
    report.data["created_records"]["forecast_id"] = forecast_id
    queued = admin.call("POST", "/procurement", {"branch_id": "1", "forecast_id": forecast_id, "budget": "300000", "strategy": "point"},
                        expected=202, label="Queue real procurement optimization")
    plan_id = wait_job(admin, queued, "procurement")
    report.data["created_records"]["plan_id"] = plan_id
    plan = admin.call("GET", "/plans/" + plan_id, label="Read optimized plan")
    report.check("Plan is ready with valid constraints", plan.get("status") == "ready" and plan.get("constraints_valid") is True and
                 bool(plan.get("requirements")) and Decimal(str(plan.get("total_cost"))) <= Decimal("300000"))
    report.check("New plan starts at version 1", plan.get("version") == 1)
    approval_path = "/plans/" + plan_id + "/approve"
    approval = {"expected_version": 1, "reason": "Isolated runtime acceptance verification", "acknowledge_shortage": True}
    users, suffix = [], uuid.uuid4().hex[:16]
    try:
        manager = scoped_user(admin, "manager", suffix, users)
        branches = manager.call("GET", "/branches", label="Manager reads assigned branch")
        report.check("Manager branch list excludes branch 2", branches.get("total") == 1 and branches.get("items", [{}])[0].get("branch_id") == "1")
        manager.call("GET", "/sales?branch_id=2", expected=403, label="Manager cannot read branch 2")
        manager.call("GET", "/exports/sales?branch_id=2", expected=403, label="Manager cannot export branch 2")
        manager.call("GET", "/users", expected=403, label="Manager cannot list users")
        manager.call("POST", "/forecasts", {"branch_id": "2"}, expected=403, label="Manager cannot queue branch 2 forecast")
        analyst = scoped_user(admin, "analyst", suffix, users)
        analyst.call("GET", "/plans/" + plan_id, label="Analyst can review plan")
        analyst.call("POST", approval_path, approval, headers={"Idempotency-Key": suffix + "-analyst"}, expected=403, label="Analyst cannot approve plan")
        warehouse = scoped_user(admin, "warehouse", suffix, users)
        warehouse.call("GET", "/inventory?branch_id=1&limit=1", label="Warehouse reads assigned inventory")
        warehouse.call("GET", "/sales?branch_id=1&limit=1", expected=403, label="Warehouse cannot read sales")
        warehouse.call("POST", "/forecasts", {"branch_id": "1"}, expected=403, label="Warehouse cannot queue forecasts")
        manager.call("POST", approval_path, approval, expected=422, label="Approval requires idempotency key")
        manager.call("POST", approval_path, {**approval, "reason": ""}, headers={"Idempotency-Key": suffix + "-reason"},
                     expected=422, label="Approval requires decision reason")
        manager.call("POST", approval_path, {**approval, "expected_version": 2}, headers={"Idempotency-Key": suffix + "-version"},
                     expected=409, label="Approval rejects stale version")
        if plan.get("shortage_count", 0) > 0:
            manager.call("POST", approval_path, {**approval, "acknowledge_shortage": False}, headers={"Idempotency-Key": suffix + "-shortage"},
                         expected=422, label="Approval requires shortage acknowledgment")
        else:
            report.data["limitations"].append("Shortage rejection not exercised: computed plan has no shortages.")
        decision_headers = {"Idempotency-Key": suffix + "-approve"}
        approved = manager.call("POST", approval_path, approval, headers=decision_headers, label="Manager approves plan")
        report.check("Approval advances status and version", approved.get("status") == "approved" and approved.get("version") == 2)
        replay = manager.call("POST", approval_path, approval, headers=decision_headers, label="Replay identical approval key")
        report.check("Idempotent replay returns identical response", replay == approved)
        manager.call("POST", approval_path, {**approval, "reason": "Different acceptance reason"}, headers=decision_headers,
                     expected=409, label="Idempotency rejects changed payload")
        manager.call("POST", approval_path, approval, headers={"Idempotency-Key": suffix + "-stale"}, expected=409, label="Approved plan rejects another decision")
        exported = admin.call("GET", "/plans/" + plan_id + "/export", raw=True, label="Export approved plan CSV")
        rows = list(csv.DictReader(io.StringIO(exported)))
        report.check("CSV preserves summary, requirements and approved status", bool(rows) and
                     {"summary", "requirement"}.issubset({row.get("row_type") for row in rows}) and
                     all(row.get("status") == "approved" and row.get("version") == "2" for row in rows))
        audit_rows, cursor = [], "0"
        while cursor is not None:
            audit = admin.call("GET", "/audit?" + urlencode({"branch_id": "1", "limit": 200, "cursor": cursor}), record=False)
            audit_rows.extend(audit.get("items", []))
            cursor = audit.get("next_cursor")
        decisions = [row for row in audit_rows if row.get("entity_id") == plan_id and row.get("action") == "plan.approved"]
        report.check("Audit stores approval exactly once", len(decisions) == 1, approval_event_count=len(decisions))
        report.check("Audit preserves reason and shortage acknowledgment", decisions[0].get("details", {}).get("reason") == approval["reason"] and
                     decisions[0].get("details", {}).get("acknowledge_shortage") is True)
        if args.skip_import:
            report.data["limitations"].append("CSV import checks skipped by --skip-import.")
        else:
            check_import(admin)
    finally:
        report.data["created_records"]["temporary_user_ids"] = [user_id for user_id, _ in users]
        cleanup_failed = False
        for user_id, role in users:
            try:
                disabled = admin.call("PATCH", "/users/" + user_id, {"role": role, "branch_ids": ["1"], "active": False},
                                      label="Deactivate temporary " + role)
                report.check("Temporary " + role + " is inactive", disabled.get("active") is False)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise Failure("Some temporary verification users could not be deactivated")
    admin.call("POST", "/session/logout", label="Close admin verification session")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8010/api/v1")
    parser.add_argument("--web-origin", default="http://localhost:3010")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.docker.local")
    parser.add_argument("--admin-email", default="admin@asboljam.local", help="Administrator of the isolated SYNTHETIC verification organization")
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts" / "verification" / "runtime.json")
    parser.add_argument("--timeout", type=int, default=120, help="Maximum seconds per durable worker job")
    parser.add_argument("--skip-import", action="store_true")
    args = parser.parse_args()
    for value in (args.api_url, args.web_origin):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error("API URL and origin must be HTTP(S) URLs without credentials, query or fragment")
    if not 1 <= args.timeout <= 1800:
        parser.error("--timeout must be between 1 and 1800 seconds")
    report, exit_code = Report(args), 0
    try:
        verify(args, report)
        report.data["status"] = "passed"
    except Failure as error:
        report.data.update(status="failed", failure=str(error))
        print("Verification failed: " + str(error), file=sys.stderr)
        exit_code = 1
    except Exception as error:
        report.data.update(status="failed", failure="Unexpected " + type(error).__name__ + "; response bodies and credentials withheld")
        print(report.data["failure"], file=sys.stderr)
        exit_code = 1
    finally:
        report.data["finished_at"] = timestamp()
        report.data["passed_check_count"] = sum(check["passed"] for check in report.data["checks"])
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Runtime acceptance: " + report.data["status"] + "; " + str(report.data["passed_check_count"]) + " checks passed.")
    return exit_code

if __name__ == "__main__":
    raise SystemExit(main())
