"""Stage 5: decide what a document actually is, and how much to trust it.

A file living in someone's drive is not evidence that they wrote it. The
folder holds instructor prompts, syllabi, downloaded papers, forms, résumés,
lab-tool exports, and other people's documents alongside the user's own
writing, and treating all of it as voice would produce a profile of the
folder rather than the person.

So every document gets a classification and an inclusion state, and both
carry a reason. The bias is conservative in a specific direction: when the
evidence is ambiguous the document is downweighted or held, not confidently
included. A profile built from thirty documents the user really wrote beats
one built from ninety documents of uncertain provenance.

One rule here is a safety rule rather than a quality rule. Drives contain
credential files, recovery codes, and password exports, and `.txt` is a prose
format, so a secret-shaped file would otherwise sail through the extension
filter. Those are detected and excluded before anything derived from them is
computed or stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.voice.corpus.cleanup import CleanupResult
from howlwriter.voice.corpus.features import DocumentFeatures

# --- classifications ---------------------------------------------------

LIKELY_AUTHORED = "likely_authored"
LIKELY_AUTHORED_WITH_REFERENCES = "likely_authored_with_reference_material"
CORRESPONDENCE = "correspondence"
NOTES = "notes"
RESUME = "resume"
TECHNICAL_DOCUMENT = "technical_document"
MIXED_AUTHORSHIP = "mixed_authorship"
TEMPLATE_OR_PROMPT = "template_or_prompt"
COPIED_REFERENCE = "copied_reference"
POSSIBLE_AI_ASSISTED_OUTLIER = "possible_ai_assisted_outlier"
UNKNOWN_AUTHORSHIP = "unknown_authorship"
NON_PROSE = "non_prose"
SENSITIVE_CONTENT = "sensitive_content"

# --- inclusion states --------------------------------------------------

INCLUDE = "include"
INCLUDE_LOW_WEIGHT = "include_low_weight"
HOLD_FOR_REVIEW = "hold_for_review"
EXCLUDE = "exclude"

#: How much a document counts toward aggregate traits.
_WEIGHTS = {INCLUDE: 1.0, INCLUDE_LOW_WEIGHT: 0.4, HOLD_FOR_REVIEW: 0.0, EXCLUDE: 0.0}

#: Below this many authored words a document cannot support a style claim.
MIN_PROSE_WORDS = 120

#: Above this share of apparatus the file is a form or a prompt wearing a
#: document's clothes.
MAX_APPARATUS_RATIO = 0.72

#: Credential-shaped content. Matching any of these excludes the document
#: outright: nothing derived from it is computed, cached, or persisted.
_SECRET_MARKERS = (
    re.compile(r"\b(?:pass(?:word|phrase)|passwd|pwd)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:recovery|backup|one[- ]?time)\s+codes?\b", re.IGNORECASE),
    re.compile(r"\b(?:2fa|mfa|totp|otp)\s+(?:codes?|secret|seed|backup)\b", re.IGNORECASE),
    re.compile(r"\b(?:api[_\s-]?key|secret[_\s-]?key|access[_\s-]?token|"
               r"private[_\s-]?key|client[_\s-]?secret)\s*[:=]", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:seed\s+phrase|mnemonic\s+phrase|wallet\s+seed)\b", re.IGNORECASE),
    re.compile(r"\bcvv\b.{0,20}\b\d{3,4}\b", re.IGNORECASE),
)

#: Filenames that announce themselves. A cheap pre-filter, not the defence --
#: the content scan above is what actually protects a file whose name says
#: nothing. Bare "secret" and bare "token" are deliberately NOT here: they are
#: ordinary words in project names ("secret_project_notes.md", "token
#: bucket rate limiting"), and excluding real writing on that basis would be a
#: false positive with no safety benefit, since such a file's content is
#: checked anyway.
_SECRET_NAME = re.compile(
    r"(?:password|passwd|credential|recovery[_\s-]?code|backup[_\s-]?code|"
    r"\b2fa\b|\bmfa\b|\botp\b|private[_\s-]?key|api[_\s-]?key|apikey|"
    r"secret[_\s-]?(?:key|store|file|vault|env)|"
    r"(?:auth|access|refresh|bearer)[_\s-]?token|"
    r"wallet[_\s-]?(?:seed|key)|seed[_\s-]?phrase|keystore|\.pem\b|id_rsa)",
    re.IGNORECASE,
)

_RESUME_MARKERS = (
    "professional experience", "work experience", "employment history",
    "technical skills", "core competencies", "education", "certifications",
    "professional summary", "career objective", "references available",
)
_CORRESPONDENCE_MARKERS = (
    "dear ", "hi ", "hello ", "best regards", "kind regards", "sincerely,",
    "thanks,", "thank you,", "sent from my", "to:", "cc:", "subject:",
    "on behalf of", "looking forward to hearing",
)
_SYLLABUS_MARKERS = (
    "course syllabus", "office hours", "attendance policy", "academic integrity",
    "course schedule", "required textbook", "grading scale", "course objectives",
    "prerequisite", "week 1", "module 1", "credit hours", "withdrawal policy",
)

_CITATION_MARKER = re.compile(r"\(\s*[A-Z][\w'’-]+(?:\s+et\s+al\.?)?,?\s*\d{4}[a-z]?\s*[,)]")
#: Lines that are unambiguously code or shell transcript. Deliberately
#: narrow: a markdown quote marker or a lone brace is not evidence of code,
#: and treating it as such threw out a real assignment during dogfood.
_CODE_ISH = re.compile(
    r"^\s*(?:def\s+\w+\s*\(|class\s+\w+\s*[(:]|import\s+\w+|from\s+\w+\s+import\s|"
    r"function\s+\w+\s*\(|(?:var|let|const)\s+\w+\s*=|#include\s*[<\"]|"
    r"(?:public|private|protected)\s+(?:static\s+)?\w+\s+\w+\s*\(|"
    r"SELECT\s+.+\s+FROM\s|INSERT\s+INTO\s|"
    r"[\w.@~-]*\s*[$#]\s+\w|</?[a-z][\w-]*(?:\s+\w+=|/?>))",
    re.MULTILINE | re.IGNORECASE,
)

#: A résumé is prose-shaped enough to slip past the other filters, so it is
#: matched on its section vocabulary plus its structure rather than on
#: sentence length alone.
_RESUME_NAME = re.compile(r"\b(?:resume|résumé|\bcv\b|curriculum[_\s-]?vitae)\b", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


@dataclass
class QualityAssessment:
    """What this document is, whether to use it, and why."""

    classification: str = UNKNOWN_AUTHORSHIP
    inclusion: str = HOLD_FOR_REVIEW
    weight: float = 0.0
    reason: str = ""
    signals: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "QualityAssessment":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


def looks_sensitive(name: str, text: str) -> bool:
    """True when a file appears to hold credentials or recovery material.

    Checked before any feature is computed. A false positive costs one
    document out of a corpus; a false negative means secrets get parsed,
    hashed, and cached, so the trade is not close.
    """
    if _SECRET_NAME.search(name):
        return True
    head = text[:20000]
    return any(pattern.search(head) for pattern in _SECRET_MARKERS)


def _count(text: str, markers: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for marker in markers if marker in lowered)


def classify_document(
    *,
    filename: str,
    raw_text: str,
    cleanup: CleanupResult,
    features: DocumentFeatures,
) -> QualityAssessment:
    """Classify one extracted document and set its inclusion state."""
    signals: list[str] = []

    if looks_sensitive(filename, raw_text):
        return QualityAssessment(
            classification=SENSITIVE_CONTENT,
            inclusion=EXCLUDE,
            weight=0.0,
            reason=(
                "file appears to contain credentials or recovery material; "
                "excluded before any derived data was computed"
            ),
            signals=["secret_shaped"],
        )

    lowered = raw_text.lower()
    prose_words = cleanup.kept_words

    # --- not prose at all ---
    lines = [line for line in raw_text.splitlines() if line.strip()]
    code_lines = len(_CODE_ISH.findall(raw_text))
    if code_lines >= 5 and lines and code_lines / len(lines) > 0.25:
        signals.append(f"code_like_lines={code_lines}/{len(lines)}")
        return QualityAssessment(
            classification=NON_PROSE, inclusion=EXCLUDE, weight=0.0,
            reason="content reads as source code or command output, not prose",
            signals=signals,
        )
    if prose_words < MIN_PROSE_WORDS:
        return QualityAssessment(
            classification=NON_PROSE, inclusion=EXCLUDE, weight=0.0,
            reason=(
                f"only {prose_words} words of authored prose survived cleanup "
                f"(minimum {MIN_PROSE_WORDS})"
            ),
            signals=signals + ["too_little_prose"],
        )
    if features.sentences < 8:
        return QualityAssessment(
            classification=NON_PROSE, inclusion=EXCLUDE, weight=0.0,
            reason=f"only {features.sentences} sentences; too fragmentary to describe style",
            signals=signals + ["too_few_sentences"],
        )

    # --- documents that are mostly apparatus ---
    prompt_blocks = cleanup.removed_kinds.get("rubric_or_prompt", 0)
    if cleanup.apparatus_ratio >= MAX_APPARATUS_RATIO:
        signals.append(f"apparatus_ratio={cleanup.apparatus_ratio:.2f}")
        return QualityAssessment(
            classification=TEMPLATE_OR_PROMPT, inclusion=EXCLUDE, weight=0.0,
            reason=(
                f"{cleanup.apparatus_ratio:.0%} of the document was boilerplate, prompt, "
                "or reference material rather than authored prose"
            ),
            signals=signals,
        )
    if _count(lowered, _SYLLABUS_MARKERS) >= 3:
        signals.append("syllabus_language")
        return QualityAssessment(
            classification=TEMPLATE_OR_PROMPT, inclusion=EXCLUDE, weight=0.0,
            reason="reads as a syllabus or course-policy document, not the user's writing",
            signals=signals,
        )
    if prompt_blocks >= 3 and prompt_blocks * 60 > prose_words:
        signals.append(f"prompt_blocks={prompt_blocks}")
        return QualityAssessment(
            classification=TEMPLATE_OR_PROMPT, inclusion=EXCLUDE, weight=0.0,
            reason="dominated by assignment-instruction language addressed to a student",
            signals=signals,
        )

    # --- documents that are prose, but not the kind that defines voice ---
    resume_markers = _count(lowered, _RESUME_MARKERS)
    named_resume = bool(_RESUME_NAME.search(filename))
    if resume_markers >= 3 or (named_resume and resume_markers >= 1):
        signals.append(f"resume_markers={resume_markers}, named={named_resume}")
        return QualityAssessment(
            classification=RESUME, inclusion=EXCLUDE, weight=0.0,
            reason=(
                "résumé or CV: achievement bullets in a fixed template, written to a "
                "convention rather than in the author's natural prose voice"
            ),
            signals=signals,
        )
    if _count(lowered[:1500], _CORRESPONDENCE_MARKERS) >= 2 and prose_words < 600:
        signals.append("correspondence_markers")
        return QualityAssessment(
            classification=CORRESPONDENCE, inclusion=INCLUDE_LOW_WEIGHT,
            weight=_WEIGHTS[INCLUDE_LOW_WEIGHT],
            reason="reads as an email or message; real writing, but a narrow register",
            signals=signals,
        )

    # --- copied or mixed authorship ---
    citation_density = len(_CITATION_MARKER.findall(raw_text)) / max(1, features.sentences)
    quoted_blocks = (
        cleanup.removed_kinds.get("long_quotation", 0)
        + cleanup.removed_kinds.get("block_quote", 0)
    )
    # Both spellings count. A loose reference line is removed as a
    # `reference_entry`, but a document with a proper "## References" heading
    # has its whole tail removed as `references_section` instead -- and that
    # is the more common shape, so counting only the former would classify a
    # properly formatted paper as having no sources at all.
    reference_entries = (
        cleanup.removed_kinds.get("reference_entry", 0)
        + cleanup.removed_kinds.get("references_section", 0)
    )

    if citation_density > 0.55:
        signals.append(f"citation_density={citation_density:.2f}")
        return QualityAssessment(
            classification=COPIED_REFERENCE, inclusion=HOLD_FOR_REVIEW, weight=0.0,
            reason=(
                "nearly every sentence carries a citation, which reads as a downloaded "
                "paper or a literature summary rather than the user's own argument"
            ),
            signals=signals,
        )
    if quoted_blocks >= 6 and quoted_blocks * 40 > prose_words:
        signals.append(f"quoted_blocks={quoted_blocks}")
        return QualityAssessment(
            classification=MIXED_AUTHORSHIP, inclusion=INCLUDE_LOW_WEIGHT,
            weight=_WEIGHTS[INCLUDE_LOW_WEIGHT],
            reason="substantial quoted material alongside the authored prose",
            signals=signals,
        )

    # --- the good cases ---
    if features.first_person_rate < 0.05 and features.second_person_rate > 1.5:
        signals.append("second_person_dominant")
        return QualityAssessment(
            classification=UNKNOWN_AUTHORSHIP, inclusion=HOLD_FOR_REVIEW, weight=0.0,
            reason=(
                "addressed to a reader in the second person with no first-person voice; "
                "authorship is unclear"
            ),
            signals=signals,
        )

    if reference_entries >= 3 or citation_density > 0.12:
        signals.append(f"citations={reference_entries}, density={citation_density:.2f}")
        return QualityAssessment(
            classification=LIKELY_AUTHORED_WITH_REFERENCES, inclusion=INCLUDE,
            weight=_WEIGHTS[INCLUDE],
            reason="sustained authored prose that cites sources; the apparatus was stripped",
            signals=signals,
        )
    if features.long_word_rate > 0.24 and features.first_person_rate < 0.4:
        signals.append(f"long_word_rate={features.long_word_rate:.2f}")
        return QualityAssessment(
            classification=TECHNICAL_DOCUMENT, inclusion=INCLUDE, weight=_WEIGHTS[INCLUDE],
            reason="dense technical prose in the user's own voice",
            signals=signals,
        )
    if prose_words < 350:
        signals.append(f"prose_words={prose_words}")
        return QualityAssessment(
            classification=NOTES, inclusion=INCLUDE_LOW_WEIGHT,
            weight=_WEIGHTS[INCLUDE_LOW_WEIGHT],
            reason="short authored piece; usable but too brief to weigh fully",
            signals=signals,
        )

    return QualityAssessment(
        classification=LIKELY_AUTHORED, inclusion=INCLUDE, weight=_WEIGHTS[INCLUDE],
        reason="sustained authored prose with no signal of copied or template content",
        signals=signals,
    )


def weight_for(inclusion: str) -> float:
    return _WEIGHTS.get(inclusion, 0.0)
