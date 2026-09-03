"""Tests for repository portability and machine-independent configuration.

Verifies:
1. No dependency on William-specific filesystem paths (/run/media/system/tallgeese).
2. Portable discovery of HowlPlane via HOWLPLANE_ROOT.
3. Honest failure with ModelRoleNotConfiguredError when model execution is absent.
4. Run records do not emit machine-specific HowlPlane paths.
5. Runtime source tree contains no private machine-root paths.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from howlwriter.citations.apa7 import APA7Formatter
from howlwriter.diagnostic.run_record import (
    RunRecord,
    get_howlplane_git_revision,
)
from howlwriter.domain.document import Document
from howlwriter.domain.source import Source, SourceType
from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    _ensure_howlplane_on_path,
)
from howlwriter.integration.model_role import (
    ModelRoleNotConfiguredError,
    WritingRole,
)
from howlwriter.linting.engine import LintEngine


def test_no_machine_path_dependency():
    """A clean environment with no machine paths runs ordinary HowlWriter functionality."""
    machine_path = "/run/media/system/tallgeese/dev/howlplane"
    assert machine_path not in sys.path

    # Verify deterministic linting
    from howlwriter.config.schema import BannedWord, HowlWriterConfig
    from howlwriter.linting import rules

    doc = Document.parse("In conclusion, it is important to delve into this tapestry.", title="test")
    config = HowlWriterConfig(banned_words=[BannedWord(word="delve")])
    engine = LintEngine()
    findings = engine.run(doc, config)
    assert any(f.rule_code == rules.AI_STYLE_BANNED_WORD for f in findings)

    # Verify deterministic APA 7 citation
    from datetime import date

    src = Source(
        id="src-1",
        title="Attention Is All You Need",
        authors=["Vaswani, A."],
        publication_date=date(2017, 6, 12),
        source_type=SourceType.JOURNAL_ARTICLE,
    )
    formatter = APA7Formatter()
    cite = formatter.in_text_parenthetical(src)
    assert "(Vaswani, 2017)" in cite.text


def test_optional_howlplane_discovery_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """HOWLPLANE_ROOT environment variable enables dynamic discovery."""
    fake_root = tmp_path / "mock_howlplane"
    fake_root.mkdir()
    fake_src = fake_root / "src"
    fake_src.mkdir()

    monkeypatch.setenv("HOWLPLANE_ROOT", str(fake_root))

    # Clean from sys.path if already present
    sys.path = [p for p in sys.path if p != str(fake_root.resolve())]

    _ensure_howlplane_on_path()
    assert str(fake_root.resolve()) in sys.path

    # Cleanup sys.path after test
    sys.path = [p for p in sys.path if p != str(fake_root.resolve())]


def test_honest_absence_raises_model_role_not_configured(monkeypatch: pytest.MonkeyPatch):
    """When HowlPlane is unconfigured or absent, requesting model execution raises ModelRoleNotConfiguredError."""
    # Case 1: HowlPlane integration completely unavailable
    monkeypatch.setattr(
        "howlwriter.integration.howlplane_bridge._try_import_howlplane",
        lambda: None,
    )
    bridge_unavailable = HowlPlaneWritingBridge(dispatcher=None, registry=None)
    assert bridge_unavailable.is_available() is False

    with pytest.raises(ModelRoleNotConfiguredError) as exc_info:
        bridge_unavailable.execute_writing_role(
            role=WritingRole.WRITER,
            prompt="Draft an academic paper about zero trust architectures.",
        )
    assert exc_info.value.role == WritingRole.WRITER

    # Case 2: HowlPlane bridge is present but the specific role is unconfigured
    monkeypatch.undo()
    bridge_unconfigured = HowlPlaneWritingBridge()
    assert bridge_unconfigured.is_role_configured(WritingRole.WRITER) is False

    with pytest.raises(ModelRoleNotConfiguredError) as exc_info2:
        bridge_unconfigured.execute_writing_role(
            role=WritingRole.WRITER,
            prompt="Draft an academic paper about zero trust architectures.",
        )
    assert exc_info2.value.role == WritingRole.WRITER


def test_run_record_no_machine_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """RunRecord does not emit machine-specific HowlPlane paths."""
    monkeypatch.delenv("HOWLPLANE_ROOT", raising=False)

    rev = get_howlplane_git_revision()
    assert rev is None or not any(
        forbidden in str(rev)
        for forbidden in ["/run/media/system/tallgeese", "/home/howlcipher"]
    )

    record = RunRecord(command="lint")
    data = record.to_dict()
    assert "/run/media/system/tallgeese" not in str(data)
    assert "/home/howlcipher" not in str(data)

    # When HOWLPLANE_ROOT points to a valid git repo, revision is discovered
    git_dir = tmp_path / "fake_repo"
    git_dir.mkdir()
    (git_dir / ".git").mkdir()

    # Stub git rev-parse inside that directory
    def fake_get_git_revision(repo_dir=None):
        if repo_dir and str(repo_dir) == str(git_dir.resolve()):
            return "abc1234"
        return None

    monkeypatch.setattr(
        "howlwriter.diagnostic.run_record.get_git_revision",
        fake_get_git_revision,
    )
    monkeypatch.setenv("HOWLPLANE_ROOT", str(git_dir))
    discovered = get_howlplane_git_revision()
    assert discovered == "abc1234"


def test_runtime_source_contains_no_private_machine_roots():
    """Regression check: private machine-root paths must not exist in runtime source."""
    repo_root = Path(__file__).resolve().parents[2]
    src_dir = repo_root / "src"

    forbidden_patterns = [
        "/run/media/system/tallgeese",
        "/home/howlcipher",
    ]

    violations = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden_patterns:
            if pattern in text:
                violations.append(f"{py_file.relative_to(repo_root)}: contains '{pattern}'")

    assert violations == [], f"Private machine-root path detected in runtime source: {violations}"
