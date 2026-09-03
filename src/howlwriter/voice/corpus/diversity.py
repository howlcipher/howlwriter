"""The check that catches a profile turning into a costume.

The failure mode this exists for is subtle and would otherwise ship. Apply a
personal voice hard enough and every output starts arriving in the same
shape: the same kind of opening, the same paragraph count, the same closing
move, the same three-beat rhythm. Each individual piece reads fine. Together
they read as an impression of a person rather than as that person, who in
real life writes a 90-word note and a 4000-word paper and does not sound
identical in both.

So generated output is measured against the corpus it came from. Real writing
varies by a certain amount across documents; generated writing should vary by
a comparable amount. Substantially less variation means the profile is being
applied as a template, and the fix belongs in the application layer -- not in
compensating with more literal detail, which would make the cloning worse.

This is a heuristic guard, not a metric. It is calibrated to catch obvious
convergence and to stay quiet otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import statistics

from howlwriter.voice.corpus.features import DocumentFeatures, extract_features

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
NOT_EVALUATED = "NOT_EVALUATED"

#: Generated variation below this share of the corpus's own variation on a
#: dimension counts as convergence on that dimension.
CONVERGENCE_RATIO = 0.45

#: A dimension where the corpus itself barely varies cannot show convergence,
#: so it is skipped rather than counted as a false positive.
MIN_CORPUS_VARIATION = 0.08

#: How many dimensions must converge before the verdict moves.
WARNING_DIMENSIONS = 4
FAIL_DIMENSIONS = 7

#: Documents a context slice needs before it may stand in for the whole corpus.
#:
#: The comparison here is between coefficients of variation, and a CV computed
#: from two documents is noise wearing a number. Substituting such a slice does
#: not merely weaken the check, it inverts it: during this work a two-document
#: professional slice produced a corpus CV large enough to clear a real
#: parenthetical convergence that the full corpus caught. Eight is a heuristic
#: floor, chosen as the point where a CV starts to mean something rather than
#: from any property of a particular corpus; below it the global corpus is
#: kept and the length mismatch is reported instead.
MIN_CONTEXT_SLICE_DOCUMENTS = 8

#: Share of outputs that may share a two-word opening before it is a tic.
MAX_SHARED_OPENING_SHARE = 0.35
MAX_SHARED_CLOSING_SHARE = 0.35

#: Minimum outputs needed to say anything about variation at all.
MIN_SAMPLES = 4

_DIMENSIONS = (
    "sentence_length_mean",
    "sentence_length_stdev",
    "paragraph_words_mean",
    "paragraph_words_stdev",
    "paragraph_sentences_mean",
    "paragraph_sentences_stdev",
    "single_sentence_paragraph_rate",
    "short_sentence_rate",
    "long_sentence_rate",
    "lexical_diversity",
    "transition_rate",
    "sentence_initial_conjunction_rate",
    "fragment_rate",
    "parenthetical_rate",
    "contraction_rate",
    "first_person_rate",
    "question_rate",
    "long_word_rate",
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+")
_HASHTAG_LINE = re.compile(r"^(?:#[\w-]+\s*)+$")


@dataclass
class DimensionComparison:
    name: str
    corpus_variation: float = 0.0
    generated_variation: float = 0.0
    ratio: float = 1.0
    converged: bool = False


@dataclass
class DiversityResult:
    verdict: str = NOT_EVALUATED
    dimensions: list[DimensionComparison] = field(default_factory=list)
    repeated_openings: dict[str, int] = field(default_factory=dict)
    repeated_closings: dict[str, int] = field(default_factory=dict)
    rhetorical_signatures: dict[str, int] = field(default_factory=dict)
    top_rhetorical_signature_share: float = 0.0
    opening_classes: dict[str, int] = field(default_factory=dict)
    closing_classes: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    samples: int = 0

    @property
    def converged_dimensions(self) -> list[str]:
        return [d.name for d in self.dimensions if d.converged]


def _coefficient_of_variation(values: list[float]) -> float:
    """Spread relative to size, so dimensions on different scales compare."""
    usable = [v for v in values if v is not None]
    if len(usable) < 2:
        return 0.0
    mean = statistics.mean(usable)
    if abs(mean) < 1e-9:
        return 0.0
    return statistics.pstdev(usable) / abs(mean)


def _opening_key(text: str) -> str:
    words = _WORD.findall(text.strip())
    return " ".join(w.lower() for w in words[:2]) if len(words) >= 2 else ""


def _closing_key(text: str) -> str:
    sentences = [s for s in _SENTENCE.split(text.strip()) if s.strip()]
    if not sentences:
        return ""
    words = _WORD.findall(sentences[-1])
    return " ".join(w.lower() for w in words[:3]) if len(words) >= 3 else ""


def _repeats(keys: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in keys:
        if key:
            counts[key] = counts.get(key, 0) + 1
    return {key: count for key, count in counts.items() if count > 1}


_FIRST_PERSON_START = re.compile(r"^(I|In my|We|In our|My)\b", re.I)
_TIME_ANECDOTAL_START = re.compile(
    r"^(Last year|A few months ago|Recently|Years ago|In \d{4}|Back when)\b", re.I
)
_PERSONAL_ANECDOTAL_START = re.compile(r"^(When I|The first time I|I remember)\b", re.I)
_CONDITIONAL_START = re.compile(r"^(If|Unless|Whenever|When)\b", re.I)
_CONTEXTUAL_START = re.compile(
    r"^(In\b|Across\b|Under\b|For\b|While\b|As\b|Within\b)", re.I
)
_PROBLEM_START = re.compile(
    r"^(The (?:problem|failure|mistake|risk|trap|myth)|"
    r"(?:Most|Many) .{0,40}\b(?:fail|break|miss|get wrong)\b)",
    re.I,
)
_IMPERATIVE_START = re.compile(
    r"^(?:Start|Stop|Use|Treat|Choose|Build|Keep|Prefer|Avoid|Make|Ask|Cap|"
    r"Set|Limit|Remove|Do|"
    r"Do not|Don't|Never)\b",
    re.I,
)
_LABELLED_CLAIM_START = re.compile(r"^([^:\n]{2,50}):\s+\S")
_FINITE_VERB_IN_LABEL = re.compile(
    r"\b(?:is|are|was|were|be|been|has|have|had|does|do|did|"
    r"improves?|fails?|breaks?|creates?|means?|turns?|makes?)\b",
    re.I,
)


def _body_paragraphs(text: str) -> list[str]:
    """Markdown prose blocks, excluding headings and hashtag-only trailers."""
    body: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [
            line.strip()
            for line in block.splitlines()
            if line.strip()
            and not _MARKDOWN_HEADING.match(line.strip())
            and not _HASHTAG_LINE.match(line.strip())
        ]
        if lines:
            body.append(" ".join(lines))
    return body


def _first_sentence(text: str) -> str:
    sentences = [s.strip() for s in _SENTENCE.split(text.strip()) if s.strip()]
    return sentences[0] if sentences else text.strip()


def _is_labelled_claim(text: str) -> bool:
    match = _LABELLED_CLAIM_START.match(text)
    if not match:
        return False
    prefix = match.group(1)
    return (
        len(_WORD.findall(prefix)) <= 6
        and _FINITE_VERB_IN_LABEL.search(prefix) is None
    )


def classify_opening(text: str) -> str:
    """Categorize the first rhetorical move, using only the first sentence."""
    paragraphs = _body_paragraphs(text)
    if not paragraphs:
        return "direct_thesis"
    first_line = _first_sentence(paragraphs[0])
    if first_line.endswith("?"):
        return "question"
    if (
        _TIME_ANECDOTAL_START.search(first_line)
        or _PERSONAL_ANECDOTAL_START.search(first_line)
    ):
        return "anecdotal_entry"
    if _FIRST_PERSON_START.search(first_line):
        return "personal_observation"
    if _CONDITIONAL_START.search(first_line):
        return "conditional_setup"
    if _PROBLEM_START.search(first_line):
        return "problem_statement"
    if _IMPERATIVE_START.search(first_line):
        return "recommendation"
    if _is_labelled_claim(first_line):
        return "labelled_claim"
    if _CONTEXTUAL_START.search(first_line):
        return "contextual_statement"
    return "direct_thesis"


_RECOMMEND_END = re.compile(
    r"(?:^(?:Start|Stop|Use|Treat|Choose|Build|Keep|Prefer|Avoid|Make|Ask|Cap|"
    r"Set|Limit|Remove|"
    r"Do not|Don't)\b|\b(?:should|must|ought to|need to|recommend|"
    r"best approach)\b)",
    re.I,
)
_IMPLICATION_END = re.compile(
    r"\b(which means|the result is|the consequence is|that leaves|"
    r"this leaves|therefore|as a result)\b",
    re.I,
)
_PERSONAL_END = re.compile(r"\b(I think|in my view|for me|my take|I suspect)\b", re.I)
_SUMMARY_END = re.compile(
    r"^(?:In short|Ultimately|In summary|To summarize)\b|"
    r"\b(?:comes down to|boils down to)\b",
    re.I,
)
_QUALIFIED_END = re.compile(
    r"^(?:If|Unless)\b|\b(?:may|might|could|likely|probably)\b", re.I
)


def classify_closing(text: str) -> str:
    """Deterministically categorize the rhetorical ending move of a piece."""
    paragraphs = _body_paragraphs(text)
    sentences = [
        s.strip()
        for s in _SENTENCE.split(paragraphs[-1] if paragraphs else "")
        if s.strip()
    ]
    if not sentences:
        return "declarative_stop"
    last_sentence = sentences[-1].strip()
    if last_sentence.endswith("?"):
        return "question"
    if _SUMMARY_END.search(last_sentence):
        return "summary"
    if _RECOMMEND_END.search(last_sentence):
        return "recommendation"
    if _IMPLICATION_END.search(last_sentence):
        return "implication"
    if _PERSONAL_END.search(last_sentence):
        return "personal_reflection"
    if _QUALIFIED_END.search(last_sentence):
        return "qualified_conclusion"
    return "declarative_stop"


_CAUSAL_MOVE = re.compile(
    r"\b(?:because|since|which means|so that|therefore|this means|"
    r"drives?|leads? to|causes?|happens when|works by|fails when)\b",
    re.I,
)
_RULE_MOVE = re.compile(
    r"\b(?:always|never|the rule|what matters is|comes down to|"
    r"should|must|need to|the better approach)\b",
    re.I,
)
_EXAMPLE_MOVE = re.compile(
    r"^(?:For example|For instance|Consider|Take )\b|"
    r"\b(?:a concrete example|in practice)\b",
    re.I,
)
_CONTRAST_MOVE = re.compile(
    r"^(?:But|Yet|However|Instead|By contrast|The alternative)\b|"
    r"\b(?:rather than|not .{0,50} but)\b",
    re.I,
)
_PROBLEM_MOVE = re.compile(
    r"\b(?:the problem|the failure|breaks? down|goes wrong|risk is|"
    r"failure mode|cost is)\b",
    re.I,
)


def classify_reasoning_moves(text: str) -> list[str]:
    """Return semantic paragraph roles before repetition is collapsed."""
    paragraphs = _body_paragraphs(text)
    moves: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        is_first = index == 0
        is_last = index == len(paragraphs) - 1
        if is_first:
            opening = classify_opening(paragraph)
            if opening == "question":
                move = "question"
            elif opening in ("personal_observation", "anecdotal_entry"):
                move = "experience"
            elif opening in ("conditional_setup", "contextual_statement"):
                move = "setup"
            elif opening == "problem_statement" or _PROBLEM_MOVE.search(paragraph):
                move = "problem"
            elif opening == "recommendation":
                move = "recommendation"
            else:
                move = "thesis"
        elif is_last:
            closing = classify_closing(paragraph)
            if closing == "question":
                move = "question"
            elif closing == "recommendation" or _RULE_MOVE.search(paragraph):
                move = "recommendation"
            elif closing == "personal_reflection":
                move = "reflection"
            elif closing in ("implication", "qualified_conclusion"):
                move = "implication"
            else:
                move = "takeaway"
        elif _EXAMPLE_MOVE.search(paragraph):
            move = "example"
        elif _RULE_MOVE.search(paragraph):
            move = "recommendation"
        elif _CAUSAL_MOVE.search(paragraph):
            move = "mechanism"
        elif _CONTRAST_MOVE.search(paragraph):
            move = "contrast"
        elif _PROBLEM_MOVE.search(paragraph):
            move = "problem"
        else:
            move = "explanation"
        moves.append(move)
    return moves or ["thesis"]


def classify_reasoning_shape(text: str) -> str:
    """Describe rhetorical progression independent of paragraph count.

    Consecutive paragraphs doing the same job collapse to one move. That keeps
    a claim followed by two explanation blocks in the same class as a claim
    followed by three; otherwise paragraph-count variance would masquerade as
    reasoning diversity.
    """
    collapsed: list[str] = []
    for move in classify_reasoning_moves(text):
        if not collapsed or collapsed[-1] != move:
            collapsed.append(move)
    return ">".join(collapsed)


def compare(
    corpus_features: list[DocumentFeatures],
    generated_texts: list[str],
    *,
    context_corpus_features: list[DocumentFeatures] | None = None,
) -> DiversityResult:
    """Compare generated variation against the corpus's own variation.

    `corpus_features` should be the TRAINING documents only. Feature vectors
    for documents that produced no measurable text are dropped here rather
    than trusted: a zero vector is not a document that happens to have short
    sentences, and during dogfood a single one of them inflated the baseline
    coefficient of variation elevenfold, which would have reported a false
    convergence failure.

    `context_corpus_features`, when supplied, narrows the baseline to one
    register so that short-form pieces are not measured against long papers.
    It is only honoured once the slice is large enough to carry a coefficient
    of variation; see `MIN_CONTEXT_SLICE_DOCUMENTS` for why a small slice is
    worse than no slice at all.
    """
    result = DiversityResult(samples=len(generated_texts))

    context_usable = [
        f for f in (context_corpus_features or []) if f.words > 0 and f.sentences > 0
    ]
    use_context = len(context_usable) >= MIN_CONTEXT_SLICE_DOCUMENTS
    source_corpus = context_usable if use_context else corpus_features
    if context_corpus_features and not use_context:
        result.notes.append(
            f"context slice held only {len(context_usable)} usable document(s), "
            f"below the {MIN_CONTEXT_SLICE_DOCUMENTS} needed for a meaningful "
            "variation baseline; compared against the full corpus instead"
        )

    usable_corpus = [f for f in source_corpus if f.words > 0 and f.sentences > 0]
    dropped = len(source_corpus) - len(usable_corpus)
    if dropped:
        result.notes.append(
            f"ignored {dropped} corpus feature vector(s) with no measurable text"
        )

    if len(generated_texts) < MIN_SAMPLES or len(usable_corpus) < 2:
        result.verdict = NOT_EVALUATED
        result.notes.append(
            f"needs at least {MIN_SAMPLES} generated outputs and 2 corpus documents; "
            f"got {len(generated_texts)} and {len(usable_corpus)}"
        )
        return result

    generated_features = [
        f for f in (extract_features(text) for text in generated_texts)
        if f.words > 0 and f.sentences > 0
    ]
    if len(generated_features) < MIN_SAMPLES:
        result.verdict = NOT_EVALUATED
        result.notes.append(
            f"only {len(generated_features)} generated outputs held measurable text"
        )
        return result

    # Comparing a corpus of long documents against a handful of very short
    # outputs measures length, not voice. Say so rather than reporting a
    # convergence failure that the sample sizes guaranteed.
    corpus_median = statistics.median(f.words for f in usable_corpus)
    generated_median = statistics.median(f.words for f in generated_features)
    length_mismatch = generated_median * 4 < corpus_median
    if length_mismatch:
        result.notes.append(
            f"generated outputs are much shorter than the corpus "
            f"(median {generated_median:.0f} vs {corpus_median:.0f} words); "
            "structural comparisons below are weakened by that difference"
        )

    corpus_features = usable_corpus

    for name in _DIMENSIONS:
        corpus_variation = _coefficient_of_variation(
            [float(getattr(f, name, 0.0) or 0.0) for f in corpus_features]
        )
        generated_variation = _coefficient_of_variation(
            [float(getattr(f, name, 0.0) or 0.0) for f in generated_features]
        )
        if corpus_variation < MIN_CORPUS_VARIATION:
            # The corpus does not vary here either, so there is nothing to
            # converge away from.
            result.dimensions.append(DimensionComparison(
                name=name, corpus_variation=round(corpus_variation, 3),
                generated_variation=round(generated_variation, 3), ratio=1.0,
            ))
            continue
        ratio = generated_variation / corpus_variation
        result.dimensions.append(DimensionComparison(
            name=name,
            corpus_variation=round(corpus_variation, 3),
            generated_variation=round(generated_variation, 3),
            ratio=round(ratio, 3),
            converged=ratio < CONVERGENCE_RATIO,
        ))

    # Check paragraph count convergence across the batch
    corpus_p_cv = _coefficient_of_variation([float(f.paragraphs) for f in corpus_features])
    gen_p_cv = _coefficient_of_variation([float(f.paragraphs) for f in generated_features])
    paragraph_count_converged = corpus_p_cv >= 0.15 and gen_p_cv < 0.05

    result.repeated_openings = _repeats([_opening_key(t) for t in generated_texts])
    result.repeated_closings = _repeats([_closing_key(t) for t in generated_texts])

    # Compute opening & closing category distributions
    op_classes: dict[str, int] = {}
    cl_classes: dict[str, int] = {}
    signatures: dict[str, int] = {}
    for text in generated_texts:
        oc = classify_opening(text)
        cc = classify_closing(text)
        sig = classify_reasoning_shape(text)
        op_classes[oc] = op_classes.get(oc, 0) + 1
        cl_classes[cc] = cl_classes.get(cc, 0) + 1
        signatures[sig] = signatures.get(sig, 0) + 1

    result.opening_classes = op_classes
    result.closing_classes = cl_classes
    result.rhetorical_signatures = signatures
    top_sig_count = max(signatures.values(), default=0)
    result.top_rhetorical_signature_share = round(top_sig_count / max(1, len(generated_texts)), 4)

    converged = result.converged_dimensions
    total = len(generated_texts)
    worst_opening = max(result.repeated_openings.values(), default=0)
    worst_closing = max(result.repeated_closings.values(), default=0)
    opening_share = worst_opening / total
    closing_share = worst_closing / total
    rhetorical_converged = total >= 6 and result.top_rhetorical_signature_share > 0.65

    if converged:
        result.notes.append(
            "generated output varies much less than the corpus on: " + ", ".join(converged)
        )
    if paragraph_count_converged:
        result.notes.append(
            f"generated outputs collapsed to uniform paragraph count "
            f"(variation {gen_p_cv:.2f} vs corpus {corpus_p_cv:.2f})"
        )
    if opening_share > MAX_SHARED_OPENING_SHARE:
        result.notes.append(
            f"{worst_opening} of {total} outputs share the same two-word opening"
        )
    if closing_share > MAX_SHARED_CLOSING_SHARE:
        result.notes.append(
            f"{worst_closing} of {total} outputs end the same way"
        )
    if rhetorical_converged:
        top_sig = max(signatures.items(), key=lambda kv: kv[1])[0]
        result.notes.append(
            f"{top_sig_count} of {total} outputs share the exact same rhetorical "
            f"progression ({result.top_rhetorical_signature_share:.0%}): {top_sig}"
        )

    tic_failure = (
        opening_share > MAX_SHARED_OPENING_SHARE
        or closing_share > MAX_SHARED_CLOSING_SHARE
        or paragraph_count_converged
        or rhetorical_converged
    )

    if len(converged) >= FAIL_DIMENSIONS or (len(converged) >= WARNING_DIMENSIONS and tic_failure):
        result.verdict = FAIL
    elif len(converged) >= WARNING_DIMENSIONS or tic_failure:
        result.verdict = WARNING
    elif length_mismatch:
        # Nothing converged, but across a fourfold length gap the structural
        # dimensions were never in a position to say so. Reporting PASS here
        # would sell a result the sample never supported.
        result.verdict = NOT_EVALUATED
        result.notes.append(
            "no convergence detected, but the length difference above leaves the "
            "structural dimensions unable to support a pass; compare against "
            "corpus documents of a similar length to get a real verdict"
        )
    else:
        result.verdict = PASS
        result.notes.append(
            "generated output varies comparably to the corpus across every dimension checked"
        )
    return result
