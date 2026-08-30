import pytest

from howlwriter.domain.document import Document
from howlwriter.editing.editor import NotConfiguredEditor, PassthroughEditor
from howlwriter.integration.model_role import ModelRoleNotConfiguredError

editor = PassthroughEditor()


def _word_tokens(text: str) -> set[str]:
    return set(text.split())


def test_passthrough_editor_normalizes_without_altering_word_content():
    raw = "Title.  \n\n\n\nBody\t\ttext here.\n\nSecond   paragraph.   "
    document = Document.parse(raw, title="t")
    edited = editor.edit(document)

    assert _word_tokens(edited.text) == _word_tokens(raw)


def test_passthrough_editor_collapses_multiple_blank_lines():
    raw = "First.\n\n\n\n\nSecond."
    edited = editor.edit(Document.parse(raw, title="t"))
    assert "\n\n\n" not in edited.text


def test_passthrough_editor_spaces_heading_markers():
    raw = "#Heading\n\nBody text."
    edited = editor.edit(Document.parse(raw, title="t"))
    assert edited.paragraphs[0].raw_text.startswith("# Heading")


def test_passthrough_editor_strips_trailing_whitespace():
    raw = "Line with trailing space.   \n\nSecond paragraph."
    edited = editor.edit(Document.parse(raw, title="t"))
    assert not any(line.endswith(" ") for line in edited.text.splitlines())


def test_not_configured_editor_raises():
    document = Document.parse("Text.", title="t")
    with pytest.raises(ModelRoleNotConfiguredError):
        NotConfiguredEditor().edit(document)
