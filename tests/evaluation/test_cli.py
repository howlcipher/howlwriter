"""Unit tests for the benchmark CLI commands."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from howlwriter.cli.main import main


def test_cli_benchmark_list(capsys):
    exit_code = main(["benchmark", "list"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Available Benchmark Cases" in captured.out
    assert "academic_privacy_001" in captured.out


def test_cli_benchmark_run_deterministic(tmp_path: Path, capsys):
    out_dir = str(tmp_path / "eval_out")
    exit_code = main([
        "benchmark",
        "run",
        "--case",
        "academic_privacy_001",
        "--deterministic-only",
        "--mock-models",
        "--output",
        out_dir,
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "HowlWriter Benchmark Report" in captured.out
    assert (tmp_path / "eval_out" / "benchmark-results.json").is_file()


def test_cli_benchmark_report(tmp_path: Path, capsys):
    # First run a case to generate a results file
    out_dir = str(tmp_path / "eval_out")
    main([
        "benchmark",
        "run",
        "--case",
        "academic_privacy_001",
        "--deterministic-only",
        "--mock-models",
        "--output",
        out_dir,
    ])

    results_json = str(tmp_path / "eval_out" / "benchmark-results.json")
    exit_code = main(["benchmark", "report", "--results-path", results_json])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Executive Summary & Verdicts" in captured.out
