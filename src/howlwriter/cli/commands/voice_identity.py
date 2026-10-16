"""`howlwriter voice scan|review|build-identity|sync|status|chat-import`.

The identity workflow on top of the existing voice commands:

    howlwriter voice scan --identity william --source "/path/to/cloud drive"
    howlwriter voice review --identity william
    howlwriter voice build-identity --identity william --profiles academic,professional
    howlwriter voice sync --identity william
    howlwriter voice status --identity william

Output is counts and reasons by default. File names appear only in the
review workflow, where deciding about a specific document requires them, and
document text appears only behind an explicit `--preview` for one document.

Exit codes: 0 success; 1 error; 2 mount unavailable (nothing changed);
3 completed but a profile could not be built (insufficient or refused).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from howlwriter.voice.identity import chat, review
from howlwriter.voice.identity.classify import AUTHORSHIP_STATES, CATEGORIES
from howlwriter.voice.identity.profiles import build_identity
from howlwriter.voice.identity.scanner import MountUnavailableError, scan
from howlwriter.voice.identity.store import IdentityStore

EXIT_MOUNT_UNAVAILABLE = 2
EXIT_PROFILE_NOT_BUILT = 3


def _identity(args: argparse.Namespace) -> str:
    if getattr(args, "identity", None):
        return args.identity
    from howlwriter.evaluation.personal import load_preferences

    preferred = load_preferences().get("preferred_identity")
    if preferred:
        return str(preferred)
    raise ValueError(
        "no identity given; pass --identity NAME or set preferred_identity in "
        "~/.howlwriter/preferences.yaml"
    )


def add_identity_subparsers(voice_subparsers: argparse._SubParsersAction) -> None:
    scan_parser = voice_subparsers.add_parser(
        "scan",
        help="Inventory a mounted drive (read-only) into an identity's private ledger.",
    )
    scan_parser.add_argument(
        "--identity", help="Identity to scan for (default: preferred_identity)."
    )
    scan_parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        metavar="PATH",
        help="Source root (first scan; remembered afterwards).",
    )
    scan_parser.add_argument(
        "--exclude",
        dest="exclusions",
        action="append",
        metavar="DIRNAME",
        default=[],
        help="Additional directory name never to enter (matched per path component, "
        "case-insensitively, at every depth).",
    )
    scan_parser.add_argument(
        "--recursive",
        action="store_true",
        default=True,
        help="Recursive (always on; accepted for clarity).",
    )
    scan_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-read every file even if unchanged since the last scan.",
    )
    scan_parser.add_argument(
        "--no-perturbations",
        dest="perturbations",
        action="store_false",
        help="Skip the mechanical-control measurements (faster scan).",
    )
    scan_parser.add_argument(
        "--google-api",
        action="store_true",
        help="Also read native Google Docs the mount cannot supply, through the Drive API with a "
        "read-only token (run `voice google-auth` once first). Processed locally only.",
    )
    scan_parser.add_argument("--json", action="store_true", help="Emit the scan report as JSON.")
    scan_parser.set_defaults(handler=run_scan)

    auth_parser = voice_subparsers.add_parser(
        "google-auth",
        help="Authorize the optional read-only Drive API fallback (one time, interactive).",
    )
    auth_parser.set_defaults(handler=run_google_auth)

    review_parser = voice_subparsers.add_parser(
        "review",
        help="Review and attest authorship of documents that would affect a profile.",
    )
    review_parser.add_argument("--identity")
    review_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Step through pending documents and answer for each.",
    )
    review_parser.add_argument(
        "--apply", metavar="FILE", help="Apply decisions from an edited review_queue.yaml."
    )
    review_parser.add_argument(
        "--set",
        nargs=2,
        metavar=("DOC_ID", "AUTHORSHIP"),
        help="Attest one document. AUTHORSHIP: "
        + ", ".join(AUTHORSHIP_STATES)
        + " (or h/l/m/a/t/u).",
    )
    review_parser.add_argument(
        "--category",
        default="",
        choices=["", *CATEGORIES],
        help="With --set: correct the document's category.",
    )
    review_parser.add_argument(
        "--context",
        default="",
        choices=["", "academic", "professional", "general", "social"],
        help="With --set: route the document to this context's profile.",
    )
    review_parser.add_argument(
        "--paragraphs",
        default="",
        help='With --set MIXED_AUTHORSHIP: your paragraphs, e.g. "1-4,7".',
    )
    review_parser.add_argument("--note", default="")
    review_parser.add_argument(
        "--preview",
        metavar="DOC_ID",
        help="Show one document's numbered paragraphs (local display only).",
    )
    review_parser.add_argument(
        "--use-proposed-extraction",
        action="store_true",
        help="With MIXED_AUTHORSHIP: use the proposed extraction (a worksheet's answer lines).",
    )
    review_parser.add_argument(
        "--groups",
        action="store_true",
        help="List pending documents grouped by family, course, series, month.",
    )
    review_parser.add_argument(
        "--group",
        metavar="GROUP_ID",
        help="Apply one decision (--decide) to every member of a group.",
    )
    review_parser.add_argument(
        "--decide", metavar="AUTHORSHIP", help="Decision for --group (same values as --set)."
    )
    review_parser.add_argument(
        "--yes",
        action="store_true",
        help="With --group: confirm the listed members without an interactive prompt.",
    )
    review_parser.add_argument("--json", action="store_true")
    review_parser.set_defaults(handler=run_review)

    build_parser = voice_subparsers.add_parser(
        "build-identity",
        help="Build an identity's context profiles from attested documents.",
    )
    build_parser.add_argument("--identity")
    build_parser.add_argument(
        "--profiles",
        default="",
        help="Comma-separated profile keys (default: all), e.g. academic,professional.",
    )
    build_parser.add_argument(
        "--model-traits",
        action="store_true",
        help="Also run model-backed trait analysis (sends cleaned text to the provider).",
    )
    build_parser.add_argument(
        "--allow-remote-content",
        action="store_true",
        help="Confirm that cleaned document text may be sent to the configured provider.",
    )
    build_parser.add_argument(
        "--allow-shrink",
        action="store_true",
        help="Rebuild even if previously trained documents were unreadable this scan.",
    )
    build_parser.add_argument("--json", action="store_true")
    build_parser.set_defaults(handler=run_build_identity)

    sync_parser = voice_subparsers.add_parser(
        "sync",
        help="Incremental rescan, then rebuild profiles whose evidence changed.",
    )
    sync_parser.add_argument("--identity")
    sync_parser.add_argument(
        "--no-build",
        dest="build",
        action="store_false",
        help="Rescan only; do not rebuild profiles.",
    )
    sync_parser.add_argument("--json", action="store_true")
    sync_parser.set_defaults(handler=run_sync)

    status_parser = voice_subparsers.add_parser(
        "status",
        help="Show an identity's corpus, review, and profile status.",
    )
    status_parser.add_argument("--identity")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(handler=run_status)

    workshop_parser = voice_subparsers.add_parser(
        "workshop",
        help="Voice Workshop: answer short prompts to add private writing samples (local, no model).",
    )
    workshop_parser.add_argument("--identity")
    workshop_actions = workshop_parser.add_subparsers(dest="workshop_command")
    w_prompt = workshop_actions.add_parser(
        "prompt", help="Show the next prompt (largest evidence gap first)."
    )
    w_prompt.add_argument("--context", choices=["academic", "professional", "technical", "casual"])
    w_prompt.add_argument("--subject", default=None, help="Your own subject for the prompt.")
    w_prompt.add_argument("--kind", choices=["short", "paragraph"])
    w_prompt.add_argument("--follow-up", dest="follow_up", metavar="SAMPLE_ID")
    w_prompt.add_argument("--json", action="store_true")
    w_answer = workshop_actions.add_parser("answer", help="Save an answer verbatim.")
    w_answer.add_argument("--prompt-id", required=True)
    w_answer.add_argument("--subject", default="")
    source = w_answer.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--file", metavar="PATH")
    w_answer.add_argument(
        "--self-written",
        action="store_true",
        help="I wrote this myself, without AI help (required for approval).",
    )
    w_answer.add_argument("--approve", action="store_true", help="Also approve it for profile use.")
    w_answer.add_argument("--json", action="store_true")
    w_list = workshop_actions.add_parser("list", help="List samples (no text unless --show-text).")
    w_list.add_argument("--show-text", action="store_true")
    w_list.add_argument("--json", action="store_true")
    for name, helptext in (
        ("approve", "Approve a sample for profile use."),
        ("exclude", "Keep a sample but exclude it from profiles."),
        ("remove", "Delete a sample's text permanently."),
    ):
        action = workshop_actions.add_parser(name, help=helptext)
        action.add_argument("sample_id")
    w_reclass = workshop_actions.add_parser("reclassify", help="Move a sample to another context.")
    w_reclass.add_argument("sample_id")
    w_reclass.add_argument("context", choices=["academic", "professional", "technical", "casual"])
    w_revise = workshop_actions.add_parser(
        "revise",
        help="Store how you would prefer it to read (kept separate; never used as evidence).",
    )
    w_revise.add_argument("sample_id")
    w_revise.add_argument("--text", required=True)
    w_cov = workshop_actions.add_parser("coverage", help="Evidence per profile, with gaps.")
    w_cov.add_argument("--json", action="store_true")
    workshop_parser.set_defaults(handler=run_workshop)

    legacy_parser = voice_subparsers.add_parser(
        "legacy-reconcile",
        help="Recover and reconcile the sources behind legacy profiles (read-only on the profiles).",
    )
    legacy_parser.add_argument("--identity")
    legacy_parser.add_argument(
        "--profiles",
        default="",
        help="Comma-separated legacy voice names (default: <identity>,<identity>_v2).",
    )
    legacy_parser.add_argument("--json", action="store_true")
    legacy_parser.set_defaults(handler=run_legacy_reconcile)

    chat_parser = voice_subparsers.add_parser(
        "chat-import",
        help="Import informal-communication evidence from a ChatGPT export.",
    )
    chat_parser.add_argument("--identity")
    group = chat_parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--export",
        metavar="PATH",
        help="conversations.json from a ChatGPT data export (or its folder).",
    )
    group.add_argument(
        "--provisional",
        action="store_true",
        help="No export available: record your own observations, labelled unvalidated.",
    )
    chat_parser.add_argument("--json", action="store_true")
    chat_parser.set_defaults(handler=run_chat_import)


# --- scan --------------------------------------------------------------


def _print_scan(report: dict) -> None:
    walk = report["walk"]
    print(f"Scan for identity '{report['identity']}' ({report['duration_seconds']}s)")
    for mount in report.get("mount", []):
        print(f"  Source filesystem:            {mount.get('filesystem') or 'unknown'}")
    print(
        f"  Excluded (never entered):     {', '.join(report['exclusions']) or 'none'}"
        f" -- {walk['excluded_directories_skipped']} directories skipped"
    )
    print(f"  Symlinks not followed:        {walk['symlinks_not_followed']}")
    print(f"  Files inventoried:            {report['files_inventoried']}")
    print(f"  Read this scan:               {report['read_this_scan']}")
    print(f"  Eligible prose-bearing files: {report['eligible_prose_files']}")
    print(f"  Read successfully:            {report['readable_documents']}")
    print(f"  Native cloud docs (no content via mount): {report['native_cloud_unavailable']}")
    print(f"  Unreadable or failed:         {report['unreadable_or_failed']}")
    print(f"  Academic candidates:          {report['academic_candidates']}")
    print(f"  Professional candidates:      {report['professional_candidates']}")
    print(f"  Duplicates grouped:           {report['duplicates']}")
    print(
        f"  Renamed / removed:            {report['renamed_since_last_scan']} / "
        f"{report['removed_since_last_scan']}"
    )
    print(f"  Pending authorship reviews:   {report['pending_reviews']}")
    if report.get("google_api"):
        g = report["google_api"]
        print(
            f"  Drive API fallback:           {g['exported']} exported of {g['attempted']} native files "
            f"({g['not_found_or_ambiguous']} not a single Doc, {g['failed']} failed)"
        )
    coverage = report["coverage"]
    print(
        f"  Content coverage:             {coverage['content_read_share_of_eligible']:.0%} of eligible files"
        f"{'' if coverage['complete'] else ' (incomplete)'}"
    )
    if coverage.get("note"):
        print(f"    {coverage['note']}")
    decisions = report["decisions"]
    if decisions["reopened_this_scan"] or decisions["carried_forward_this_scan"]:
        print(
            f"  Decisions reopened / carried forward this scan: "
            f"{decisions['reopened_this_scan']} / {decisions['carried_forward_this_scan']}"
        )


def run_scan(args: argparse.Namespace) -> int:
    identity = _identity(args)
    try:
        outcome = scan(
            identity,
            sources=args.sources,
            additional_exclusions=args.exclusions,
            force=args.force,
            perturbations=args.perturbations,
            progress=None if args.json else _scan_progress,
            google_api=args.google_api,
        )
    except MountUnavailableError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_MOUNT_UNAVAILABLE
    except RuntimeError as error:
        if type(error).__name__ == "GoogleFallbackUnavailable":
            print(f"error: Google API fallback unavailable: {error}", file=sys.stderr)
            return 1
        raise
    if args.json:
        print(json.dumps(outcome.report, indent=2))
        return 0
    print()
    _print_scan(outcome.report)
    if outcome.report["pending_reviews"]:
        print()
        print(f"Review queue: {outcome.review_queue_path}")
        print(f"  howlwriter voice review --identity {identity} --interactive")
    print("Private data: the ledger is local, owner-only, and never tracked by Git.")
    return 0


def run_google_auth(args: argparse.Namespace) -> int:
    from howlwriter.voice.identity import google_fallback

    print(google_fallback.DISCLOSURE)
    print("Requested scope: " + ", ".join(google_fallback.DRIVE_READONLY_SCOPES))
    path = google_fallback.authorize()
    print(f"Saved read-only token to {path} (owner-only).")
    return 0


def _scan_progress(stage: str, data: dict) -> None:
    if stage == "google_api":
        print(f"  {data['disclosure']}", flush=True)
    elif stage == "read":
        print(f"  read {data['processed']}/{data['total']}", flush=True)
    elif stage == "walk":
        print(
            f"  walked: {data['files']} files; {data['excluded_directories']} excluded directories skipped",
            flush=True,
        )


# --- review ------------------------------------------------------------


def run_review(args: argparse.Namespace) -> int:
    store = IdentityStore(_identity(args))
    if not store.exists():
        raise ValueError(f"identity '{store.identity}' has not been scanned yet")
    if args.preview:
        for line in review.preview(store, args.preview):
            print(line)
        return 0
    if args.set:
        doc_id, authorship = args.set
        decision = review.attest(
            store,
            doc_id,
            authorship,
            category=args.category,
            context=args.context,
            include_paragraphs=args.paragraphs,
            note=args.note,
            use_proposed_extraction=args.use_proposed_extraction,
        )
        review.refresh_queue(store)
        extra = f" (extraction: {decision.extraction})" if decision.extraction else ""
        print(f"Recorded {decision.authorship} for {decision.path}{extra}")
        return 0
    if args.group:
        return _decide_group(store, args)
    if args.groups:
        return _print_groups(store, args.json)
    if args.apply:
        result = review.apply_worksheet(store, args.apply)
        print(
            f"Applied {result['applied']}, skipped {result['skipped']} pending, {result['errors']} error(s)."
        )
        for problem in result["problems"]:
            print(f"  - {problem}")
        return 1 if result["errors"] else 0
    if args.interactive:
        return _interactive(store)

    items = review.queue(store)
    if args.json:
        print(
            json.dumps(
                {"summary": review.summary(store), "pending": [i.to_dict() for i in items]},
                indent=2,
            )
        )
        return 0
    summary = review.summary(store)
    print(
        f"Identity '{store.identity}': {summary['pending']} document(s) await review; "
        f"{summary['decisions']} decision(s) recorded, {summary['reopened']} reopened."
    )
    for item in items:
        flags = " [reopened]" if item.reopened else ""
        print(f"\n  {item.doc_id}  {item.path}{flags}")
        print(
            f"    {item.category} ({item.context}), ~{item.eligible_words} eligible words "
            f"of {item.words}, value {item.value}"
        )
        print(
            f"    proposed: {item.proposed}"
            + (f" + {item.proposed_extraction}" if item.proposed_extraction else "")
        )
        print(
            f"    history: {item.revision_history}"
            + (
                f"; trained legacy profiles: {', '.join(item.legacy_profiles)}"
                if item.legacy_profiles
                else ""
            )
        )
        for reason in item.reasons[:4]:
            print(f"    - {reason}")
        for signal in item.style_signals:
            print(f"    - style: {signal}")
    if items:
        print(f"\nAttest with:  howlwriter voice review --identity {store.identity} --set DOC_ID h")
        print(
            f"Or edit the worksheet and apply it:  howlwriter voice review --identity {store.identity} "
            f"--apply {store.directory / 'review_queue.yaml'}"
        )
    return 0


_PROMPT = (
    "  [h] my writing   [l] mine, light AI editing   [m] mixed (choose paragraphs)\n"
    "  [w] mixed: use only the proposed answer lines   [a] mostly AI-generated\n"
    "  [t] someone else's   [u] not sure   [p] preview   [?] explain   [s] skip   [q] quit\n> "
)


def _print_descriptions() -> None:
    for value, text in review.AUTHORSHIP_DESCRIPTIONS.items():
        print(f"  {value}: {text}")


def _print_groups(store: IdentityStore, as_json: bool) -> int:
    found = review.groups(store)
    if as_json:
        print(json.dumps([g.to_dict() for g in found], indent=2))
        return 0
    if not found:
        print("No groups of two or more pending documents.")
        return 0
    for group in found:
        print(
            f"\n{group.group_id}  {group.label}: {len(group.doc_ids)} documents, "
            f"~{group.eligible_words} eligible words"
        )
        print("    " + ", ".join(f"{k} x{v}" for k, v in sorted(group.categories.items())))
        for title in group.titles:
            print(f"    - {title}")
    print(
        f"\nDecide a group:  howlwriter voice review --identity {store.identity} --group GROUP_ID --decide h"
    )
    return 0


def _decide_group(store: IdentityStore, args: argparse.Namespace) -> int:
    if not args.decide:
        raise ValueError("--group needs --decide AUTHORSHIP")
    group = next((g for g in review.groups(store) if g.group_id == args.group), None)
    if group is None:
        raise ValueError(f"no pending review group {args.group!r}; list them with --groups")
    value = review.normalize_authorship(args.decide)
    print(f"Apply {value} to all {len(group.doc_ids)} documents in '{group.label}'?")
    print(f"  {review.AUTHORSHIP_DESCRIPTIONS[value]}")
    for title in group.titles:
        print(f"  - {title}")
    if not args.yes:
        if not sys.stdin.isatty():
            raise ValueError(
                "bulk decisions need confirmation: rerun with --yes after reading the list"
            )
        if input("Type 'yes' to confirm every listed document: ").strip().lower() != "yes":
            print("Cancelled; nothing recorded.")
            return 0
    decisions = review.attest_group(
        store,
        group.group_id,
        value,
        confirmed_doc_ids=group.doc_ids,
        use_proposed_extraction=args.use_proposed_extraction,
        note=args.note or f"bulk decision for group {group.group_id}",
    )
    print(f"Recorded {value} for {len(decisions)} documents.")
    return 0


def _interactive(store: IdentityStore) -> int:
    items = review.queue(store)
    if not items:
        print("Nothing awaits review.")
        return 0
    print(f"{len(items)} document(s) await review. Decisions are saved as you go.")
    for position, item in enumerate(items, start=1):
        print(f"\n[{position}/{len(items)}] {item.path}")
        print(
            f"  {item.category} ({item.context}), ~{item.eligible_words} eligible of {item.words} words; "
            f"proposed {item.proposed}"
            + (f" + {item.proposed_extraction}" if item.proposed_extraction else "")
        )
        print(f"  history: {item.revision_history}")
        for reason in item.reasons[:4]:
            print(f"  - {reason}")
        while True:
            answer = input(_PROMPT).strip().lower()
            if answer == "q":
                review.refresh_queue(store)
                return 0
            if answer in ("s", ""):
                break
            if answer == "?":
                _print_descriptions()
                continue
            if answer == "p":
                for line in review.preview(store, item.doc_id, max_paragraphs=12, max_chars=240):
                    print("   " + line)
                continue
            try:
                paragraphs = ""
                use_extraction = answer == "w"
                if use_extraction:
                    answer = "m"
                elif answer in ("m", "mixed"):
                    paragraphs = input('  your paragraphs (e.g. "1-4,7"): ').strip()
                decision = review.attest(
                    store,
                    item.doc_id,
                    answer,
                    include_paragraphs=paragraphs,
                    use_proposed_extraction=use_extraction,
                )
                print(f"  recorded {decision.authorship}")
                break
            except ValueError as error:
                print(f"  {error}")
    review.refresh_queue(store)
    return 0


# --- build / sync / status ---------------------------------------------


def _print_builds(results: list) -> None:
    for result in results:
        print(f"\n{result.voice}: {result.status.upper()}")
        if result.reason:
            print(f"  {result.reason}")
        print(
            f"  Attested documents: {result.eligible_documents} ({result.eligible_words:,} words); "
            f"pending reviews affecting it: {result.pending_reviews_affecting}"
        )
        if result.status == "built":
            print(
                f"  Training / holdout: {result.training_documents} / {result.holdout_documents}; "
                f"sufficiency {result.sufficiency}; validation {result.validation_confidence}"
            )
            vm = result.voice_match
            sep = vm.get("pooled_separation") or {}
            print(
                f"  Voice Match calibration: {vm.get('genuine_calibration_documents')} genuine documents; "
                f"{'usable' if vm.get('usable') else 'NOT usable'}; "
                f"controls {vm.get('controls') or 'none'}; "
                f"separation AUC {sep.get('auc')} {sep.get('interval_95') or ''}"
            )
            nat = result.naturalness
            nsep = nat.get("pooled_separation") or {}
            print(
                f"  Naturalness calibration: {nat.get('reference_documents')} reference documents; "
                f"{'usable' if nat.get('usable') else 'NOT usable'}; control AUC {nsep.get('auc')}"
            )
            print(f"  Drift baseline: {result.drift_windows} windows")
            if result.workshop_bundles.get("train") or result.workshop_bundles.get("calibration"):
                print(
                    f"  Voice Workshop: {result.workshop_bundles.get('train', 0)} training bundle(s) "
                    f"({result.workshop_words} words), {result.workshop_bundles.get('calibration', 0)} "
                    f"calibration bundle(s)"
                    + ("; WORKSHOP-ONLY provisional profile" if result.workshop_only else "")
                )
        for warning in result.warnings[:6]:
            print(f"  note: {warning}")


def run_build_identity(args: argparse.Namespace) -> int:
    identity = _identity(args)
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()] or None
    results = build_identity(
        identity,
        profiles=profiles,
        model_traits=args.model_traits,
        allow_remote_content=args.allow_remote_content,
        allow_shrink=args.allow_shrink,
    )
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        _print_builds(results)
    return 0 if all(r.status == "built" for r in results) else EXIT_PROFILE_NOT_BUILT


def run_sync(args: argparse.Namespace) -> int:
    identity = _identity(args)
    try:
        outcome = scan(identity)
    except MountUnavailableError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_MOUNT_UNAVAILABLE
    report = outcome.report
    changed = [
        e
        for e in outcome.inventory["entries"].values()
        if e.get("change") in ("added", "modified", "removed", "renamed")
    ]
    summary = {
        "added": sum(1 for e in changed if e["change"] == "added"),
        "modified": sum(1 for e in changed if e["change"] == "modified"),
        "removed": sum(1 for e in changed if e["change"] == "removed"),
        "renamed": sum(1 for e in changed if e["change"] == "renamed"),
        "reopened_decisions": report["decisions"]["reopened_this_scan"],
        "pending_reviews": report["pending_reviews"],
    }
    results = []
    if args.build:
        results = build_identity(identity)
    if args.json:
        print(
            json.dumps(
                {"changes": summary, "scan": report, "builds": [r.to_dict() for r in results]},
                indent=2,
            )
        )
    else:
        print(
            f"Sync for '{identity}': {summary['added']} added, {summary['modified']} modified, "
            f"{summary['removed']} removed, {summary['renamed']} renamed; "
            f"{summary['reopened_decisions']} decision(s) reopened; "
            f"{summary['pending_reviews']} pending review."
        )
        _print_builds(results)
    return 0


def run_status(args: argparse.Namespace) -> int:
    from howlwriter.voice.identity.status import identity_status

    status = identity_status(_identity(args))
    if args.json:
        print(json.dumps(status, indent=2))
        return 0
    scan_report = status.get("scan") or {}
    if scan_report:
        _print_scan(scan_report)
    else:
        print("Not scanned yet.")
    print(
        f"\nReview: {status['review']['pending']} pending, {status['review']['decisions']} decided"
    )
    for profile in status["profiles"]:
        print(f"\n{profile['voice']}: {profile['state']}")
        if profile.get("built_at"):
            print(
                f"  built {profile['built_at']}; {profile['training_documents']} training, "
                f"{profile['holdout_documents']} holdout; confidence {profile['confidence']}"
            )
        if profile.get("voice_match"):
            vm = profile["voice_match"]
            print(
                f"  Voice Match: {vm['status']} ({vm['genuine_documents']} genuine calibration docs)"
            )
    return 0


def _print_coverage(coverage: dict) -> None:
    for profile, entry in coverage["profiles"].items():
        print(
            f"  {profile}: {entry['documents']} attested documents ({entry['document_words']:,} words); "
            f"workshop {entry['workshop_samples']} samples ({entry['workshop_words']} words; "
            f"{entry['workshop_train']} training / {entry['workshop_calibration']} calibration) -- "
            f"{entry['sufficiency']}"
        )
        for gap in entry["gaps"]:
            print(f"    gap: {gap}")
    contexts = ", ".join(
        f"{name} {c['approved']} approved/{c['pending']} pending"
        for name, c in coverage["contexts"].items()
    )
    print(f"  Samples by context: {contexts}")


def run_workshop(args: argparse.Namespace) -> int:
    from howlwriter.voice.identity.workshop import Workshop

    workshop = Workshop(_identity(args))
    command = getattr(args, "workshop_command", None)
    if command is None:
        return _workshop_session(workshop)
    if command == "prompt":
        prompt = workshop.next_prompt(
            context=args.context,
            subject=args.subject,
            kind=args.kind,
            follow_up_of=args.follow_up,
        )
        if args.json:
            print(json.dumps(prompt.to_dict(), indent=2))
        else:
            print(f"[{prompt.prompt_id}] ({prompt.context}, {prompt.kind}) {prompt.text}")
            print(f"  why this prompt: {prompt.reason}")
        return 0
    if command == "answer":
        text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
        sample = workshop.add(
            prompt_id=args.prompt_id,
            subject=args.subject,
            text=text,
            self_written=args.self_written,
            approve=args.approve,
        )
        if args.json:
            data = sample.to_dict()
            data.pop("text")
            print(json.dumps(data, indent=2))
        else:
            print(f"Saved {sample.sample_id} ({sample.words} words, {sample.status}).")
            if sample.duplicate_of or sample.same_prompt_as:
                print("  note: this repeats an earlier answer and will not count twice.")
        return 0
    if command == "list":
        from howlwriter.voice.identity.workshop import counting_ids

        samples = workshop.samples()
        counting = counting_ids(samples.values())
        rows = []
        for sample in sorted(samples.values(), key=lambda x: x.created_at):
            row = sample.to_dict()
            row["counts"] = sample.sample_id in counting
            if not args.show_text:
                row.pop("text")
                row.pop("preferred_revision")
            rows.append(row)
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        for row in rows:
            flag = "counts" if row["counts"] else "not counted"
            print(
                f"{row['sample_id']} {row['status']:8} {row['context']:12} {row['words']:4} words "
                f"{row['side'] or '-':11} {flag}  {row['prompt_text'][:60]}"
            )
            if args.show_text and row.get("text"):
                print(f"    {row['text']}")
        return 0
    if command in ("approve", "exclude", "remove"):
        sample = getattr(workshop, command)(args.sample_id)
        print(f"{sample.sample_id}: {sample.status}" + (f" ({sample.side})" if sample.side else ""))
        return 0
    if command == "reclassify":
        sample = workshop.reclassify(args.sample_id, args.context)
        print(f"{sample.sample_id}: now {sample.context}")
        return 0
    if command == "revise":
        workshop.set_preferred_revision(args.sample_id, args.text)
        print(
            "Preferred revision stored separately; your original answer is unchanged and is the only "
            "text used as evidence."
        )
        return 0
    coverage = workshop.coverage()
    if args.json:
        print(json.dumps(coverage, indent=2))
    else:
        _print_coverage(coverage)
    return 0


def _read_answer() -> str:
    print("Your answer (finish with an empty line):")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip() and lines:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _workshop_session(workshop) -> int:
    print("Voice Workshop -- answers are saved privately and verbatim; nothing is sent anywhere.")
    _print_coverage(workshop.coverage())
    last = None
    while True:
        choice = (
            input(
                "\n[enter] next prompt  [c] choose context  [s] choose subject  [f] follow-up  [q] quit > "
            )
            .strip()
            .lower()
        )
        if choice == "q":
            return 0
        context = subject = None
        follow = None
        if choice == "c":
            context = (
                input("  context (academic/professional/technical/casual): ").strip().lower()
                or None
            )
        elif choice == "s":
            subject = input("  subject: ").strip() or None
        elif choice == "f":
            if last is None:
                print("  answer a prompt first")
                continue
            follow = last
        try:
            prompt = workshop.next_prompt(context=context, subject=subject, follow_up_of=follow)
        except ValueError as error:
            print(f"  {error}")
            continue
        print(f"\n{prompt.text}\n  ({prompt.context}, {prompt.kind}; {prompt.reason})")
        text = _read_answer()
        if not text:
            print("  skipped")
            continue
        own = input("Did you write this yourself, without AI help? [y/N] ").strip().lower() in (
            "y",
            "yes",
        )
        approve = own and input("Include it in your profiles? [y/N] ").strip().lower() in (
            "y",
            "yes",
        )
        sample = workshop.add(
            prompt_id=prompt.prompt_id,
            subject=prompt.subject,
            text=text,
            self_written=own,
            approve=approve,
        )
        last = sample.sample_id
        print(
            f"  saved {sample.sample_id} ({sample.status}"
            + (f", {sample.side}" if sample.side else "")
            + ")"
        )


def run_legacy_reconcile(args: argparse.Namespace) -> int:
    from howlwriter.voice.identity.legacy import reconcile

    names = [n.strip() for n in args.profiles.split(",") if n.strip()] or None
    payload = reconcile(_identity(args), legacy_profiles=names)
    summary = payload["summary"]
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    print(
        f"Legacy profiles read (not modified): {', '.join(payload['legacy_profiles']) or 'none found'}"
    )
    print(
        f"  Historical sources:        {summary['historical_sources']} "
        f"({summary['historically_used']} used, {summary['historically_trained']} trained)"
    )
    print(
        f"  Matched now:               {summary['matched_by_path']} by path, "
        f"{summary['matched_by_content']} by content; {summary['missing']} missing"
    )
    print(f"  Changed since legacy build: {summary['content_changed_since_legacy_build']}")
    print(f"  Historical duplicates:     {summary['historical_duplicates']}")
    print(f"  Recommendations:           {summary['recommendations']}")
    print(
        f"  Trained sources now excluded: {summary['trained_sources_now_excluded']} "
        f"({summary['trained_word_share_now_excluded']:.0%} of legacy training words)"
    )
    print(f"  Confirmed / pending review: {summary['confirmed']} / {summary['pending_review']}")
    print("Private ledger: legacy_reconciliation.json in the identity directory.")
    return 0


def run_chat_import(args: argparse.Namespace) -> int:
    store = IdentityStore(_identity(args))
    store.ensure()
    evidence = chat.import_export(args.export) if args.export else chat.provisional_evidence()
    store.save_chat_evidence(evidence)
    if args.json:
        print(json.dumps(evidence, indent=2))
        return 0
    print(f"Chat evidence for '{store.identity}': {evidence['status']} ({evidence['source']})")
    stats = evidence.get("statistics") or {}
    if stats:
        print(
            f"  user messages used: {stats.get('messages', 0)}; excluded: "
            + ", ".join(f"{k}={v}" for k, v in sorted(evidence["excluded"].items()))
        )
    for tendency in evidence["tendencies"]:
        print(f"  - {tendency}")
    print("Supporting evidence only: it never sets a score baseline or raises profile confidence.")
    print("It is attached to profiles on their next build (voice build-identity).")
    return 0
