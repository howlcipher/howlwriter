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


def _assignment_ctx(**overrides) -> RenderContext:
    defaults = dict(
        title="Critical Infrastructure Paper",
        line_spacing=1.5,
        page_numbers=True,
        title_page={
            "author": "Jane Student",
            "affiliation": "Example University",
            "course": "INFA 000",
            "assignment": "Deliverable 1",
            "instructor": "Dr. Example",
            "date": "2026-09-12",
        },
    )
    defaults.update(overrides)
    return RenderContext(**defaults)


def test_render_context_title_page_lines_follow_apa_order_and_skip_blanks():
    ctx = _assignment_ctx(title_page={"date": "2026-09-12", "author": "Jane Student", "course": ""})
    assert ctx.title_page_lines() == ["Jane Student", "2026-09-12"]
    assert RenderContext().title_page_lines() == []


def test_docx_renderer_assignment_formatting():
    """1.5 spacing, a separate title page, and a header PAGE field (APA 7)."""
    import docx

    doc = Document.parse("# Critical Infrastructure Paper\n\nBody paragraph one.\n\n## References\n\nRef (2024).", title="x")
    artifact = DocxRenderer().render(doc, _assignment_ctx())
    word_doc = docx.Document(io.BytesIO(artifact.binary_content))

    assert word_doc.styles["Normal"].paragraph_format.line_spacing == 1.5
    texts = [p.text for p in word_doc.paragraphs]
    for line in ("Jane Student", "Example University", "INFA 000", "Deliverable 1", "Dr. Example", "2026-09-12"):
        assert line in texts
    # Title page precedes the body and ends with a hard page break.
    assert texts.index("Jane Student") < texts.index("Body paragraph one.")
    xml = word_doc.element.xml
    assert 'w:type="page"' in xml
    references = next(p for p in word_doc.paragraphs if p.text == "References")
    assert references.paragraph_format.page_break_before is True
    for heading in (p for p in word_doc.paragraphs if p.style.name.startswith("Heading")):
        assert all(run.font.size.pt == 12 for run in heading.runs)
        assert heading.paragraph_format.space_before.pt == 0
        assert heading.paragraph_format.space_after.pt == 0
    # Body paragraphs carry the requested spacing (240 twips = single).
    body = next(p for p in word_doc.paragraphs if p.text == "Body paragraph one.")
    assert body.paragraph_format.line_spacing == 1.5
    assert body.paragraph_format.space_after.pt == 0
    header_xml = word_doc.sections[0].header._element.xml
    assert "PAGE" in header_xml and "fldChar" in header_xml
    assert 'w:rFonts w:ascii="Times New Roman"' in header_xml
    assert 'w:sz w:val="24"' in header_xml


def test_docx_renderer_uses_default_academic_formatting():
    import docx

    doc = Document.parse("# T\n\nBody.", title="x")
    artifact = DocxRenderer().render(doc, RenderContext(title="T"))
    word_doc = docx.Document(io.BytesIO(artifact.binary_content))

    # Default academic profile
    assert word_doc.styles["Normal"].font.name == "Times New Roman"
    assert word_doc.styles["Normal"].font.size.pt == 12
    assert word_doc.styles["Normal"].paragraph_format.line_spacing == 1.0
    section = word_doc.sections[0]
    assert section.top_margin.inches == 1.0
    assert section.bottom_margin.inches == 1.0
    assert section.left_margin.inches == 1.0
    assert section.right_margin.inches == 1.0

    body = next(p for p in word_doc.paragraphs if p.text == "Body.")
    assert body.paragraph_format.line_spacing == 1.0

    # Single spacing is represented in OOXML as 240 twips
    xml = word_doc.element.xml
    assert 'w:spacing' in xml
    assert 'w:line="240"' in xml
    assert 'w:lineRule="auto"' in xml


def test_pdf_renderer_assignment_formatting_adds_title_page_and_spacing():
    pypdf = pytest.importorskip("pypdf")
    from howlwriter.rendering.pdf import _markdown_to_html

    ctx = _assignment_ctx()
    html_doc = _markdown_to_html(
        "# Critical Infrastructure Paper\n\nBody.\n\n# References\n\nRef (2024).",
        title=ctx.title,
        context=ctx,
    )
    assert "line-height: 1.5;" in html_doc
    assert 'class="title-page"' in html_doc
    assert 'class="references-heading"' in html_doc
    assert "break-before: page;" in html_doc
    assert "h1 {\n    font-size: 12pt;" in html_doc
    assert "h2 {\n    font-size: 12pt;" in html_doc
    assert "border-bottom: none;" in html_doc
    assert "Jane Student" in html_doc and "Deliverable 1" in html_doc
    assert "@bottom-right" not in html_doc  # Chromium ignores margin boxes; header template is used instead

    doc = Document.parse("# Critical Infrastructure Paper\n\nBody.", title="x")
    try:
        artifact = PdfRenderer().render(doc, ctx)
    except RuntimeError as exc:
        pytest.skip(f"PDF rendering backend unavailable: {exc}")
    reader = pypdf.PdfReader(io.BytesIO(artifact.binary_content))
    assert len(reader.pages) >= 2
    assert "Jane Student" in (reader.pages[0].extract_text() or "")
    # The header template prints the page number on each page.
    assert "2" in (reader.pages[1].extract_text() or "")


