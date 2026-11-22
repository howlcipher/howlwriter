"""Adjacent Markdown paragraph content must survive academic PDF HTML rendering."""

from pathlib import Path

from howlwriter.rendering.base import RenderContext
from howlwriter.rendering.pdf import _markdown_to_html

FIXTURE = Path(__file__).parent / "fixtures" / "heading_adjacent.md"


def test_heading_does_not_discard_adjacent_paragraph():
    html = _markdown_to_html(FIXTURE.read_text(), "Synthetic paper", RenderContext())
    assert "<h2>Results</h2>" in html
    assert "<p>Measurement evidence belongs in the exported paper.</p>" in html


def test_stacked_headings_preserve_depth():
    html = _markdown_to_html("## First\n### Second\n#### Third\nBody.", "Paper", RenderContext())
    for level, heading in enumerate(("First", "Second", "Third"), start=2):
        assert f"<h{level}>{heading}</h{level}>" in html
    assert "<p>Body.</p>" in html


def test_following_section_ends_reference_styling():
    html = _markdown_to_html(
        "## References\nCitation.\n\n## Appendix\nBody.", "Paper", RenderContext()
    )
    assert '<p class="reference-entry">Citation.</p>' in html
    assert "<p>Body.</p>" in html


def test_fallback_keep_paragraph_following_heading():
    import io
    from unittest.mock import patch

    from pypdf import PdfReader

    from howlwriter.domain.document import Document
    from howlwriter.rendering.pdf import PdfRenderer

    with patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("unavailable")):
        artifact = PdfRenderer().render(Document.parse(FIXTURE.read_text()))
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(artifact.raw_bytes)).pages)
    assert "Measurement evidence belongs in the exported paper." in text
