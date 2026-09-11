"""Security and privacy boundary guards for benchmark datasets and fixtures."""

from __future__ import annotations

from pathlib import Path
import re
from howlwriter.evaluation.fixtures import DATASET_PATH, load_all_cases

_CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)(?:api_key|secret_key|private_key|auth_token|bearer\s+[a-z0-9_\-\.]{20,})"),
    re.compile(r"ghp_[A-Za-z0-9_]{36}"),
    re.compile(r"sk-[A-Za-z0-9_-]{32,}"),
]


def test_no_credentials_in_benchmark_dataset():
    raw_content = DATASET_PATH.read_text(encoding="utf-8")
    for pattern in _CREDENTIAL_PATTERNS:
        match = pattern.search(raw_content)
        assert match is None, f"Potential credential or sensitive token found in cases.yaml: {match.group(0)}"


def test_no_private_user_data_in_cases():
    cases = load_all_cases()
    # Ensure all cases are synthetic or public open-access standards
    for case in cases:
        assert not case.id.startswith("private_"), f"Private case prefix found in {case.id}"
        # Context should not contain absolute home paths or user directory paths
        for k, v in case.context.items():
            val_str = str(v)
            assert "/home/" not in val_str, f"User directory path found in context of {case.id}"
            assert "/Users/" not in val_str, f"User directory path found in context of {case.id}"


def test_evaluation_output_directory_ignored():
    gitignore_path = Path(".gitignore")
    assert gitignore_path.is_file()
    content = gitignore_path.read_text(encoding="utf-8")
    assert "output/*" in content, ".gitignore must contain output/* to keep benchmark runs private."
