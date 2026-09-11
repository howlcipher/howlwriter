"""`howlwriter publish <file> --to <destination>` -- publish finished deliverables to cloud destinations."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from howlwriter.diagnostic.run_record import compute_sha256, generate_run_id
from howlwriter.publishing import (
    PublicationArtifact,
    PublishContext,
    PublishDestination,
    get_publisher,
)


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "publish",
        help="Publish a finished deliverable to Google Docs or other destinations.",
    )
    parser.add_argument(
        "file",
        help="Path to file to publish (Markdown, DOCX, or text).",
    )
    parser.add_argument(
        "--to",
        dest="destination",
        required=True,
        help="Publish destination (e.g. google-docs).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Document title in target destination (default: derived from filename or file content).",
    )
    parser.add_argument(
        "--folder",
        default=None,
        help="Target folder name or ID in destination (e.g. cloud storage folder ID).",
    )
    parser.add_argument(
        "--update-doc",
        dest="update_doc_id",
        default=None,
        help="Explicit document ID to update rather than creating a new document.",
    )
    parser.add_argument(
        "--update-mode",
        dest="update_mode",
        choices=["replace", "append"],
        default="replace",
        help="Update mode when updating an existing document ('replace' or 'append').",
    )
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="Allow publication of documents without prior verification authorization.",
    )
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"error: file not found: '{args.file}'", file=sys.stderr)
        return 1

    content_bytes = file_path.read_bytes()
    try:
        content_text = content_bytes.decode("utf-8")
        is_text = True
    except UnicodeDecodeError:
        content_text = ""
        is_text = False

    # Derive title
    title = args.title
    if not title:
        if is_text and content_text.startswith("# "):
            title = content_text.split("\n", 1)[0][2:].strip()
        else:
            title = file_path.stem.replace("-", " ").replace("_", " ").title()

    run_id = generate_run_id()
    content_hash = compute_sha256(content_text if is_text else str(content_bytes))

    artifact = PublicationArtifact(
        title=title,
        content=content_text if is_text else content_bytes,
        format=file_path.suffix.lstrip(".").lower() or "txt",
        source_run_id=run_id,
        authorized_sha256=content_hash,
        metadata={"status": "READY" if args.allow_unverified else "UNKNOWN"},
    )

    dest = PublishDestination(
        destination_type=args.destination,
        target=args.folder or title,
        folder=args.folder,
        update_doc_id=args.update_doc_id,
        update_mode=args.update_mode,
        metadata={"title": title},
    )

    ctx = PublishContext(
        run_id=run_id,
        allow_unverified=args.allow_unverified,
    )

    try:
        publisher = get_publisher(args.destination)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Publishing '{file_path.name}' to {args.destination}...")
    result = publisher.publish(artifact, dest, ctx)

    if result.is_success:
        print("\nPublication Successful!")
        print(f"  Destination: {result.destination_type}")
        print(f"  Title:       {result.artifact_title}")
        if result.artifact_id:
            print(f"  Document ID: {result.artifact_id}")
        if result.url:
            print(f"  URL:         {result.url}")
        print(f"  Published:   {result.published_at}")
        return 0
    else:
        print(f"\nPublication Failed: {result.status}", file=sys.stderr)
        for diag in result.diagnostics:
            print(f"  - {diag}", file=sys.stderr)
        return 1
