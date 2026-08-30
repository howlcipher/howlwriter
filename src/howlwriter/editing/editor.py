"""The Editor capability.

PassthroughEditor is the MVP default: deterministic whitespace and heading
normalization only (trailing spaces, tabs, collapsed blank lines, spaced
heading markers). It never touches prose -- sentence-level rewriting is the
model-backed Editor Protocol, unconfigured by default. Splitting the two
lets `howl` run a real, non-trivial EDIT stage without risking meaning.
"""

from __future__ import annotations

import re
from typing import Protocol

from howlwriter.domain.document import Document
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole

_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_MULTIPLE_BLANK_LINES = re.compile(r"\n{3,}")
_HEADING_MARKER = re.compile(r"^(#{1,6})[ \t]*(?=\S)", re.MULTILINE)
_TABS = re.compile(r"\t")


class Editor(Protocol):
    role: WritingRole

    def edit(self, document: Document) -> Document: ...


class PassthroughEditor:
    role = WritingRole.EDITOR

    def edit(self, document: Document) -> Document:
        normalized_text = self._normalize(document.text)
        return Document.parse(normalized_text, title=document.title, mode=document.mode)

    @staticmethod
    def _normalize(text: str) -> str:
        text = _TABS.sub("    ", text)
        text = _TRAILING_WHITESPACE.sub("", text)
        text = _HEADING_MARKER.sub(lambda m: f"{m.group(1)} ", text)
        text = _MULTIPLE_BLANK_LINES.sub("\n\n", text)
        return text.strip()


class NotConfiguredEditor(NotConfiguredRole):
    """The model-backed editing mode (sentence-level rewriting), unconfigured."""

    def __init__(self) -> None:
        super().__init__(WritingRole.EDITOR)

    def edit(self, document: Document) -> Document:
        return self.run(document)
