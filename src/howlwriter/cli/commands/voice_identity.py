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
        )
        review.refresh_queue(store)
        print(f"Recorded {decision.authorship} for {decision.path}")
        return 0
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
            f"    {item.category} ({item.context}), {item.words} words, {item.paragraphs} paragraphs"
        )
        print(f"    proposed: {item.proposed}")
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
    "  [a] mostly AI-generated   [t] someone else's   [u] not sure   [p] preview   [s] skip   [q] quit\n> "
)


def _interactive(store: IdentityStore) -> int:
    items = review.queue(store)
    if not items:
        print("Nothing awaits review.")
        return 0
    print(f"{len(items)} document(s) await review. Decisions are saved as you go.")
    for position, item in enumerate(items, start=1):
        print(f"\n[{position}/{len(items)}] {item.path}")
        print(f"  {item.category} ({item.context}), {item.words} words; proposed {item.proposed}")
        for reason in item.reasons[:4]:
            print(f"  - {reason}")
        while True:
            answer = input(_PROMPT).strip().lower()
            if answer == "q":
                review.refresh_queue(store)
                return 0
            if answer in ("s", ""):
                break
            if answer == "p":
                for line in review.preview(store, item.doc_id, max_paragraphs=12, max_chars=240):
                    print("   " + line)
                continue
            try:
                paragraphs = ""
                if answer in ("m", "mixed"):
                    paragraphs = input('  your paragraphs (e.g. "1-4,7"): ').strip()
                decision = review.attest(store, item.doc_id, answer, include_paragraphs=paragraphs)
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
