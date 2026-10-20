"""`howlwriter writer` flags citations that match no supplied source."""

from types import SimpleNamespace

import pytest

from howlwriter.cli.commands import writer as writer_command
from howlwriter.cli.main import main
from howlwriter.domain.document import Document


@pytest.fixture
def drafted(monkeypatch):
    """Run `writer` with a configured role and a fake model that returns the given text."""

    def use(text: str) -> None:
        bridge = SimpleNamespace(is_role_configured=lambda role: True)
        monkeypatch.setattr(writer_command, "get_howlplane_bridge", lambda: bridge)

        class FakeWriter:
            def draft_paper(self, spec, sources, config=None):
                return SimpleNamespace(document=Document.parse(text, title=spec.title))

        monkeypatch.setattr(writer_command, "ModelAcademicWriter", FakeWriter)

    return use


def test_invented_citation_is_reported_and_fails_only_when_asked(drafted, capsys, tmp_path):
    drafted("Updates close known holes (Smith, 2024).")
    out = tmp_path / "draft.md"

    assert main(["writer", "--out", str(out), "--", "Why update software"]) == 0
    assert "cites 1 work(s) that are not in the sources: Smith, 2024" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8").startswith("Updates close known holes")

    assert main(["writer", "--fail-if-blocked", "--out", str(out), "--", "Why update software"]) == 3


def test_draft_without_citations_passes_the_check(drafted, capsys, tmp_path):
    drafted("Updates close known holes.")
    assert main(["writer", "--fail-if-blocked", "--out", str(tmp_path / "d.md"), "--", "Why update"]) == 0
    assert "warning" not in capsys.readouterr().err


def test_invented_identifier_is_reported_unless_the_prompt_names_it(drafted, capsys, tmp_path):
    drafted("A patch fixed CVE-2099-12345 last spring.")
    out = str(tmp_path / "d.md")
    assert main(["writer", "--fail-if-blocked", "--out", out, "--", "Why update software"]) == 3
    assert "exact identifier(s) found in no source or the prompt: CVE-2099-12345" in capsys.readouterr().err

    assert main(["writer", "--fail-if-blocked", "--out", out, "--", "Explain CVE-2099-12345"]) == 0
