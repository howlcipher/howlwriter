"""Detect internal workflow commentary that leaked into text meant for a reader.

A final post should not tell the reader how it was drafted or checked: "this is
my recommendation, not a cited result" is a provenance note, and provenance
belongs in the machine-facing record. A real limitation, a source
qualification or an honest statement of uncertainty about the *subject* is
different and must stay.

The detector is deliberately narrow. It matches phrasing that talks about the
drafting and verification process (retrieved or supplied sources, status
codes, source ids, model self-reference, editing instructions), never a word
list that would also catch ordinary scholarship. It reports; it does not
rewrite or delete. Callers decide what to do with a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from howlwriter.domain.sentences import split_sentences
from howlwriter.domain.serialization import DataClassSerializationMixin

LEAK_PROVENANCE_NOTE = "LEAK_PROVENANCE_NOTE"
LEAK_SOURCE_PROCESS = "LEAK_SOURCE_PROCESS"
LEAK_VERIFICATION_STATUS = "LEAK_VERIFICATION_STATUS"
LEAK_EDITORIAL_INSTRUCTION = "LEAK_EDITORIAL_INSTRUCTION"
LEAK_MODEL_SELF_REFERENCE = "LEAK_MODEL_SELF_REFERENCE"
LEAK_PLACEHOLDER = "LEAK_PLACEHOLDER"

_SEVERITY_ERROR = "error"
_SEVERITY_WARNING = "warning"

# (code, severity, pattern, why). Patterns are matched per sentence.
_RULES: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    (LEAK_PROVENANCE_NOTE, _SEVERITY_WARNING,
     re.compile(
         r"\b(?:my|our|the author'?s)\s+(?:own\s+)?(?:recommendation|interpretation|inference|opinion|view|reading)"
         r"s?,?\s+(?:and\s+)?not\s+(?:a\s+|an\s+)?(?:cited|sourced|verified|supported|established)\b"
         r"|\bnot\s+a\s+(?:cited|sourced|verified)\s+(?:result|claim|finding|fact|statement)\b"
         r"|\b(?:this|that|it)\s+(?:is|was)\s+(?:an?\s+)?(?:unsourced|uncited|unverified)\s+"
         r"(?:recommendation|interpretation|inference|claim)\b",
         re.IGNORECASE),
     "Provenance note addressed to a checker, not the reader. The first-person framing already marks "
     "a recommendation; record the distinction in provenance."),
    (LEAK_SOURCE_PROCESS, _SEVERITY_WARNING,
     re.compile(
         r"\b(?:the\s+)?(?:supplied|provided|retrieved|collected|given)\s+(?:sources?|materials?|documents?|evidence)"
         r"\b(?!\s+(?:were\s+)?(?:screened|coded|analy[sz]ed|reviewed))"
         r"|\b(?:according\s+to|per|based\s+on)\s+the\s+(?:supplied|provided|retrieved)\s+(?:sources?|evidence)\b"
         r"|\bsources?\s+(?:I|we)\s+(?:was|were)\s+given\b"
         r"|\bonly\s+(?:what\s+)?the\s+(?:supplied|provided)\s+sources?\s+(?:say|state|support)\b",
         re.IGNORECASE),
     "Refers to how sources were gathered for the task rather than to the sources' content."),
    (LEAK_VERIFICATION_STATUS, _SEVERITY_ERROR,
     re.compile(
         r"\b(?-i:NEEDS_REVIEW|READY_FOR_HUMAN_REVIEW|UNVERIFIABLE|VERIFIED|MISMATCH|INCOMPLETE|"
         r"CITATION_[A-Z_]+|AI_STYLE_[A-Z_]+|METADATA_UNKNOWN)\b"
         r"|\[(?:S\d{3}|source\s*id[^\]]*)\]"
         r"|\bsource\s+S\d{3}\b"
         r"|\b(?:claim|citation|meaning)\s+(?:verification|check|preservation)\s+"
         r"(?:passed|failed|flagged|status|result)\b"
         r"|\bverified\s+(?:against|with)\s+(?:the\s+)?(?:primary\s+source|retrieved|crossref|doi)\b",
         re.IGNORECASE),
     "Verification status or an internal identifier appears in reader-facing prose."),
    (LEAK_EDITORIAL_INSTRUCTION, _SEVERITY_ERROR,
     re.compile(
         r"\b(?:here(?:'s| is)\s+(?:the\s+|your\s+|a\s+)?(?:revised|final|updated|rewritten)\s+"
         r"(?:draft|version|post|response|text))\b"
         r"|\b(?:as\s+(?:requested|instructed)|per\s+your\s+(?:instructions|request))\b"
         r"|\bnote\s+to\s+(?:the\s+)?(?:reviewer|editor|grader|self)\b"
         r"|\b(?:word\s+count|target\s+length)\s*[:=]?\s*\d+\b"
         r"|\(\s*\d{2,4}\s+words?\s*\)",
         re.IGNORECASE),
     "Editing or task instruction left in the text."),
    (LEAK_MODEL_SELF_REFERENCE, _SEVERITY_ERROR,
     re.compile(
         r"\bas\s+an?\s+(?:ai|artificial\s+intelligence|large\s+language\s+model|llm|language\s+model)\b"
         r"|\bI\s+(?:am|'m)\s+(?:an?\s+)?(?:ai|language\s+model|assistant)\b"
         r"|\bI\s+(?:cannot|can't|am\s+unable\s+to)\s+(?:browse|access\s+the\s+internet|verify\s+this)\b"
         r"|\bHowlWriter\b|\bHowlPlane\b",
         re.IGNORECASE),
     "Unrequested reference to the model or tool that produced the text."),
    (LEAK_PLACEHOLDER, _SEVERITY_ERROR,
     re.compile(r"\[(?:citation\s+needed|insert[^\]]*|TODO[^\]]*|TBD[^\]]*|your\s+name|source\s+needed)\]"
                r"|\bTODO\b|\bFIXME\b|\bXXX\b",
                re.IGNORECASE),
     "Unresolved placeholder."),
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_HEADING_OR_REFERENCE_START = re.compile(r"^\s*#{1,6}\s*(?:references|bibliography|works cited)\b", re.I)


@dataclass
class LeakageFinding(DataClassSerializationMixin):
    code: str
    severity: str
    sentence: str
    matched_text: str
    sentence_index: int
    message: str


def _body(text: str) -> str:
    """The reader-facing body: text before a References/Bibliography section."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _HEADING_OR_REFERENCE_START.match(line) or line.strip().lower().strip("*# ") in {
                "references", "bibliography", "works cited"}:
            return "\n".join(lines[:i])
    return text


def detect_leakage(text: str, *, genre: str = "") -> list[LeakageFinding]:
    """Find internal workflow commentary in the body of `text`.

    In a research paper ("academic_research_paper") a methodology may describe
    how sources were collected, so source-process phrasing is not flagged there;
    the hard markers (status codes, ids, instructions, model self-reference,
    placeholders) still are.
    """
    findings: list[LeakageFinding] = []
    sentences = split_sentences(_body(text).replace("\n", " "))
    for index, sentence in enumerate(sentences):
        for code, severity, pattern, why in _RULES:
            if code == LEAK_SOURCE_PROCESS and genre == "academic_research_paper":
                continue
            match = pattern.search(sentence)
            if match is not None:
                findings.append(LeakageFinding(
                    code=code, severity=severity, sentence=sentence, matched_text=match.group(0),
                    sentence_index=index, message=why))
    return findings


def has_blocking_leakage(findings: list[LeakageFinding]) -> bool:
    return any(f.severity == _SEVERITY_ERROR for f in findings)
