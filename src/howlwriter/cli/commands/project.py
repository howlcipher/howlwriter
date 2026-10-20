"""`howlwriter project ...` -- Source Intelligence for a folder of project materials.

    project open FOLDER            create the private workspace and scan it
    project list | status P        projects; one project's state
    project scan P                 incremental rescan (resumes an interrupted scan)
    project sources P              inventory with categories and extraction status
    project classify P SRC CAT     correct a source's category (kept across rescans)
    project evidence P             the evidence library
    project search P QUERY         task-specific retrieval, with the reason for each hit
    project requirements P         the requirements ledger and coverage
    project require P TEXT         add a requirement by hand
    project req-status P ID STATUS mark a requirement (e.g. not_applicable)
    project compare P A B          deterministic before/after packet-capture comparison
    project brief P                evidence-to-requirement map for writing
    project draft P                write the report (--skeleton needs no model)
    project validate P DRAFT       citations, unsupported claims, numbers, coverage
    project authorize-remote P     allow evidence excerpts to be sent to a remote model
    project browse P               research / observe / interactive browser session
    project actions P              the browser action audit trail

P is a project id or the folder it was opened from.

Exit codes: 0 success; 1 error; 2 refused (remote-inference gate, browser
policy); 3 a validated draft is not ready for review; 4 an owner-only
decision (--allow-remote, authorize-remote) was asked for without a terminal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from howlwriter.cli import owner
from howlwriter.voice.selection import add_selection_arguments

# Sending private evidence off the machine is the owner's decision (see howlwriter.cli.owner).
_SENDS = "sends private project evidence to a remote model"


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "project",
        help="Source Intelligence: evidence-grounded projects from a folder of materials.",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="project_command", required=True)

    def add(name: str, help_text: str, project: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        if project:
            p.add_argument("project", help="Project id or folder.")
        p.add_argument("--json", dest="as_json", action="store_true", help="Machine-readable output.")
        return p

    def scan_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--force", action="store_true", help="Re-extract every file, ignoring cached results.")
        p.add_argument(
            "--no-transcribe", action="store_true", help="Skip speech transcription of audio/video."
        )
        p.add_argument("--no-frames", action="store_true", help="Skip video frame sampling and OCR.")
        p.add_argument(
            "--no-ocr", action="store_true", help="Skip OCR of images, frames, and image-only PDF pages."
        )
        p.add_argument(
            "--threads", type=int, default=None, help="Compute threads for OCR/transcription (default 2)."
        )
        p.add_argument(
            "--job-timeout", type=float, default=None, help="Seconds allowed per OCR job (default 90)."
        )
        p.add_argument(
            "--only",
            action="append",
            default=None,
            metavar="PATH",
            help="Re-extract only this file (path relative to the project; repeatable).",
        )

    p = add("open", "Create a project for a folder and scan it.", project=False)
    p.add_argument("folder")
    p.add_argument("--name", default=None)
    p.add_argument("--no-scan", action="store_true")
    scan_options(p)
    add("list", "List projects.", project=False)
    add("status", "Show a project's state.")
    p = add("scan", "Rescan a project incrementally.")
    scan_options(p)
    p = add("sources", "List sources.")
    p.add_argument("--category", default=None)
    p = add("classify", "Correct a source's category.")
    p.add_argument("source", help="Source id or relative path.")
    p.add_argument("category")
    p.add_argument(
        "--owner-confirmed",
        action="store_true",
        help="Record the change as relayed from the owner (they told you this category). "
        "Without a terminal and without this flag it is recorded as an agent's change.",
    )
    p = add("evidence", "List evidence.")
    p.add_argument("--source", default=None, help="Only this source (id or relative path).")
    p.add_argument("--kind", default=None)
    p.add_argument("--limit", type=int, default=50)
    p = add("search", "Retrieve evidence for a query.")
    p.add_argument("query")
    p.add_argument("--purpose", choices=("facts", "observations", "requirements"), default="facts")
    p.add_argument("--limit", type=int, default=8)
    add("requirements", "Show the requirements ledger.")
    p = add("require", "Add a requirement.")
    p.add_argument("text")
    p.add_argument("--kind", default=None)
    p = add("req-status", "Set a requirement's status.")
    p.add_argument("requirement_id")
    p.add_argument(
        "status",
        help="satisfied_with_evidence | partially_satisfied | pending_user_work | blocked | "
        "not_applicable | clear",
    )
    p.add_argument("--note", default="")
    p = add("compare", "Compare two packet captures.")
    p.add_argument("first")
    p.add_argument("second")
    p = add("brief", "Build the evidence-to-requirement brief.")
    p.add_argument("--section", action="append", default=None, help="Section title (repeatable).")
    p.add_argument("--topic", default="")
    p = add("draft", "Write the report from the brief.")
    p.add_argument("--section", action="append", default=None)
    p.add_argument("--topic", default="")
    p.add_argument("--skeleton", action="store_true", help="Deterministic evidence skeleton; no model.")
    p.add_argument("--mode", default="academic")
    p.add_argument("--voice", default=None)
    p.add_argument("--voice-profile", dest="voice_profile", default=None)
    add_selection_arguments(p)
    p.add_argument(
        "--allow-remote", action="store_true", help="Send evidence excerpts to a remote model this once."
    )
    owner.add_argument(p)
    p.add_argument("--instructions", default="")
    p.add_argument(
        "--voice-examples",
        choices=("auto", "on", "off"),
        default="auto",
        help="Show the model short passages of your own writing as style examples: auto = local models "
        "only (default), on = also remote models (sends those passages), off = never.",
    )
    p.add_argument(
        "--no-voice-revision",
        dest="voice_revision",
        action="store_false",
        help="Skip the measured revision pass that brings each part closer to your voice.",
    )
    p.add_argument("--out", default=None, help="Also write the draft to this file.")
    p.add_argument(
        "--fail-if-blocked",
        dest="fail_if_blocked",
        action="store_true",
        help="Exit 3 when the draft's validation verdict is not READY_FOR_HUMAN_REVIEW "
        "(the draft is still saved and printed).",
    )
    p = add("validate", "Validate a draft.")
    p.add_argument("draft")
    p = add("authorize-remote", "Allow (or --revoke) remote inference on this project's evidence.")
    p.add_argument("--revoke", action="store_true")
    owner.add_argument(p)
    p = add("browse", "Run a controlled browser session.")
    p.add_argument("--mode", choices=("research", "observe", "interactive"), default="research")
    p.add_argument("--allow", action="append", default=[], help="Approved origin (repeatable).")
    p.add_argument("--lab", action="append", default=[], help="Approved interactive lab origin (repeatable).")
    p.add_argument(
        "--step",
        action="append",
        default=[],
        help="goto:URL | read | screenshot[:LABEL] | "
        "click:SELECTOR | fill:SELECTOR=VALUE | fill-secret:SELECTOR=ENVVAR (repeatable, in order)",
    )
    p.add_argument("--headless", action="store_true", help="Hide the browser window (default: visible).")
    p.add_argument(
        "--yes", action="store_true", help="Approve state-changing steps without asking (interactive)."
    )
    p = add("actions", "Show the browser action log.")
    p.add_argument("--limit", type=int, default=50)
    parser.set_defaults(handler=run)
    return parser


def _out(args, payload, text: str | None = None) -> int:
    if getattr(args, "as_json", False) or text is None:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(text)
    return 0


def _extractors(args, meta: dict):
    from howlwriter.projects.resources import ResourcePolicy
    from howlwriter.projects.scan import Extractors

    resources = dict(meta.get("resources") or {})
    if args.threads:
        resources["threads"] = args.threads
    if args.job_timeout:
        resources["job_timeout"] = args.job_timeout
    policy = ResourcePolicy.from_dict(resources)

    class _Off:
        available = False
        name = "disabled"

        def close(self) -> None:
            pass

    return Extractors(
        policy=policy,
        media_frames=not args.no_frames,
        ocr=_Off() if args.no_ocr else None,
        transcriber=_Off() if args.no_transcribe else None,
    )


def _scan(args, workspace) -> int:
    from howlwriter.projects.scan import scan_project

    extractors = _extractors(args, workspace.load_meta())
    quiet = getattr(args, "as_json", False)
    try:
        report = scan_project(
            workspace,
            extractors=extractors,
            force=args.force or bool(args.only),
            only=set(args.only) if args.only else None,
            progress=None if quiet else (lambda p: print(f"  reading {p}", file=sys.stderr)),
        )
    except KeyboardInterrupt:
        print("interrupted: progress is saved; run `project scan` again to resume", file=sys.stderr)
        return 130
    finally:
        extractors.close()
    data = report.to_dict()
    lines = [
        f"project {workspace.project_id}: {data['files']} files, {data['new_or_changed']} read, "
        f"{data['unchanged']} unchanged, {data['duplicates']} duplicates, {data['failed']} failed, "
        f"{data['removed']} removed; {data['evidence_items']} evidence items in {data['seconds']} s",
        "categories: " + ", ".join(f"{k} {v}" for k, v in sorted(data["by_category"].items())),
        "status: " + ", ".join(f"{k} {v}" for k, v in sorted(data["by_status"].items())),
    ]
    if data["skipped"]:
        lines.append("not entered: " + ", ".join(f"{k} {v}" for k, v in sorted(data["skipped"].items())))
    if data.get("workload"):
        w = data["workload"]
        lines.append(
            f"heavy jobs: {w['jobs']} ({w['timeouts']} timed out, {w['errors']} errors) on "
            f"{w['policy']['threads']} idle-priority threads"
        )
    return _out(args, data, "\n".join(lines))


def run(args: argparse.Namespace) -> int:
    try:
        return _run(args)
    except owner.OwnerConfirmationRequired as error:
        return owner.report(error)
    except PermissionError as error:  # remote-inference gate, browser policy refusals
        print(f"refused: {error}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    from howlwriter.projects import service
    from howlwriter.projects.workspace import ProjectWorkspace

    command = args.project_command
    if command == "open":
        workspace = ProjectWorkspace.create(args.folder, name=args.name)
        print(f"project {workspace.project_id} -> {workspace.source_root}", file=sys.stderr)
        if args.no_scan:
            return _out(args, service.summary(workspace), f"opened {workspace.project_id}")
        return _scan(args, workspace)
    if command == "list":
        rows = [service.summary(ProjectWorkspace(pid)) for pid in ProjectWorkspace.list_projects()]
        return _out(
            args,
            rows,
            "\n".join(
                f"{r['project_id']}  {r['sources']} sources, {r['evidence']} evidence, "
                f"{r['requirements']} requirements  {r['root']}"
                for r in rows
            )
            or "no projects",
        )
    workspace = service.resolve(args.project)
    if command == "status":
        data = service.summary(workspace)
        return _out(args, data, "\n".join(f"{k}: {v}" for k, v in data.items()))
    if command == "scan":
        return _scan(args, workspace)
    if command == "sources":
        rows = [
            s
            for s in workspace.load_sources().values()
            if s.present and (not args.category or s.category == args.category)
        ]
        rows.sort(key=lambda s: s.path)
        return _out(
            args,
            [s.to_dict() for s in rows],
            "\n".join(
                f"{s.source_id}  {s.category:24} {s.status:11} {s.evidence_count:4}  {s.path}"
                + (f"  ({s.status_reason})" if s.status_reason else "")
                for s in rows
            ),
        )
    if command == "classify":
        from howlwriter.projects.scan import set_category

        record = set_category(workspace, args.source, args.category, by=owner.actor(args))
        summary = f"{record.path}: {record.category} ({record.category_reason}; kept across rescans)"
        return _out(args, record.to_dict(), summary)
    if command == "evidence":
        items = list(workspace.load_evidence().values())
        if args.source:
            items = [e for e in items if args.source in (e.source_id, e.source_path)]
        if args.kind:
            items = [e for e in items if e.kind == args.kind]
        items.sort(key=lambda e: (e.source_path, str(e.locator)))
        items = items[: args.limit]
        return _out(
            args,
            [e.to_dict() for e in items],
            "\n".join(
                f"[{e.evidence_id}] {e.citation} ({e.status}, {e.method})\n    {e.excerpt[:200]}"
                for e in items
            ),
        )
    if command == "search":
        from howlwriter.projects.retrieval import EvidenceIndex

        hits = EvidenceIndex(workspace.load_evidence()).search(
            args.query, purpose=args.purpose, limit=args.limit
        )
        return _out(
            args,
            [h.to_dict() for h in hits],
            "\n".join(
                f"[{h.item.evidence_id}] {h.item.citation} ({h.item.status})\n    why: {h.explain()}\n    "
                f"{h.item.excerpt[:200]}"
                for h in hits
            )
            or "no matching evidence",
        )
    if command == "requirements":
        from howlwriter.projects.validate import coverage_check

        data = coverage_check(workspace)
        return _out(
            args,
            data,
            "\n".join(
                [
                    f"{data['total']} requirements; "
                    + ", ".join(f"{k} {v}" for k, v in data["by_status"].items())
                ]
                + [
                    f"{r['requirement_id']}  {r['status']:24} ({r['kind']}) {r['text'][:110]}\n"
                    f"    from {r['location']}; "
                    f"{r['reason']}"
                    for r in data["rows"]
                ]
            ),
        )
    if command == "require":
        from howlwriter.projects.requirements import add_requirement

        req = add_requirement(workspace, args.text, args.kind)
        return _out(
            args, req.to_dict(), f"{req.requirement_id} ({req.kind}) {req.status}: {req.status_reason}"
        )
    if command == "req-status":
        from howlwriter.projects.requirements import set_status

        req = set_status(
            workspace, args.requirement_id, "" if args.status == "clear" else args.status, args.note
        )
        return _out(args, req.to_dict(), f"{req.requirement_id}: {req.status}")
    if command == "compare":
        data = service.compare_captures(workspace, args.first, args.second)
        return _out(
            args,
            data,
            "\n".join(
                [f"{data['before']} -> {data['after']}"] + [f"- {f['statement']}" for f in data["findings"]]
            ),
        )
    if command == "brief":
        from howlwriter.projects.writing import build_brief

        brief = build_brief(workspace, sections=args.section, topic=args.topic)
        return _out(
            args,
            brief,
            "\n".join(
                [
                    f"{s['title']}: {len(s['evidence'])} evidence, {len(s['missing'])} missing"
                    for s in brief["sections"]
                ]
            ),
        )
    if command == "draft":
        return _draft(args, workspace)
    if command == "validate":
        from howlwriter.projects.validate import check_draft

        result = check_draft(workspace, Path(args.draft).read_text(encoding="utf-8"))
        text = [
            f"verdict: {result['verdict']}",
            f"citations: {result['citations']}, claim sentences: " f"{result['sentences_with_claims']}",
            "issues: " + (", ".join(f"{k} {v}" for k, v in result["issue_counts"].items()) or "none"),
        ]
        text += [f"  - {i['type']}: {i['sentence'][:160]}" for i in result["issues"][:30]]
        text += [f"  missing: {x}" for x in result["missing_placeholders"][:20]]
        cov = result["requirements"]
        text.append(
            f"requirements: {cov['total']}, unmet {cov['unmet']}: "
            + ", ".join(f"{k} {v}" for k, v in cov["by_status"].items())
        )
        _out(args, result, "\n".join(text))
        return 0 if result["verdict"] == "READY_FOR_HUMAN_REVIEW" else 3
    if command == "authorize-remote":
        if not args.revoke:  # revoking only ever keeps material local
            owner.source(args, "Authorizing remote inference", _SENDS)
        data = service.authorize_remote(workspace, not args.revoke)
        return _out(
            args,
            data,
            "remote inference "
            + ("authorized" if not args.revoke else "revoked")
            + f" for {workspace.project_id}",
        )
    if command == "browse":
        return _browse(args, workspace)
    if command == "actions":
        actions = workspace.load_actions()[-args.limit:]
        return _out(
            args,
            [a.to_dict() for a in actions],
            "\n".join(
                f"{a.requested_at} {a.mode:11} {a.kind:10} {a.decision:8} {a.outcome:7} "
                f"{'STATE-CHANGE ' if a.changed_state else ''}{a.url[:70]} {a.target[:40]} {a.error[:60]}"
                for a in actions
            )
            or "no browser actions",
        )
    raise ValueError(f"unknown project command {command}")


def _draft(args, workspace) -> int:
    from howlwriter.projects.writing import build_brief, draft, save_draft, skeleton
    from howlwriter.projects.workspace import utc_now

    if args.allow_remote and not args.skeleton:
        owner.source(args, "--allow-remote", _SENDS)

    brief = build_brief(workspace, sections=args.section, topic=args.topic)
    if args.skeleton:
        text = skeleton(brief, title=workspace.load_meta().get("name", ""))
        path = save_draft(workspace, text, {"created_at": utc_now(), "kind": "skeleton", "model": None})
        result = {"text": text, "path": str(path)}
    else:
        from howlwriter.config.loader import ConfigLoader
        from howlwriter.domain.modes import parse_mode
        from howlwriter.voice.selection import apply_selection

        mode = parse_mode(args.mode)
        config = ConfigLoader().load(mode=mode)
        apply_selection(
            config,
            voice=args.voice,
            voice_profile=args.voice_profile,
            spec_value=config.voice_profile,
            spec_source="config",
            identity=args.identity,
            auto_voice=args.auto_voice,
            allow_generic=args.allow_generic,
            mode=mode.value,
        )
        result = draft(
            workspace,
            brief,
            config=config,
            mode=args.mode,
            instructions=args.instructions,
            allow_remote=args.allow_remote,
            voice_examples=args.voice_examples,
            revise=args.voice_revision,
            progress=lambda message: print(message, file=sys.stderr),
        )
        _print_draft_report(result["provenance"])
    if args.out:
        Path(args.out).write_text(result["text"], encoding="utf-8")
    print(f"draft saved privately: {result['path']}", file=sys.stderr)
    code = _out(args, {k: v for k, v in result.items() if k != "prompt"}, result["text"])
    verdict = ((result.get("provenance") or {}).get("validation") or {}).get("verdict")
    if args.fail_if_blocked and not args.skeleton and verdict != "READY_FOR_HUMAN_REVIEW":
        return 3
    return code


def _print_draft_report(record: dict) -> None:
    """How the draft was written and how close it came to the person's voice (stderr)."""
    out = sys.stderr
    print(
        f"parts: {record.get('parts')}  voice: {record.get('voice_block_form')} description, "
        f"{(record.get('voice_examples') or {}).get('shown', 0)} style example(s) shown",
        file=out,
    )
    for repair in record.get("grounding_repairs") or []:
        state = "applied" if repair["applied"] else f"not applied ({repair['rejected_because']})"
        print(
            f"part {repair['part']}: citation repair {state}; problems "
            f"{repair['problems_before']} -> {repair['problems_after']}",
            file=out,
        )
    for revision in record.get("voice_revisions") or []:
        state = "applied" if revision["applied"] else f"not applied ({revision['rejected_because']})"
        print(f"part {revision['part']}: voice revision {state}", file=out)
    scores = record.get("scores") or {}
    if scores.get("voice_match") or scores.get("naturalness"):
        match, natural = scores.get("voice_match") or {}, scores.get("naturalness") or {}

        def shown(report: dict) -> str:
            return str(report.get("score") if report.get("score") is not None else report.get("status"))

        band = f" ({match['band']})" if match.get("band") else ""
        print(
            f"Voice Match: {shown(match)}{band}; Naturalness: {shown(natural)}; "
            f"style differences left: {scores.get('drift_findings')}",
            file=out,
        )
        print(scores.get("note", ""), file=out)
    validation = record.get("validation") or {}
    if validation:
        issues = ", ".join(f"{k} {v}" for k, v in sorted((validation.get("issue_counts") or {}).items()))
        print(f"Validator: {validation.get('verdict')}{' (' + issues + ')' if issues else ''}", file=out)
        if validation.get("verdict") in ("BLOCKED", "INCOMPLETE"):
            print(
                "This draft is not ready: run `project validate` for the sentences, fix or cite them, "
                "or redraft with a stronger model.",
                file=out,
            )


