"""Outline conformance checking for academic assignments."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin


@dataclass
class TopicResult(DataClassSerializationMixin):
    topic: str
    status: str  # "PASS" | "FAIL"
    matched_section: str | None = None
    reason: str = ""


@dataclass
class OutlineResult(DataClassSerializationMixin):
    status: str  # "PASS" | "FAIL"
    required_topics_count: int = 0
    present_topics_count: int = 0
    topic_results: list[TopicResult] = field(default_factory=list)


def _normalize_text(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def check_outline_conformance(
    document: Document, outline: list[str]
) -> OutlineResult:
    """Checks whether each topic in the required outline is represented in the document.

    Matches against headings, subheadings, and section introductory sentences.
    """
    if not outline:
        return OutlineResult(status="PASS", required_topics_count=0, present_topics_count=0)

    headings: list[str] = []
    paragraphs: list[str] = []
    for p in document.paragraphs:
        for line in p.raw_text.splitlines():
            line_str = line.strip()
            if line_str.startswith("#"):
                headings.append(line_str.lstrip("#").strip())
            elif line_str:
                paragraphs.append(line_str)

    topic_results: list[TopicResult] = []
    present_count = 0

    for topic in outline:
        topic_norm = _normalize_text(topic)
        topic_words = set(topic_norm.split())

        matched_section: str | None = None
        matched_reason = ""

        # 1. Try matching against headings (exact or high-overlap)
        for h in headings:
            h_norm = _normalize_text(h)
            if topic_norm in h_norm or h_norm in topic_norm:
                matched_section = h
                matched_reason = "Matched heading"
                break
            h_words = set(h_norm.split())
            if topic_words and (len(topic_words & h_words) / len(topic_words) >= 0.6):
                matched_section = h
                matched_reason = "Substantial heading keyword match"
                break

        # 2. If no heading match, try matching against first sentences of paragraphs
        if not matched_section:
            for p in paragraphs:
                first_sent = p.split(".")[0] if "." in p else p[:120]
                p_norm = _normalize_text(first_sent)
                if topic_norm in p_norm:
                    matched_section = first_sent[:80]
                    matched_reason = "Matched topic sentence"
                    break
                p_words = set(p_norm.split())
                if topic_words and (len(topic_words & p_words) / len(topic_words) >= 0.75):
                    matched_section = first_sent[:80]
                    matched_reason = "Topic sentence keyword match"
                    break

        if matched_section:
            present_count += 1
            topic_results.append(
                TopicResult(
                    topic=topic,
                    status="PASS",
                    matched_section=matched_section,
                    reason=matched_reason,
                )
            )
        else:
            topic_results.append(
                TopicResult(
                    topic=topic,
                    status="FAIL",
                    matched_section=None,
                    reason="No heading or section found representing this required topic",
                )
            )

    all_passed = present_count == len(outline)
    return OutlineResult(
        status="PASS" if all_passed else "FAIL",
        required_topics_count=len(outline),
        present_topics_count=present_count,
        topic_results=topic_results,
    )