def test_docx_renderer_respects_line_spacing_overrides():
    import docx

    doc = Document.parse("# T\n\nBody.", title="x")
    ctx_15 = RenderContext(title="T", line_spacing=1.5)
    artifact = DocxRenderer().render(doc, ctx_15)
    word_doc = docx.Document(io.BytesIO(artifact.binary_content))
    assert word_doc.styles["Normal"].paragraph_format.line_spacing == 1.5
    body = next(p for p in word_doc.paragraphs if p.text == "Body.")
    assert body.paragraph_format.line_spacing == 1.5
    assert 'w:line="360"' in word_doc.element.xml

    ctx_20 = RenderContext(title="T", line_spacing=2.0)
    artifact2 = DocxRenderer().render(doc, ctx_20)
    word_doc2 = docx.Document(io.BytesIO(artifact2.binary_content))
    assert 'w:line="480"' in word_doc2.element.xml


def test_docx_renderer_propagates_custom_font_family_and_size():
    import docx

    ctx = RenderContext(title="T", font_family="Arial", font_size_pt=11)
    doc = Document.parse("# T\n\nBody.", title="x")
    artifact = DocxRenderer().render(doc, ctx)
    word_doc = docx.Document(io.BytesIO(artifact.binary_content))
    assert word_doc.styles["Normal"].font.name == "Arial"
    assert word_doc.styles["Normal"].font.size.pt == 11
    body = next(p for p in word_doc.paragraphs if p.text == "Body.")
    assert all(run.font.name == "Arial" for run in body.runs)


def test_docx_renderer_applies_custom_margins():
    import docx

    ctx = RenderContext(
        title="T",
        margin_top_in=1.5,
        margin_bottom_in=1.25,
        margin_left_in=1.0,
        margin_right_in=1.0,
    )
    doc = Document.parse("# T\n\nBody.", title="x")
    artifact = DocxRenderer().render(doc, ctx)
    word_doc = docx.Document(io.BytesIO(artifact.binary_content))
    section = word_doc.sections[0]
    assert section.top_margin.inches == 1.5
    assert section.bottom_margin.inches == 1.25
    assert section.left_margin.inches == 1.0
    assert section.right_margin.inches == 1.0


def test_pdf_renderer_generates_default_academic_css():
    from howlwriter.rendering.pdf import _markdown_to_html

    ctx = RenderContext(title="T")
    html_doc = _markdown_to_html("Body.", title="T", context=ctx)
    assert "font-family: 'Times New Roman', Times, Georgia, serif;" in html_doc
    assert "font-size: 12pt;" in html_doc
    assert "line-height: 1.0;" in html_doc
    assert "margin: 1in 1in 1in 1in;" in html_doc


def test_pdf_renderer_applies_formatting_overrides():
    from howlwriter.rendering.pdf import _markdown_to_html

    ctx = RenderContext(
        title="T",
        font_family="Arial",
        font_size_pt=11,
        line_spacing=1.5,
        margin_top_in=1.5,
        margin_bottom_in=1.25,
        margin_left_in=1.0,
        margin_right_in=1.0,
    )
    html_doc = _markdown_to_html("Body.", title="T", context=ctx)
    assert "font-family: 'Arial', Times, Georgia, serif;" in html_doc
    assert "font-size: 11pt;" in html_doc
    assert "line-height: 1.5;" in html_doc
    assert "margin: 1.5in 1in 1.25in 1in;" in html_doc


def test_pdf_renderer_passes_margins_to_chromium():
    pytest.importorskip("playwright")
    from unittest.mock import MagicMock, patch

    from howlwriter.rendering.pdf import PdfRenderer

    ctx = RenderContext(
        title="T",
        line_spacing=1.5,
        margin_top_in=1.25,
        margin_bottom_in=1.0,
        margin_left_in=1.5,
        margin_right_in=1.5,
        page_numbers=True,
    )
    renderer = PdfRenderer()
    doc = Document.parse("# T\n\nBody.", title="x")

    with patch("playwright.sync_api.sync_playwright") as mock_sync:
        mock_playwright = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.pdf = MagicMock(return_value=b"%PDF")
        mock_browser.new_page.return_value = mock_page
        mock_playwright.chromium.launch.return_value = mock_browser
        mock_sync.return_value.__enter__.return_value = mock_playwright

        renderer.render(doc, ctx)

    call_kwargs = mock_page.pdf.call_args.kwargs
    assert call_kwargs["margin"]["top"] == "1.25in"
    assert call_kwargs["margin"]["bottom"] == "1in"
    assert call_kwargs["margin"]["left"] == "1.5in"
    assert call_kwargs["margin"]["right"] == "1.5in"
    assert call_kwargs["display_header_footer"] is True
    assert '<span class="pageNumber"></span>' in call_kwargs["header_template"]


def test_infa_713_assignment_renders_at_one_and_half_spacing():
    """An explicit 1.5 spacing requirement must not be silently replaced by the single-spaced default."""
    import docx

    ctx = RenderContext(
        title="Critical Infrastructure Paper",
        line_spacing=1.5,
        page_numbers=True,
        title_page={
            "author": "William Elias",
            "affiliation": "Dakota State University",
            "course": "INFA 713",
            "assignment": "Deliverable 1: Critical Infrastructure",
            "instructor": "Chad R. Fenner, PhD",
            "date": "September 12, 2026",
        },
    )
    doc = Document.parse(
        "# Critical Infrastructure Paper\n\nBody paragraph one.\n\n## References\n\nRef (2024).",
        title="x",
    )
    artifact = DocxRenderer().render(doc, ctx)
    word_doc = docx.Document(io.BytesIO(artifact.binary_content))
    assert word_doc.styles["Normal"].paragraph_format.line_spacing == 1.5
    body = next(p for p in word_doc.paragraphs if p.text == "Body paragraph one.")
    assert body.paragraph_format.line_spacing == 1.5
    assert 'w:line="360"' in word_doc.element.xml
    # Title page and page numbering still work
    assert "William Elias" in [p.text for p in word_doc.paragraphs]
    assert "fldChar" in word_doc.sections[0].header._element.xml