def _browse(args, workspace) -> int:
    from howlwriter.projects.browser import BrowserPolicy, BrowserPolicyError, BrowserSession

    policy = BrowserPolicy(mode=args.mode, allowed_origins=args.allow, interactive_origins=args.lab)
    session = BrowserSession(workspace, policy, headless=args.headless)
    results = []
    session.start()
    try:
        for step in args.step:
            verb, _, rest = step.partition(":")
            if verb == "goto":
                a = session.navigate(rest)
                results.append({"step": step, "outcome": a.outcome, "url": a.url, "error": a.error})
            elif verb == "read":
                item = session.read()
                results.append(
                    {
                        "step": step,
                        "evidence_id": item.evidence_id,
                        "citation": item.citation,
                        "injection_flagged": item.observation.get("prompt_injection_suspected"),
                    }
                )
            elif verb == "screenshot":
                item = session.screenshot(rest or "page")
                results.append(
                    {"step": step, "evidence_id": item.evidence_id, "file": item.observation["file"]}
                )
            elif verb in ("click", "fill", "fill-secret"):
                selector, _, value = rest.partition("=") if verb != "click" else (rest, "", "")
                try:
                    action_id = session.request(
                        "fill" if verb != "click" else "click",
                        selector,
                        value if verb == "fill" else None,
                        secret_env=value if verb == "fill-secret" else None,
                    )
                except BrowserPolicyError as error:
                    results.append({"step": step, "outcome": "refused", "error": str(error)})
                    continue
                pending = session.pending[action_id].action
                approved = (
                    args.yes
                    or input(
                        f"APPROVE state change: {pending.kind} {pending.target} on {pending.url}? [y/N] "
                    )
                    .strip()
                    .lower()
                    == "y"
                )
                action = session.approve(action_id) if approved else session.deny(action_id)
                results.append(
                    {
                        "step": step,
                        "outcome": action.outcome,
                        "decision": action.decision,
                        "changed_state": action.changed_state,
                        "evidence_ids": action.evidence_ids,
                    }
                )
            else:
                raise ValueError(f"unknown step {step!r}")
    finally:
        blocked = list(session.blocked)
        session.stop()
    payload = {"mode": args.mode, "steps": results, "blocked_requests": blocked}
    return _out(
        args,
        payload,
        "\n".join(
            [f"- {r['step']}: " + ", ".join(f"{k}={v}" for k, v in r.items() if k != "step") for r in results]
            + [f"blocked: {b['method']} {b['url'][:80]} ({b['reason']})" for b in blocked]
        ),
    )
