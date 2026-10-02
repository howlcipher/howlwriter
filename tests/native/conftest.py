import json
from pathlib import Path
import sys

import pytest

FAKE = Path(__file__).with_name("fake_provider.py")


@pytest.fixture
def command_config(tmp_path):
    def make(mode: str = "echo") -> Path:
        path = tmp_path / f"provider-{mode}.json"
        path.write_text(json.dumps({
            "argv": [sys.executable, str(FAKE), mode],
            "remote": True,
            "timeout_seconds": 30,
            "output_format": "claude-json",
        }))
        return path
    return make


@pytest.fixture
def dream_candidate():
    return {
        "schema_version": "howl.candidate/v1",
        "candidate_id": "hd-20261002-000000-abcdefabcdef/candidate/3",
        "source_run_id": "hd-20261002-000000-abcdefabcdef",
        "parent_request_id": "hd-20261002-000000-abcdefabcdef",
        "objective": "Make the portfolio lead with software artifacts.",
        "text": "Lead with the deployment CLI and keep verification metrics in context.",
        "status": "GENERATED",
        "authority": {"type": "ADVISORY", "executable": False},
        "evidence_refs": ["resume.json#stats"],
        "assumptions": ["Visitors scan the first screen only."],
        "contradictions": [],
        "provenance": {
            "producer_component": "howldream",
            "run_id": "hd-20261002-000000-abcdefabcdef",
            "transformations": ["run_candidate_export"],
            "hard_constraints": ["Do not claim production adoption."],
            "execution": {"inference_occurred": True, "mocked": False},
        },
    }


@pytest.fixture
def copy_spec():
    return {
        "audience": "engineering hiring managers",
        "factual_constraints": ["Keep dry-run qualifiers."],
        "items": [
            {
                "item_id": "verification",
                "desired_copy_role": "Selected Work verification line",
                "current_copy": (
                    "Dry-run validated representative deployment paths for 25 of 28 repositories."
                ),
                "max_words": 20,
                "evidence": [{"ref": "resume.json#ach-cicd", "text":
                              "dry-run validated representative deployment paths for 25 of 28 repositories"}],
            },
            {
                "item_id": "scope",
                "desired_copy_role": "Selected Work scope line",
                "current_copy": (
                    "56 Azure DevOps build/release definitions across 28 standardized repositories."
                ),
                "evidence": [],
            },
        ],
    }
