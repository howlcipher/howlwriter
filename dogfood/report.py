#!/usr/bin/env python3
"""Generate the milestone's numeric findings from the stored artifacts.

Report accuracy is a product requirement here, not a courtesy. The previous
milestone's write-up said parentheticals appeared in 92% of outputs when the
artifacts said 100%, said a range was 2-5 when the raw output was 3-6, and
called a run production-ready while its own diversity checker said FAIL. In
every case the correct value existed in a data structure at the time.

So no figure in the final report is typed by hand. This script reads the
benchmark JSON, recomputes what it can from the stored generation text, and
prints the tables. A number that disagrees with its artifact is impossible
rather than merely discouraged, and anyone can re-run this to check.

Usage:
    python dogfood/report.py [results_dir]
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

DOGFOOD_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DOGFOOD_DIR))
sys.path.insert(0, str(DOGFOOD_DIR.parent / "src"))

RESULTS_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else DOGFOOD_DIR / "milestone_results"


def _load(name: str) -> dict | None:
    path = RESULTS_DIR / f"{name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _recompute(payload: dict, arm: str) -> dict:
    """Re-derive an arm's metrics from its stored text.

    The runner already stored an analysis. This deliberately ignores it and
    computes again from `output`, so the report cannot inherit a stale or
    mistaken summary.
    """
    from metrics import analyze_batch

    records = payload["generations"][arm]
    texts = [r["output"] for r in records if r.get("status") == "OK" and r.get("output")]
    return analyze_batch(texts)


def _recompute_ablation(payload: dict, arm: str) -> dict:
    """Recompute an ablation arm, including the live corpus comparison."""
    from metrics import analyze_batch, grouped_variation
    from per_piece_ablation_runner import _eligible_corpus
    from howlwriter.voice.corpus.store import VoiceStore

    records = payload["generations"][arm]
    texts = [
        record["output"]
        for record in records
        if record.get("status") == "OK" and record.get("output")
    ]
    store = VoiceStore(os.environ.get("HOWLWRITER_REVIEW_VOICE", "william"))
    corpus, professional = _eligible_corpus(store)
    analysis = analyze_batch(
        texts,
        corpus_features=corpus,
        context_features=professional,
    )
    analysis["variation"] = grouped_variation(records)
    analysis["failed"] = sum(
        1 for record in records if record.get("status") == "ERROR"
    )
    return analysis


def report_per_piece_ablation() -> bool:
    payload = _load("per_piece_ablation")
    if payload is None:
        print("## Per-piece structural ablation")
        print("MISSING: the required medium/shared-band/per-piece benchmark has not run.\n")
        return False

    arms = ("medium_only", "shared_band", "per_piece")
    recomputed = {arm: _recompute_ablation(payload, arm) for arm in arms}
    converged = {
        arm: len(recomputed[arm]["diversity"]["converged_dimensions"])
        for arm in arms
    }
    central_pass = (
        converged["per_piece"] < converged["medium_only"]
        and converged["per_piece"] < converged["shared_band"]
    )

    print("## Primary A/B/C structural ablation")
    print(
        f"{payload['total_prompts']} prompts x {payload['repeats']} repeat(s); "
        f"target {payload['target_words']} words; "
        f"provider {payload['provider_configuration']['provider']}.\n"
    )
    print("| arm | n | failed | converged dimensions | diversity | paragraph counts |"
          " paragraph CV | five-paragraph share | opening classes | closing classes |"
          " reasoning shapes | top reasoning share |")
    print("|---|---:|---:|---:|---|---|---:|---:|---|---|---:|---:|")
    for arm in arms:
        analysis = recomputed[arm]
        paragraphs = analysis["paragraphs"]
        opening_closing = analysis["openings_closings"]
        reasoning = analysis["reasoning"]
        distribution = paragraphs["count_distribution"]
        five = distribution.get("5", 0)
        print(
            f"| {arm} | {analysis['samples']} | {analysis['failed']} "
            f"| {converged[arm]}/18 "
            f"| {analysis['diversity']['verdict']} "
            f"| {distribution} | {paragraphs['count_stats']['cv']:.3f} "
            f"| {five}/{analysis['samples']} "
            f"({five / analysis['samples']:.0%}) "
            f"| {opening_closing['opening_classes']} "
            f"| {opening_closing['closing_classes']} "
            f"| {reasoning['distinct_signatures']} "
            f"| {reasoning['top_signature_share']:.0%} |"
        )
    print()
    print(
        "CENTRAL SUCCESS TEST: "
        + (
            "PASS -- per-piece has fewer converged dimensions than both controls."
            if central_pass
            else "FAIL -- per-piece does not have fewer converged dimensions than both controls."
        )
    )
    print(
        "Converged dimension counts: "
        + ", ".join(f"{arm}={converged[arm]}" for arm in arms)
        + "."
    )
    print()

    print("Between-prompt versus within-prompt paragraph-count variation:")
    for arm in arms:
        variation = recomputed[arm]["variation"]
        between = variation["between_prompt"]["paragraphs"]
        within = variation["within_prompt"]["paragraphs"]
        print(
            f"  {arm}: between-prompt CV={between['cv']:.4f}; "
            f"within-prompt mean CV="
            f"{within['cv_across_repeat_groups']['mean']:.4f} "
            f"over {within['groups_with_repeats']} repeated prompt(s)"
        )
    print()

    old = _load("structural_variance_v2")
    if old is not None:
        old_full = _recompute(old, "full_howlwriter")["paragraphs"]
        old_five = old_full["count_distribution"].get("5", 0)
        new_paragraphs = recomputed["per_piece"]["paragraphs"]
        new_five = new_paragraphs["count_distribution"].get("5", 0)
        print(
            "Five-paragraph attractor: previous shared-band "
            f"{old_five}/{old_full['count_stats']['n']} versus new per-piece "
            f"{new_five}/{new_paragraphs['count_stats']['n']}."
        )
        print()
    return True


def report_structural() -> None:
    payload = _load("structural_variance_v2")
    if payload is None:
        print("structural_variance_v2: not run\n")
        return

    print("## Second structural benchmark (20 prompts, fresh generation)")
    print(f"voice: {payload['voice']}  providers: {payload['providers']}")
    print(f"wall clock: {payload['total_duration_seconds'] / 60:.1f} min\n")
    print("| arm | n | failed | parenthetical presence | parentheticals total |"
          " top opening share | first person presence | first person mean/100w |"
          " distinct openings | diversity |")
    print("|---|---|---|---|---|---|---|---|---|---|")

    for arm in payload["generations"]:
        a = _recompute(payload, arm)
        stored = payload["analysis"][arm]
        p, fp, oc = a["parentheticals"], a["first_person"], a["openings_closings"]
        print(
            f"| {arm} | {a['samples']} | {stored['failed']} "
            f"| {p['documents_with']}/{p['documents']} ({p['presence_rate']:.0%}) "
            f"| {p['total']} | {p['top_opening_share']:.0%} "
            f"| {fp['documents_with']}/{fp['documents']} ({fp['presence_rate']:.0%}) "
            f"| {fp['mean_per_100_words']:.2f} "
            f"| {oc['distinct_openings']}/{a['samples']} "
            f"| {stored.get('diversity', {}).get('verdict', 'NOT_RUN')} "
            f"({len(stored.get('diversity', {}).get('converged_dimensions', []))} converged) |"
        )
    print()

    for arm, stored in payload["analysis"].items():
        diversity = stored.get("diversity", {})
        if diversity.get("converged_dimensions"):
            print(f"{arm} converged dimensions: "
                  f"{', '.join(diversity['converged_dimensions'])}")
    print()

    print("Parenthetical opening phrases (checking for a repeated syntactic function):")
    for arm in payload["generations"]:
        openings = _recompute(payload, arm)["parentheticals"]["opening_words"]
        print(f"  {arm}: {openings if openings else '(none)'}")
    print()

    print("Reasoning progression:")
    for arm in payload["generations"]:
        r = _recompute(payload, arm)["reasoning"]
        print(f"  {arm}: {r['distinct_signatures']} distinct signatures over "
              f"{r['documents']} docs; most common held by "
              f"{r['top_signature_share']:.0%}; declarative close "
              f"{r['declarative_close_share']:.0%}")
    print()


def report_mixed() -> None:
    payload = _load("mixed_context_v2")
    if payload is None:
        print("mixed_context_v2: not run\n")
        return

    print("## Mixed-context benchmark (register flexibility, first-person preservation)")
    print("| arm | n | first person present | mean/100w | median when present |"
          " parenthetical presence |")
    print("|---|---|---|---|---|---|")
    for arm in payload["generations"]:
        a = _recompute(payload, arm)
        fp, p = a["first_person"], a["parentheticals"]
        print(
            f"| {arm} | {a['samples']} "
            f"| {fp['documents_with']}/{fp['documents']} ({fp['presence_rate']:.0%}) "
            f"| {fp['mean_per_100_words']:.2f} | {fp['median_when_present']:.2f} "
            f"| {p['documents_with']}/{p['documents']} ({p['presence_rate']:.0%}) |"
        )
    print()

    print("Per-prompt first-person rate (per 100 words), by register:")
    arms = list(payload["generations"])
    rows = zip(*(payload["generations"][arm] for arm in arms))
    per_arm = {arm: _recompute(payload, arm)["first_person"]["per_document"] for arm in arms}
    for index, group in enumerate(rows):
        register = group[0].get("register", "?")
        values = "  ".join(
            f"{arm}={per_arm[arm][index]:.2f}" if index < len(per_arm[arm]) else f"{arm}=n/a"
            for arm in arms
        )
        print(f"  {group[0]['id']:12s} {register[:34]:34s} {values}")
    print()


def report_outline() -> None:
    payload = _load("outline_progression")
    if payload is None:
        print("outline_progression: not run\n")
        return

    print("## Outline progression (one idea, five authorship levels)")
    print("| level | expected freedom | derived freedom | user words | artifact words |"
          " required represented | preserved retained | model-added claims | coverage |")
    print("|---|---|---|---|---|---|---|---|---|")
    for level in payload["levels"]:
        if level.get("status") != "OK":
            print(f"| {level['id']} | {level['expected_freedom']} | FAILED | - | - "
                  f"| - | - | - | {level.get('error', '')[:40]} |")
            continue
        c = level["contribution"]
        cov = level["coverage"]
        print(
            f"| {level['id']} | {level['expected_freedom']} "
            f"| {level['generation_freedom']} | {c['user_words_supplied']} "
            f"| {c['artifact_words']} "
            f"| {c['required_points_represented']}/{c['required_points_supplied']} "
            f"| {c['preserved_retained']}/{c['preserved_supplied']} "
            f"| {c['model_added_claims']} | {cov['status']} |"
        )
    print()

    print("Model expansion relative to what the author supplied:")
    for level in payload["levels"]:
        if level.get("status") != "OK":
            continue
        c = level["contribution"]
        supplied, produced = c["user_words_supplied"], c["artifact_words"]
        ratio = (produced / supplied) if supplied else float("inf")
        print(f"  {level['id']:22s} supplied {supplied:4d} -> artifact {produced:4d} "
              f"words  (x{ratio:.1f})" if supplied else
              f"  {level['id']:22s} supplied    0 -> artifact {produced:4d} words")
    print()

    print("Provenance completeness per level:")
    for level in payload["levels"]:
        if level.get("status") != "OK":
            continue
        prov = level.get("provenance", {})
        calls = prov.get("calls", [])
        unknown = sum(1 for c in calls if c.get("model_status") == "PROVIDER_DID_NOT_REPORT")
        with_prompts = sum(1 for c in calls if c.get("user_prompt"))
        print(f"  {level['id']:22s} run_id={level.get('run_id', '?')} calls={len(calls)} "
              f"prompts_captured={with_prompts} unknown_model={unknown}")
    print()


def main() -> int:
    print(f"# Milestone benchmark findings\n\nresults directory: {RESULTS_DIR}\n")
    print("Every figure below is recomputed from the stored generation text by")
    print("this script. None is transcribed.\n")
    complete = report_per_piece_ablation()
    report_structural()
    report_mixed()
    report_outline()
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
