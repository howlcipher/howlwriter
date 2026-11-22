"""Check the exported DOCX rather than the intermediary Markdown."""

import io
from pathlib import Path

import docx

from howlwriter.domain.document import Document
from howlwriter.rendering import DocxRenderer, RenderContext

FIXTURE = Path(__file__).parent / "fixtures" / "heading_adjacent.md"


def _render(text):
    artifact = DocxRenderer().render(Document.parse(text), RenderContext(title="Synthetic paper"))
    return docx.Document(io.BytesIO(artifact.raw_bytes)).paragraphs


def test_docx_retains_prose_immediately_after_heading():
    paragraphs = [(p.style.name, p.text) for p in _render(FIXTURE.read_text(encoding="utf-8"))]
    assert paragraphs[1:] == [
        ("Heading 2", "Results"),
        ("Normal", "Measurement evidence belongs in the exported paper."),
        ("Heading 2", "References"),
        ("Normal", "Synthetic reference is preserved."),
    ]


def test_docx_preserves_heading_depth_and_reference_scope():
    paragraphs = _render(
        "# Synthetic paper\nOpening prose.\n## Results\n### Detail\nA result.\n"
        "## References\nA reference.\n## Appendix\nAppendix prose."
    )
    assert [(p.style.name, p.text) for p in paragraphs[1:]] == [
        ("Normal", "Opening prose."),
        ("Heading 2", "Results"),
        ("Heading 3", "Detail"),
        ("Normal", "A result."),
        ("Heading 2", "References"),
        ("Normal", "A reference."),
        ("Heading 2", "Appendix"),
        ("Normal", "Appendix prose."),
    ]
    assert paragraphs[6].paragraph_format.first_line_indent.inches == -0.5
    assert paragraphs[8].paragraph_format.first_line_indent is None


def test_docx_adjacent_fenced_code_preserves_heading_like_lines():
    paragraphs = _render("## Example\n```text\n## literal\n\n### also literal\n```")
    assert [(p.style.name, p.text) for p in paragraphs[1:]] == [
        ("Heading 2", "Example"),
        ("Normal", "## literal\n\n### also literal"),
    ]


def test_docx_indented_fence_keeps_info_bearing_lines_literal():
    paragraphs = _render(
        "## Example\n   ```text\nBefore\n```literal\n## Still code\n   ````\n\nFollowing prose."
    )
    assert [(p.style.name, p.text) for p in paragraphs[1:]] == [
        ("Heading 2", "Example"),
        ("Normal", "Before\n```literal\n## Still code"),
        ("Normal", "Following prose."),
    ]


def test_docx_long_fence_preserves_shorter_fence_as_code():
    paragraphs = _render("## Example\n````text\n```\n## Still code\n````\n\nFollowing prose.")
    assert [(p.style.name, p.text) for p in paragraphs[1:]] == [
        ("Heading 2", "Example"),
        ("Normal", "```\n## Still code"),
        ("Normal", "Following prose."),
    ]
