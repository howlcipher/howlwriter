"""Academic genres: conventions for kinds of academic writing within one voice.

A writing mode is a task and a context is a register (see voice/application.py
MODE_CONTEXTS). Genres refine the academic task without adding a register or an
identity: every academic genre resolves to WritingMode.ACADEMIC, so the same
`<identity>-academic` voice profile applies. A genre changes what the writer is
asked to produce and what the checks expect, never whose voice it is.
"""

from __future__ import annotations

from dataclasses import dataclass
import enum
import re

from howlwriter.domain.serialization import DataClassSerializationMixin


class AcademicGenre(str, enum.Enum):
    DISCUSSION = "academic_discussion"
    PEER_REPLY = "academic_peer_reply"
    RESEARCH_PAPER = "academic_research_paper"


def parse_genre(value: str | AcademicGenre | None) -> AcademicGenre | None:
    """Resolve a genre name, tolerating hyphens and case. None if it is not a genre."""
    if isinstance(value, AcademicGenre):
        return value
    if not value:
        return None
    try:
        return AcademicGenre(str(value).strip().lower().replace("-", "_"))
    except ValueError:
        return None


def base_mode_name(mode: str | None) -> str:
    """The writing-mode name for a mode string, with academic genres folded into "academic".

    Mode-keyed tables (profile routing, context lookup) use plain mode names; a
    genre is an academic task, so it must resolve there rather than miss.
    """
    name = (mode or "").strip().lower()
    return "academic" if parse_genre(name) is not None else name


@dataclass(frozen=True)
class GenreProfile:
    mission: str
    guidance: str
    allows_headings: bool


PROFILES: dict[AcademicGenre, GenreProfile] = {
    AcademicGenre.DISCUSSION: GenreProfile(
        mission="Your mission is to draft a graduate discussion-board post that argues a clear position, "
                "grounded in the retrieved sources.",
        guidance=(
            "GENRE: ACADEMIC DISCUSSION POST (not a research paper)\n"
            "- State a position early and develop it as one cohesive argument; do not list points.\n"
            "- Short paragraphs, no section headings, no title, no abstract or formal conclusion.\n"
            "- First person is natural where the author is giving a recommendation or judgment.\n"
            "- Cite only what a source actually says; keep the author's own recommendations in the\n"
            "  author's voice rather than attributing them to a source.\n"
            "- Do not describe your drafting or verification process in the prose."
        ),
        allows_headings=False,
    ),
    AcademicGenre.PEER_REPLY: GenreProfile(
        mission="Your mission is to draft a graduate discussion-board REPLY to a classmate that engages "
                "their actual argument and adds something new, grounded in the retrieved sources.",
        guidance=(
            "GENRE: PEER REPLY (a conversation with a classmate, not a review or an essay)\n"
            "- Speak to the classmate directly ('you'), not about them in the third person.\n"
            "- Describe their position only as the supplied reference material states it; never invent\n"
            "  or stretch what they said.\n"
            "- Contribute one substantive addition: a technical insight, a counterargument, or an\n"
            "  application. Agreement or disagreement is fine but is not the contribution.\n"
            "- Do not open with praise or agreement formulas ('Great post', 'I completely agree').\n"
            "- No headings, no title, no formal conclusion. Conversational academic tone.\n"
            "- Do not cite the classmate's post as a source; refer to it in prose.\n"
            "- Do not describe your drafting or verification process in the prose."
        ),
        allows_headings=False,
    ),
    AcademicGenre.RESEARCH_PAPER: GenreProfile(
        mission="Your mission is to draft a rigorous, high-quality academic research paper on the specified "
                "topic, strictly structured according to the required outline and strictly grounded in the "
                "retrieved sources.",
        guidance=(
            "GENRE: ACADEMIC RESEARCH PAPER\n"
            "- Formal structure with headings for the required outline sections.\n"
            "- Deeper source integration: synthesize across sources and compare their findings."
        ),
        allows_headings=True,
    ),
}

GENRE_PROFILE_LEGACY_MISSION = PROFILES[AcademicGenre.RESEARCH_PAPER].mission


