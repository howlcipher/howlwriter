"""Markdown document renderer."""

from __future__ import annotations

import re

from howlwriter.domain.document import Document
from howlwriter.rendering.base import DocumentRenderer, RenderContext, RenderedArtifact


class MarkdownRenderer(DocumentRenderer):
    """Renders a Document as standardized Markdown."""

    def __init__(self, include_frontmatter: bool = False) -> None:
        self.include_frontmatter = include_frontmatter

    def render(
        self, document: Document, context: RenderContext | None = None
    ) -> RenderedArtifact:
        ctx = context or RenderContext()
        title = ctx.title or document.title or "Untitled Document"

        text = document.text.strip()
        has_top_title = bool(re.match(r"^#\s+", text))

        blocks: list[str] = []

        if self.include_frontmatter and ctx.metadata:
            import yaml

            frontmatter_data = dict(ctx.metadata)
            if "title" not in frontmatter_data and title:
                frontmatter_data["title"] = title
            yaml_str = yaml.dump(frontmatter_data, sort_keys=False).strip()
            blocks.append(f"---\n{yaml_str}\n---")

        if not has_top_title and title:
            blocks.append(f"# {title}\n")

        blocks.append(text)

        if ctx.include_ai_disclosure and ctx.ai_disclosure_text:
            blocks.append("\n---\n")
            blocks.append("## AI-Use Disclosure\n")
            blocks.append(ctx.ai_disclosure_text.strip())

        rendered_text = "\n\n".join(blocks).strip() + "\n"

        return RenderedArtifact(
            format="md",
            content=rendered_text,
            mime_type="text/markdown; charset=utf-8",
            title=title,
            filename_extension=".md",
        )
