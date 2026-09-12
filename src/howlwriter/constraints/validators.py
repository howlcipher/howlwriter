"""Lightweight deterministic validators that feed the constraint enforcer.

These validators are intentionally conservative: they surface candidates
and contradictions for the model-backed enforcer to review, rather than
silently deleting content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from howlwriter.domain.document import Document


@dataclass
class RedundancyFinding:
    paragraph_index: int
    table_paragraph_index: int
    overlap_ratio: float
    note: str


@dataclass
class SequenceFinding:
    step_number: int
    step_text: str
    issue: str
    severity: Literal["warning", "error"] = "warning"


@dataclass
class SpecificityFinding:
    paragraph_index: int
    sentence_index: int
    text: str
    pattern: str
    note: str


@dataclass
class HeadingMismatchFinding:
    paragraph_index: int
    heading: str
    note: str


@dataclass
class ValidationReport:
    redundancy: list[RedundancyFinding] = field(default_factory=list)
    sequence: list[SequenceFinding] = field(default_factory=list)
    specificity: list[SpecificityFinding] = field(default_factory=list)
    heading_mismatch: list[HeadingMismatchFinding] = field(default_factory=list)

    def render_text(self) -> str:
        lines: list[str] = []
        if self.redundancy:
            lines.append("Redundancy findings:")
            for f in self.redundancy:
                lines.append(
                    f"  - Paragraph {f.paragraph_index} overlaps table "
                    f"{f.table_paragraph_index} by {f.overlap_ratio:.0%}: {f.note}"
                )
        if self.sequence:
            lines.append("Sequence / dependency findings:")
            for f in self.sequence:
                lines.append(
                    f"  - Step {f.step_number}: {f.issue} ({f.severity})"
                )
        if self.specificity:
            lines.append("Unsupported specificity candidates:")
            for f in self.specificity:
                lines.append(
                    f"  - Paragraph {f.paragraph_index}: [{f.pattern}] {f.note}"
                )
        if self.heading_mismatch:
            lines.append("Heading / content mismatch findings:")
            for f in self.heading_mismatch:
                lines.append(f"  - {f.heading}: {f.note}")
        return "\n".join(lines) if lines else "No deterministic findings."


class RedundancyDetector:
    """Surface prose paragraphs that largely repeat a preceding table."""

    def detect(self, document: Document) -> list[RedundancyFinding]:
        findings: list[RedundancyFinding] = []
        table_texts: dict[int, set[str]] = {}

        for paragraph in document.paragraphs:
            raw = paragraph.raw_text.strip()
            if self._is_markdown_table(raw):
                table_texts[paragraph.index] = self._table_words(raw)

        if not table_texts:
            return findings

        for paragraph in document.paragraphs:
            p_idx = paragraph.index
            if p_idx in table_texts:
                continue
            words = self._word_set(paragraph.raw_text)
            if len(words) < 4:
                continue
            for t_idx, t_words in table_texts.items():
                if t_idx >= p_idx:
                    continue
                if not t_words:
                    continue
                overlap = len(words & t_words) / len(words)
                if overlap >= 0.5:
                    findings.append(
                        RedundancyFinding(
                            paragraph_index=p_idx,
                            table_paragraph_index=t_idx,
                            overlap_ratio=overlap,
                            note="Paragraph repeats many words from a prior table.",
                        )
                    )
                    break
        return findings

    @staticmethod
    def _is_markdown_table(text: str) -> bool:
        return bool(re.search(r"\n*\|[-\s|]+\|", text)) and "|" in text

    @staticmethod
    def _table_words(text: str) -> set[str]:
        # Strip markdown table delimiters and collect lower-cased words.
        cleaned = re.sub(r"[|\-:\n\r]+", " ", text)
        return RedundancyDetector._word_set(cleaned)

    @staticmethod
    def _word_set(text: str) -> set[str]:
        return {
            w.lower()
            for w in re.findall(r"\b\w+\b", text)
            if len(w) > 2
        }


class SequenceValidator:
    """Lightweight ordered-step consistency check.

    Full causal reasoning is delegated to the model-backed enforcer. This
    validator only catches mechanically suspicious patterns, such as a step
    using a resource before another step grants it.
    """

    # Phrases that suggest a step *grants* a capability/access later on.
    _GRANT_PATTERNS = [
        re.compile(r"\b(gains?|obtains?|acquires?|extracts?|discovers?|leaks?|compromises?)\b", re.I),
        re.compile(r"\b(credentials?|tokens?|keys?|secrets?|passwords?|access)\b", re.I),
    ]
    _STEP_PREFIX = re.compile(r"^(?:Step\s+\d+|Stage\s+\d+|Phase\s+\d+|\d+[.)])\s*", re.I)

    def validate(self, document: Document) -> list[SequenceFinding]:
        findings: list[SequenceFinding] = []
        steps: list[tuple[int, str]] = []

        for paragraph in document.paragraphs:
            raw = paragraph.raw_text.strip()
            first_sentence = paragraph.sentences[0].text if paragraph.sentences else raw
            if self._STEP_PREFIX.match(first_sentence):
                steps.append((paragraph.index, raw))

        if len(steps) < 2:
            return findings

        # Heuristic: if a later step "grants" a resource but an earlier step
        # already *uses* that resource, flag for review.
        for i, (idx, text) in enumerate(steps):
            for grant_pat, resource_pat in zip(self._GRANT_PATTERNS[::2], self._GRANT_PATTERNS[1::2]):
                if not grant_pat.search(text):
                    continue
                resource = resource_pat.search(text)
                if not resource:
                    continue
                resource_term = resource.group(0).lower()
                resource_root = resource_term.split()[0]
                for prev_idx, prev_text in steps[:i]:
                    prev_lower = prev_text.lower()
                    if resource_term in prev_lower or resource_root in prev_lower:
                        findings.append(
                            SequenceFinding(
                                step_number=i + 1,
                                step_text=text,
                                issue=(
                                    f"Step appears to grant '{resource_term}', but an earlier "
                                    "step already used it."
                                ),
                                severity="warning",
                            )
                        )
                        break
        return findings


class UnsupportedSpecificityValidator:
    """Surface candidate exact identifiers that may not be grounded.

    These are hints, not verdicts. The enforcer decides whether each
    candidate is actually unsupported and should be generalized.
    """

    _PATTERNS: list[tuple[str, re.Pattern]] = [
        ("CVE", re.compile(r"CVE-\d{4}-\d+")),
        ("Event ID", re.compile(r"\bEvent ID[s]?[:\s]+\d+", re.I)),
        ("finding name", re.compile(r"\bfinding[s]?\s+[A-Z][A-Za-z0-9_/-]+\b")),
        (" GuardDuty / service finding", re.compile(r"\b(GuardDuty|CloudTrail|SIEM|Splunk)\b.*\bfinding\b", re.I)),
        ("entropy threshold", re.compile(r"\bentropy\s*[<>]=?\s*\d+(\.\d+)?\b", re.I)),
        ("jitter percentage", re.compile(r"\b\d+%?\s+jitter\b|\bjitter\s+\d+%?\b", re.I)),
        ("numeric threshold with units", re.compile(r"\b\d+(\.\d+)?\s*(ms|seconds|minutes|hours|days|GB|MB|KB)\b")),
        ("exact percentage claim", re.compile(r"\b\d{1,2}(\.\d+)?%\s+(randomization|interval|beacon|success|failure|rate)\b", re.I)),
    ]

    def validate(self, document: Document) -> list[SpecificityFinding]:
        findings: list[SpecificityFinding] = []
        for p_idx, s_idx, sentence in document.all_sentences():
            for label, pattern in self._PATTERNS:
                for match in pattern.finditer(sentence.text):
                    findings.append(
                        SpecificityFinding(
                            paragraph_index=p_idx,
                            sentence_index=s_idx,
                            text=match.group(0),
                            pattern=label,
                            note=(
                                "Candidate exact identifier or threshold. "
                                "Verify in source material or generalize."
                            ),
                        )
                    )
        return findings


class HeadingConsistencyValidator:
    """Surface headings whose keywords are absent from the section body.

    This is intentionally shallow; the model-backed enforcer performs the
    real semantic check.
    """

    def validate(self, document: Document) -> list[HeadingMismatchFinding]:
        findings: list[HeadingMismatchFinding] = []
        # Identify likely heading paragraphs (single short sentence starting
        # with # or all-caps / title case).
        headings: list[tuple[int, str, str]] = []
        for paragraph in document.paragraphs:
            raw = paragraph.raw_text.strip()
            heading = self._extract_heading(raw)
            if heading:
                headings.append((paragraph.index, heading, raw))

        for h_idx, heading, raw in headings:
            # Look at the next non-heading paragraph as the body.
            body = ""
            for paragraph in document.paragraphs:
                if paragraph.index <= h_idx:
                    continue
                if self._extract_heading(paragraph.raw_text.strip()):
                    break
                body += " " + paragraph.raw_text
            if not body:
                continue
            keywords = self._heading_keywords(heading)
            missing = [kw for kw in keywords if kw not in body.lower()]
            if missing and len(keywords) >= 2:
                findings.append(
                    HeadingMismatchFinding(
                        paragraph_index=h_idx,
                        heading=heading,
                        note=(
                            f"Heading keywords ({', '.join(missing)}) not found in "
                            "the following body text."
                        ),
                    )
                )
        return findings

    @staticmethod
    def _extract_heading(text: str) -> str | None:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            return None
        first = lines[0]
        if first.startswith("#"):
            return first.lstrip("#").strip()
        if first.istitle() or first.isupper():
            if len(first) < 100 and not first.endswith("."):
                return first
        return None

    @staticmethod
    def _heading_keywords(heading: str) -> list[str]:
        words = re.findall(r"\b\w+\b", heading.lower())
        return [w for w in words if len(w) > 3 and w not in {"about", "with", "from", "this", "that", "overview", "analysis"}]
