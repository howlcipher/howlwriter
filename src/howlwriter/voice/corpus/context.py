"""Stage 6: work out what KIND of writing a document is.

Nobody writes one way. The same person is careful and hedged in a graduate
paper, direct and concrete in a work document, and looser again in something
personal -- and a profile that averages those three into one "voice" describes
none of them. So documents are sorted into contexts, and the profile carries
context blocks that modify the global tendencies.

The rule that matters most here is that a folder name is not evidence. A file
under `school docs/` may be a work document someone parked there; a file under
`documents/` may be a graduate paper. Path words contribute a small prior --
capped well below what any single content signal is worth -- and never enough
to decide a classification on their own.

The second rule is that ambiguity is an answer. `unknown` and `mixed` are
real outcomes: a document that will not commit contributes to the global
profile and to no context, which is better than inventing a context block
from a document that never supported it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from howlwriter.voice.corpus.cleanup import CleanupResult
from howlwriter.voice.corpus.features import DocumentFeatures

ACADEMIC = "academic"
PROFESSIONAL = "professional"
GENERAL = "general"
SOCIAL = "social"
UNKNOWN = "unknown"
MIXED = "mixed"

#: The most a path can contribute. One strong content signal is worth 2.0,
#: so the path can tip a close call and can never win one by itself.
MAX_PATH_PRIOR = 0.8

#: How far ahead the leader must be to claim a context outright. Inside this
#: margin with two strong candidates the answer is `mixed`; with none, it is
#: `unknown`.
DECISION_MARGIN = 1.5

#: Below this the evidence is too thin to name any context.
MIN_DECISIVE_SCORE = 2.5

_CITATION = re.compile(r"\(\s*[A-Z][\w'’-]+(?:\s+et\s+al\.?)?,?\s*\d{4}[a-z]?\s*[,)]")
_NUMERIC_CITATION = re.compile(r"\[\d{1,3}\]")

_ACADEMIC_PHRASES = (
    "this paper", "this study", "this analysis", "this report examines",
    "the literature", "prior research", "previous studies", "the findings",
    "the results suggest", "this research", "the methodology", "the framework",
    "research question", "the data indicate", "as noted by", "according to",
    "et al", "peer-reviewed", "hypothesis", "empirical", "theoretical",
    "in conclusion", "the scope of this", "limitations of this",
)
_ACADEMIC_HEDGES = (
    "may suggest", "appears to", "tends to", "is likely", "could indicate",
    "arguably", "to some extent", "it is possible that", "generally",
    "in most cases", "the evidence suggests",
)
_PROFESSIONAL_PHRASES = (
    "the team", "stakeholder", "deliverable", "deployment", "rollout",
    "incident", "postmortem", "runbook", "on-call", "sprint", "roadmap",
    "the client", "the customer", "our organization", "the business",
    "sla", "kpi", "requirements gathering", "project plan", "handoff",
    "in production", "the environment", "escalation", "change request",
    "onboarding", "quarterly", "leadership", "budget", "vendor",
    "best practice", "lessons learned", "next steps", "action item",
)
_SOCIAL_PHRASES = (
    "i've been thinking", "hot take", "unpopular opinion", "quick thought",
    "just shipped", "shout out", "shoutout", "my two cents",
    "here's the thing", "let's be real", "comment below", "follow me",
    "connect with me", "drop a comment", "link in", "what do you think?",
)

#: Hashtags are a genuine social signal, but they must be matched as tags.
#: Matching a bare "#" counted every markdown heading as social evidence and
#: pushed academic papers toward a social score during dogfood.
_HASHTAG = re.compile(r"(?:^|\s)#[A-Za-z][\w]{2,}")
_ASSIGNMENT_STRUCTURE = re.compile(
    r"\b(?:assignment|coursework|module\s+\d|week\s+\d|part\s+[ivx1-9]|"
    r"question\s+\d|section\s+\d|lab\s+\d|exercise\s+\d)\b",
    re.IGNORECASE,
)

#: Weak path priors. Multiple hits do not stack past MAX_PATH_PRIOR.
_PATH_HINTS: tuple[tuple[str, str], ...] = (
    ("school", ACADEMIC), ("class", ACADEMIC), ("course", ACADEMIC),
    ("assignment", ACADEMIC), ("turn in", ACADEMIC), ("turnin", ACADEMIC),
    ("paper", ACADEMIC), ("thesis", ACADEMIC), ("essay", ACADEMIC),
    ("homework", ACADEMIC), ("semester", ACADEMIC), ("lecture", ACADEMIC),
    ("work", PROFESSIONAL), ("job", PROFESSIONAL), ("client", PROFESSIONAL),
    ("project", PROFESSIONAL), ("business", PROFESSIONAL), ("career", PROFESSIONAL),
    ("meeting", PROFESSIONAL), ("report", PROFESSIONAL),
    ("post", SOCIAL), ("posts", SOCIAL), ("linkedin", SOCIAL),
    ("blog", SOCIAL), ("social", SOCIAL), ("tweet", SOCIAL),
    ("note", GENERAL), ("notes", GENERAL), ("journal", GENERAL),
    ("personal", GENERAL), ("draft", GENERAL),
)


@dataclass
class ContextAssessment:
    """The context a document belongs to, with the evidence behind it."""

    context: str = UNKNOWN
    confidence: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    path_prior: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ContextAssessment":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


def path_prior(path: Path | str) -> tuple[dict[str, float], str]:
    """Score contexts from directory and file names. Weak by construction."""
    text = str(path).lower()
    scores: dict[str, float] = {}
    matched: list[str] = []
    for token, context in _PATH_HINTS:
        if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", text):
            scores[context] = scores.get(context, 0.0) + 0.4
            matched.append(token)
    for context in list(scores):
        scores[context] = min(MAX_PATH_PRIOR, scores[context])
    return scores, ",".join(sorted(set(matched)))


def _count(text: str, phrases: tuple[str, ...]) -> int:
    return sum(text.count(phrase) for phrase in phrases)


def classify_context(
    *,
    path: Path | str,
    text: str,
    cleanup: CleanupResult,
    features: DocumentFeatures,
) -> ContextAssessment:
    """Classify a cleaned document's writing context from its own content."""
    lowered = text.lower()
    scores: dict[str, float] = {ACADEMIC: 0.0, PROFESSIONAL: 0.0, GENERAL: 0.0, SOCIAL: 0.0}
    signals: list[str] = []

    def add(context: str, amount: float, label: str) -> None:
        scores[context] = scores.get(context, 0.0) + amount
        signals.append(f"{label}(+{amount:.1f} {context})")

    # --- academic evidence ---
    citations = len(_CITATION.findall(text)) + len(_NUMERIC_CITATION.findall(text))
    if citations >= 3:
        add(ACADEMIC, 3.0, f"citations={citations}")
    elif citations >= 1:
        add(ACADEMIC, 1.2, f"citations={citations}")

    references_removed = cleanup.removed_kinds.get("reference_entry", 0) + cleanup.removed_kinds.get(
        "references_section", 0
    )
    if references_removed >= 3:
        add(ACADEMIC, 2.0, f"reference_section={references_removed}")

    academic_phrases = _count(lowered, _ACADEMIC_PHRASES)
    if academic_phrases >= 4:
        add(ACADEMIC, 2.0, f"academic_phrases={academic_phrases}")
    elif academic_phrases >= 2:
        add(ACADEMIC, 1.0, f"academic_phrases={academic_phrases}")

    hedges = _count(lowered, _ACADEMIC_HEDGES)
    if hedges >= 3:
        add(ACADEMIC, 1.0, f"hedging={hedges}")

    if _ASSIGNMENT_STRUCTURE.search(text):
        add(ACADEMIC, 0.8, "assignment_structure")

    if features.contraction_rate < 0.15 and features.sentence_length_mean > 20:
        add(ACADEMIC, 1.5, "formal_register")

    # --- professional evidence ---
    professional_phrases = _count(lowered, _PROFESSIONAL_PHRASES)
    if professional_phrases >= 5:
        add(PROFESSIONAL, 3.0, f"workplace_vocabulary={professional_phrases}")
    elif professional_phrases >= 2:
        add(PROFESSIONAL, 1.5, f"workplace_vocabulary={professional_phrases}")

    if 0.15 <= features.contraction_rate <= 1.2 and 13 <= features.sentence_length_mean <= 22:
        add(PROFESSIONAL, 1.0, "measured_register")
    if features.heading_rate > 0.15 and citations == 0 and professional_phrases >= 2:
        add(PROFESSIONAL, 1.0, "structured_no_citations")

    # --- social evidence ---
    social_phrases = _count(lowered, _SOCIAL_PHRASES) + len(_HASHTAG.findall(text))
    if social_phrases >= 3:
        add(SOCIAL, 2.5, f"social_phrases={social_phrases}")
    elif social_phrases >= 1:
        add(SOCIAL, 0.8, f"social_phrases={social_phrases}")
    if features.words < 400 and features.contraction_rate > 1.5 and features.question_rate > 0.08:
        add(SOCIAL, 2.0, "short_conversational")
    if features.first_person_rate > 3.0 and features.paragraph_words_mean < 45:
        add(SOCIAL, 1.0, "personal_short_paragraphs")

    # --- general evidence ---
    if features.contraction_rate > 0.8 and citations == 0 and professional_phrases < 2:
        add(GENERAL, 1.8, "informal_uncited")
    if 0.4 < features.first_person_rate <= 3.0 and citations == 0:
        add(GENERAL, 1.2, "reflective_first_person")

    # --- weak path prior, applied last ---
    priors, matched = path_prior(path)
    for context, amount in priors.items():
        scores[context] = scores.get(context, 0.0) + amount
    if matched:
        signals.append(f"path_prior({matched}, capped at {MAX_PATH_PRIOR})")

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    runner, runner_score = ranked[1] if len(ranked) > 1 else ("", 0.0)

    if top_score < MIN_DECISIVE_SCORE:
        return ContextAssessment(
            context=UNKNOWN, confidence=0.0, scores=scores, signals=signals,
            path_prior=matched,
            reason=(
                f"no context reached the evidence threshold (best was {top} at "
                f"{top_score:.1f}, needs {MIN_DECISIVE_SCORE}); counted toward the "
                "global profile only"
            ),
        )

    if top_score - runner_score < DECISION_MARGIN and runner_score >= MIN_DECISIVE_SCORE:
        return ContextAssessment(
            context=MIXED, confidence=0.0, scores=scores, signals=signals,
            path_prior=matched,
            reason=(
                f"{top} ({top_score:.1f}) and {runner} ({runner_score:.1f}) are within "
                f"{DECISION_MARGIN} of each other; treated as mixed and counted toward "
                "the global profile only"
            ),
        )

    # A path prior must never be the reason a document got its context, so
    # the decision is re-checked with the prior removed.
    without_prior = top_score - priors.get(top, 0.0)
    runner_without = runner_score - priors.get(runner, 0.0)
    if without_prior < MIN_DECISIVE_SCORE or (without_prior - runner_without) < DECISION_MARGIN:
        return ContextAssessment(
            context=UNKNOWN, confidence=0.0, scores=scores, signals=signals,
            path_prior=matched,
            reason=(
                f"{top} only led once the folder-name prior was added; content alone "
                "does not support the classification"
            ),
        )

    spread = top_score - runner_score
    confidence = round(min(1.0, 0.45 + 0.1 * spread + 0.03 * min(top_score, 8.0)), 3)
    return ContextAssessment(
        context=top, confidence=confidence, scores=scores, signals=signals,
        path_prior=matched,
        reason=f"{top} led on content evidence ({top_score:.1f} vs {runner_score:.1f})",
    )
