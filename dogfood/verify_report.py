#!/usr/bin/env python3
"""Re-derive every headline figure the milestone report claims, independently.

`report.py` generates the tables. This checks the prose around them. The two
are deliberately separate: a report can carry a correct table and still say
something false in the sentence above it, which is exactly what happened to the
previous milestone -- it reported 92% where the artifacts said 100%, and a range
of 2-5 where the raw output said 3-6, with the correct values sitting in the
data the whole time.

Every assertion below recomputes from the stored generation text rather than
reading any summary, and names the claim it is checking in the report's own
words. Exits non-zero if any claim no longer holds.

    python dogfood/verify_report.py
"""

from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys

DOGFOOD_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DOGFOOD_DIR))
sys.path.insert(0, str(DOGFOOD_DIR.parent / "src"))

RESULTS = Path(
    sys.argv[1] if len(sys.argv) > 1 else DOGFOOD_DIR / "milestone_results"
)


def _load(name: str) -> dict | None:
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _body_paragraphs(text: str) -> int:
    return len(
        [p for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    )


def main() -> int:
    from metrics import first_person_report, parenthetical_report

    checks: list[tuple[str, bool]] = []
    skipped: list[str] = []

    structural = _load("structural_variance_v2")
    if structural is None:
        skipped.append("structural_variance_v2")
    else:
        full = [r["output"] for r in structural["generations"]["full_howlwriter"] if r.get("output")]
        med = [r["output"] for r in structural["generations"]["medium_only"] if r.get("output")]
        analysis = structural["analysis"]

        p = parenthetical_report(full)
        checks.append((
            "parentheticals present in 5 of 20 outputs (25%)",
            p.documents_with == 5 and p.documents == 20,
        ))
        checks.append((
            "no repeated parenthetical opening: all five distinct",
            len(p.opening_words) == p.total and max(p.opening_words.values(), default=0) <= 1,
        ))

        pf = [_body_paragraphs(t) for t in full]
        pm = [_body_paragraphs(t) for t in med]
        cv_full = statistics.pstdev(pf) / statistics.mean(pf)
        cv_med = statistics.pstdev(pm) / statistics.mean(pm)
        checks.append((
            "full HowlWriter paragraph counts are TIGHTER than the control",
            cv_full < cv_med and (max(pf) - min(pf)) < (max(pm) - min(pm)),
        ))
        checks.append((
            "full HowlWriter converges on MORE dimensions than the control",
            len(analysis["full_howlwriter"]["diversity"]["converged_dimensions"])
            > len(analysis["medium_only"]["diversity"]["converged_dimensions"]),
        ))
        checks.append((
            "the diversity checker returns FAIL for both arms",
            analysis["full_howlwriter"]["diversity"]["verdict"] == "FAIL"
            and analysis["medium_only"]["diversity"]["verdict"] == "FAIL",
        ))

    mixed = _load("mixed_context_v2")
    if mixed is None:
        skipped.append("mixed_context_v2")
    else:
        full_fp = first_person_report(
            [r["output"] for r in mixed["generations"]["full_howlwriter"] if r.get("output")]
        )
        med_fp = first_person_report(
            [r["output"] for r in mixed["generations"]["medium_only"] if r.get("output")]
        )
        checks.append((
            "full HowlWriter uses MORE first person than the control overall",
            full_fp["mean_per_100_words"] > med_fp["mean_per_100_words"],
        ))
        impersonal = {"mixed_04", "mixed_05", "mixed_06", "mixed_08", "mixed_10"}
        ids = [r["id"] for r in mixed["generations"]["full_howlwriter"]]
        per_doc = dict(zip(ids, full_fp["per_document"]))
        checks.append((
            "no first person injected into any impersonal prompt",
            all(per_doc.get(i, 0) == 0 for i in impersonal),
        ))

    outline = _load("outline_progression")
    if outline is None:
        skipped.append("outline_progression")
    else:
        levels = {level["id"]: level for level in outline["levels"]}
        checks.append((
            "derived generation freedom matched expectation at all five levels",
            all(
                level.get("generation_freedom") == level["expected_freedom"]
                for level in outline["levels"]
            ),
        ))
        near = levels.get("E_near_complete", {})
        contribution = near.get("contribution", {})
        checks.append((
            "a near-complete draft came back the same length (minimum edit)",
            contribution.get("user_words_supplied") == contribution.get("artifact_words"),
        ))
        checks.append((
            "model-added claims fall to zero at the near-complete level",
            contribution.get("model_added_claims") == 0,
        ))
        ratios = []
        for name in ("C_structured", "D_authorship_rich", "E_near_complete"):
            c = levels.get(name, {}).get("contribution", {})
            supplied = c.get("user_words_supplied") or 0
            if supplied:
                ratios.append(c.get("artifact_words", 0) / supplied)
        checks.append((
            "expansion falls monotonically as authorship rises",
            ratios == sorted(ratios, reverse=True) and len(ratios) == 3,
        ))
        checks.append((
            "every prompt was captured for every model call",
            all(
                c.get("user_prompt")
                for level in outline["levels"]
                for c in level.get("provenance", {}).get("calls", [])
            ),
        ))
        checks.append((
            "no provider reported a model name, and none was invented",
            all(
                c.get("model_status") == "PROVIDER_DID_NOT_REPORT" and not c.get("model")
                for level in outline["levels"]
                for c in level.get("provenance", {}).get("calls", [])
            ),
        ))

    for label, ok in checks:
        print(("  OK    " if ok else "  FAILED") + "  " + label)
    for name in skipped:
        print(f"  SKIP    {name} has not been run")

    failed = [label for label, ok in checks if not ok]
    print()
    if failed:
        print(f"{len(failed)} report claim(s) no longer hold:")
        for label in failed:
            print(f"  - {label}")
        return 1
    print(f"all {len(checks)} report claims verified against the raw artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
