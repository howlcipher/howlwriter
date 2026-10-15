"""`howlwriter evaluate <file>` -- Naturalness and Voice Match, side by side.

    howlwriter evaluate paper.md --mode academic --voice william-academic
    howlwriter evaluate article.md --mode professional --voice william-professional
    howlwriter evaluate document.md --identity william --auto-voice
    howlwriter evaluate original.md --compare revised.md --identity william --auto-voice

Deterministic and local: no model is called and nothing is rewritten. A
score that the evidence does not support is shown as unavailable with the
reason, never as a number.

Exit codes: 0 report produced; 1 error; 3 (--compare) the revision changes
substance (meaning, numbers, citations, or a requirement); 4 (--strict) a
requested score was unavailable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from howlwriter.evaluation.personal import compare_texts, evaluate_text
from howlwriter.voice.corpus.extract import extract

EXIT_SUBSTANCE_CHANGED = 3
EXIT_UNAVAILABLE = 4


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "evaluate",
        help="Score a document's Human Naturalness and Personal Voice Match (calibrated, explainable).",
    )
    parser.add_argument("path", help="Document to evaluate (.md, .txt, .docx, .odt, .html, .pdf).")
    parser.add_argument(
        "--mode",
        default=None,
        help="Writing mode (academic, professional, linkedin, technical, documentation, email).",
    )
    parser.add_argument("--voice", default=None, help="Compare against this named profile.")
    parser.add_argument("--identity", default=None, help="Choose among this identity's profiles.")
    parser.add_argument(
        "--auto-voice",
        action="store_true",
        help="Pick the profile from the document's content (uses preferred_identity if no --identity).",
    )
    parser.add_argument(
        "--compare",
        metavar="REVISED",
        default=None,
        help="Evaluate a revision against PATH and check it preserved substance.",
    )
    parser.add_argument(
        "--requirements",
        metavar="FILE",
        default=None,
        help="YAML with min_words, max_words, required_terms, required_sections (for --compare).",
    )
    parser.add_argument(
        "--naturalness-reference",
        metavar="DIR",
        default=None,
        help="Calibrate Naturalness against a folder of human writing instead of the identity's.",
    )
    parser.add_argument("--strict", action="store_true", help="Exit 4 when a score is unavailable.")
    parser.add_argument("--json", action="store_true", help="Emit the full report as JSON.")
    parser.set_defaults(handler=run)
    return parser


def _read(path: str) -> str:
    target = Path(path).expanduser()
    if target.suffix.lower() in (".md", ".txt", ".markdown", ".text"):
        return target.read_text(encoding="utf-8")
    result = extract(target)
    if not result.ok:
        raise ValueError(f"could not read {path}: {result.reason}")
    return result.text


def _score_line(label: str, block: dict, extra: str = "") -> str:
    if block["status"] == "SCORED":
        step = f"  (±{block['resolution']:.0f}-point steps)" if block.get("resolution") else ""
        return f"{label:22} {block['score']:5.1f} / 100   {extra}{block['confidence']}{step}"
    return f"{label:22}   n/a         {block['reason']}"


def render(report: dict, display_name: str = "") -> str:
    lines: list[str] = []
    selection = report["profile_selection"]
    lines.append(f"Evaluation ({report['context']} context, {report['words']} words)")
    lines.append(f"Profile: {selection['voice'] or 'none'} -- {selection['reason']}")
    lines.append("")
    natural = report["naturalness"]
    voice = report["voice_match"]
    voice_label = f"{display_name} Voice Match" if display_name else "Personal Voice Match"
    lines.append(_score_line("Human Naturalness", natural))
    lines.append(_score_line(voice_label, voice, f"{voice['band']}  " if voice.get("band") else ""))
    if natural["status"] == "SCORED":
        lines.append(f"  Naturalness basis: {natural['confidence_basis']}")
    if voice["status"] == "SCORED":
        lines.append(f"  Voice Match basis: {voice['confidence_basis']}")
        if voice.get("comparison_share_as_close") is not None:
            lines.append(
                "  Comparison-author documents at least this close: "
                f"{voice['comparison_share_as_close']:.0f}%"
            )

    if natural["dimensions"]:
        lines += [
            "",
            "Naturalness by dimension (100 = at least as natural as every reference document)",
        ]
        for dim in natural["dimensions"]:
            score = "  n/a" if dim["score"] is None else f"{dim['score']:5.0f}"
            lines.append(f"  {dim['label']:32} {score}   value {dim['value']}")
    if natural["weaknesses"]:
        lines += ["", "Weaknesses"] + [f"  - {w}" for w in natural["weaknesses"]]
    if natural["strengths"]:
        lines += ["", "Strengths"] + [f"  - {s}" for s in natural["strengths"][:6]]
    if natural["locations"]:
        lines += ["", "Where"]
        for loc in natural["locations"][:12]:
            where = (
                f"paragraph {loc['paragraph_index'] + 1}"
                if loc["paragraph_index"] is not None
                else "document"
            )
            lines.append(
                f"  - {where}: {loc['message']}"
                + (f' -- "{loc["excerpt"]}"' if loc["excerpt"] else "")
            )
    if natural["suggestions"]:
        lines += ["", "Suggestions (nothing has been rewritten)"] + [
            f"  - {s}" for s in dict.fromkeys(natural["suggestions"])
        ]

    if voice["dimensions"]:
        lines += ["", "Voice similarity by dimension (robust distance; lower is closer)"]
        for dim in voice["dimensions"]:
            typical = (
                f"  (typical {dim['typical_distance']})"
                if dim.get("typical_distance") is not None
                else ""
            )
            lines.append(f"  {dim['label']:32} {dim['distance']:5.2f}{typical}")
    if voice["differences"]:
        lines += ["", "Significant differences from the profile"] + [
            f"  - {d}" for d in voice["differences"]
        ]
    drift = report["drift"]
    if drift.get("findings"):
        lines += ["", "Voice drift"]
        for finding in drift["findings"][:12]:
            lines.append(
                f"  - {finding['span'].capitalize()} {finding['message']} "
                f"[{finding['severity']}, {finding['confidence']} confidence]"
            )
        lines.append(f"  {drift.get('note', '')}")
    elif drift.get("status") == "UNAVAILABLE":
        lines += ["", f"Voice drift: unavailable ({drift.get('reason')})"]
    lines += ["", natural["disclaimer"], voice["disclaimer"]]
    return "\n".join(lines)


def render_comparison(report: dict, display_name: str = "") -> str:
    lines = [
        f"Revision comparison ({report['context']} context)",
        f"Profile: {report['profile_selection']['voice'] or 'none'}",
        "",
    ]

    def row(label: str, block: dict) -> str:
        fmt = lambda v: "  n/a" if v is None else f"{v:5.1f}"  # noqa: E731
        delta = "" if block["delta"] is None else f"{block['delta']:+.1f}"
        return f"  {label:22} {fmt(block['original'])} -> {fmt(block['revised'])}   {delta}"

    lines.append(row("Human Naturalness", report["naturalness"]))
    lines.append(
        row(f"{display_name} Voice Match" if display_name else "Voice Match", report["voice_match"])
    )
    if report["changed_dimensions"]:
        lines += ["", "Changed dimensions"]
        for change in report["changed_dimensions"]:
            detail = (
                change.get("delta")
                if change["family"] == "naturalness"
                else change.get("direction")
            )
            lines.append(f"  - {change['label']} ({change['family']}): {detail}")
    lines += [
        "",
        "Integrity",
        f"  Meaning preservation: {report['meaning_preservation']['status']}",
        f"  Factual integrity:    {report['factual_integrity']['status']}",
        f"  Citations:            {report['citations']['status']}",
        f"  Requirements:         {report['requirements']['status']}",
    ]
    for diff in report["meaning_preservation"]["differences"][:8]:
        lines.append(f"    - {diff['kind']}: {diff['description']}")
    for finding in report["factual_integrity"]["findings"][:8]:
        lines.append(f"    - {finding['code']}: {finding['message']}")
    if report["remaining_drift"]:
        lines += ["", f"Remaining drift findings in the revision: {len(report['remaining_drift'])}"]
    lines += ["", f"Verdict: {report['verdict']}"]
    for problem in report["integrity_problems"]:
        lines.append(f"  - {problem}")
    lines += ["", report["policy"]]
    return "\n".join(lines)


def _display_name(report: dict) -> str:
    identity = (report.get("profile_selection") or {}).get("identity")
    if not identity:
        return ""
    from howlwriter.voice.identity.store import IdentityStore

    name = IdentityStore(identity).load_config().display_name
    return name.split()[0] if name else identity


def run(args: argparse.Namespace) -> int:
    options = dict(
        mode=args.mode,
        voice=args.voice,
        identity=args.identity,
        auto_voice=args.auto_voice,
        naturalness_reference=(
            Path(args.naturalness_reference) if args.naturalness_reference else None
        ),
    )
    text = _read(args.path)
    if args.compare:
        requirements = None
        if args.requirements:
            requirements = yaml.safe_load(Path(args.requirements).read_text(encoding="utf-8")) or {}
        report = compare_texts(text, _read(args.compare), requirements=requirements, **options)
        print(
            json.dumps(report, indent=2)
            if args.json
            else render_comparison(report, _display_name(report))
        )
        if report["verdict"] == "REVISION_CHANGES_SUBSTANCE":
            return EXIT_SUBSTANCE_CHANGED
        unavailable = (
            report["naturalness"]["revised"] is None or report["voice_match"]["revised"] is None
        )
    else:
        report = evaluate_text(text, **options)
        print(json.dumps(report, indent=2) if args.json else render(report, _display_name(report)))
        unavailable = (
            report["naturalness"]["status"] != "SCORED"
            or report["voice_match"]["status"] != "SCORED"
        )
    return EXIT_UNAVAILABLE if (args.strict and unavailable) else 0