# ----------------------------------------------------------- conformance

GENRE_HEADINGS = "GENRE_HEADINGS_IN_SHORT_FORM"
GENRE_FORMULAIC_OPENING = "GENRE_FORMULAIC_OPENING"
GENRE_THIRD_PERSON_PEER = "GENRE_THIRD_PERSON_PEER"
GENRE_PAPER_REGISTER = "GENRE_PAPER_REGISTER"

_OPENING_FORMULAS = re.compile(
    r"^\W*(?:(?:great|excellent|wonderful|fantastic|nice|good|awesome|interesting|insightful)\s+"
    r"(?:post|job|work|points?|insights?|read|discussion|analysis|take)"
    r"|(?:i|we)\s+(?:completely|totally|fully|wholeheartedly|absolutely)\s+agree"
    r"|thank\s+you\s+for\s+(?:sharing|your\s+post|posting)"
    r"|thanks\s+for\s+(?:sharing|your\s+post|posting)"
    r"|i\s+(?:really\s+)?(?:enjoyed|appreciate[d]?)\s+(?:reading|your|this)"
    r"|this\s+is\s+(?:a|an)\s+(?:great|excellent|insightful|interesting|well[- ]written)\b)",
    re.IGNORECASE,
)
_THIRD_PERSON_OPENING = re.compile(
    r"^\W*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\s+(?:argues|says|states|notes|points\s+out|suggests|writes|"
    r"mentions|explains|claims|observes|makes\s+the\s+point|raises)\b")
_PAPER_REGISTER = re.compile(
    r"\b(?:this\s+(?:paper|essay|study|report)\s+(?:will|examines|argues|explores)|in\s+conclusion|"
    r"the\s+remainder\s+of\s+this|in\s+summary,|to\s+summari[sz]e,)", re.IGNORECASE)
_HEADING = re.compile(r"^\s*#{1,6}\s+\S", re.MULTILINE)
_REFERENCES_HEADING = re.compile(r"^\s*(?:#{1,6}\s*|\*\*)\s*(?:references|bibliography)\b", re.IGNORECASE | re.MULTILINE)


@dataclass
class GenreFinding(DataClassSerializationMixin):
    code: str
    message: str
    severity: str = "warning"
    matched_text: str = ""


def _body_before_references(text: str) -> str:
    m = _REFERENCES_HEADING.search(text)
    return text[: m.start()] if m else text


def check_genre_conformance(text: str, genre: AcademicGenre | str | None) -> list[GenreFinding]:
    """Findings where text reads like the wrong genre. Reports only; never edits."""
    genre = parse_genre(genre)
    if genre is None or genre is AcademicGenre.RESEARCH_PAPER:
        return []
    body = _body_before_references(text).strip()
    findings: list[GenreFinding] = []
    heading = _HEADING.search(body)
    if heading:
        findings.append(GenreFinding(
            GENRE_HEADINGS, "A discussion post or reply should read as prose, without section headings.",
            matched_text=heading.group(0).strip()))
    paper = _PAPER_REGISTER.search(body)
    if paper:
        findings.append(GenreFinding(
            GENRE_PAPER_REGISTER, "Research-paper phrasing in a discussion-board genre.",
            matched_text=paper.group(0)))
    if genre is AcademicGenre.PEER_REPLY:
        prose = re.sub(r"^\s*#{1,6}[^\n]*\n", "", body).lstrip()
        first = re.split(r"(?<=[.!?])\s", prose, maxsplit=1)[0] if prose else ""
        opening = _OPENING_FORMULAS.match(first)
        if opening:
            findings.append(GenreFinding(
                GENRE_FORMULAIC_OPENING, "Formulaic praise or agreement opening.",
                matched_text=opening.group(0).strip()))
        if _THIRD_PERSON_OPENING.match(first) and not re.search(r"\b(?:you|your|you're|you've)\b", body, re.I):
            findings.append(GenreFinding(
                GENRE_THIRD_PERSON_PEER,
                "Reply discusses the classmate in the third person and never addresses them; "
                "it reads as a review of the post rather than a conversation.",
                matched_text=first[:60]))
    return findings
