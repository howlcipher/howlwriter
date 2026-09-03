"""Telling three kinds of model addition apart.

Expanding an outline necessarily produces sentences the user did not write.
Most of them are harmless and some are not, and the difference is not length or
confidence but what the sentence ASSERTS.

LOGICAL EXPANSION restates or develops something the outline already claimed.
"Implementation cost created friction" becoming "that friction is what
protected incumbents from fast followers" adds no new commitment; it unpacks
one the author made.

CONNECTIVE PROSE asserts nothing about the world. Transitions, framing,
restatement. It cannot be wrong about a fact because it makes no factual claim.

A NEW FACTUAL ASSERTION is a commitment the author never made and may not agree
with. "Most enterprises replaced their data teams in 2024" is a claim about the
world that arrived from the model. In a research-backed mode it must be
supported, generalised, or removed. In an opinion piece it is not automatically
wrong -- but silently upgrading someone's opinion into an evidence-sounding
technical claim is, so it is surfaced either way.

The classifier is deliberately conservative in one direction. Where it cannot
tell, it reports NEW_FACTUAL rather than clearing the sentence: a false alarm
costs a glance, a false clear is the failure this exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.domain.outline import Outline

LOGICAL_EXPANSION = "LOGICAL_EXPANSION"
CONNECTIVE_PROSE = "CONNECTIVE_PROSE"
NEW_FACTUAL = "NEW_FACTUAL"

#: Overlap with the outline's own claims above which an addition reads as a
#: restatement of something the author already committed to.
_GROUNDED_OVERLAP = 0.60

#: Markers of a checkable assertion about the world: quantities, dates, named
#: proportions, attributed findings. These are what make a sentence something
#: the author could be wrong about rather than something they merely said.
_FACTUAL_MARKERS = (
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent)\b", re.I),
    re.compile(r"\b(?:19|20)\d{2}\b"),
    re.compile(r"\b\d[\d,]{2,}\b"),
    re.compile(r"\b(?:most|majority|nearly all|the average|studies|research|"
               r"survey|report(?:s|ed)?|data show|according to)\b", re.I),
    re.compile(r"\b(?:industry|enterprises|companies|organizations|teams)\s+"
               r"(?:are|have|now|increasingly)\b", re.I),
)

#: Sentences that assert nothing checkable.
_CONNECTIVE_MARKERS = (
    re.compile(r"^\s*(?:but|and|so|which|that|this|here|there|meanwhile|"
               r"in other words|put differently|the point is)\b", re.I),
)

_WORD = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have how i if in into is it its of
    on or that the their there they this to was were what when which who will with
    you your we our us not no than then so such can could would should may might
    must do does did done being been over under about after before more most some
    any each other same only own too very just also""".split()
)


#: Suffixes stripped before comparing. Without this, "creates friction" and
#: "created friction" share only one word out of two, and a plain restatement
#: of the author's own claim gets reported as a new assertion. Crude stemming
#: is enough here: the comparison is between two short sentences about the same
#: subject, not across a corpus.
_SUFFIXES = ("ing", "ed", "es", "s", "ly", "ive", "ion", "ions")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _content_words(text: str) -> set[str]:
    return {
        _stem(w)
        for w in _WORD.findall(text.lower())
        if w not in _STOPWORDS and len(w) > 2
    }


@dataclass
class ClaimFinding:
    claim: str
    classification: str
    basis: str = ""
    grounded_in: str = ""
    overlap: float = 0.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "classification": self.classification,
            "basis": self.basis,
            "grounded_in": self.grounded_in,
            "overlap": round(self.overlap, 3),
            "detail": self.detail,
        }


