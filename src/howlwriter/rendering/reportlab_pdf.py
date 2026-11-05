"""Flow-based PDF fallback, retaining prose, tables, and local figures."""
from __future__ import annotations

import html
import io
import re
from pathlib import Path

from howlwriter.rendering.base import RenderContext


def render_reportlab(text: str, title: str, ctx: RenderContext) -> bytes:
    """Render without a browser using Platypus wrapping and pagination."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        HRFlowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
        Table, TableStyle,
    )
    from howlwriter.rendering.pdf import _format_inline_html

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf, pagesize=letter, title=title, author=ctx.author,
        leftMargin=ctx.margin_left_in * 72, rightMargin=ctx.margin_right_in * 72,
        topMargin=ctx.margin_top_in * 72, bottomMargin=ctx.margin_bottom_in * 72,
    )
    # Standard PDF fonts are portable; arbitrary system font names require
    # explicit registration and cannot safely be assumed available here.
    family = {'Arial': 'Helvetica', 'Helvetica': 'Helvetica',
              'Courier': 'Courier'}.get(ctx.font_family, 'Times-Roman')
    bold = {'Times-Roman': 'Times-Bold', 'Helvetica': 'Helvetica-Bold',
            'Courier': 'Courier-Bold'}[family]
    base = ParagraphStyle('Body', fontName=family, fontSize=ctx.font_size_pt,
                          leading=ctx.font_size_pt * 1.2 * ctx.line_spacing,
                          spaceAfter=6, splitLongWords=True,
                          allowWidows=False, allowOrphans=False)
    heading = ParagraphStyle('Heading', parent=base, fontName=bold,
                             spaceBefore=10, spaceAfter=6, keepWithNext=True)
    caption = ParagraphStyle('Caption', parent=base, keepWithNext=False)
    code = ParagraphStyle('Code', parent=base, fontName='Courier', fontSize=9,
                          leading=12, spaceAfter=4)
    story = []

    def inline(value: str) -> str:
        # ReportLab supports its own small inline markup vocabulary.
        value = _format_inline_html(value)
        value = re.sub(r'<code[^>]*>', '<font name="Courier">', value).replace('</code>', '</font>')
        return (value.replace('<strong>', '<b>').replace('</strong>', '</b>')
                .replace('<em>', '<i>').replace('</em>', '</i>'))

    if ctx.title_page:
        centered = ParagraphStyle('Title', parent=heading, alignment=TA_CENTER)
        title_metadata = ParagraphStyle('TitleMetadata', parent=base, alignment=TA_CENTER)
        story.extend([Spacer(1, 120), Paragraph(html.escape(title), centered)])
        story.extend(Paragraph(html.escape(line), title_metadata) for line in ctx.title_page_lines())
        story.append(PageBreak())

    # Keep fenced code intact across blank lines; paragraph blocks otherwise
    # follow the existing renderer's Markdown contract.
    blocks = []
    current = []
    fenced = False
    for line in text.splitlines():
        if line.startswith('```'):
            if not fenced and current:
                blocks.append('\n'.join(current))
                current = []
            current.append(line)
            fenced = not fenced
            if not fenced:
                blocks.append('\n'.join(current))
                current = []
        elif not line.strip() and not fenced:
            if current:
                blocks.append('\n'.join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append('\n'.join(current))

    for block in blocks:
        lines = block.splitlines()
        first = lines[0].strip()
        if first == '<!-- pagebreak -->':
            story.append(PageBreak())
        elif first.startswith('```'):
            for line in lines[1:-1]:
                story.append(Paragraph(html.escape(line).replace(' ', '&nbsp;') or '&#160;', code))
        elif re.match(r'^#{1,6} ', first):
            value = re.sub(r'^#+\s+', '', first)
            if ctx.title_page and value.lower() == 'references':
                story.append(PageBreak())
            story.append(Paragraph(inline(value), heading))
        elif (image := re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', block.strip())):
            path = Path(image[2])
            if not path.is_absolute():
                path = Path(ctx.metadata.get('asset_base_dir', '.')) / path
            figure = Image(str(path.resolve(strict=True)))
            factor = min(pdf.width / figure.imageWidth, (pdf.height - 48) / figure.imageHeight, 1)
            figure.drawWidth = figure.imageWidth * factor
            figure.drawHeight = figure.imageHeight * factor
            story.extend([figure, Spacer(1, 6)])
        elif len(lines) > 1 and '|' in first and re.match(r'^\s*\|?\s*:?-+', lines[1]):
            rows = [[cell.strip() for cell in line.strip().strip('|').split('|')]
                    for line in [lines[0], *lines[2:]]]
            columns = len(rows[0])
            cells = [[Paragraph(inline(value), base) for value in (row + [''] * columns)[:columns]]
                     for row in rows]
            table = Table(cells, colWidths=[pdf.width / columns] * columns, repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .5, colors.grey),
                                       ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                       ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke)]))
            story.extend([table, Spacer(1, 8)])
        elif first in ('---', '***', '___'):
            story.append(HRFlowable(width='100%', spaceBefore=6, spaceAfter=6))
        elif all(re.match(r'^\s*(?:[-*•]|\d+\.)\s+', line) for line in lines):
            for line in lines:
                value = re.sub(r'^\s*(?:[-*•]|\d+\.)\s+', '', line)
                story.append(Paragraph(inline(value), base, bulletText='•'))
        else:
            value = ' '.join(line.lstrip('> ').strip() for line in lines)
            story.append(Paragraph(inline(value), caption if first.startswith('Figure ') else base))
    if ctx.include_ai_disclosure and ctx.ai_disclosure_text:
        story.extend([Paragraph('AI-Use Disclosure', heading),
                      Paragraph(inline(ctx.ai_disclosure_text), base)])

    def page_number(canvas, doc):
        if ctx.page_numbers:
            canvas.saveState()
            canvas.setFont(family, ctx.font_size_pt)
            canvas.drawRightString(letter[0] - doc.rightMargin, letter[1] - 36, str(doc.page))
            canvas.restoreState()

    pdf.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return buf.getvalue()
