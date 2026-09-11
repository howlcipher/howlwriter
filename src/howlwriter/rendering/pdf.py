"""Deterministic PDF document renderer supporting academic styling."""

from __future__ import annotations

import html
import re

from howlwriter.domain.document import Document
from howlwriter.rendering.base import DocumentRenderer, RenderContext, RenderedArtifact


def _markdown_to_html(markdown_text: str, title: str, context: RenderContext) -> str:
    """Converts academic markdown prose into semantic HTML with academic print CSS."""
    blocks = re.split(r"\n\s*\n", markdown_text.strip())

    html_parts: list[str] = []
    in_references = False

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        first = lines[0].strip()

        # Headings
        if first.startswith("# "):
            h_text = html.escape(first[2:].strip())
            html_parts.append(f"<h1>{h_text}</h1>")
            in_references = "reference" in h_text.lower()
            continue
        elif first.startswith("## "):
            h_text = html.escape(first[3:].strip())
            html_parts.append(f"<h2>{h_text}</h2>")
            in_references = "reference" in h_text.lower()
            continue
        elif first.startswith("### "):
            h_text = html.escape(first[4:].strip())
            html_parts.append(f"<h3>{h_text}</h3>")
            continue
        elif first.startswith("#### "):
            h_text = html.escape(first[5:].strip())
            html_parts.append(f"<h4>{h_text}</h4>")
            continue

        # Horizontal rule
        if first in ("---", "***", "___"):
            html_parts.append("<hr />")
            continue

        # Blockquote
        if first.startswith(">"):
            quote_content = "<br />".join(
                html.escape(l.lstrip("> ").strip()) for l in lines
            )
            html_parts.append(f"<blockquote><p>{quote_content}</p></blockquote>")
            continue

        # Table
        if len(lines) >= 2 and "|" in first and "|" in lines[1]:
            header_cells = [c.strip() for c in lines[0].strip().split("|") if c.strip()]
            row_htmls = []
            for line in lines[2:]:
                if "|" in line:
                    cells = [c.strip() for c in line.strip().split("|") if c.strip()]
                    tds = "".join(f"<td>{html.escape(c)}</td>" for c in cells)
                    row_htmls.append(f"<tr>{tds}</tr>")
            ths = "".join(f"<th>{html.escape(h)}</th>" for h in header_cells)
            tbody = "".join(row_htmls)
            html_parts.append(
                f"<table><thead><tr>{ths}</tr></thead><tbody>{tbody}</tbody></table>"
            )
            continue

        # Bullet list
        if any(l.strip().startswith(("- ", "* ", "• ")) for l in lines):
            items = []
            for l in lines:
                l = l.strip()
                if l.startswith(("- ", "* ", "• ")):
                    item_text = _format_inline_html(l[2:].strip())
                    items.append(f"<li>{item_text}</li>")
            html_parts.append(f"<ul>{''.join(items)}</ul>")
            continue

        # Numbered list
        if any(re.match(r"^\d+\.\s+", l.strip()) for l in lines):
            items = []
            for l in lines:
                l = l.strip()
                m = re.match(r"^\d+\.\s+(.*)$", l)
                if m:
                    item_text = _format_inline_html(m.group(1))
                    items.append(f"<li>{item_text}</li>")
            html_parts.append(f"<ol>{''.join(items)}</ol>")
            continue

        # Standard paragraph or reference entry
        joined = " ".join(l.strip() for l in lines)
        p_text = _format_inline_html(joined)
        css_class = ' class="reference-entry"' if in_references else ""
        html_parts.append(f"<p{css_class}>{p_text}</p>")

    # AI-Use Disclosure if requested
    if context.include_ai_disclosure and context.ai_disclosure_text:
        disc_text = html.escape(context.ai_disclosure_text.strip()).replace("\n", "<br />")
        html_parts.append(
            f'<section class="ai-disclosure"><h2>AI-Use Disclosure</h2><p>{disc_text}</p></section>'
        )

    body_content = "\n".join(html_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{html.escape(title)}</title>
<style>
  @page {{
    size: letter;
    margin: 1in;
    @bottom-right {{
      content: counter(page);
    }}
  }}
  body {{
    font-family: 'Times New Roman', Times, Georgia, serif;
    font-size: 12pt;
    line-height: 1.6;
    color: #111;
    margin: 0;
    padding: 0;
  }}
  h1 {{
    font-size: 18pt;
    font-weight: bold;
    margin-top: 0;
    margin-bottom: 12pt;
    text-align: center;
  }}
  h2 {{
    font-size: 14pt;
    font-weight: bold;
    margin-top: 18pt;
    margin-bottom: 6pt;
    border-bottom: 1px solid #ddd;
    padding-bottom: 2pt;
  }}
  h3 {{
    font-size: 12pt;
    font-weight: bold;
    margin-top: 12pt;
    margin-bottom: 4pt;
  }}
  p {{
    margin-top: 0;
    margin-bottom: 8pt;
    text-align: justify;
  }}
  .reference-entry {{
    margin-left: 0.5in;
    text-indent: -0.5in;
    margin-bottom: 6pt;
    text-align: left;
  }}
  blockquote {{
    margin-left: 0.5in;
    margin-right: 0.5in;
    font-style: italic;
    color: #333;
    border-left: 3px solid #ccc;
    padding-left: 8pt;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 10pt;
    margin-bottom: 10pt;
  }}
  th, td {{
    border: 1px solid #666;
    padding: 5pt 8pt;
    text-align: left;
    font-size: 10.5pt;
  }}
  th {{
    background-color: #f2f2f2;
    font-weight: bold;
  }}
  a {{
    color: #0563C1;
    text-decoration: underline;
  }}
  hr {{
    border: 0;
    border-top: 1px solid #ccc;
    margin: 14pt 0;
  }}
  .ai-disclosure {{
    margin-top: 24pt;
    font-size: 10pt;
    color: #444;
  }}
</style>
</head>
<body>
{body_content}
</body>
</html>"""


def _format_inline_html(text: str) -> str:
    """Escapes HTML and parses inline markdown links, bold, italic, and code."""
    # Temporarily extract links to avoid escaping their URLs
    links: list[tuple[str, str]] = []

    def save_link(m: re.Match) -> str:
        idx = len(links)
        links.append((m.group(1), m.group(2)))
        return f"__LINK_PLACEHOLDER_{idx}__"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", save_link, text)

    escaped = html.escape(text)

    # Bold
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    # Italic
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    # Code
    escaped = re.sub(
        r"`([^`]+)`", r'<code style="font-family: monospace;">\1</code>', escaped
    )

    # Restore links
    for idx, (lt, lu) in enumerate(links):
        safe_lt = html.escape(lt)
        safe_lu = html.escape(lu)
        escaped = escaped.replace(
            f"__LINK_PLACEHOLDER_{idx}__",
            f'<a href="{safe_lu}">{safe_lt}</a>',
        )

    return escaped


class PdfRenderer(DocumentRenderer):
    """Renders a Document into a print-ready PDF using headless Chromium or ReportLab."""

    def render(
        self, document: Document, context: RenderContext | None = None
    ) -> RenderedArtifact:
        ctx = context or RenderContext()
        title = ctx.title or document.title or "Untitled Document"

        # Check for Playwright
        try:
            from playwright.sync_api import sync_playwright

            html_doc = _markdown_to_html(document.text, title=title, context=ctx)

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_content(html_doc, wait_until="networkidle")
                pdf_bytes = page.pdf(
                    format="Letter",
                    margin={
                        "top": "1in",
                        "bottom": "1in",
                        "left": "1in",
                        "right": "1in",
                    },
                    print_background=True,
                )
                browser.close()

            return RenderedArtifact(
                format="pdf",
                content=pdf_bytes,
                mime_type="application/pdf",
                title=title,
                filename_extension=".pdf",
            )
        except Exception as playwright_exc:
            # Check for ReportLab fallback if available
            try:
                import reportlab  # noqa: F401
                # If reportlab is installed, implement minimal reportlab fallback
                from reportlab.lib.pagesizes import letter
                from reportlab.pdfgen import canvas
                import io

                buf = io.BytesIO()
                c = canvas.Canvas(buf, pagesize=letter)
                c.setFont("Helvetica-Bold", 16)
                c.drawString(72, 720, title)
                c.setFont("Helvetica", 11)
                y = 690
                for line in document.text.split("\n"):
                    if line.strip():
                        c.drawString(72, y, line[:80])
                        y -= 14
                        if y < 72:
                            c.showPage()
                            y = 720
                c.save()
                return RenderedArtifact(
                    format="pdf",
                    content=buf.getvalue(),
                    mime_type="application/pdf",
                    title=title,
                    filename_extension=".pdf",
                )
            except Exception:
                raise RuntimeError(
                    f"PDF rendering failed: Playwright browser error ({playwright_exc}). "
                    "Ensure chromium is installed (`python -m playwright install chromium`) "
                    "or install reportlab with `pip install 'howlwriter[pdf]'`."
                ) from playwright_exc
