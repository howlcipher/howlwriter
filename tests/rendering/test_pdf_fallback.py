"""PDF fallback must retain document content when a browser is unavailable."""
import io
from unittest.mock import patch

from pypdf import PdfReader

from howlwriter.domain.document import Document
from howlwriter.rendering.base import RenderContext
from howlwriter.rendering.pdf import PdfRenderer


def test_fallback_preserves_long_paragraphs_and_structure():
    text = ('# Investigation\n\n' + 'Long paragraph content. ' * 80 +
            'UNTRUNCATED_END\n\n## Findings\n\n'
            '| Host | Event |\n| --- | --- |\n| synthetic-host | 4720 |\n\n'
            'Figure 1. Synthetic caption.\n\n<!-- pagebreak -->\n\n'
            '## Final page\n\nFINAL_MARKER')
    with patch('playwright.sync_api.sync_playwright', side_effect=RuntimeError('unavailable')):
        artifact = PdfRenderer().render(Document.parse(text), RenderContext(page_numbers=True))
    pdf = PdfReader(io.BytesIO(artifact.raw_bytes))
    extracted = '\n'.join(p.extract_text() for p in pdf.pages)
    for value in ['UNTRUNCATED_END', 'Findings', 'synthetic-host', '4720', 'Figure 1.', 'FINAL_MARKER']:
        assert value in extracted
    assert len(pdf.pages) >= 2
    assert 'FINAL_MARKER' in pdf.pages[-1].extract_text()
    assert '<!-- pagebreak -->' not in extracted


def test_fallback_embeds_local_figure_and_wraps_code(tmp_path):
    from PIL import Image
    image = tmp_path / 'synthetic.png'
    Image.new('RGB', (1200, 600), 'blue').save(image)
    text = ('# Synthetic fixture\n\n![Synthetic figure](synthetic.png)\n\n'
            'Figure 1. Synthetic screenshot fixture.\n\n```text\n' +
            'x' * 240 + 'CODE_END\n```')
    with patch('playwright.sync_api.sync_playwright', side_effect=RuntimeError('unavailable')):
        artifact = PdfRenderer().render(
            Document.parse(text), RenderContext(metadata={'asset_base_dir': str(tmp_path)})
        )
    pdf = PdfReader(io.BytesIO(artifact.raw_bytes))
    assert sum(len(page.images) for page in pdf.pages) == 1
    extracted = ''.join(page.extract_text() for page in pdf.pages)
    assert 'CODE_END' in extracted
    assert 'Figure 1. Synthetic screenshot fixture.' in extracted


def test_fallback_missing_figure_fails_instead_of_omitting_it(tmp_path):
    import pytest
    with patch('playwright.sync_api.sync_playwright', side_effect=RuntimeError('unavailable')):
        with pytest.raises(RuntimeError):
            PdfRenderer().render(Document.parse('![Missing](absent.png)'),
                                 RenderContext(metadata={'asset_base_dir': str(tmp_path)}))


def test_docx_and_html_embed_figure_and_page_break(tmp_path):
    import docx
    from PIL import Image
    from howlwriter.rendering.docx import DocxRenderer
    from howlwriter.rendering.pdf import _markdown_to_html

    Image.new('RGB', (1200, 600), 'blue').save(tmp_path / 'synthetic.png')
    ctx = RenderContext(title='Synthetic title', author='Synthetic author',
                        metadata={'asset_base_dir': str(tmp_path)})
    text = '![Synthetic fixture](synthetic.png)\n\nFigure 1. Caption.\n\n<!-- pagebreak -->\n\n## Next'
    word = docx.Document(io.BytesIO(DocxRenderer().render(Document.parse(text), ctx).raw_bytes))
    assert len(word.inline_shapes) == 1
    assert word.core_properties.title == 'Synthetic title'
    assert word.core_properties.author == 'Synthetic author'
    assert any('Figure 1. Caption.' in p.text for p in word.paragraphs)
    assert 'w:type="page"' in word.element.xml
    html_doc = _markdown_to_html(text, 'Synthetic', ctx)
    assert 'src="data:image/png;base64,' in html_doc
    assert 'break-before:page' in html_doc


def test_docx_fenced_commands_keep_lines_without_markup():
    import docx
    from howlwriter.rendering.docx import DocxRenderer

    command = 'net user synthetic.user * /add\nnet localgroup Administrators synthetic.user /add'
    artifact = DocxRenderer().render(
        Document.parse('```cmd\n' + command + '\n```'),
        RenderContext(line_spacing=1.5),
    )
    word = docx.Document(io.BytesIO(artifact.raw_bytes))
    assert any(p.text == command for p in word.paragraphs)
    assert not any('``' in p.text for p in word.paragraphs)


def test_pdf_title_metadata_uses_body_font():
    seen = []
    context = RenderContext(title='Synthetic title', title_page={'author': 'Synthetic author'})
    with patch('playwright.sync_api.sync_playwright', side_effect=RuntimeError('unavailable')):
        artifact = PdfRenderer().render(Document.parse('Body text.'), context)
    page = PdfReader(io.BytesIO(artifact.raw_bytes)).pages[0]
    page.extract_text(visitor_text=lambda text, cm, tm, font, size: seen.append(
        (text, str(font.get('/BaseFont', '')) if font else '')
    ))
    assert any('Synthetic title' in text and font == '/Times-Bold' for text, font in seen)
    assert any('Synthetic author' in text and font == '/Times-Roman' for text, font in seen)


def test_inline_code_keeps_literal_query_wildcards():
    from howlwriter.rendering.pdf import _format_inline_html

    text = 'Query `winlog.channel:*Synthetic*` and **bold**.'
    formatted = _format_inline_html(text)
    assert 'winlog.channel:*Synthetic*</code>' in formatted
    assert '<strong>bold</strong>' in formatted
    with patch('playwright.sync_api.sync_playwright', side_effect=RuntimeError('unavailable')):
        artifact = PdfRenderer().render(Document.parse(text))
    extracted = PdfReader(io.BytesIO(artifact.raw_bytes)).pages[0].extract_text()
    assert 'winlog.channel:*Synthetic*' in extracted
