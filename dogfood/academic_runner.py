#!/usr/bin/env python3
"""Phase 10.5 -- one realistic academic outline through the full pipeline.

Live: real research retrieval, real model calls, real APA formatting. The
point is not the paper but whether the outline constrains a pipeline that
still runs every check it ran before.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback
from datetime import datetime, timezone

DOGFOOD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOGFOOD_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, os.environ.get("HOWLPLANE_ROOT", str(REPO_ROOT.parent / "howlplane")))

os.environ.setdefault("HOWLPLANE_ROLE_WRITING_WRITER", "agy")
os.environ.setdefault("HOWLPLANE_ROLE_WRITING_HUMANIZER", "agy")
os.environ.setdefault("HOWLPLANE_ROLE_WRITING_FINAL_REVIEWER", "codex")

RESULTS = Path(os.environ.get("HOWLWRITER_BENCH_RESULTS", DOGFOOD_DIR / "milestone_results"))
OUTLINE = DOGFOOD_DIR / "outlines" / "academic_credential_abuse.yaml"


def main() -> int:
    from howlwriter.academic.ai_disclosure import render_provenance_appendix
    from howlwriter.academic.pipeline import run_academic_pipeline
    from howlwriter.config.loader import ConfigLoader
    from howlwriter.domain.modes import WritingMode
    from howlwriter.domain.outline import load_outline
    from howlwriter.provenance.assemble import finalize

    outline = load_outline(OUTLINE)
    config = ConfigLoader().load(mode=WritingMode.ACADEMIC)
    config.voice_profile = outline.voice_profile

    started = time.time()
    payload = {
        "experiment": "academic_outline",
        "schema": "howlwriter.benchmark/v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "outline_path": str(OUTLINE),
        "status": "OK",
    }
    try:
        result = run_academic_pipeline(
            None, config=config, outline=outline, cwd=DOGFOOD_DIR
        )
        provenance = finalize(result.provenance, level="full")
        payload.update(
            {
                "output": result.final_document.text,
                "report_status": result.report.status,
                "words": len(result.final_document.text.split()),
                "authorship_coverage": (
                    result.authorship_coverage.to_dict()
                    if result.authorship_coverage else None
                ),
                "outline_conformance": result.outline_result.to_dict(),
                "coverage_result": result.coverage_result.to_dict(),
                "sources": [s.to_dict() for s in result.sources],
                "source_count": len(result.sources),
                "claims": len(result.provenance_graph.claims),
                "unsupported_claims": [
                    c.text for c in result.provenance_graph.unsupported_claims()
                ],
                "citation_analysis": result.citation_analysis.to_dict(),
                "ai_use_statement": result.ai_use_statement.to_dict(),
                "ai_use_rendered": result.ai_use_statement.render(),
                "provenance_appendix": render_provenance_appendix(provenance),
                "provenance": json.loads(provenance.to_json()),
                "report": result.report.to_dict(),
            }
        )
        print("status:", result.report.status, "| words:", payload["words"])
        print("sources:", payload["source_count"], "| claims:", payload["claims"])
        if result.authorship_coverage:
            print("authorship coverage:", result.authorship_coverage.status)
    except Exception as exc:                                    # noqa: BLE001
        payload.update(
            {
                "status": "FAILED",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-3000:],
            }
        )
        print("FAILED:", type(exc).__name__, exc)

    payload["duration_seconds"] = round(time.time() - started, 2)
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / "academic_outline.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
