#!/usr/bin/env python3
"""Run the mandatory three-arm structural-realization ablation.

The arms differ in exactly one layer:

* medium_only: LinkedIn mode and humanizer rules, no personal voice.
* shared_band: the personal voice rendered as the previous corpus-wide bands.
* per_piece: the same personal voice plus one seeded empirical realization.

Every response is checkpointed immediately. Raw outputs are also written as
individual Markdown files so an interrupted or partially failed run remains
auditable and no successful generation is silently discarded.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

DOGFOOD_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DOGFOOD_DIR))
sys.path.insert(0, str(DOGFOOD_DIR.parent / "src"))

from dogfood_structural_variance_runner import PROMPTS  # noqa: E402
from metrics import analyze_batch, grouped_variation  # noqa: E402

from howlwriter.config.defaults import default_config  # noqa: E402
from howlwriter.domain.document import Document  # noqa: E402
from howlwriter.domain.generation_provenance import redact  # noqa: E402
from howlwriter.domain.modes import WritingMode  # noqa: E402
from howlwriter.humanize.rewriter import (  # noqa: E402
    ModelHumanizerRewriter,
    _load_voice_profile,
)
from howlwriter.integration.howlplane_bridge import (  # noqa: E402
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from howlwriter.voice.corpus.features import DocumentFeatures  # noqa: E402
from howlwriter.voice.corpus.store import VoiceStore  # noqa: E402
from howlwriter.voice.realization import derive_structural_realization  # noqa: E402
from src.control_plane.role_binding import (  # noqa: E402
    RoleBinding,
    RoleBindingRegistry,
    RoleDispatcher,
)

ARMS = ("medium_only", "shared_band", "per_piece")
SCHEMA = "howlwriter.structural_ablation/v1"


def _configure_provider(provider: str) -> None:
    """Bind every arm to the same provider through the same dispatcher."""
    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(domain="writing", role="humanizer", provider=provider)
    )
    set_howlplane_bridge(
        HowlPlaneWritingBridge(
            dispatcher=RoleDispatcher(binding_registry=registry),
            registry=registry,
        )
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _raw_path(output_dir: Path, arm: str, prompt_id: str, repeat: int) -> Path:
    return output_dir / "raw" / arm / f"{prompt_id}_r{repeat:02d}.md"


def _write_raw(
    output_dir: Path,
    arm: str,
    prompt_id: str,
    repeat: int,
    output: str,
) -> str:
    path = _raw_path(output_dir, arm, prompt_id, repeat)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output.rstrip() + "\n", encoding="utf-8")
    return str(path.relative_to(output_dir))


def _generate(
    *,
    arm: str,
    prompt_text: str,
    profile_path: str,
    target_words: int,
    seed: int,
) -> dict[str, Any]:
    config = default_config()
    config.voice_profile = None if arm == "medium_only" else profile_path
    document = Document.parse(
        prompt_text,
        title="structural_ablation_prompt",
        mode=WritingMode.LINKEDIN,
    )

    realization = None
    if arm == "per_piece":
        profile = _load_voice_profile(profile_path)
        if profile is None:
            raise RuntimeError("local voice profile could not be loaded")
        realization = derive_structural_realization(
            profile=profile,
            mode=WritingMode.LINKEDIN,
            target_words=target_words,
            input_text=prompt_text,
            seed=seed,
            freedom="HIGH",
        )

    result = ModelHumanizerRewriter().rewrite(
        document,
        config,
        realization=realization,
    )
    return {
        "output": result.document.text.strip(),
        "provider": result.provider,
        "model": result.model,
        "provider_duration_seconds": result.duration_seconds,
        "structural_realization": (
            realization.to_dict() if realization is not None else None
        ),
    }


def _eligible_corpus(
    store: VoiceStore,
) -> tuple[list[DocumentFeatures], list[DocumentFeatures]]:
    sources = store.load_sources()
    cached = store.load_features()
    eligible = {
        key
        for key, source in sources.items()
        if source.split == "train"
        and source.inclusion in ("include", "include_low_weight")
    }
    ordered_keys = sorted(eligible)
    corpus = [
        DocumentFeatures.from_dict(cached[key]["features"])
        for key in ordered_keys
        if key in cached and isinstance(cached[key].get("features"), dict)
    ]
    professional = [
        DocumentFeatures.from_dict(cached[key]["features"])
        for key in ordered_keys
        if key in cached
        and sources[key].context == "professional"
        and isinstance(cached[key].get("features"), dict)
    ]
    return corpus, professional


def _new_payload(
    *,
    provider: str,
    repeats: int,
    target_words: int,
    seed_base: int,
    corpus: list[DocumentFeatures],
    professional: list[DocumentFeatures],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "experiment": "Per-Piece Structural Realization A/B/C",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "total_prompts": len(PROMPTS),
        "repeats": repeats,
        "target_words": target_words,
        "seed_base": seed_base,
        "provider_configuration": {
            "role": "writing:humanizer",
            "provider": provider,
            "same_pipeline_for_all_arms": True,
            "model": "PROVIDER_DID_NOT_REPORT_UNLESS_RECORDED_PER_CALL",
        },
        "voice": "local_profile",
        "corpus_evidence": {
            "eligible_training_vectors": len(corpus),
            "professional_training_vectors": len(professional),
            "raw_text_persisted": False,
            "source_identity_persisted": False,
        },
        # Numeric/categorical structural measurements make report verification
        # self-contained without persisting the private profile name, paths, or
        # source keys. Structural statistics are the permitted evidence here.
        "structural_evidence": {
            "training_feature_vectors": [item.to_dict() for item in corpus],
            "professional_feature_vectors": [item.to_dict() for item in professional],
        },
        "arm_definitions": {
            "medium_only": "mode rules; no personal voice profile",
            "shared_band": "mode rules plus prior corpus-wide shared-band voice",
            "per_piece": "mode rules plus seeded joint empirical structural anchor",
        },
        "generations": {arm: [] for arm in ARMS},
        "analysis": {},
    }


def _record_exists(
    payload: dict[str, Any], arm: str, prompt_id: str, repeat: int
) -> bool:
    return any(
        record.get("id") == prompt_id and record.get("repeat") == repeat
        for record in payload["generations"][arm]
    )


def _refresh_analysis(
    payload: dict[str, Any],
    corpus: list[DocumentFeatures],
    professional: list[DocumentFeatures],
) -> None:
    for arm in ARMS:
        records = payload["generations"][arm]
        texts = [
            record["output"]
            for record in records
            if record.get("status") == "OK" and record.get("output")
        ]
        analysis = analyze_batch(
            texts,
            corpus_features=corpus,
            context_features=professional,
        )
        analysis["failed"] = sum(
            1 for record in records if record.get("status") == "ERROR"
        )
        analysis["variation"] = grouped_variation(records)
        payload["analysis"][arm] = analysis
    converged = {
        arm: len(
            payload["analysis"][arm]
            .get("diversity", {})
            .get("converged_dimensions", [])
        )
        for arm in ARMS
    }
    payload["central_success_test"] = {
        "criterion": (
            "per_piece converged_dimensions is strictly lower than both "
            "medium_only and shared_band"
        ),
        "converged_dimensions": converged,
        "passed": (
            converged["per_piece"] < converged["medium_only"]
            and converged["per_piece"] < converged["shared_band"]
        ),
    }


def _validate_resume(
    payload: dict[str, Any],
    *,
    provider: str,
    repeats: int,
    target_words: int,
    seed_base: int,
) -> None:
    expected = {
        "schema": SCHEMA,
        "repeats": repeats,
        "target_words": target_words,
        "seed_base": seed_base,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(
                f"cannot resume: stored {key}={payload.get(key)!r}, "
                f"requested {value!r}"
            )
    stored_provider = payload.get("provider_configuration", {}).get("provider")
    if stored_provider != provider:
        raise ValueError(
            f"cannot resume: stored provider={stored_provider!r}, "
            f"requested {provider!r}"
        )


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).expanduser().resolve()
    report_path = output_dir / "per_piece_ablation.json"
    store = VoiceStore(args.voice)
    if not store.exists():
        raise RuntimeError("requested local voice profile does not exist")

    profile_path = str(store.directory / "profile.json")
    corpus, professional = _eligible_corpus(store)
    if len(corpus) < 2:
        raise RuntimeError("fewer than two eligible training structural vectors")

    _configure_provider(args.provider)
    if args.resume and report_path.is_file():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        _validate_resume(
            payload,
            provider=args.provider,
            repeats=args.repeats,
            target_words=args.target_words,
            seed_base=args.seed_base,
        )
    else:
        payload = _new_payload(
            provider=args.provider,
            repeats=args.repeats,
            target_words=args.target_words,
            seed_base=args.seed_base,
            corpus=corpus,
            professional=professional,
        )

    started = time.monotonic()
    total = len(PROMPTS) * args.repeats * len(ARMS)
    completed = sum(len(payload["generations"][arm]) for arm in ARMS)

    for repeat in range(1, args.repeats + 1):
        for prompt_index, item in enumerate(PROMPTS, 1):
            # Rotate order to avoid assigning a provider warm-up/time trend to
            # one arm throughout the campaign.
            offset = (prompt_index + repeat) % len(ARMS)
            ordered_arms = ARMS[offset:] + ARMS[:offset]
            for arm in ordered_arms:
                if _record_exists(payload, arm, item["id"], repeat):
                    continue
                completed += 1
                seed = args.seed_base + repeat * 10_000 + prompt_index
                print(
                    f"[{completed:03d}/{total:03d}] {arm:12s} "
                    f"{item['id']} repeat={repeat}",
                    flush=True,
                )
                call_started = time.monotonic()
                record: dict[str, Any] = {
                    "id": item["id"],
                    "category": item["category"],
                    "prompt": item["sparse_text"],
                    "repeat": repeat,
                    "seed": seed if arm == "per_piece" else None,
                }
                try:
                    generated = _generate(
                        arm=arm,
                        prompt_text=item["sparse_text"],
                        profile_path=profile_path,
                        target_words=args.target_words,
                        seed=seed,
                    )
                    record.update(generated)
                    record["status"] = "OK"
                    record["raw_artifact"] = _write_raw(
                        output_dir,
                        arm,
                        item["id"],
                        repeat,
                        record["output"],
                    )
                except Exception as error:
                    record.update(
                        {
                            "status": "ERROR",
                            "output": "",
                            "error": redact(str(error), mask_paths=True),
                            "structural_realization": None,
                        }
                    )
                    print(f"  ERROR: {record['error']}", flush=True)
                record["wall_duration_seconds"] = round(
                    time.monotonic() - call_started, 3
                )
                payload["generations"][arm].append(record)
                _refresh_analysis(payload, corpus, professional)
                payload["elapsed_seconds"] = round(
                    time.monotonic() - started, 3
                )
                _atomic_json(report_path, payload)

    payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    payload["elapsed_seconds"] = round(time.monotonic() - started, 3)
    _refresh_analysis(payload, corpus, professional)
    _atomic_json(report_path, payload)
    failures = sum(
        analysis.get("failed", 0) for analysis in payload["analysis"].values()
    )
    print(f"report: {report_path}", flush=True)
    print(f"failures: {failures}", flush=True)
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_voice = os.environ.get("HOWLWRITER_REVIEW_VOICE")
    parser.add_argument(
        "--voice",
        default=default_voice,
        required=default_voice is None,
        help=(
            "local voice registry name (or set HOWLWRITER_REVIEW_VOICE); "
            "the name is never written to the benchmark artifact"
        ),
    )
    parser.add_argument("--provider", default="agy")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--target-words", type=int, default=200)
    parser.add_argument("--seed-base", type=int, default=20260902)
    parser.add_argument(
        "--output-dir",
        default=str(
            Path("/var/tmp")
            / (
                "howlwriter-per-piece-ablation-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            )
        ),
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.target_words < 1:
        parser.error("--target-words must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
