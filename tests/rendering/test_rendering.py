"""Tests for multi-format document rendering engine: Markdown, DOCX, PDF, and CombinedDocument."""

import io
import pytest

from howlwriter.domain.document import Document
from howlwriter.domain.source import Source, SourceType
from howlwriter.rendering import (
    DocxRenderer,
    DocumentSection,
    MarkdownRenderer,
    PdfRenderer,
    RenderContext,
    build_combined_document,
)


def test_markdown_renderer_plain():
    doc = Document.parse(
        "# Title\n\nParagraph 1.\n\nParagraph 2 with [link](https://example.com).",
        title="test.md",
    )
    renderer = MarkdownRenderer()
    ctx = RenderContext(title="Test Title")
    artifact = renderer.render(doc, ctx)

    assert artifact.format in ("md", "markdown")
    assert artifact.text_content is not None
    assert "# Title" in artifact.text_content
    assert "Paragraph 1." in artifact.text_content
    assert "https://example.com" in artifact.text_content


def test_markdown_renderer_with_frontmatter():
    doc = Document.parse("Body content.", title="test.md")
    renderer = MarkdownRenderer(include_frontmatter=True)
    ctx = RenderContext(title="Paper", metadata={"author": "Alice", "style": "apa7"})
    artifact = renderer.render(doc, ctx)

    assert artifact.text_content.startswith("---")
    assert "author: Alice" in artifact.text_content
    assert "style: apa7" in artifact.text_content
    assert "Body content." in artifact.text_content


def test_docx_renderer_structure():
    doc_text = (
        "# Main Heading\n\n"
        "Here is some text with **bold**, *italic*, and a [hyperlink](https://example.com).\n\n"
        "## Subheading 1\n\n"
        "> A quoted passage representing evidence.\n\n"
        "- Bullet item 1\n"
        "- Bullet item 2\n\n"
        "| Header A | Header B |\n"
        "| --- | --- |\n"
        "| Cell 1 | Cell 2 |\n\n"
        "## References\n\n"
        "Smith, J. (2020). *Sample Title*. Academic Press.\n"
    )
    doc = Document.parse(doc_text, title="Main Heading")
    renderer = DocxRenderer()
    ctx = RenderContext(title="Document Title")
    artifact = renderer.render(doc, ctx)

    assert artifact.format == "docx"
    assert artifact.binary_content is not None
    assert len(artifact.binary_content) > 0

    # Verify document can be opened by python-docx
    import docx
    word_doc = docx.Document(io.BytesIO(artifact.binary_content))
    headings = [p.text for p in word_doc.paragraphs if p.style.name.startswith("Heading")]
    assert "Document Title" in [p.text for p in word_doc.paragraphs] or "Document Title" in headings
    assert "Main Heading" in headings
    assert "Subheading 1" in headings

    # Verify tables
    assert len(word_doc.tables) >= 1
    table = word_doc.tables[0]
    assert table.rows[0].cells[0].text == "Header A"
    assert table.rows[1].cells[1].text == "Cell 2"


def test_pdf_renderer():
    doc = Document.parse("# PDF Test\n\nThis is rendered to PDF with styling.", title="PDF Test")
    renderer = PdfRenderer()
    ctx = RenderContext(title="PDF Document")

    # If neither playwright nor reportlab can run, skip gracefully
    try:
        artifact = renderer.render(doc, ctx)
        assert artifact.format == "pdf"
        assert artifact.binary_content is not None
        assert artifact.binary_content.startswith(b"%PDF")
    except RuntimeError as exc:
        pytest.skip(f"PDF rendering backend unavailable: {exc}")


def test_combined_document_assembly():
    s1 = Source(id="S001", title="Source One", authors=["Smith, A."], source_type=SourceType.JOURNAL_ARTICLE)
    s2 = Source(id="S002", title="Source Two", authors=["Doe, B."], source_type=SourceType.BOOK)

    sec1 = DocumentSection(
        id="main_post",
        title="Main Discussion Post",
        content="Primary analysis on cybersecurity regulations (Smith, 2020).",
        sources=[s1],
    )
    sec2 = DocumentSection(
        id="peer_resp_1",
        title="Peer Response 1",
        content="Insightful response to classmate (Doe, 2021).",
        sources=[s2],
    )

    doc = build_combined_document(
        title="Week 3 Discussion Deliverables",
        sections=[sec1, sec2],
    )

    assert "# Week 3 Discussion Deliverables" in doc.text
    assert "## Main Discussion Post" in doc.text
    assert "Primary analysis on cybersecurity regulations" in doc.text
    assert "## Peer Response 1" in doc.text
    assert "Insightful response to classmate" in doc.text
    assert "## References" in doc.text
    assert "Smith, A." in doc.text
    assert "Doe, B." in doc.text
