"""What a document is, and who proposed-or-confirmed wrote it.

Two separate axes, because conflating them is how a profile gets built from
the wrong writing.

**Category** is the document's purpose and genre: an academic lab, a
discussion response, engineering documentation, assignment instructions. It
is read from content (reusing the corpus pipeline's quality and context
classifiers, which treat folder names as a small capped prior, never as
evidence on their own) and can be corrected by the user.

**Authorship** is provenance, not style:

    CONFIRMED_HUMAN_AUTHORED         primary voice evidence
    HUMAN_AUTHORED_LIGHT_AI_EDITING  usable at reduced weight, if attested
    MIXED_AUTHORSHIP                 only attested passages may be used
    SUBSTANTIALLY_AI_GENERATED       never used as personal voice evidence
    THIRD_PARTY                      never used
    UNKNOWN_AUTHORSHIP               held for review

The scanner only ever PROPOSES an authorship, with reasons. A proposal of
CONFIRMED_HUMAN_AUTHORED is not a confirmation: that state is reachable only
through the person's own attestation (`howlwriter voice review`). No
stylometric signal here can distinguish a person's unaided writing from
their AI-assisted drafts, and nothing pretends to. Style signals (formulaic
density, outlier distance) raise a document's review priority; they never
move it into or out of a profile.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re

from howlwriter.voice.corpus import quality as quality_stage
from howlwriter.voice.identity.provenance import ProvenanceSignals

# --- authorship ------------------------------------------------------------

CONFIRMED_HUMAN_AUTHORED = "CONFIRMED_HUMAN_AUTHORED"
HUMAN_AUTHORED_LIGHT_AI_EDITING = "HUMAN_AUTHORED_LIGHT_AI_EDITING"
MIXED_AUTHORSHIP = "MIXED_AUTHORSHIP"
SUBSTANTIALLY_AI_GENERATED = "SUBSTANTIALLY_AI_GENERATED"
THIRD_PARTY = "THIRD_PARTY"
UNKNOWN_AUTHORSHIP = "UNKNOWN_AUTHORSHIP"

AUTHORSHIP_STATES = (
    CONFIRMED_HUMAN_AUTHORED,
    HUMAN_AUTHORED_LIGHT_AI_EDITING,
    MIXED_AUTHORSHIP,
    SUBSTANTIALLY_AI_GENERATED,
    THIRD_PARTY,
    UNKNOWN_AUTHORSHIP,
)

#: Weight a document carries in a personal profile, by attested authorship.
#: Mixed documents contribute only their attested paragraphs, at full weight
#: for those paragraphs; without a paragraph selection they contribute nothing.
PROFILE_WEIGHTS = {
    CONFIRMED_HUMAN_AUTHORED: 1.0,
    HUMAN_AUTHORED_LIGHT_AI_EDITING: 0.5,
    MIXED_AUTHORSHIP: 1.0,
}

# --- categories ------------------------------------------------------------

ACADEMIC_PAPER = "academic_paper"
ACADEMIC_DISCUSSION = "academic_discussion"
ACADEMIC_LAB = "academic_lab"
RESEARCH_ANALYSIS = "research_analysis"
TECHNICAL_DOCUMENTATION = "technical_documentation"
PROFESSIONAL_ENGINEERING = "professional_engineering_document"
PROFESSIONAL_ARTICLE = "professional_article"
PUBLIC_COMMENTARY = "linkedin_or_public_commentary"
PERSONAL_WRITING = "personal_writing"
INFORMAL_COMMUNICATION = "informal_communication"
NOTES_OUTLINE = "notes_and_outlines"
TEMPLATE = "template"
ASSIGNMENT_INSTRUCTIONS = "assignment_instructions"
COPIED_REFERENCE = "copied_reference"
THIRD_PARTY_DOCUMENT = "third_party_document"
AI_GENERATED_DOCUMENT = "ai_generated_document"
MIXED_AUTHORSHIP_DOCUMENT = "mixed_authorship_document"
RESUME = "resume"
ADMINISTRATIVE = "administrative_record"
NON_PROSE = "non_prose"
CONFIDENTIAL = "confidential_excluded"
UNKNOWN = "unknown"

CATEGORIES = (
    ACADEMIC_PAPER,
    ACADEMIC_DISCUSSION,
    ACADEMIC_LAB,
    RESEARCH_ANALYSIS,
    TECHNICAL_DOCUMENTATION,
    PROFESSIONAL_ENGINEERING,
    PROFESSIONAL_ARTICLE,
    PUBLIC_COMMENTARY,
    PERSONAL_WRITING,
    INFORMAL_COMMUNICATION,
    NOTES_OUTLINE,
    TEMPLATE,
    ASSIGNMENT_INSTRUCTIONS,
    COPIED_REFERENCE,
    THIRD_PARTY_DOCUMENT,
    AI_GENERATED_DOCUMENT,
    MIXED_AUTHORSHIP_DOCUMENT,
    RESUME,
    ADMINISTRATIVE,
    NON_PROSE,
    CONFIDENTIAL,
    UNKNOWN,
)

#: Which profile context each category feeds. Categories absent here never
#: feed a profile, whatever their authorship.
CATEGORY_CONTEXT = {
    ACADEMIC_PAPER: "academic",
    ACADEMIC_DISCUSSION: "academic",
    ACADEMIC_LAB: "academic",
    RESEARCH_ANALYSIS: "academic",
    TECHNICAL_DOCUMENTATION: "professional",
    PROFESSIONAL_ENGINEERING: "professional",
    PROFESSIONAL_ARTICLE: "professional",
    PUBLIC_COMMENTARY: "professional",
}

_LAB = re.compile(
    r"\b(?:lab(?:oratory)?\s*(?:\d+|report|exercise)?|screenshot|figure\s+\d+|"
    r"wireshark|kibana|suricata|security onion|virtual machine|\bvm\b|terminal|"
    r"command|ran the|i ran|we ran|output shows|captured)\b",
    re.IGNORECASE,
)
_DISCUSSION = re.compile(
    r"\b(?:discussion|peer response|in response to|i agree|great post|your post|"
    r"you mentioned|you raised|classmates?|initial post)\b",
    re.IGNORECASE,
)
_RESEARCH = re.compile(
    r"\b(?:findings|methodology|literature|results indicate|this paper|this study|"
    r"research question|analysis of|we analyze|data set|dataset)\b",
    re.IGNORECASE,
)
_DOCS = re.compile(
    r"\b(?:install|configure|run the|usage|prerequisites|deploy(?:ment)?|"
    r"step \d|troubleshoot|endpoint|parameter|returns|handoff|runbook|readme)\b",
    re.IGNORECASE,
)
_ADMIN = re.compile(
    r"\b(?:transcript|financial aid|deferment|tuition|award letter|enrollment "
    r"verification|invoice|receipt|account number|policy number)\b",
    re.IGNORECASE,
)
_SELF_ASSESSMENT = re.compile(r"\bself[- ]assessment\b", re.IGNORECASE)
#: License texts and legal notices bundled with software. Drives that hold an
#: unpacked SDK or runtime contain dozens of them, and they are prose-shaped
#: enough to pass every structural filter.
_LICENSE = re.compile(
    r"permission is hereby granted|the software is provided \"?as is|licensed under the|"
    r"redistribution and use in source and binary forms|gnu (?:general|lesser) public license|"
    r"apache license|all rights reserved|warranties of merchantability|"
    r"without warranty of any kind|this notice shall be included|copyright \(c\)|"
    r"\bspdx-license-identifier\b|^#+\s*\S+\s+v?\d[\w.]*\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_PROFILE_EXPORT = re.compile(r"linkedin\.com/in/|www\.linkedin\.com", re.IGNORECASE)
_PROFILE_SECTIONS = re.compile(
    r"^\s*(?:top skills|contact|experience|education|summary|certifications|languages|honors-awards)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CITATION = re.compile(r"\(\s*[A-Z][\w'’-]+(?:\s+et\s+al\.?)?,?\s*\d{4}[a-z]?\s*[,)]")


@dataclass
class Classification:
    category: str = UNKNOWN
    category_confidence: float = 0.0
    context: str = "unknown"
    context_confidence: float = 0.0
    quality_classification: str = ""
    quality_inclusion: str = ""
    quality_reason: str = ""
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Classification":
        data = data or {}
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


@dataclass
class AuthorshipProposal:
    authorship: str = UNKNOWN_AUTHORSHIP
    confidence: str = "LOW"
    reasons: list[str] = field(default_factory=list)
    needs_review: bool = True
    review_priority: int = 0
    affects_profile: bool = False
    style_signals: list[str] = field(default_factory=list)
    #: A named extraction (see worksheet.EXTRACTIONS) that would isolate the
    #: author's text, proposed for the person to confirm.
    proposed_extraction: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "AuthorshipProposal":
        data = data or {}
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


def classify_category(
    *,
    quality: quality_stage.QualityAssessment,
    context: str,
    context_confidence: float,
    text: str,
    words: int,
    first_person_rate: float,
    list_rate: float,
    heading_rate: float,
    filename: str,
) -> Classification:
    """Category from content, using the corpus classifiers as the base."""
    result = Classification(
        context=context,
        context_confidence=context_confidence,
        quality_classification=quality.classification,
        quality_inclusion=quality.inclusion,
        quality_reason=quality.reason,
    )
    q = quality.classification
    lowered = text[:20000]

    def done(category: str, confidence: float, signal: str) -> Classification:
        result.category = category
        result.category_confidence = confidence
        result.signals.append(signal)
        return result

    if q == quality_stage.SENSITIVE_CONTENT:
        return done(CONFIDENTIAL, 1.0, "credential-shaped content")
    if len(_LICENSE.findall(lowered)) >= 2:
        return done(COPIED_REFERENCE, 0.8, "software license or legal notice")
    admin_hits = [m.lower() for m in _ADMIN.findall(lowered[:4000])]
    if len(set(admin_hits)) >= 2 or (len(admin_hits) >= 3 and words < 1500):
        return done(ADMINISTRATIVE, 0.7, "administrative record vocabulary")
    if q == quality_stage.RESUME:
        return done(RESUME, 0.8, quality.reason)
    if (
        _PROFILE_EXPORT.search(lowered[:6000])
        and len(_PROFILE_SECTIONS.findall(lowered[:12000])) >= 2
    ):
        return done(
            RESUME, 0.75, "professional-network profile export (formatted sections, not prose)"
        )
    if q == quality_stage.NON_PROSE:
        if list_rate >= 0.4 or heading_rate >= 0.3:
            return done(NOTES_OUTLINE, 0.5, "list- or heading-dominated with little prose")
        return done(NON_PROSE, 0.7, quality.reason)
    if q == quality_stage.TEMPLATE_OR_PROMPT:
        if "template" in filename.lower():
            return done(TEMPLATE, 0.7, "template structure (and named as one)")
        return done(ASSIGNMENT_INSTRUCTIONS, 0.6, quality.reason)
    if q == quality_stage.COPIED_REFERENCE:
        return done(COPIED_REFERENCE, 0.6, quality.reason)
    if q == quality_stage.CORRESPONDENCE:
        return done(INFORMAL_COMMUNICATION, 0.6, quality.reason)
    if q == quality_stage.NOTES:
        return done(NOTES_OUTLINE, 0.5, quality.reason)

    if context == "academic":
        discussion = len(_DISCUSSION.findall(lowered))
        lab = len(_LAB.findall(lowered))
        research = len(_RESEARCH.findall(lowered))
        if discussion >= 2 and words < 1500:
            return done(ACADEMIC_DISCUSSION, 0.6, f"discussion markers={discussion}")
        if lab >= 4:
            return done(ACADEMIC_LAB, 0.6, f"lab procedure markers={lab}")
        if research >= 3:
            return done(RESEARCH_ANALYSIS, 0.55, f"research analysis markers={research}")
        return done(ACADEMIC_PAPER, 0.55, "academic register")
    if context == "professional":
        docs = len(_DOCS.findall(lowered))
        if docs >= 4 or (heading_rate >= 0.15 and list_rate >= 0.15):
            return done(TECHNICAL_DOCUMENTATION, 0.55, f"documentation markers={docs}")
        if words >= 500 and heading_rate < 0.1:
            return done(PROFESSIONAL_ARTICLE, 0.45, "sustained professional prose")
        return done(PROFESSIONAL_ENGINEERING, 0.5, "professional register")
    if context == "social":
        return done(PUBLIC_COMMENTARY, 0.5, "public commentary register")

    # The context classifier abstains on documents whose register is
    # ambiguous, which is common for lab worksheets and short assignments.
    # Abstaining there would silently keep a person's own coursework out of
    # review, so content markers get a second, low-confidence look.
    lab = len(_LAB.findall(lowered))
    research = len(_RESEARCH.findall(lowered))
    citations = len(_CITATION.findall(lowered))
    if lab >= 4:
        result.context = "academic"
        return done(ACADEMIC_LAB, 0.35, f"lab markers={lab}; context classifier undecided")
    if citations >= 3 or (research >= 3 and q == quality_stage.LIKELY_AUTHORED_WITH_REFERENCES):
        result.context = "academic"
        return done(ACADEMIC_PAPER, 0.35, f"citations={citations}; context classifier undecided")
    if context == "general":
        if first_person_rate >= 1.0:
            return done(PERSONAL_WRITING, 0.45, "first-person general writing")
        return done(UNKNOWN, 0.3, "general register; purpose unclear")
    return done(UNKNOWN, 0.2, f"context {context}")


def propose_authorship(
    *,
    classification: Classification,
    provenance: ProvenanceSignals,
    filename: str,
    naturalness_values: dict[str, float] | None = None,
    auto_accept_pre_llm_bylined: bool = False,
) -> AuthorshipProposal:
    """A provenance proposal with reasons. Never a confirmation by itself."""
    proposal = AuthorshipProposal()
    reasons = proposal.reasons
    category = classification.category
    feeds_profile = category in CATEGORY_CONTEXT
    proposal.affects_profile = feeds_profile

    values = naturalness_values or {}
    if values.get("formulaic_density", 0.0) >= 6.0:
        proposal.style_signals.append(
            "formulaic phrasing is dense (advisory only; style is not evidence of authorship)"
        )
    if values.get("stock_transitions", 0.0) >= 0.15:
        proposal.style_signals.append("many sentences open with stock connectives (advisory only)")
    reasons.extend(provenance.notes)

    if category in (CONFIDENTIAL, ADMINISTRATIVE, NON_PROSE, RESUME):
        proposal.authorship = UNKNOWN_AUTHORSHIP
        proposal.needs_review = False
        proposal.affects_profile = False
        reasons.insert(0, f"category '{category}' never feeds a personal profile")
        return proposal

    if category in (TEMPLATE, ASSIGNMENT_INSTRUCTIONS, COPIED_REFERENCE):
        proposal.authorship = THIRD_PARTY
        proposal.confidence = "MEDIUM"
        proposal.needs_review = provenance.byline_identity
        proposal.review_priority = 1 if provenance.byline_identity else 0
        reasons.insert(0, f"content reads as {category.replace('_', ' ')}")
        if provenance.byline_identity:
            reasons.append("but it names you near the top; confirm whether any of it is yours")
        return proposal

    if provenance.ownership == "shared_with_me" and not provenance.byline_identity:
        # Routine: excluding someone else's shared file costs the profile
        # nothing, so it does not interrupt the person. It stays attestable.
        proposal.authorship = THIRD_PARTY
        proposal.confidence = "MEDIUM"
        proposal.needs_review = False
        reasons.insert(0, "shared with you by another Drive account and does not name you")
        return proposal

    if provenance.byline_other_person and not provenance.byline_identity:
        proposal.authorship = THIRD_PARTY
        proposal.confidence = "MEDIUM"
        proposal.needs_review = feeds_profile
        proposal.review_priority = 1
        reasons.insert(0, "a name/author field near the top names someone else")
        return proposal

    if classification.quality_classification == quality_stage.MIXED_AUTHORSHIP:
        proposal.authorship = MIXED_AUTHORSHIP
        proposal.confidence = "MEDIUM"
        proposal.review_priority = 3
        reasons.insert(0, "substantial quoted or copied material alongside authored prose")
        return proposal

    if provenance.generated_by_library:
        proposal.authorship = UNKNOWN_AUTHORSHIP
        proposal.review_priority = 4
        reasons.insert(
            0, "assembled by a document-generation program; whose words it holds is unknown"
        )
        return proposal

    if provenance.predates_llm_era and provenance.byline_identity:
        proposal.authorship = CONFIRMED_HUMAN_AUTHORED
        proposal.confidence = "MEDIUM"
        proposal.review_priority = 2
        proposal.needs_review = not auto_accept_pre_llm_bylined
        reasons.insert(0, "names you and predates public LLM tools (30 Nov 2022)")
        if not auto_accept_pre_llm_bylined:
            reasons.append("proposed only: confirmation is yours to give")
        return proposal

    proposal.authorship = UNKNOWN_AUTHORSHIP
    proposal.review_priority = 5 if feeds_profile else 1
    if provenance.byline_identity:
        reasons.insert(0, "names you, but was written when AI-assisted drafting was possible")
    elif provenance.predates_llm_era:
        reasons.insert(0, "predates public LLM tools, but nothing in it identifies the author")
    else:
        reasons.insert(0, "nothing in the document or its metadata establishes who wrote it")
    if proposal.style_signals:
        proposal.review_priority += 1
    proposal.needs_review = feeds_profile
    return proposal


def worksheet_proposal(
    proposal: AuthorshipProposal, *, answer_words: int, total_words: int, worth_reviewing: bool
) -> AuthorshipProposal:
    """Re-propose a publisher worksheet as mixed, with answers-only extraction."""
    reasons = [
        f"publisher lab worksheet: about {answer_words} of {total_words} words are the "
        "student's answer lines; the rest is the publisher's header, prompts and labels"
    ]
    if worth_reviewing:
        reasons.append(
            "confirm as MIXED_AUTHORSHIP with the worksheet_answers extraction to use only "
            "the answer lines"
        )
    else:
        reasons.append("too little answer text to contribute to a profile")
    reasons.extend(r for r in proposal.reasons if r not in reasons)
    return AuthorshipProposal(
        authorship=MIXED_AUTHORSHIP,
        confidence="MEDIUM",
        reasons=reasons,
        needs_review=worth_reviewing,
        review_priority=proposal.review_priority if worth_reviewing else 0,
        affects_profile=worth_reviewing,
        style_signals=list(proposal.style_signals),
        proposed_extraction="worksheet_answers" if worth_reviewing else "",
    )


def effective_category(category: str, authorship: str | None) -> str:
    """The category to show once an authorship decision exists."""
    if authorship == THIRD_PARTY and category in CATEGORY_CONTEXT:
        return THIRD_PARTY_DOCUMENT
    if authorship == SUBSTANTIALLY_AI_GENERATED:
        return AI_GENERATED_DOCUMENT
    if authorship == MIXED_AUTHORSHIP:
        return MIXED_AUTHORSHIP_DOCUMENT
    return category
