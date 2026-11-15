"""`howlwriter linkedin ...`: manage the private LinkedIn post queue.

Argument parsing and rendering only. Every command works on a publishing
repository directory (``--repo`` or HOWLWRITER_LINKEDIN_REPO), is deterministic,
and needs no model. None of these commands sends anything to LinkedIn.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

from howlwriter.linkedin.checks import has_errors
from howlwriter.linkedin.models import MediaRef, Post, parse_utc
from howlwriter.linkedin.service import DEFAULT, KEEP, QueueService
from howlwriter.linkedin.store import QueueStore
from howlwriter.publishing.base import RevisionConflictError

REPO_ENV = "HOWLWRITER_LINKEDIN_REPO"
DEFAULT_ACTOR = "local-cli"


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "linkedin",
        help="Manage the private LinkedIn post queue and schedule (never sends anything).",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help=f"Path to the private publishing repository (default: ${REPO_ENV}).",
    )
    commands = parser.add_subparsers(dest="linkedin_command", required=True)

    def command(name: str, handler, help_text: str, *, actor: bool = False) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--json", action="store_true", help="Emit the result as JSON.")
        if actor:
            sub.add_argument(
                "--actor", default=DEFAULT_ACTOR, help="Who is making this change, for the audit trail."
            )
        sub.set_defaults(handler=_guarded(handler))
        return sub

    command("init", _init, "Create the repository layout and a starter publisher.yaml (publishing off).")

    add = command("add", _add, "Add a draft post.", actor=True)
    add.add_argument("--title", required=True, help="Internal title (not sent to LinkedIn).")
    add.add_argument(
        "--text-file", required=True, help="File holding the post text, or - for standard input."
    )
    add.add_argument("--url", action="append", default=[], help="A link the post references (repeatable).")
    add.add_argument("--image", default=None, help="Image inside the repository's media/ directory.")
    add.add_argument("--alt", default=None, help="Alt text for --image (required with it).")
    add.add_argument("--date", default=None, help="Local scheduled date, YYYY-MM-DD.")
    add.add_argument("--time", default=None, help="Time override, HH:MM; must be a supported slot.")

    edit = command(
        "edit", _edit, "Edit a post. Changing text or links discards verification and approval.", actor=True
    )
    edit.add_argument("id")
    edit.add_argument("--title", default=None)
    edit.add_argument("--text-file", default=None, help="File holding the new text, or - for standard input.")
    edit.add_argument("--url", action="append", default=None, help="Replace the link list (repeatable).")

    listing = command("list", _list, "List posts.")
    listing.add_argument("--state", default=None, help="Only posts in this lifecycle state.")

    command("show", _show, "Inspect one post.").add_argument("id")
    command(
        "validate", _validate, "Run the deterministic checks on one post (exit 1 on errors)."
    ).add_argument("id")
    command(
        "submit", _submit, "Move a draft to READY_FOR_REVIEW after it passes the checks.", actor=True
    ).add_argument("id")
    command("schedule", _schedule, "Queue an APPROVED post on its scheduled date.", actor=True).add_argument(
        "id"
    )
    command(
        "cancel", _cancel, "Take one post out of the queue (keeps its approval).", actor=True
    ).add_argument("id")
    command(
        "archive", _archive, "Archive a post record. Never deletes from LinkedIn.", actor=True
    ).add_argument("id")

    queue = command("queue", _queue, "Preview the queue in schedule order.")
    queue.add_argument("--at", default=None, help="Preview as of this UTC time (YYYY-MM-DDTHH:MM:SSZ).")

    evaluate = command(
        "evaluate", _evaluate, "Dry-run scheduling evaluation: what a run would do. Changes nothing."
    )
    evaluate.add_argument("--at", default=None, help="Evaluate as of this UTC time (YYYY-MM-DDTHH:MM:SSZ).")

    reschedule = command(
        "reschedule", _reschedule, "Reschedule one post (keeps verification and approval).", actor=True
    )
    reschedule.add_argument("id")
    reschedule.add_argument("--date", default=None, help="New local date, YYYY-MM-DD.")
    reschedule.add_argument(
        "--time", default=None, help="New time HH:MM, or 'default' to follow the default slot."
    )

    bulk = command(
        "reschedule-all", _reschedule_all, "Reschedule every eligible future post (plan first).", actor=True
    )
    bulk.add_argument("--shift-days", type=int, default=0, help="Move each post by this many days.")
    bulk.add_argument("--time", default=None, help="Set this time on each post, or 'default'.")
    bulk.add_argument("--from-date", default=None, help="Only posts scheduled on or after this date.")
    bulk.add_argument(
        "--apply", action="store_true", help="Apply the plan. Without it the plan is only shown."
    )

    pause = command("pause", _pause, "Pause all scheduled publishing.", actor=True)
    pause.add_argument("--reason", default="")
    command("resume", _resume, "Resume scheduled publishing.", actor=True)

    reconcile = command(
        "reconcile", _reconcile, "Resolve an UNCERTAIN post after checking LinkedIn yourself.", actor=True
    )
    reconcile.add_argument("id")
    outcome = reconcile.add_mutually_exclusive_group(required=True)
    outcome.add_argument(
        "--published", metavar="LINKEDIN_ID", help="It is on LinkedIn; record its post ID or URL."
    )
    outcome.add_argument("--not-published", action="store_true", help="It is definitely not on LinkedIn.")

    return parser


def _guarded(handler):
    def run(args: argparse.Namespace) -> int:
        try:
            return handler(args)
        except RevisionConflictError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

    return run


def _store(args: argparse.Namespace) -> QueueStore:
    repo = args.repo or os.environ.get(REPO_ENV)
    if not repo:
        raise ValueError(f"no publishing repository given: pass --repo or set {REPO_ENV}")
    return QueueStore(Path(repo).expanduser())


def _service(args: argparse.Namespace) -> QueueService:
    store = _store(args)
    at = getattr(args, "at", None)
    return QueueService(store, _FixedClock(parse_utc(at)) if at else None)


def _emit(args: argparse.Namespace, payload, text: str) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else text)


def _read_text(source: str) -> str:
    return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")


def _summary(post: Post) -> str:
    when = (
        f"{post.scheduled_date} {post.scheduled_time or 'default time'}"
        if post.scheduled_date
        else "unscheduled"
    )
    return f"{post.id}  {post.state.value:<16}  {when:<24}  {post.title}"


def _changed(args: argparse.Namespace, post: Post, verb: str) -> int:
    _emit(args, post.to_dict(), f"{verb}: {_summary(post)}")
    return 0


def _init(args: argparse.Namespace) -> int:
    store = _store(args)
    created = store.initialize()
    config = store.load_config()
    _emit(
        args,
        {"root": str(store.root), "created": created, "config": config.to_dict()},
        f"Publishing repository ready at {store.root}\n"
        f"  created: {', '.join(created) or 'nothing (already initialized)'}\n"
        f"  publishing_enabled={config.publishing_enabled} dry_run={config.dry_run}",
    )
    return 0


def _media(store: QueueStore, image: str | None, alt: str | None) -> tuple[MediaRef, ...]:
    if image is None:
        if alt is not None:
            raise ValueError("--alt was given without --image")
        return ()
    if not alt or not alt.strip():
        raise ValueError("--image requires --alt: every image needs alt text")
    path = Path(image).expanduser().resolve()
    root = store.root.resolve()
    if root / "media" not in path.parents or not path.is_file():
        raise ValueError(f"--image must be an existing file inside {root / 'media'}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (MediaRef(path=path.relative_to(root).as_posix(), sha256=digest, alt_text=alt),)


def _add(args: argparse.Namespace) -> int:
    service = _service(args)
    post = service.add_draft(
        title=args.title,
        text=_read_text(args.text_file),
        actor=args.actor,
        urls=tuple(args.url),
        media=_media(service.store, args.image, args.alt),
        scheduled_date=args.date,
        scheduled_time=args.time,
    )
    return _changed(args, post, "added")


def _edit(args: argparse.Namespace) -> int:
    post = _service(args).update_content(
        args.id,
        actor=args.actor,
        title=args.title,
        text=_read_text(args.text_file) if args.text_file else None,
        urls=tuple(args.url) if args.url is not None else None,
    )
    return _changed(args, post, "edited")


def _list(args: argparse.Namespace) -> int:
    snapshot = _store(args).load_snapshot()
    posts = [post for post in snapshot.posts if not args.state or post.state.value == args.state.upper()]
    posts.sort(key=lambda post: (post.scheduled_date is None, post.scheduled_date or "", post.id))
    lines = [_summary(post) for post in posts] or ["no posts"]
    lines += [f"INVALID {item.path}: {'; '.join(item.problems)}" for item in snapshot.invalid]
    _emit(
        args,
        {
            "posts": [post.to_dict() for post in posts],
            "invalid": [{"path": item.path, "problems": list(item.problems)} for item in snapshot.invalid],
        },
        "\n".join(lines),
    )
    return 1 if snapshot.invalid else 0


def _show(args: argparse.Namespace) -> int:
    post = _store(args).load_post(args.id)
    text = (
        f"{_summary(post)}\n"
        f"  fingerprint:  {post.computed_fingerprint()}\n"
        f"  verification: {post.verification_ref.path if post.verification_ref else 'none'}\n"
        f"  approval:     {post.approval_ref.path if post.approval_ref else 'none'}\n"
        f"  attempts:     {len(post.attempts)}\n"
        f"  linkedin id:  {post.linkedin_post_id or 'none'}\n"
        f"  links:        {', '.join(post.urls) or 'none'}\n\n{post.text}"
    )
    _emit(args, post.to_dict(), text)
    return 0


def _validate(args: argparse.Namespace) -> int:
    findings = _service(args).validate(args.id)
    lines = [f"{finding.severity.upper():<8} {finding.code}: {finding.message}" for finding in findings]
    failed = has_errors(findings)
    _emit(
        args,
        {"id": args.id, "ok": not failed, "findings": [finding.to_dict() for finding in findings]},
        "\n".join(lines + [f"{args.id}: {'FAILED' if failed else 'passed the deterministic checks'}"]),
    )
    return 1 if failed else 0


def _submit(args: argparse.Namespace) -> int:
    return _changed(args, _service(args).submit_for_review(args.id, actor=args.actor), "submitted")


def _schedule(args: argparse.Namespace) -> int:
    return _changed(args, _service(args).schedule(args.id, actor=args.actor), "scheduled")


def _cancel(args: argparse.Namespace) -> int:
    return _changed(args, _service(args).cancel(args.id, actor=args.actor), "cancelled")


def _archive(args: argparse.Namespace) -> int:
    return _changed(args, _service(args).archive(args.id, actor=args.actor), "archived")


def _queue(args: argparse.Namespace) -> int:
    service = _service(args)
    rows = service.preview_queue()
    control = service.store.load_control()
    lines = ["scheduling is PAUSED"] if control.paused else []
    for row in rows:
        when = f"{row['scheduled_date']} {row['scheduled_time']}" if row["scheduled_date"] else "unscheduled"
        status = f" [{row['queue_status']}]" if row["queue_status"] else ""
        lines.append(f"{when:<18} {row['state']:<16}{status} {row['id']}  {row['title']}")
        lines += [f"{'':<18} reason: {reason}" for reason in row["reasons"]]
    _emit(args, {"paused": control.paused, "queue": rows}, "\n".join(lines or ["the queue is empty"]))
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    service = _service(args)
    config = service.store.load_config()
    evaluation = service.evaluate()
    lines = [
        f"as of {evaluation.now} (local day {evaluation.local_date}, {config.timezone})",
        f"decision: {evaluation.action.value} ({evaluation.reason.value})"
        + (f" post {evaluation.candidate_id}" if evaluation.candidate_id else ""),
        f"switches: publishing_enabled={config.publishing_enabled} dry_run={config.dry_run}",
    ]
    lines += [f"note: {note}" for note in evaluation.notes]
    for item in evaluation.assessments:
        lines.append(f"  {item.post_id}: {item.status.value} due {item.due_at}")
        lines += [f"    {reason}" for reason in item.reasons]
    lines.append("This was an evaluation only. Nothing was changed or sent.")
    payload = evaluation.to_dict() | {
        "publishing_enabled": config.publishing_enabled,
        "dry_run": config.dry_run,
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _emit(args, payload, "\n".join(lines))
    return 0


def _time_argument(value: str | None) -> str:
    return KEEP if value is None else (DEFAULT if value == "default" else value)


def _reschedule(args: argparse.Namespace) -> int:
    if args.date is None and args.time is None:
        raise ValueError("give --date, --time, or both")
    post = _service(args).reschedule(
        args.id, actor=args.actor, new_date=args.date, new_time=_time_argument(args.time)
    )
    return _changed(args, post, "rescheduled")


def _reschedule_all(args: argparse.Namespace) -> int:
    service = _service(args)
    options = dict(shift_days=args.shift_days, new_time=_time_argument(args.time), from_date=args.from_date)
    if args.apply:
        plan = service.apply_bulk_reschedule(actor=args.actor, **options)
    else:
        plan = service.plan_bulk_reschedule(**options)
    applied = args.apply and plan.is_applicable
    lines = [
        f"{move.post_id}: {move.describe()}"
        for move in plan.moves
    ]
    lines += [f"CONFLICT: {conflict}" for conflict in plan.conflicts]
    if applied:
        lines.append(f"applied: {len(plan.moves)} post(s) rescheduled")
    elif plan.conflicts:
        lines.append("nothing was changed")
    elif not plan.moves:
        lines.append("no eligible posts; nothing was changed")
    else:
        lines.append("plan only; repeat with --apply to make these changes")
    _emit(args, plan.to_dict() | {"applied": applied}, "\n".join(lines))
    return 1 if plan.conflicts else 0


def _pause(args: argparse.Namespace) -> int:
    control = _service(args).set_paused(True, actor=args.actor, reason=args.reason)
    _emit(args, control.to_dict(), "scheduling is paused")
    return 0


def _resume(args: argparse.Namespace) -> int:
    control = _service(args).set_paused(False, actor=args.actor)
    _emit(args, control.to_dict(), "scheduling is resumed")
    return 0


def _reconcile(args: argparse.Namespace) -> int:
    post = _service(args).reconcile(
        args.id,
        actor=args.actor,
        was_published=not args.not_published,
        linkedin_post_id=args.published,
    )
    return _changed(args, post, "reconciled")
