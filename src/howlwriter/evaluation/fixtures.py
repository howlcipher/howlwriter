"""Benchmark suite definitions and fixture loading utilities."""

from __future__ import annotations

from pathlib import Path
import yaml

from howlwriter.evaluation.models import BenchmarkCase, BenchmarkSuite

DATASET_PATH = Path(__file__).resolve().parent / "dataset" / "cases.yaml"


def load_all_cases(yaml_path: Path | str | None = None) -> list[BenchmarkCase]:
    """Loads and validates all benchmark cases from YAML."""
    path = Path(yaml_path) if yaml_path else DATASET_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Benchmark cases dataset not found: {path}")

    raw_data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, list):
        raise ValueError(f"Expected list of cases in {path}, got {type(raw_data).__name__}")

    cases = []
    for item in raw_data:
        case = BenchmarkCase.from_dict(item)
        cases.append(case)

    return cases


def get_benchmark_suite(name: str = "core", cases_path: Path | str | None = None) -> BenchmarkSuite:
    """Returns a named BenchmarkSuite filtering the full case dataset."""
    all_cases = load_all_cases(cases_path)
    suite_name = name.strip().lower()

    if suite_name == "all":
        return BenchmarkSuite(
            name="all",
            description="Complete suite of 35 diverse benchmark cases across all 11 categories.",
            cases=all_cases,
        )

    if suite_name == "core":
        # Exactly one high-leverage case per category (11 cases)
        core_ids = {
            "academic_privacy_001",
            "tech_raft_paxos_001",
            "doc_webhook_security_001",
            "arg_monolith_microservices_001",
            "prof_postmortem_001",
            "social_career_transition_001",
            "edit_vendor_proposal_001",
            "voice_outage_story_001",
            "synth_password_standards_001",
            "fact_log4shell_cve_001",
            "outline_security_audit_001",
        }
        cases = [c for c in all_cases if c.id in core_ids]
        return BenchmarkSuite(
            name="core",
            description="Core suite of 11 representative benchmark cases spanning all 11 evaluation categories.",
            cases=cases,
        )

    if suite_name == "academic":
        cases = [c for c in all_cases if c.mode == "academic" or "academic" in c.category or "synth" in c.id]
        return BenchmarkSuite(
            name="academic",
            description="Academic research, citation, and source-grounded synthesis cases.",
            cases=cases,
        )

    if suite_name == "technical":
        cases = [c for c in all_cases if c.mode in ("technical", "documentation") or "tech" in c.category]
        return BenchmarkSuite(
            name="technical",
            description="Technical explanation, systems documentation, and engineering architecture cases.",
            cases=cases,
        )

    if suite_name == "rewrite":
        cases = [c for c in all_cases if "rewrite" in c.category or c.input_text]
        return BenchmarkSuite(
            name="rewrite",
            description="Editing, de-slopification, and voice-preserving rewrite cases.",
            cases=cases,
        )

    if suite_name == "professional":
        cases = [c for c in all_cases if c.mode in ("professional", "linkedin")]
        return BenchmarkSuite(
            name="professional",
            description="Executive memos, postmortems, and LinkedIn professional writing cases.",
            cases=cases,
        )

    # Category matching
    matching = [c for c in all_cases if suite_name in c.category.lower() or suite_name in c.tags]
    if matching:
        return BenchmarkSuite(
            name=suite_name,
            description=f"Custom suite matching category '{suite_name}'.",
            cases=matching,
        )

    raise ValueError(f"Unknown benchmark suite '{name}'. Available: all, core, academic, technical, rewrite, professional")
