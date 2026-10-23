"""Verify what a destination actually holds, not what the pipeline meant to send.

After a document is published, the destination is read back and compared with
the approved text: every paragraph still there, none duplicated, every citation
and reference entry intact, no truncated reference list, and the word count
recomputed from what was read. A publish that cannot be confirmed this way is
not reported as successful.

Comparison is on normalized text so a destination that renders Markdown and one
that stores it literally both compare equal on content; the difference in
presentation is reported separately.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from howlwriter.citations.extract import extract_in_text_citations
from howlwriter.citations.revalidation import citation_key, parse_references, split_body_and_references
from howlwriter.domain.serialization import DataClassSerializationMixin

EMPTY_APPROVED = "READBACK_NOTHING_APPROVED"
EXTRA_CONTENT = "READBACK_EXTRA_CONTENT"
REORDERED_CONTENT = "READBACK_REORDERED_CONTENT"
TEXT_TOO_LARGE = "READBACK_TEXT_TOO_LARGE"
MISSING_PARAGRAPH = "READBACK_MISSING_PARAGRAPH"
DUPLICATED_CONTENT = "READBACK_DUPLICATED_CONTENT"
CITATION_LOST = "READBACK_CITATION_LOST"
REFERENCE_LOST = "READBACK_REFERENCE_LOST"
REFERENCES_TRUNCATED = "READBACK_REFERENCES_TRUNCATED"
TEXT_TRUNCATED = "READBACK_TEXT_TRUNCATED"
WORD_COUNT_CHANGED = "READBACK_WORD_COUNT_CHANGED"
WORD_COUNT_OUT_OF_RANGE = "READBACK_WORD_COUNT_OUT_OF_RANGE"
PRIOR_CONTENT_LOST = "READBACK_PRIOR_CONTENT_LOST"
FORMATTING_LITERAL = "READBACK_MARKDOWN_SHOWN_LITERALLY"
UNSUPPORTED_ELEMENT = "READBACK_UNSUPPORTED_ELEMENT"
HASH_MISMATCH = "ARTIFACT_CHANGED_AFTER_APPROVAL"

_MIN_PARAGRAPH_WORDS = 6
MAX_COMPARE_CHARS = 2_000_000
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def looks_like_sha256(value: str) -> bool:
    return bool(_HEX64.match(value or ""))


def normalize(text: str) -> str:
    """Lower-cased words with Markdown syntax and punctuation spacing removed."""
    text = re.sub(r"\[([^\]\n]{1,300})\]\([^)\n]{0,2000}\)", r"\1", text)
    text = re.sub(r"^[ \t]*#{1,6}[ \t]+", "", text, flags=re.M)
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _paragraphs(text: str) -> list[str]:
    return [p for p in (normalize(x) for x in re.split(r"\n+", text)) if p]


def _body_word_count(text: str) -> int:
    body, _ = split_body_and_references(text)
    # A plain "References" line (no Markdown) also ends the body.
    body = re.split(r"(?im)^[ \t]*references[ \t]*$", body, maxsplit=1)[0]
    return len(re.findall(r"\b[\w'-]+\b", re.sub(r"[*_`#]", "", re.sub(
        r"\[([^\]\n]{1,300})\]\([^)\n]{0,2000}\)", r"\1", body))))


# ---------------------------------------------------------------- approved record


@dataclass
class ArtifactRecord(DataClassSerializationMixin):
    """What was approved for publication, kept so the published text can be compared to it."""

    title: str
    sha256: str
    run_id: str
    words: int
    paragraphs: int
    citations: list[str] = field(default_factory=list)
    reference_entries: int = 0
    authorized_sha256: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def approved_record(text: str, *, title: str = "", run_id: str = "") -> ArtifactRecord:
    body, _ = split_body_and_references(text)
    cites = sorted({f"{k[0]} {k[1]}" for c in extract_in_text_citations(body) if c.source_id is None
                    for k in [citation_key(c.names, c.year)]})
    return ArtifactRecord(
        title=title, sha256=sha256_text(text), run_id=run_id, words=_body_word_count(text),
        paragraphs=len(_paragraphs(body)), citations=cites, reference_entries=len(parse_references(text)))


def write_record(record: ArtifactRecord, directory: str | Path) -> Path:
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"approved-artifact-{record.sha256[:12]}.json"
    path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------------ destination text


def extract_document_text(doc: dict[str, Any]) -> str:
    """Plain text of a destination document: a stored string, or a Google Docs body structure."""
    body = doc.get("body")
    if isinstance(body, str):
        return body
    parts: list[str] = []
    for element in (body or {}).get("content", []) if isinstance(body, dict) else []:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for run in paragraph.get("elements", []):
            content = (run.get("textRun") or {}).get("content")
            if content:
                parts.append(content)
    return "".join(parts)


# ------------------------------------------------------------------- read-back check


@dataclass
class ReadbackFinding(DataClassSerializationMixin):
    code: str
    message: str
    severity: str = "error"  # "error" | "warning" | "info"
    detail: str = ""


@dataclass
class ReadbackVerification(DataClassSerializationMixin):
    status: str  # VERIFIED | MISMATCH
    approved_words: int
    readback_words: int
    findings: list[ReadbackFinding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.status == "VERIFIED"


def verify_readback(
    approved_text: str,
    readback_text: str,
    *,
    title: str = "",
    prior_text: str = "",
    min_words: int | None = None,
    max_words: int | None = None,
) -> ReadbackVerification:
    """Compare the text read back from a destination with the approved text."""
    findings: list[ReadbackFinding] = []
    if len(approved_text) > MAX_COMPARE_CHARS or len(readback_text) > MAX_COMPARE_CHARS:
        return ReadbackVerification("MISMATCH", 0, 0, [ReadbackFinding(
            TEXT_TOO_LARGE, f"Texts over {MAX_COMPARE_CHARS} characters are not compared.", "error")], [])
    read = readback_text
    if title and normalize(read).startswith(normalize(title)):
        # Destinations that add the title as a first line: not part of the body.
        read = re.sub(r"^[ \t]*" + re.escape(title) + r"[ \t]*\n", "", read.lstrip(), count=1)
    norm_read = normalize(read)
    approved_paras = _paragraphs(approved_text)
    read_paras = _paragraphs(read)

    if not approved_paras:
        findings.append(ReadbackFinding(EMPTY_APPROVED, "There is no approved text to compare the destination with.",
                                        "error"))
    elif prior_text:
        # Appending: the approved text must appear in order among the existing content.
        position = 0
        for para in approved_paras:
            try:
                position = read_paras.index(para, position) + 1
            except ValueError:
                if para in read_paras:
                    findings.append(ReadbackFinding(REORDERED_CONTENT, "Approved paragraphs are out of order.",
                                                    "error", para[:100]))
                else:
                    findings.append(ReadbackFinding(MISSING_PARAGRAPH, "A paragraph of the approved text is missing "
                                                    "or altered in the published document.", "error", para[:100]))
    elif approved_paras != read_paras:
        if sorted(approved_paras) == sorted(read_paras):
            findings.append(ReadbackFinding(REORDERED_CONTENT, "The paragraphs are the same but in a different order.",
                                            "error"))
        else:
            ops = difflib.SequenceMatcher(a=approved_paras, b=read_paras, autojunk=False).get_opcodes()
            for tag, i1, i2, j1, j2 in ops:
                if tag in ("delete", "replace"):
                    for para in approved_paras[i1:i2]:
                        findings.append(ReadbackFinding(
                            MISSING_PARAGRAPH, "A paragraph of the approved text is missing or altered in the "
                            "published document.", "error", para[:100]))
                if tag in ("insert", "replace"):
                    for para in read_paras[j1:j2]:
                        duplicate = para in approved_paras
                        findings.append(ReadbackFinding(
                            DUPLICATED_CONTENT if duplicate else EXTRA_CONTENT,
                            "A paragraph appears more often than in the approved text." if duplicate else
                            "The published document contains text that was not in the approved text.",
                            "error", para[:100]))

    approved_body, _ = split_body_and_references(approved_text)
    read_body, _ = split_body_and_references(read)
    approved_cites = {citation_key(c.names, c.year) for c in extract_in_text_citations(approved_body) if c.source_id is None}
    read_cites = {citation_key(c.names, c.year) for c in extract_in_text_citations(norm_read_or(read_body, read)) if c.source_id is None}
    for lead, year in sorted(approved_cites - read_cites):
        findings.append(ReadbackFinding(CITATION_LOST, f"In-text citation ({lead} {year}) did not survive publication.",
                                        "error"))

    approved_refs = parse_references(approved_text)
    read_refs = parse_references(read)
    read_ref_text = normalize(read)
    missing_refs = [r for r in approved_refs if normalize(r.raw) not in read_ref_text]
    if approved_refs and not read_refs and any(normalize(r.raw) not in read_ref_text for r in approved_refs):
        findings.append(ReadbackFinding(REFERENCES_TRUNCATED, "The reference list is missing from the published document.",
                                        "error"))
    else:
        for ref in missing_refs:
            truncated = normalize(ref.raw)[:25] in read_ref_text
            code, msg = (REFERENCES_TRUNCATED, "A reference entry is cut short.") if truncated else (
                REFERENCE_LOST, "A reference entry is missing.")
            findings.append(ReadbackFinding(code, msg, "error", ref.raw[:100]))

    tail = normalize(approved_text)[-60:]
    if tail and not norm_read.endswith(tail) and not prior_text:
        findings.append(ReadbackFinding(TEXT_TRUNCATED, "The end of the approved text is not at the end of the "
                                        "published document.", "error", tail))

    approved_words, read_words = _body_word_count(approved_text), _body_word_count(read)
    # When appending to an existing document the destination legitimately holds more words.
    if approved_words != read_words and not prior_text:
        findings.append(ReadbackFinding(
            WORD_COUNT_CHANGED, f"Word count changed from {approved_words} to {read_words}.", "warning"))
    if not prior_text and (
            (min_words is not None and read_words < min_words) or (max_words is not None and read_words > max_words)):
        findings.append(ReadbackFinding(
            WORD_COUNT_OUT_OF_RANGE, f"Published body has {read_words} words; required "
            f"{min_words if min_words is not None else 0}-{max_words if max_words is not None else 'any'}.", "error"))

    if prior_text and normalize(prior_text) and normalize(prior_text) not in norm_read:
        findings.append(ReadbackFinding(PRIOR_CONTENT_LOST, "Content that was in the destination before the update "
                                        "is no longer there.", "error"))

    # Presentation: report, do not fail.
    if re.search(r"\*\*[^*\n]+\*\*", read) or re.search(r"(?m)^[ \t]*#{1,6}[ \t]+\S", read):
        findings.append(ReadbackFinding(FORMATTING_LITERAL, "Markdown markers appear as literal characters in the "
                                        "published document.", "info"))
    if re.search(r"(?m)^\|.*\|[ \t]*$", approved_text) or "![" in approved_text:
        findings.append(ReadbackFinding(UNSUPPORTED_ELEMENT, "The approved text has tables or images, which this "
                                        "destination does not carry as plain text.", "info"))

    status = "MISMATCH" if any(f.severity == "error" for f in findings) else "VERIFIED"
    return ReadbackVerification(
        status, approved_words, read_words, findings,
        checks_run=["paragraphs", "duplicates", "in-text citations", "reference entries", "text end",
                    "word count", "formatting"] + (["prior content"] if prior_text else []))


def norm_read_or(body: str, whole: str) -> str:
    """Body text to scan for citations: the body when a reference split exists, else the whole text."""
    return body if body.strip() else whole
