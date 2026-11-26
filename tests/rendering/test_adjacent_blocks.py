"""Adjacent Markdown blocks preserve content and pagination in exports."""

import io
from pathlib import Path
from unittest.mock import patch

import docx
import pytest
from pypdf import PdfReader

from howlwriter.domain.document import Document
from howlwriter.rendering.base import RenderContext
from howlwriter.rendering.docx import DocxRenderer
from howlwriter.rendering.pdf import PdfRenderer, _markdown_to_html

PAGE_BREAK_TEXT = "BeforeBreak\n<!-- pagebreak -->\nAfterBreak"


@pytest.fixture
def chromium():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is not installed")
    with patch("howlwriter.rendering.reportlab_pdf.render_reportlab",
               side_effect=AssertionError("Chromium export must not fall back to ReportLab")):
        yield


def test_adjacent_break_docx():
    artifact = DocxRenderer().render(
        Document.parse(PAGE_BREAK_TEXT), RenderContext(title="Synthetic")
    )
    paragraphs = docx.Document(io.BytesIO(artifact.raw_bytes)).paragraphs
    assert [(p.text.strip(), bool(p._p.xpath(".//w:br[@w:type='page']")))
            for p in paragraphs][-3:] == [
        ("BeforeBreak", False), ("", True), ("AfterBreak", False),
    ]


@pytest.mark.parametrize("backend", ["chromium", "reportlab"])
def test_adjacent_break_pdf(backend, request):
    document = Document.parse(PAGE_BREAK_TEXT)
    if backend == "chromium":
        request.getfixturevalue("chromium")
        artifact = PdfRenderer().render(document)
    else:
        with patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("unavailable")):
            artifact = PdfRenderer().render(document)
    pages = [p.extract_text() for p in PdfReader(io.BytesIO(artifact.raw_bytes)).pages]
    assert len(pages) == 2
    assert pages[0].count("BeforeBreak") == 1 and "AfterBreak" not in pages[0]
    assert pages[1].count("AfterBreak") == 1 and "BeforeBreak" not in pages[1]
    assert "<!-- pagebreak -->" not in "".join(pages)


@pytest.mark.parametrize(("marker", "tag"), [("-", "ul"), ("1.", "ol")])
def test_adjacent_list_html(marker, tag):
    text = f"# Start\nBeforeList\n{marker} ListedItem\nAfterList"
    rendered = _markdown_to_html(text, "Synthetic", RenderContext())
    assert f"<h1>Start</h1>\n<p>BeforeList</p>\n<{tag}><li>ListedItem</li></{tag}>\n<p>AfterList</p>" in rendered


@pytest.mark.parametrize("marker", ["-", "1."])
def test_adjacent_list_chromium_pdf(marker, chromium):
    text = f"# Start\nBeforeList\n{marker} ListedItem\nAfterList"
    artifact = PdfRenderer().render(Document.parse(text))
    extracted = PdfReader(io.BytesIO(artifact.raw_bytes)).pages[0].extract_text()
    markers = ["BeforeList", "ListedItem", "AfterList"]
    assert all(extracted.count(value) == 1 for value in markers)
    assert [extracted.index(value) for value in markers] == sorted(extracted.index(value) for value in markers)


def test_heading_after_prose():
    rendered = _markdown_to_html("Before\n## Next\nAfter", "Synthetic", RenderContext())
    assert "<p>Before</p>\n<h2>Next</h2>\n<p>After</p>" in rendered


@pytest.mark.parametrize("fence", ["```", "````"])
def test_fence_preserves_literal_blocks(fence):
    payload = "alpha\n\n# literal\n- literal\n<!-- pagebreak -->"
    text = f"{fence}txt\n{payload}\n{fence}\nAfter"
    rendered = _markdown_to_html(text, "Synthetic", RenderContext())
    assert rendered.count("<pre ") == 1
    assert "alpha\n\n# literal\n- literal\n&lt;!-- pagebreak --&gt;</pre>\n<p>After</p>" in rendered
