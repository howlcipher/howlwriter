"""Web API routes for empirical benchmark inspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Query

from howlwriter.evaluation.fixtures import load_all_cases

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])
DEFAULT_EVAL_DIR = Path("output/evaluation")


@router.get("/cases")
def list_benchmark_cases(category: str | None = None) -> list[dict[str, Any]]:
    """Lists available evaluation benchmark cases."""
    cases = load_all_cases()
    if category:
        cases = [c for c in cases if category.lower() in c.category.lower()]
    return [c.to_dict() for c in cases]


@router.get("/runs")
def list_benchmark_runs() -> list[dict[str, Any]]:
    """Lists stored benchmark run summaries."""
    results_path = DEFAULT_EVAL_DIR / "benchmark-results.json"
    if not results_path.is_file():
        return []

    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        return [{
            "run_id": data.get("run_id"),
            "suite_name": data.get("suite_name"),
            "timestamp": data.get("timestamp"),
            "total_cases": summary.get("total_cases_evaluated"),
            "systems": summary.get("systems_evaluated"),
            "verdicts": summary.get("verdicts"),
        }]
    except Exception as err:
        return []


@router.get("/runs/{run_id}")
def get_benchmark_run(run_id: str) -> dict[str, Any]:
    """Returns complete details for a benchmark run."""
    results_path = DEFAULT_EVAL_DIR / "benchmark-results.json"
    if not results_path.is_file():
        raise HTTPException(status_code=404, detail="No benchmark runs available.")

    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
        if data.get("run_id") == run_id or run_id == "latest":
            return data
        raise HTTPException(status_code=404, detail=f"Benchmark run '{run_id}' not found.")
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))
