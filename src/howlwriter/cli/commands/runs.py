"""`howlwriter runs` -- inspect local dogfood run records and diagnostics."""

from __future__ import annotations

import argparse
import json
import sys

from howlwriter.diagnostic.run_record import (
    RunRecord,
    get_default_runs_dir,
)


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "runs", help="Inspect local diagnostic run records and execution history."
    )
    sub_commands = parser.add_subparsers(dest="subcommand", required=False)

    # list sub-subcommand
    list_parser = sub_commands.add_parser(
        "list", help="List recent diagnostic run records."
    )
    list_parser.add_argument(
        "--limit", type=int, default=15, help="Number of records to display."
    )

    # show sub-subcommand
    show_parser = sub_commands.add_parser(
        "show", help="Display details of a specific run record."
    )
    show_parser.add_argument("run_id", help="The run ID or JSON filename to inspect.")
    show_parser.add_argument(
        "--raw", action="store_true", help="Print raw JSON record."
    )

    # prune sub-subcommand
    prune_parser = sub_commands.add_parser(
        "prune",
        help="Remove old run records (dry-run unless --yes is given).",
    )
    prune_parser.add_argument(
        "--older-than-days", type=int, default=None, dest="older_than_days",
        help="Prune runs whose id timestamp is older than N days.",
    )
    prune_parser.add_argument(
        "--keep-latest", type=int, default=None, dest="keep_latest",
        help="Keep only the newest N runs. With --older-than-days, a run is "
             "pruned only if it satisfies both.",
    )
    prune_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be removed (this is also the default).",
    )
    prune_parser.add_argument(
        "--yes", action="store_true",
        help="Actually delete. Without it nothing is removed.",
    )

    # path sub-subcommand
    sub_commands.add_parser(
        "path", help="Print the local runs storage directory."
    )

    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    sub = getattr(args, "subcommand", None) or "list"

    if sub == "prune":
        return _prune(args)

    if sub == "path":
        print(get_default_runs_dir())
        return 0

    if sub == "show":
        record = RunRecord.load(args.run_id)
        if record is None:
            print(f"error: run record '{args.run_id}' not found in {get_default_runs_dir()}")
            return 1

        if getattr(args, "raw", False):
            print(json.dumps(record.to_dict(), indent=2))
            return 0

        print(f"RUN RECORD: {record.run_id}")
        print(f"  Timestamp:           {record.timestamp}")
        print(f"  Command:             howlwriter {record.command}")
        print(f"  Success:             {'YES' if record.success else 'NO'}")
        print(f"  Status:              {record.status}")
        print(f"  Humanizer Provider:  {record.humanizer_provider or 'none'}")
        print(f"  Reviewer Provider:   {record.meaning_reviewer_provider or 'none'}")
        print(f"  Independence:        {record.reviewer_independence or 'none'}")
        print(f"  Duration:            {record.total_duration_seconds or 0.0}s")
        if record.error_message:
            print(f"  Failure Category:    {record.failure_category or 'unknown'}")
            print(f"  Error Message:       {record.error_message}")
        print(f"  Input:               {record.input_path or 'unknown'} ({record.input_chars} chars)")
        if record.output_path:
            print(f"  Output:              {record.output_path} ({record.output_chars or 0} chars)")
        return 0

    # default: list
    limit = getattr(args, "limit", 15)
    records = RunRecord.list_records(limit=limit)
    if not records:
        print(f"No run records found in {get_default_runs_dir()}")
        return 0

    print(f"{'RUN ID':<32} {'CMD':<10} {'STATUS':<12} {'HUMANIZER':<12} {'REVIEWER':<12} {'DUR':<8}")
    print("-" * 90)
    for r in records:
        status_str = r.status if r.success else f"FAIL({r.failure_category or 'ERR'})"
        dur_str = f"{r.total_duration_seconds:.1f}s" if r.total_duration_seconds is not None else "-"
        print(
            f"{r.run_id:<32} "
            f"{r.command:<10} "
            f"{status_str:<12} "
            f"{(r.humanizer_provider or '-'):<12} "
            f"{(r.meaning_reviewer_provider or '-'):<12} "
            f"{dur_str:<8}"
        )
    return 0


def _prune(args: argparse.Namespace) -> int:
    from howlwriter.diagnostic.retention import execute_prune, plan_prune

    if args.older_than_days is None and args.keep_latest is None:
        print("error: specify --older-than-days and/or --keep-latest", file=sys.stderr)
        return 2
    if args.dry_run and args.yes:
        print("error: --dry-run and --yes are mutually exclusive", file=sys.stderr)
        return 2
    try:
        plan = plan_prune(
            get_default_runs_dir(),
            older_than_days=args.older_than_days,
            keep_latest=args.keep_latest,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    deleting = args.yes
    print(f"Runs directory: {plan.runs_dir}")
    print(f"Run records found: {plan.total_runs}; selected for removal: {len(plan.candidates)}")
    for c in plan.candidates:
        print(f"  {'REMOVE' if deleting else 'would remove'} {c.run_id} ({c.reason}) [{len(c.files)} file(s)]")
    for name in plan.skipped:
        print(f"  skipped unsafe entry: {name}")
    if not deleting:
        if plan.candidates:
            print("Dry run: nothing was deleted. Re-run with --yes to delete.")
        return 0
    removed = execute_prune(plan)
    print(f"Removed {len(removed)} file(s).")
    return 0
