"""Check a reply against the post it answers.

A reply can sound convincing while describing something the other person never
said. This module extracts the places where the reply attributes a position to
the peer ("you note that ...", "Casey argues ...") and tests each against the
peer's actual post. It also checks that the reply adds something, that quoted
words are real, and that it did not carry out an instruction smuggled into the
post.

It is lexical. It finds invented or stretched attributions and reversed polarity
in the common case; it cannot prove a paraphrase faithful, so a GROUNDED result
means "nothing here contradicts the post", and a person still reads both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
import re

from howlwriter.domain.genres import check_genre_conformance
from howlwriter.domain.sentences import split_sentences
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.replies.untrusted import InjectionFinding, scan_untrusted


class GroundingState(str, enum.Enum):
    GROUNDED = "GROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    UNSUPPORTED = "UNSUPPORTED"
    UNGROUNDED = "UNGROUNDED"  # no source post was available


SUPPORTED_COVERAGE = 0.6
PARTIAL_COVERAGE = 0.4
MIN_ATTRIBUTION_WORDS = 3
MIN_NOVEL_SENTENCES = 2
MIN_QUOTE_WORDS = 4

NO_SOURCE_POST = "REPLY_NO_SOURCE_POST"
ATTRIBUTION_UNSUPPORTED = "REPLY_ATTRIBUTION_UNSUPPORTED"
ATTRIBUTION_PARTIAL = "REPLY_ATTRIBUTION_PARTIAL"
ATTRIBUTION_POLARITY = "REPLY_ATTRIBUTION_POLARITY"
NO_ATTRIBUTION = "REPLY_NO_ATTRIBUTION_FOUND"
QUOTE_NOT_IN_POST = "REPLY_QUOTE_NOT_IN_POST"
NO_NEW_CONTRIBUTION = "REPLY_NO_NEW_CONTRIBUTION"
INJECTION_IN_POST = "REPLY_POST_CONTAINS_INSTRUCTIONS"
INJECTION_ECHOED = "REPLY_FOLLOWED_POST_INSTRUCTION"
WORD_COUNT = "REPLY_WORD_COUNT"

# Findings that bear on whether the reply is grounded in the post. Word count and
# genre conventions are reported alongside but do not change the grounding state.
_GROUNDING_CODES = frozenset({
    "REPLY_ATTRIBUTION_PARTIAL", "REPLY_ATTRIBUTION_POLARITY", "REPLY_NO_ATTRIBUTION_FOUND",
    "REPLY_NO_NEW_CONTRIBUTION", "REPLY_POST_CONTAINS_INSTRUCTIONS",
})

_STOP = frozenset("""a an the and or but if then so of to in on at by for with from as is are was were be been being it its this
that these those i we you your our their his her they them he she not no do does did can could would should may might
will shall have has had also just very more most than into about over under between both each other such own same too
only which who whom what when where why how there here""".split())
_NEG = re.compile(r"\b(?:not|no|never|neither|nor|cannot|without|n't|none|nobody|nothing)\b|n't\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_VERBS = (r"(?:points?\s+out|pointed\s+out|notes?|noted|argues?|argued|says?|said|suggests?|suggested|mentions?|mentioned|"
          r"raises?|raised|claims?|claimed|states?|stated|writes?|wrote|describes?|described|emphasi[sz]es?|emphasi[sz]ed|"
          r"highlights?|highlighted|observes?|observed|proposes?|proposed|explains?|explained|recommends?|recommended|"
          r"makes?\s+the\s+point|made\s+the\s+point)")
_YOU = re.compile(rf"\byou(?:'ve|\s+have)?\s+(?:also\s+|then\s+|already\s+|rightly\s+|correctly\s+)?{_VERBS}\b(?:\s+that)?\s*(.*)",
                  re.I)
_YOUR = re.compile(r"\byour\s+(?:point|argument|claim|post|view|observation|suggestion|recommendation|"
                   r"emphasis|framing|description)\s+(?:about|on|that|regarding|is\s+that|of)?\s*(.*)", re.I)
_QUOTE = re.compile(r"[“\"]([^”\"]{10,300})[”\"]")
# Where the reply stops reporting the peer and starts speaking for itself. ", and that ..." continues
# the attribution; ", and the ..." or ", which ..." is the author's own clause.
_CUT_AT_OWN_VIEW = re.compile(
    r",?\s*(?:and|but|so|which|yet)\s+(?:I|we)\b|;|\.\s+(?:I|we)\b|,\s*(?:and|but|so|which|yet)\s+(?!that\b)")
# Words that may sit before an attribution at the start of its clause. Anything else before "you"
# ("the review you mention ...") makes it a relative clause inside the author's own sentence.
_CLAUSE_LEADS = frozenset({"and", "but", "while", "as", "so", "because", "since", "though", "although", "yet",
                           "if", "when", "also", "then", "first", "second", "finally", "clearly", "indeed"})
_CITATION_PAREN = re.compile(r"\s*\([^()]*\d{4}[^()]*\)")


def _starts_a_clause(sentence: str, match_start: int) -> bool:
    before = sentence[:match_start].rstrip()
    if not before:
        return True
    if before[-1] in ",;:(":
        return True
    last = re.findall(r"[A-Za-z']+", before)
    return bool(last) and last[-1].lower() in _CLAUSE_LEADS


def _stem(word: str) -> str:
    for suffix in ("ations", "ation", "ingly", "ing", "edly", "ed", "ies", "ly", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _content_stems(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9][a-z0-9'-]*", text.lower()) if w not in _STOP and len(w) > 2]


def _sentences(text: str) -> list[str]:
    return split_sentences(text)


@dataclass
class SourcePost(DataClassSerializationMixin):
    text: str
    author: str = ""
    label: str = ""


@dataclass
class Attribution(DataClassSerializationMixin):
    reply_sentence: str
    attributed_clause: str
    coverage: float
    status: str  # SUPPORTED | PARTIAL | UNSUPPORTED | TOO_THIN
    best_post_sentence: str = ""


@dataclass
class GroundingFinding(DataClassSerializationMixin):
    code: str
    message: str
    severity: str = "warning"  # "error" | "warning" | "info"
    evidence: str = ""


@dataclass
class GroundingReport(DataClassSerializationMixin):
    state: GroundingState
    word_count: int = 0
    attributions: list[Attribution] = field(default_factory=list)
    findings: list[GroundingFinding] = field(default_factory=list)
    injection_attempts: list[InjectionFinding] = field(default_factory=list)

    @property
    def fully_source_grounded(self) -> bool:
        return self.state is GroundingState.GROUNDED


def _peer_names(posts: list[SourcePost]) -> list[str]:
    names: list[str] = []
    for post in posts:
        parts = post.author.split()
        names.extend(n for n in (post.author, parts[0] if parts else "") if n)
    return names


def _attributions(reply: str, posts: list[SourcePost]) -> list[tuple[str, str]]:
    """(sentence, clause) pairs where the reply says what the peer said."""
    pairs: list[tuple[str, str]] = []
    named = [re.compile(rf"\b{re.escape(n)}\s+(?:also\s+)?{_VERBS}\b(?:\s+that)?\s*(.*)", re.I)
             for n in _peer_names(posts)]
    for sentence in _sentences(reply):
        for pattern in (_YOU, _YOUR, *named):
            m = pattern.search(sentence)
            if m and _starts_a_clause(sentence, m.start()):
                clause = _CUT_AT_OWN_VIEW.split(_CITATION_PAREN.sub("", m.group(1)))[0].strip(" ,;.")
                pairs.append((sentence, clause))
                break
    return pairs


def _polarity_clash(clause: str, post_sentence: str) -> bool:
    return bool(_NEG.search(clause)) != bool(_NEG.search(post_sentence))


def check_reply(
    reply: str,
    posts: list[SourcePost] | None,
    *,
    min_words: int | None = None,
    max_words: int | None = None,
    extra_quotable_text: str = "",
    genre: str = "academic_peer_reply",
) -> GroundingReport:
    """Ground a reply against the post(s) it answers."""
    body = re.split(r"\n[ \t]*(?:#{1,6}[ \t]*|\*\*)[ \t]*(?:references|bibliography)\b", reply, maxsplit=1, flags=re.I)[0]
    words = len(re.findall(r"\b[\w'-]+\b", body))
    findings: list[GroundingFinding] = []

    if min_words is not None and words < min_words or max_words is not None and words > max_words:
        findings.append(GroundingFinding(
            WORD_COUNT, f"Reply has {words} words; allowed {min_words or 0}-{max_words or 'any'}.", "error"))

    posts = [p for p in (posts or []) if p.text.strip()]
    if not posts:
        findings.append(GroundingFinding(
            NO_SOURCE_POST,
            "The post being answered was not supplied, so what the reply attributes to the peer cannot "
            "be checked. Do not treat this reply as source-grounded.", "error"))
        return GroundingReport(GroundingState.UNGROUNDED, words, [], findings)

    post_text = "\n".join(p.text for p in posts)
    post_stems = set(_content_stems(post_text))
    post_sentences = _sentences(post_text)

    injections = [f for p in posts for f in scan_untrusted(p.text)]
    if injections:
        findings.append(GroundingFinding(
            INJECTION_IN_POST,
            f"The post contains {len(injections)} instruction-like passage(s) aimed at a model. "
            "They were treated as quoted text only.", "warning", injections[0].sentence[:160]))
    reply_norm = re.sub(r"\W+", " ", body.lower())
    for hit in injections:
        words_in_hit = re.sub(r"\W+", " ", hit.sentence.lower()).split()
        for i in range(0, max(len(words_in_hit) - 5, 0) + 1):
            window = " ".join(words_in_hit[i:i + 6])
            if len(window.split()) == 6 and window in reply_norm:
                findings.append(GroundingFinding(
                    INJECTION_ECHOED, "The reply repeats wording from an instruction embedded in the post.",
                    "error", hit.sentence[:160]))
                break

    attributions: list[Attribution] = []
    attributed_sentences: set[str] = set()
    for sentence, clause in _attributions(body, posts):
        attributed_sentences.add(sentence)
        stems = _content_stems(clause)
        if len(stems) < MIN_ATTRIBUTION_WORDS:
            attributions.append(Attribution(sentence, clause, 1.0, "TOO_THIN"))
            continue
        coverage = sum(1 for s in stems if s in post_stems) / len(stems)
        best = max(post_sentences, key=lambda ps: len(set(stems) & set(_content_stems(ps))), default="")
        if coverage >= SUPPORTED_COVERAGE:
            status = "SUPPORTED"
        elif coverage >= PARTIAL_COVERAGE:
            status = "PARTIAL"
        else:
            status = "UNSUPPORTED"
        if status != "UNSUPPORTED" and best and _polarity_clash(clause, best):
            overlap = len(set(stems) & set(_content_stems(best))) / max(len(set(stems)), 1)
            if overlap >= 0.5:
                findings.append(GroundingFinding(
                    ATTRIBUTION_POLARITY,
                    "The reply and the closest sentence in the post differ in negation; check the reply "
                    "does not reverse what the peer said.", "warning", f"reply: {clause[:100]} | post: {best[:100]}"))
        attributions.append(Attribution(sentence, clause, round(coverage, 2), status, best))
        if status == "UNSUPPORTED":
            findings.append(GroundingFinding(
                ATTRIBUTION_UNSUPPORTED,
                f"The post does not appear to say this ({coverage:.0%} of the attributed wording is in it).",
                "error", clause[:160]))
        elif status == "PARTIAL":
            findings.append(GroundingFinding(
                ATTRIBUTION_PARTIAL, f"Only part of this attribution is in the post ({coverage:.0%}).",
                "warning", clause[:160]))

    if not attributions:
        findings.append(GroundingFinding(
            NO_ATTRIBUTION,
            "No sentence attributes a position to the peer, so the reply's engagement with their "
            "argument cannot be checked.", "warning"))

    haystack = re.sub(r"\s+", " ", (post_text + " " + extra_quotable_text).lower())
    for m in _QUOTE.finditer(body):
        quoted = re.sub(r"\s+", " ", m.group(1).strip()).lower().rstrip(".,;")
        if len(quoted.split()) >= MIN_QUOTE_WORDS and quoted not in haystack:
            findings.append(GroundingFinding(
                QUOTE_NOT_IN_POST, "Quoted words do not appear in the post or the supplied sources.",
                "error", m.group(1)[:160]))

    novel = 0
    for sentence in _sentences(body):
        if sentence in attributed_sentences:
            continue
        stems = _content_stems(sentence)
        if len(stems) >= 5 and sum(1 for s in stems if s not in post_stems) / len(stems) >= 0.5:
            novel += 1
    if novel < MIN_NOVEL_SENTENCES:
        findings.append(GroundingFinding(
            NO_NEW_CONTRIBUTION,
            f"Only {novel} sentence(s) add wording beyond the post; the reply may restate the peer's "
            "argument without extending it.", "warning"))

    for f in check_genre_conformance(body, genre):
        findings.append(GroundingFinding(f.code, f.message, f.severity, f.matched_text))

    if any(a.status == "UNSUPPORTED" for a in attributions) or any(
            f.code in (QUOTE_NOT_IN_POST, INJECTION_ECHOED) for f in findings):
        state = GroundingState.UNSUPPORTED
    elif any(f.code in _GROUNDING_CODES for f in findings):
        state = GroundingState.PARTIALLY_GROUNDED
    else:
        state = GroundingState.GROUNDED
    return GroundingReport(state, words, attributions, findings, injections)
