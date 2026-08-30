"""HumanizerRewriter: model-backed prose rewriting ("make this sound less
AI"), unconfigured by default -- HowlWriter does not attempt this itself.

SafeRewriter is the one rewrite the MVP performs without a model: literal
substitution of a banned word for its configured replacement, and only
when the caller opts in via config.apply_safe_rewrites. Everything else
stays findings-only (see humanize/detector.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.domain.report import ChangeRecord
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole


class HumanizerRewriter(Protocol):
    role: WritingRole

    def rewrite(self, document: Document, config: HowlWriterConfig) -> Document: ...


class NotConfiguredHumanizer(NotConfiguredRole):
    def __init__(self) -> None:
        super().__init__(WritingRole.HUMANIZER)

    def rewrite(self, document: Document, config: HowlWriterConfig) -> Document:
        return self.run(document, config)


@dataclass
class SafeRewriteResult:
    document: Document
    changes: list[ChangeRecord] = field(default_factory=list)


class SafeRewriter:
    def rewrite(self, document: Document, config: HowlWriterConfig) -> SafeRewriteResult:
        replacements = {bw.word.lower(): bw.replacement for bw in config.banned_words if bw.replacement}
        if not config.apply_safe_rewrites or not replacements:
            return SafeRewriteResult(document=document, changes=[])

        pattern = re.compile(
            r"\b(" + "|".join(re.escape(word) for word in replacements) + r")\b", re.IGNORECASE
        )
        changes: list[ChangeRecord] = []

        def _substitute(match: re.Match) -> str:
            original = match.group(0)
            replacement = replacements[original.lower()]
            changes.append(ChangeRecord(description=f'replaced "{original}" with "{replacement}"'))
            return replacement

        new_text = pattern.sub(_substitute, document.text)
        new_document = Document.parse(new_text, title=document.title, mode=document.mode)
        return SafeRewriteResult(document=new_document, changes=changes)
