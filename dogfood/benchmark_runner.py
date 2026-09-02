#!/usr/bin/env python3
"""The five Phase 10 benchmarks, one result schema, metrics recomputed on read.

Runs against real providers. Not a pytest suite and not collected by one.

Every arm writes the same envelope -- run id, exact input, configuration,
provider, model, output, timestamp -- so a report figure can always be traced
to the generation that produced it. Metrics are never stored as the runner's
opinion; `metrics.analyze_batch` recomputes them from the stored text, so a
disagreement between a report and its artifacts is impossible rather than
merely discouraged.

Usage:
    python dogfood/benchmark_runner.py structural
    python dogfood/benchmark_runner.py mixed
    python dogfood/benchmark_runner.py outline
    python dogfood/benchmark_runner.py personal
    python dogfood/benchmark_runner.py all
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback
from datetime import datetime, timezone

DOGFOOD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOGFOOD_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(DOGFOOD_DIR))
sys.path.insert(
    0, os.environ.get("HOWLPLANE_ROOT", str(REPO_ROOT.parent / "howlplane"))
)

RESULTS_DIR = Path(
    os.environ.get("HOWLWRITER_BENCH_RESULTS", DOGFOOD_DIR / "milestone_results")
)
VOICE_NAME = os.environ.get("HOWLWRITER_BENCH_VOICE", "william_v2")

# Independence is only real when the reviewer can run somewhere the humanizer
# did not. Both are on PATH here, so the split is the honest configuration.
WRITER_PROVIDER = os.environ.get("HOWLWRITER_BENCH_WRITER", "agy")
HUMANIZER_PROVIDER = os.environ.get("HOWLWRITER_BENCH_HUMANIZER", "agy")
REVIEWER_PROVIDER = os.environ.get("HOWLWRITER_BENCH_REVIEWER", "codex")

os.environ.setdefault("HOWLPLANE_ROLE_WRITING_WRITER", WRITER_PROVIDER)
os.environ.setdefault("HOWLPLANE_ROLE_WRITING_HUMANIZER", HUMANIZER_PROVIDER)
os.environ.setdefault("HOWLPLANE_ROLE_WRITING_FINAL_REVIEWER", REVIEWER_PROVIDER)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(name: str, payload: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {path}")
    return path


def _corpus_features():
    """Training-document feature vectors, for the diversity comparison."""
    from howlwriter.voice.corpus.features import DocumentFeatures
    from howlwriter.voice.corpus.store import VoiceStore

    store = VoiceStore(VOICE_NAME)
    if not store.exists():
        raise RuntimeError(
            f"voice {VOICE_NAME!r} not found. Build it first with "
            f"`howlwriter voice build --name {VOICE_NAME} --source ...`"
        )
    return [
        DocumentFeatures.from_dict(entry["features"])
        for entry in store.load_features().values()
        if entry.get("features")
    ]


def _profile_reference() -> str:
    from howlwriter.voice.corpus.resolve import profile_reference

    return profile_reference(VOICE_NAME)


# --- generation arms -----------------------------------------------------

def _medium_only(text: str) -> dict:
    """Mode rules and no personal voice. The control arm."""
    from howlwriter.config.loader import ConfigLoader
    from howlwriter.domain.document import Document
    from howlwriter.domain.modes import WritingMode
    from howlwriter.humanize.rewriter import ModelHumanizerRewriter

    config = ConfigLoader().load(mode=WritingMode.LINKEDIN)
    config.voice_profile = None
    started = time.time()
    result = ModelHumanizerRewriter().rewrite(
        Document.parse(text, mode=WritingMode.LINKEDIN), config
    )
    return {
        "output": result.document.text,
        "provider": result.provider,
        "model": result.model,
        "duration": round(time.time() - started, 2),
    }


def _full_howlwriter(text: str) -> dict:
    """Mode rules plus the personal voice profile."""
    from howlwriter.config.loader import ConfigLoader
    from howlwriter.domain.document import Document
    from howlwriter.domain.modes import WritingMode
    from howlwriter.humanize.rewriter import ModelHumanizerRewriter

    config = ConfigLoader().load(mode=WritingMode.LINKEDIN)
    config.voice_profile = _profile_reference()
    started = time.time()
    result = ModelHumanizerRewriter().rewrite(
        Document.parse(text, mode=WritingMode.LINKEDIN), config
    )
    return {
        "output": result.document.text,
        "provider": result.provider,
        "model": result.model,
        "duration": round(time.time() - started, 2),
    }


def _run_prompt_suite(prompts: list[dict], arms: dict, label: str) -> dict:
    """Run every prompt through every arm, recording failures as failures."""
    generations: dict[str, list[dict]] = {name: [] for name in arms}
    started = time.time()

    for index, prompt in enumerate(prompts, start=1):
        text = prompt["sparse_text"]
        print(f"[{label}] {index}/{len(prompts)} {prompt['id']}")
        for arm_name, arm in arms.items():
            try:
                produced = arm(text)
                record = {
                    "id": prompt["id"],
                    "prompt": text,
                    "status": "OK",
                    **{k: v for k, v in prompt.items() if k not in ("sparse_text",)},
                    **produced,
                }
            except Exception as exc:                        # noqa: BLE001
                # A failed generation is data. Dropping it would quietly
                # improve every statistic computed from what remains.
                record = {
                    "id": prompt["id"],
                    "prompt": text,
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "output": "",
                }
                print(f"    {arm_name} FAILED: {type(exc).__name__}: {exc}")
            generations[arm_name].append(record)

    return {
        "generations": generations,
        "total_duration_seconds": round(time.time() - started, 2),
    }


def _analyze(generations: dict[str, list[dict]], corpus) -> dict:
    from metrics import analyze_batch

    analysis = {}
    for arm, records in generations.items():
        texts = [r["output"] for r in records if r.get("status") == "OK" and r.get("output")]
        analysis[arm] = analyze_batch(texts, corpus_features=corpus)
        analysis[arm]["attempted"] = len(records)
        analysis[arm]["failed"] = sum(1 for r in records if r.get("status") != "OK")
    return analysis


def _envelope(experiment: str, extra: dict) -> dict:
    return {
        "experiment": experiment,
        "schema": "howlwriter.benchmark/v1",
        "timestamp": _now(),
        "voice": VOICE_NAME,
        "providers": {
            "writer": WRITER_PROVIDER,
            "humanizer": HUMANIZER_PROVIDER,
            "final_reviewer": REVIEWER_PROVIDER,
        },
        **extra,
    }


# --- the five benchmarks -------------------------------------------------

def run_structural() -> dict:
    """10.1 -- a fresh generation of the existing twenty prompts."""
    from dogfood_structural_variance_runner import PROMPTS

    corpus = _corpus_features()
    result = _run_prompt_suite(
        PROMPTS,
        {"medium_only": _medium_only, "full_howlwriter": _full_howlwriter},
        "structural",
    )
    payload = _envelope(
        "structural_variance_v2",
        {
            "prompt_count": len(PROMPTS),
            "total_duration_seconds": result["total_duration_seconds"],
            "generations": result["generations"],
            "analysis": _analyze(result["generations"], corpus),
        },
    )
    _write("structural_variance_v2", payload)
    return payload


def run_mixed() -> dict:
    """10.2 and 10.4 -- register flexibility and first-person preservation."""
    from dogfood_mixed_context_runner import PROMPTS

    corpus = _corpus_features()
    result = _run_prompt_suite(
        PROMPTS,
        {"medium_only": _medium_only, "full_howlwriter": _full_howlwriter},
        "mixed",
    )
    payload = _envelope(
        "mixed_context_v2",
        {
            "prompt_count": len(PROMPTS),
            "total_duration_seconds": result["total_duration_seconds"],
            "generations": result["generations"],
            "analysis": _analyze(result["generations"], corpus),
        },
    )
    _write("mixed_context_v2", payload)
    return payload


def run_outline_progression() -> dict:
    """10.3 -- one idea at five authorship levels.

    The claim under test is that supplying more authorship reduces model
    freedom, so the same idea is submitted five times with progressively more
    of it written by the user, and the outputs are compared for how much the
    model added and how much of the user's wording survived.
    """
    from outline_progression_prompts import LEVELS
    from howlwriter.config.loader import ConfigLoader
    from howlwriter.domain.modes import WritingMode
    from howlwriter.domain.outline import load_outline
    from howlwriter.pipeline.howl import run_howl_pipeline
    from howlwriter.provenance.assemble import finalize

    corpus = _corpus_features()
    records = []
    started = time.time()

    for level in LEVELS:
        print(f"[outline] {level['id']} ({level['expected_freedom']})")
        config = ConfigLoader().load(mode=WritingMode.LINKEDIN)
        config.voice_profile = _profile_reference()
        outline = load_outline(level["outline"])
        entry = {
            "id": level["id"],
            "expected_freedom": level["expected_freedom"],
            "outline": level["outline"],
            "status": "OK",
        }
        try:
            result = run_howl_pipeline(
                None, config, outline=outline,
                writing_mode=WritingMode.LINKEDIN, provenance_level="full",
            )
            provenance = finalize(result.provenance, level="full")
            entry.update(
                {
                    "output": result.final_document.text,
                    "generation_freedom": result.provenance.generation_freedom,
                    "coverage": result.coverage.to_dict(),
                    "contribution": result.provenance.contribution.to_dict(),
                    "provenance": json.loads(provenance.to_json()),
                    "run_id": result.provenance.run_id,
                }
            )
        except Exception as exc:                            # noqa: BLE001
            entry.update(
                {
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-2000:],
                    "output": "",
                }
            )
            print(f"    FAILED: {type(exc).__name__}: {exc}")
        records.append(entry)

    from metrics import analyze_batch

    payload = _envelope(
        "outline_progression",
        {
            "total_duration_seconds": round(time.time() - started, 2),
            "levels": records,
            "analysis": analyze_batch(
                [r["output"] for r in records if r.get("output")],
                corpus_features=corpus,
            ),
        },
    )
    _write("outline_progression", payload)
    return payload


BENCHMARKS = {
    "structural": run_structural,
    "mixed": run_mixed,
    "outline": run_outline_progression,
}


def main(argv: list[str]) -> int:
    which = argv[1] if len(argv) > 1 else "all"
    names = list(BENCHMARKS) if which == "all" else [which]
    for name in names:
        if name not in BENCHMARKS:
            print(f"unknown benchmark {name!r}; choose from {', '.join(BENCHMARKS)} or 'all'")
            return 2
    for name in names:
        print(f"\n=== {name} ===")
        BENCHMARKS[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
