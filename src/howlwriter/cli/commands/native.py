"""`howlwriter native` -- the bounded, structured Writer path.

  request  build a howlwriter.request/v1 from a Dream export and a copy spec
  write    run one bounded remote provider call and emit a copy package
  amend    record an operator edit to one proposal without crediting Writer
  check    run the deterministic factual fidelity check on two texts

No subcommand launches a coding agent, runs git, or writes anywhere other
than the paths given on the command line.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from howlwriter.native.contracts import ContractError, WriterRequest
from howlwriter.native.engine import WriterExecutionError, amend, command_provider, write_copy
from howlwriter.native.fidelity import compare
from howlwriter.native.intake import request_from_dream, request_from_operator

EXIT_PROVIDER_FAILURE = 3
EXIT_FACTUAL_FINDINGS = 4


def _load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error.msg} (line {error.lineno})") from None


def _emit(value: dict, out: str | None) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "native", help="Bounded structured copy rewriting (Dream -> Writer -> Create handoff)."
    )
    native = parser.add_subparsers(dest="native_command", required=True)

    req = native.add_parser("request", help="Build a Writer request from a Dream export and copy spec.")
    req.add_argument("--spec", required=True, help="Copy spec JSON: items, audience, constraints.")
    req.add_argument("--from-dream", help="howl.candidate/v1 JSON from `howldream export`.")
    req.add_argument("--out", help="Write the request here instead of stdout.")
    req.set_defaults(handler=_run_request)

    write = native.add_parser("write", help="Run one bounded provider call; emit a copy package.")
    write.add_argument("--request", required=True)
    write.add_argument("--command-config", required=True,
                       help="Operator provider-core command config (remote only).")
    write.add_argument("--allow-local", action="store_true",
                       help="Permit local inference; ignored while HOWL_FORBID_LOCAL_INFERENCE is set.")
    write.add_argument("--out", help="Write the copy package here instead of stdout.")
    write.add_argument("--failure-out", help="Write sanitized failure metadata here on failure.")
    write.set_defaults(handler=_run_write)

    edit = native.add_parser("amend", help="Record an operator edit to one proposal.")
    edit.add_argument("--request", required=True)
    edit.add_argument("--package", required=True)
    edit.add_argument("--item", required=True)
    edit.add_argument("--text", required=True)
    edit.add_argument("--reason", required=True)
    edit.add_argument("--editor", default="operator")
    edit.add_argument("--out", help="Defaults to rewriting --package in place.")
    edit.set_defaults(handler=_run_amend)

    check = native.add_parser("check", help="Deterministic factual fidelity check.")
    check.add_argument("--source", required=True, help="File with the source copy.")
    check.add_argument("--proposal", required=True, help="File with the proposed copy.")
    check.add_argument("--evidence", action="append", default=[], help="Canonical evidence file.")
    check.set_defaults(handler=_run_check)
    return parser


def _run_request(args: argparse.Namespace) -> int:
    spec = _load(args.spec)
    try:
        if args.from_dream:
            request = request_from_dream(_load(args.from_dream), spec)
        else:
            request = request_from_operator(spec)
    except ContractError as error:
        raise ValueError(str(error)) from None
    _emit(request.to_dict(), args.out)
    return 0


def _run_write(args: argparse.Namespace) -> int:
    try:
        request = WriterRequest.from_dict(_load(args.request))
    except ContractError as error:
        raise ValueError(str(error)) from None
    try:
        provider = command_provider(args.command_config, allow_local=args.allow_local)
        package = write_copy(request, provider)
    except WriterExecutionError as error:
        failure = {
            "status": "FAILED",
            "stage": "howlwriter.native.write",
            "request_id": request.request_id,
            "source_idea_id": request.source_idea_id,
            "failure": error.failure,
            "execution": error.execution,
        }
        if args.failure_out:
            _emit(failure, args.failure_out)
        print(f"error: provider call failed: {error}", file=sys.stderr)
        return EXIT_PROVIDER_FAILURE
    except Exception as error:  # provider-core config/policy errors
        if type(error).__name__ == "ProviderError":
            print(f"error: {error}", file=sys.stderr)
            return EXIT_PROVIDER_FAILURE
        raise
    _emit(package.to_dict(), args.out)
    print(
        f"{package.writer_proposal_id}: {len(package.proposals)} proposals, "
        f"factual_status={package.factual_status}",
        file=sys.stderr,
    )
    return 0


def _run_amend(args: argparse.Namespace) -> int:
    request = WriterRequest.from_dict(_load(args.request))
    package = amend(_load(args.package), request, args.item, args.text,
                    reason=args.reason, editor=args.editor)
    _emit(package, args.out or args.package)
    return 0


def _run_check(args: argparse.Namespace) -> int:
    source = Path(args.source).read_text(encoding="utf-8")
    proposal = Path(args.proposal).read_text(encoding="utf-8")
    evidence = [Path(p).read_text(encoding="utf-8") for p in args.evidence]
    result = compare(source, proposal, evidence=evidence)
    _emit(result.to_dict(), None)
    return 0 if result.status == "FACTUALLY_PRESERVED" else EXIT_FACTUAL_FINDINGS
