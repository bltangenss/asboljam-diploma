"""Reproduce measured synthetic-data forecasts and procurement experiments.

Run: python scripts/run_research.py
Outputs CSV tables, complete calculation JSON and hashed provenance under
artifacts/research. It never reads research_only or oracle/generator targets.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Avoid Windows WMIC hardware probing; numerical libraries are also limited by
# the engine during estimation. This does not change model/data seeds.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
from apps.api.engine import MODELS, forecast, procurement


INPUTS = ("daily_sales", "ingredients", "recipes", "inventory_lots", "supplier_offers", "suppliers")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not rows:
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(data_dir: Path, output: Path, branches: list[str] | None = None) -> dict:
    started = time.perf_counter()
    loaded, source_hashes = {}, {}
    for name in INPUTS:
        path = data_dir / f"{name}.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            loaded[name] = list(csv.DictReader(handle))
        if not loaded[name] or any(row.get("data_origin") != "SYNTHETIC" for row in loaded[name]):
            raise ValueError(
                f"{name}.csv must contain only explicitly SYNTHETIC records. "
                "REAL, mixed, missing-origin and empty inputs cannot produce synthetic research artifacts."
            )
        source_hashes[path.name] = {"sha256": file_hash(path), "rows": len(loaded[name])}
    available = sorted({row["branch_id"] for row in loaded["daily_sales"]})
    branches = branches or available
    if set(branches) - set(available):
        raise ValueError("Requested branch is absent from daily_sales.csv")
    output.mkdir(parents=True, exist_ok=True)
    all_forecasts, all_plans = [], []
    metrics, predictions, summaries, requirements, lines = [], [], [], [], []
    for branch in branches:
        print(f"Branch {branch}: computing the common 28-day test and next-day forecasts...", flush=True)
        for model in MODELS:
            result = forecast(loaded["daily_sales"], branch, "2025-12-31", model)
            all_forecasts.append(result)
            metric = result["selected_model_metrics"]
            metrics.append({"branch_id": branch, **metric, "seed": result["metadata"]["seed"],
                            "data_hash": result["metadata"]["data_hash"],
                            "train_start": result["metadata"]["train_start"],
                            "train_end": result["metadata"]["train_end"]})
            predictions += [{"branch_id": branch, "model": model,
                             "target_date": result["target_date"], **row} for row in result["predictions"]]
            scenarios = [("budget_zero", "point", "0", loaded["suppliers"]),
                         ("budget_limited", "point", "75000", loaded["suppliers"]),
                         ("budget_standard", "point", "200000", loaded["suppliers"])]
            if model == "hist_gradient_boosting":
                scenarios += [("median", "p50", "200000", loaded["suppliers"]),
                              ("stress", "p90_stress", "200000", loaded["suppliers"]),
                              ("unavailable_suppliers", "point", "200000", [])]
            for scenario, strategy, budget, suppliers in scenarios:
                plan = procurement(result, loaded["ingredients"], loaded["recipes"],
                                   loaded["inventory_lots"], loaded["supplier_offers"],
                                   suppliers, branch, result["target_date"], budget, strategy)
                if not plan["constraints_valid"]:
                    raise RuntimeError("Research calculation returned an invalid procurement plan")
                identifier = f"branch-{branch}-{model}-{scenario}"
                all_plans.append({"experiment_id": identifier, "model": model, "scenario": scenario, **plan})
                summaries.append({
                    "experiment_id": identifier, "branch_id": branch, "model": model,
                    "scenario": scenario, "strategy": strategy, "budget": budget,
                    "total_cost": plan["total_cost"], "remaining_budget": plan["remaining_budget"],
                    "shortage_count": plan["shortage_count"], "supplier_line_count": len(plan["lines"]),
                    "solver_status": plan["solver_status"], "constraints_valid": plan["constraints_valid"],
                    "input_hash": plan["metadata"]["input_hash"],
                    "elapsed_seconds": plan["metadata"]["elapsed_seconds"],
                })
                requirements += [{"experiment_id": identifier, "branch_id": branch, **row}
                                 for row in plan["requirements"]]
                lines += [{"experiment_id": identifier, "branch_id": branch, **row}
                          for row in plan["lines"]]
        print(f"Branch {branch}: recorded 3 model tests and 12 procurement scenarios.", flush=True)
    provenance = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_origin": "SYNTHETIC", "mode": "LIVE_COMPUTE", "seed": 42,
        "forecast_origin": "2025-12-31", "forecast_target": "2026-01-01",
        "inventory_snapshot": "2026-01-01", "branches": branches, "models": list(MODELS),
        "input_files": source_hashes,
        "engine_sha256": file_hash(ROOT / "apps" / "api" / "engine.py"),
        "script_sha256": file_hash(Path(__file__)),
        "runtime_versions": all_forecasts[0]["metadata"]["runtime_versions"],
        "forecast_runs": len(all_forecasts), "procurement_runs": len(all_plans),
        "duration_seconds": round(time.perf_counter() - started, 6),
        "metric_units": {"mae": "portions", "rmse": "portions", "bias": "portions, predicted minus observed",
                         "wape": "fraction; null for zero observed sales", "coverage": "fraction",
                         "crossing_rate": "fraction of raw quantile triplets"},
        "protocol": "28 identical one-step test days; HGB fit frozen before test; previous test sales are legal past lags. Final HGB refit through origin.",
        "interpretation": [
            "Synthetic demonstration; not external validation or measured savings at a real enterprise.",
            "Observed sales are potentially stockout-censored; they are not latent demand.",
            "Baselines have no uncertainty intervals. HGB p10-p90 is an 80% nominal central interval.",
            "Summed marginal p90 is a stress heuristic, not a joint 90% availability guarantee.",
            "Ingredient shortages/excesses retain their kg/L units; unlike units are never summed.",
            "No shipping/tax data exist; purchase costs cover base unit prices times pack quantities only.",
            "Budgets are declared synthetic scenarios. Metrics are measured; no superiority is assumed.",
        ],
    }
    write_csv(output / "metrics.csv", metrics)
    write_csv(output / "forecast_predictions.csv", predictions)
    write_csv(output / "procurement_scenarios.csv", summaries)
    write_csv(output / "procurement_requirements.csv", requirements)
    write_csv(output / "procurement_lines.csv", lines)
    write_json(output / "runs.json", {"forecasts": all_forecasts, "procurement": all_plans})
    write_json(output / "provenance.json", provenance)
    report = [
        "# Қайта өндіру нәтижелері", "",
        "**SYNTHETIC — жасанды деректер.** Бұл нақты кәсіпорынның тиімділігі немесе үнемі туралы дәлел емес.", "",
        f"Нақты есептелді: {len(all_forecasts)} болжам, {len(all_plans)} сатып алу сценарийі. Seed: 42.",
        "Болжам күні: 01.01.2026. Тарих соңы: 31.12.2025. Қойма кесіндісі: 01.01.2026.",
        "Барлық модельге ортақ тест: 04.12.2025–31.12.2025; әр бөлімшеде 336 бақылау.", "",
        "| Бөлімше | Модель | MAE, порция | RMSE, порция | WAPE | Bias, порция | p10–p90 қамту |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in metrics:
        wape = "null" if item["wape"] is None else f"{item['wape'] * 100:.2f}%"
        coverage = "—" if item["coverage"] is None else f"{item['coverage'] * 100:.2f}%"
        report.append(f"| {item['branch_id']} | {item['model']} | {item['mae']:.3f} | {item['rmse']:.3f} | {wape} | {item['bias']:.3f} | {coverage} |")
    report += [
        "", "Bias = болжам − бақыланған сатылым. Нөлге жақын мән бағытталған қатенің аз екенін білдіреді.",
        "p10–p90 номинал қамтуы — 80%; кесте нақты тесттегі эмпирикалық қамтуды көрсетеді.",
        "Базалық модельдерде квантильдер жоқ. Болашақ нақты сатылым, oracle және генератор параметрлері қолданылмайды.", "",
        "Сатып алу сценарийлері: 0 / 75 000 / 200 000 ₸ бюджет, HGB медианасы, p90 stress және жеткізушісіз сценарий.",
        "Әр нәтиженің қаптама бүтіндігі, MOQ, max_packs, бюджет, сақтау сыйымдылығы және сол күнгі жеткізуі қайта тексерілген.",
        "Тапшылық ingredient жолында өз бірлігімен көрсетіледі; кг мен литр қосылмайды. Шешуші мәртебесі бөлек сақталған.", "",
        "Файлдар: metrics.csv, forecast_predictions.csv, procurement_scenarios.csv, procurement_requirements.csv, procurement_lines.csv, runs.json, provenance.json.",
        "Қайта орындау: `python scripts/run_research.py`. Орта нұсқалары, кіріс және код SHA256 мәндері provenance.json ішінде.",
    ]
    (output / "README_KK.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.resolve()), "forecast_runs": len(all_forecasts),
                      "procurement_runs": len(all_plans), "duration_seconds": provenance["duration_seconds"]}), flush=True)
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "research")
    parser.add_argument("--branch", action="append", help="Branch ID; repeat to select multiple branches")
    args = parser.parse_args()
    run(args.data_dir, args.output, args.branch)


if __name__ == "__main__":
    main()
