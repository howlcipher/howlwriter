"""Standalone semantic-review calibration helper for audit use."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Use the installed howlwriter from the audit worktree
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from howlwriter.domain.document import Document
from howlwriter.review.meaning import RealModelMeaningReviewer


def main() -> int:
    if len(sys.argv) != 5:
        print(
            "usage: review_calibrate.py <original.md> <revised.md> "
            "<humanizer_provider> <reviewer_provider>",
            file=sys.stderr,
        )
        return 2

    original_path, revised_path, humanizer_provider, reviewer_provider = sys.argv[1:5]
    os.environ["HOWLPLANE_ROLE_WRITING_FINAL_REVIEWER"] = reviewer_provider

    original = Document.parse(Path(original_path).read_text(encoding="utf-8"), title="original")
    revised = Document.parse(Path(revised_path).read_text(encoding="utf-8"), title="revised")

    result = RealModelMeaningReviewer().compare(
        original,
        revised,
        humanizer_provider=humanizer_provider,
    )
    print(f"REVIEWER: {reviewer_provider}")
    print(f"VERDICT: {result.verdict}")
    print(f"INDEPENDENCE: {result.independence_status}")
    print(f"RATIONALE: {result.rationale}")
    for d in result.differences:
        print(f"  - [{d.kind}] {d.description}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
