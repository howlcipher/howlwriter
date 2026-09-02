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


_FIRST_PERSON_START = re.compile(r"^(I|In my|When I|We|In our|My)\b", re.I)
_TIME_ANECDOTAL_START = re.compile(
    r"^(Last year|A few months ago|Recently|Years ago|In \d{4}|Back when)\b", re.I
)
_CONTEXTUAL_START = re.compile(r"^(In\b|Across\b|When\b|Under\b|For\b|While\b|As\b|Within\b)", re.I)


def classify_opening(text: str) -> str:
    """Deterministically categorize the rhetorical opening move of a piece."""
    stripped = text.strip()
    if not stripped:
        return "direct_thesis"
    paragraphs = [p.strip() for p in stripped.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    first_line = paragraphs[0] if paragraphs else stripped
    if first_line.endswith("?") or "?" in first_line[:60]:
        return "question"
    if _FIRST_PERSON_START.search(first_line):
        return "personal_observation"
    if _TIME_ANECDOTAL_START.search(first_line):
        return "anecdotal_entry"
    if ":" in first_line[:40]:
        return "technical_assertion"
    if _CONTEXTUAL_START.search(first_line):
        return "contextual_statement"
    return "direct_thesis"


_RECOMMEND_END = re.compile(r"\b(should|must|ought to|recommend|prefer|start by|best approach)\b", re.I)
_IMPLICATION_END = re.compile(
    r"\b(which means|the result is|the consequence|real cost|leaves behind|trade-off)\b",
    re.I,
)
_PERSONAL_END = re.compile(r"\b(I think|in my view|for me|my take|I suspect)\b", re.I)
_SUMMARY_END = re.compile(r"\b(in short|ultimately|in summary|comes down to|boils down)\b", re.I)


def classify_closing(text: str) -> str:
    """Deterministically categorize the rhetorical ending move of a piece."""
    sentences = [s for s in _SENTENCE.split(text.strip()) if s.strip()]
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
    return "declarative_stop"


def classify_reasoning_shape(text: str) -> str:
    """Describe argumentative progression across paragraphs."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    causal = re.compile(r"\b(because|since|which means|so that|therefore|this means|drives|leads to)\b", re.I)
    rule = re.compile(r"\b(always|never|every|the rule|what matters is|comes down to)\b", re.I)
    hedge = re.compile(r"\b(probably|might|may|could|likely|seems)\b", re.I)

    shape: list[str] = []
    for paragraph in paragraphs:
        moves: list[str] = []
        if causal.search(paragraph):
            moves.append("mechanism")
        if rule.search(paragraph):
            moves.append("rule")
        if hedge.search(paragraph):
            moves.append("hedge")
        shape.append("+".join(moves) if moves else "assert")
    return ">".join(shape) if shape else "assert"


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