@dataclass
class ClaimReview:
    findings: list[ClaimFinding] = field(default_factory=list)
    #: True when a research-backed mode carries an unsupported new assertion.
    blocks_readiness: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def new_factual(self) -> list[ClaimFinding]:
        return [f for f in self.findings if f.classification == NEW_FACTUAL]

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "counts": {
                LOGICAL_EXPANSION: sum(
                    1 for f in self.findings if f.classification == LOGICAL_EXPANSION
                ),
                CONNECTIVE_PROSE: sum(
                    1 for f in self.findings if f.classification == CONNECTIVE_PROSE
                ),
                NEW_FACTUAL: len(self.new_factual),
            },
            "blocks_readiness": self.blocks_readiness,
            "notes": list(self.notes),
        }


def classify_addition(text: str, outline: Outline | None) -> ClaimFinding:
    """Decide what one model-added statement actually commits the author to."""
    stripped = text.strip()
    if not stripped:
        return ClaimFinding(claim=text, classification=CONNECTIVE_PROSE, detail="empty")

    best_overlap = 0.0
    best_source = ""
    if outline is not None:
        wanted = _content_words(stripped)
        if wanted:
            for node in outline.claims() + outline.preserved():
                overlap = len(wanted & _content_words(node.text)) / len(wanted)
                if overlap > best_overlap:
                    best_overlap, best_source = overlap, node.id

    if best_overlap >= _GROUNDED_OVERLAP:
        return ClaimFinding(
            claim=stripped,
            classification=LOGICAL_EXPANSION,
            grounded_in=best_source,
            overlap=best_overlap,
            detail="develops a claim the outline already made",
        )

    if any(marker.search(stripped) for marker in _FACTUAL_MARKERS):
        return ClaimFinding(
            claim=stripped,
            classification=NEW_FACTUAL,
            overlap=best_overlap,
            detail="asserts something checkable that the outline did not supply",
        )

    if any(marker.match(stripped) for marker in _CONNECTIVE_MARKERS):
        return ClaimFinding(
            claim=stripped,
            classification=CONNECTIVE_PROSE,
            overlap=best_overlap,
            detail="joins existing material without asserting anything new",
        )

    # Unclear. Reported as a new assertion rather than cleared, because a false
    # clear is the failure this exists to prevent.
    return ClaimFinding(
        claim=stripped,
        classification=NEW_FACTUAL,
        overlap=best_overlap,
        detail=(
            "could not be traced to the outline; reported as a new assertion "
            "rather than cleared"
        ),
    )


def review_additions(
    added_claims: list[dict] | None,
    outline: Outline | None,
    *,
    research_backed: bool,
    supported_claims: set[str] | None = None,
) -> ClaimReview:
    """Classify everything the writer reported adding.

    `research_backed` decides consequence, not classification. The same
    sentence is the same kind of addition in a LinkedIn post and a dissertation;
    what differs is whether an unsupported one may ship.
    """
    review = ClaimReview()
    supported = supported_claims or set()

    for entry in added_claims or []:
        text = str(entry.get("claim", "")) if isinstance(entry, dict) else str(entry)
        finding = classify_addition(text, outline)
        if isinstance(entry, dict):
            finding.basis = str(entry.get("basis", ""))
        if finding.classification == NEW_FACTUAL and text in supported:
            # Evidence changes whether a new assertion is safe, not where it
            # came from. Relabelling a source-backed model addition as a
            # LOGICAL_EXPANSION made genuinely added facts disappear from
            # provenance counts.
            finding.detail = "new factual assertion matched to retrieved evidence"
        review.findings.append(finding)

    unsupported = [f for f in review.new_factual if f.claim not in supported]
    if research_backed and unsupported:
        review.blocks_readiness = True
        review.notes.append(
            f"{len(unsupported)} new factual assertion(s) were added during "
            "expansion and are not supported by retrieved evidence. In a "
            "research-backed mode each must be supported, generalised, or "
            "removed before the document is ready."
        )
    elif unsupported:
        review.notes.append(
            f"{len(unsupported)} new factual assertion(s) were added during "
            "expansion. They are recorded in the provenance rather than "
            "blocking readiness, because this is not a research-backed mode -- "
            "but an opinion should not arrive sounding like evidence, so they "
            "are worth reading before publishing."
        )
    return review
