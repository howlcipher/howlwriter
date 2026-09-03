"""Stage 4: measurable style statistics, computed the same way every time.

These are the features that do not need a model. They are pure functions of
the cleaned text, use only the standard library, and are the backbone of the
profile: a provider outage can cost the higher-order traits, but it can never
cost these, and they are what makes a rebuild reproducible.

The spread matters as much as the average. Storing only a mean sentence
length would describe an author as "writes 18-word sentences", and applying
that back would flatten them into exactly that. Percentiles and standard
deviations are what let the profile say "varies widely, from short to long",
which is a tendency rather than a template.

Nothing here is a precision claim. Passive voice is approximated without a
POS tagger, fragments are approximated without a parser, and readability is a
syllable heuristic. Each approximation is marked as such below, and
`docs/voice.md` repeats the warning where users will see it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
import statistics
from typing import Any

from howlwriter.domain.document import Document
from howlwriter.domain.voice import VoiceDistributions

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_CONTRACTION = re.compile(r"\b\w+(?:n't|'re|'ll|'ve|'d|'m|'s)\b", re.IGNORECASE)
_FIRST_PERSON = re.compile(r"\b(?:i|me|my|mine|myself|we|us|our|ours|ourselves)\b", re.IGNORECASE)
_SECOND_PERSON = re.compile(r"\b(?:you|your|yours|yourself|yourselves)\b", re.IGNORECASE)
#: Matches a whole heading line, not just its first word. Stopping at the
#: first non-space character left the rest of the heading behind as a
#: sentence fragment, which pulled the mean sentence length down.
_HEADING_LINE = re.compile(r"^[ \t]*#{1,6}[ \t]+.*$", re.MULTILINE)
_LIST_LINE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.MULTILINE)

#: Approximate passive voice: a form of "to be" (or "get") followed within a
#: couple of words by a past participle. No POS tagger, so "is interested"
#: counts and "was quickly overcome by nostalgia" may not. Directionally
#: useful across a corpus, not reliable on one sentence.
_PASSIVE = re.compile(
    r"\b(?:am|is|are|was|were|be|been|being|get|gets|got|gotten)\b"
    r"(?:\s+\w+ly)?\s+\w+(?:ed|en|wn|rn|ne|de|lt|pt)\b",
    re.IGNORECASE,
)

_COMMON_VERBS = re.compile(
    r"\b(is|are|was|were|am|be|been|being|has|have|had|do|does|did|will|would|"
    r"shall|should|can|could|may|might|must)\b",
    re.IGNORECASE,
)
_VERB_SUFFIX = re.compile(r"\b\w+(s|ed|ing)\b", re.IGNORECASE)
_MIN_WORDS_FOR_CLAUSE = 4

#: Transition words a writer reaches for to join ideas. Counting them
#: separates a writer who signposts heavily from one who lets sentences
#: butt against each other.
_TRANSITIONS = (
    "however", "therefore", "moreover", "furthermore", "additionally",
    "consequently", "nevertheless", "nonetheless", "meanwhile", "similarly",
    "conversely", "accordingly", "subsequently", "thus", "hence", "besides",
    "instead", "otherwise", "likewise", "ultimately", "overall", "finally",
    "in addition", "in contrast", "on the other hand", "as a result",
    "for example", "for instance", "in other words", "that said",
    "in conclusion", "to summarize", "in summary", "first of all",
)
_TRANSITION_RE = re.compile(
    r"(?:^|(?<=[\s(,;—-]))(?:" + "|".join(re.escape(t) for t in _TRANSITIONS) + r")\b",
    re.IGNORECASE,
)
_INITIAL_CONJUNCTION = re.compile(
    r"^\s*(?:and|but|or|so|yet|because|although|while|though)\b", re.IGNORECASE
)

_VOWEL_GROUP = re.compile(r"[aeiouy]+", re.IGNORECASE)


@dataclass
class DocumentFeatures:
    """Deterministic style measurements for one cleaned document.

    Rates are per-sentence unless the name says otherwise; punctuation rates
    are per 100 words so they stay comparable between a 400-word post and a
    4000-word paper.
    """

    words: int = 0
    sentences: int = 0
    paragraphs: int = 0
    sentence_length_mean: float = 0.0
    sentence_length_median: float = 0.0
    sentence_length_stdev: float = 0.0
    sentence_length_p10: float = 0.0
    sentence_length_p90: float = 0.0
    sentence_length_min: int = 0
    sentence_length_max: int = 0
    paragraph_sentences_mean: float = 0.0
    paragraph_sentences_stdev: float = 0.0
    paragraph_sentences_p10: float = 0.0
    paragraph_sentences_p50: float = 0.0
    paragraph_sentences_p90: float = 0.0
    paragraph_words_mean: float = 0.0
    paragraph_words_stdev: float = 0.0
    paragraph_words_p10: float = 0.0
    paragraph_words_p50: float = 0.0
    paragraph_words_p90: float = 0.0
    single_sentence_paragraph_rate: float = 0.0
    short_sentence_rate: float = 0.0
    long_sentence_rate: float = 0.0
    lexical_diversity: float = 0.0
    mean_word_length: float = 0.0
    long_word_rate: float = 0.0
    contraction_rate: float = 0.0
    first_person_rate: float = 0.0
    second_person_rate: float = 0.0
    passive_rate: float = 0.0
    question_rate: float = 0.0
    exclamation_rate: float = 0.0
    comma_rate: float = 0.0
    semicolon_rate: float = 0.0
    colon_rate: float = 0.0
    em_dash_rate: float = 0.0
    parenthetical_rate: float = 0.0
    quote_rate: float = 0.0
    list_rate: float = 0.0
    heading_rate: float = 0.0
    transition_rate: float = 0.0
    sentence_initial_conjunction_rate: float = 0.0
    fragment_rate: float = 0.0
    repetition_rate: float = 0.0
    readability_grade: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def to_structural_vector(
        self,
        *,
        context: str = "",
        opening_class: str = "",
        closing_class: str = "",
        reasoning_shape: str = "",
    ) -> Any:
        from howlwriter.domain.voice import StructuralVector

        return StructuralVector(
            words=self.words,
            paragraphs=self.paragraphs,
            paragraph_words_mean=self.paragraph_words_mean,
            paragraph_words_stdev=self.paragraph_words_stdev,
            paragraph_sentences_mean=self.paragraph_sentences_mean,
            sentence_length_mean=self.sentence_length_mean,
            sentence_length_stdev=self.sentence_length_stdev,
            short_sentence_rate=self.short_sentence_rate,
            long_sentence_rate=self.long_sentence_rate,
            single_sentence_paragraph_rate=self.single_sentence_paragraph_rate,
            transition_rate=self.transition_rate,
            sentence_initial_conjunction_rate=self.sentence_initial_conjunction_rate,
            fragment_rate=self.fragment_rate,
            first_person_rate=self.first_person_rate,
            parenthetical_rate=self.parenthetical_rate,
            question_rate=self.question_rate,
            list_rate=self.list_rate,
            heading_rate=self.heading_rate,
            opening_class=opening_class,
            closing_class=closing_class,
            reasoning_shape=reasoning_shape,
            context=context,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentFeatures":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


#: The features that get aggregated into a profile and compared against
#: holdout documents. Counts (`words`, `sentences`, `paragraphs`) are excluded
#: because they describe document size, not style.
COMPARABLE_FEATURES = tuple(
    name for name in DocumentFeatures.__dataclass_fields__
    if name not in ("words", "sentences", "paragraphs")
)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


#: Public alias. Aggregation needs the same linear-interpolation
#: percentile the per-document extractor uses, so that a corpus-level
#: percentile and a document-level one are computed the same way rather
#: than by two implementations that could drift apart.
percentile = _percentile


def _syllables(word: str) -> int:
    """Approximate syllable count: vowel groups, with a silent-e correction."""
    lowered = word.lower().strip("'’-")
    if not lowered:
        return 0
    groups = len(_VOWEL_GROUP.findall(lowered))
    if lowered.endswith("e") and not lowered.endswith(("le", "ee", "ye")) and groups > 1:
        groups -= 1
    return max(1, groups)


def _is_fragment(text: str) -> bool:
    """Approximate: short and showing no sign of a finite verb.

    Same heuristic the legacy learner uses, kept deliberately consistent so
    fragment_rate means the same thing across both code paths.
    """
    words = text.split()
    if len(words) < _MIN_WORDS_FOR_CLAUSE:
        return True
    if _COMMON_VERBS.search(text) or _VERB_SUFFIX.search(text):
        return False
    return True


def _repetition_rate(sentences: list[str]) -> float:
    """How often a sentence reuses an opening it has already used.

    A writer who starts six sentences the same way has a real tic; the same
    measure applied to generated output is how `diversity.py` notices a
    profile has been turned into a template.
    """
    if len(sentences) < 3:
        return 0.0
    openings: dict[str, int] = {}
    for sentence in sentences:
        words = _WORD.findall(sentence)
        if len(words) < 2:
            continue
        key = " ".join(w.lower() for w in words[:2])
        openings[key] = openings.get(key, 0) + 1
    repeats = sum(count - 1 for count in openings.values() if count > 1)
    return repeats / len(sentences)


def extract_features(text: str, *, headings: int | None = None) -> DocumentFeatures:
    """Measure one cleaned document.

    Headings are excluded from sentence and lexical statistics (a heading is
    a label, not a sentence) but counted for `heading_rate`, so structural
    habits survive without distorting cadence.
    """
    features = DocumentFeatures()
    if not text or not text.strip():
        return features

    heading_count = headings if headings is not None else len(_HEADING_LINE.findall(text))
    list_count = len(_LIST_LINE.findall(text))

    prose = _HEADING_LINE.sub("", text)
    document = Document.parse(prose, title="")
    sentence_texts = [s.text for _, _, s in document.all_sentences()]
    if not sentence_texts:
        return features

    sentence_lengths = [len(_WORD.findall(s)) for s in sentence_texts]
    sentence_lengths = [n for n in sentence_lengths if n > 0]
    if not sentence_lengths:
        return features

    words = _WORD.findall(prose)
    word_count = len(words)
    sentence_count = len(sentence_lengths)
    per_100 = (100.0 / word_count) if word_count else 0.0

    paragraph_sentence_counts = [len(p.sentences) for p in document.paragraphs]
    paragraph_word_counts = [len(_WORD.findall(p.raw_text)) for p in document.paragraphs]

    features.words = word_count
    features.sentences = sentence_count
    features.paragraphs = len(document.paragraphs)

    features.sentence_length_mean = statistics.mean(sentence_lengths)
    features.sentence_length_median = statistics.median(sentence_lengths)
    features.sentence_length_stdev = (
        statistics.pstdev(sentence_lengths) if sentence_count > 1 else 0.0
    )
    features.sentence_length_p10 = _percentile(sentence_lengths, 0.10)
    features.sentence_length_p90 = _percentile(sentence_lengths, 0.90)
    features.sentence_length_min = min(sentence_lengths)
    features.sentence_length_max = max(sentence_lengths)

    features.paragraph_sentences_mean = statistics.mean(paragraph_sentence_counts)
    features.paragraph_sentences_stdev = (
        statistics.pstdev(paragraph_sentence_counts) if len(paragraph_sentence_counts) > 1 else 0.0
    )
    features.paragraph_words_mean = statistics.mean(paragraph_word_counts)
    features.paragraph_words_stdev = (
        statistics.pstdev(paragraph_word_counts) if len(paragraph_word_counts) > 1 else 0.0
    )

    features.short_sentence_rate = (
        sum(1 for n in sentence_lengths if n <= 9) / sentence_count if sentence_count else 0.0
    )
    features.long_sentence_rate = (
        sum(1 for n in sentence_lengths if n >= 28) / sentence_count if sentence_count else 0.0
    )

    if paragraph_sentence_counts:
        features.single_sentence_paragraph_rate = (
            sum(1 for c in paragraph_sentence_counts if c == 1) / len(paragraph_sentence_counts)
        )
        features.paragraph_sentences_p10 = _percentile(
            [float(c) for c in paragraph_sentence_counts], 0.10
        )
        features.paragraph_sentences_p50 = float(statistics.median(paragraph_sentence_counts))
        features.paragraph_sentences_p90 = _percentile(
            [float(c) for c in paragraph_sentence_counts], 0.90
        )
    if paragraph_word_counts:
        features.paragraph_words_p10 = _percentile(
            [float(c) for c in paragraph_word_counts], 0.10
        )
        features.paragraph_words_p50 = float(statistics.median(paragraph_word_counts))
        features.paragraph_words_p90 = _percentile(
            [float(c) for c in paragraph_word_counts], 0.90
        )

    lowered = [w.lower() for w in words]
    # Type/token ratio rises as documents get shorter, so it is measured over
    # a fixed window; otherwise a 400-word post always looks more varied than
    # a 4000-word paper by the same author.
    window = lowered[:1000]
    features.lexical_diversity = (len(set(window)) / len(window)) if window else 0.0
    features.mean_word_length = statistics.mean(len(w) for w in words) if words else 0.0
    features.long_word_rate = (
        sum(1 for w in words if len(w) >= 8) / word_count if word_count else 0.0
    )

    features.contraction_rate = len(_CONTRACTION.findall(prose)) * per_100
    features.first_person_rate = len(_FIRST_PERSON.findall(prose)) * per_100
    features.second_person_rate = len(_SECOND_PERSON.findall(prose)) * per_100
    features.passive_rate = len(_PASSIVE.findall(prose)) / sentence_count

    features.question_rate = sum(1 for s in sentence_texts if s.rstrip().endswith("?")) / sentence_count
    features.exclamation_rate = (
        sum(1 for s in sentence_texts if s.rstrip().endswith("!")) / sentence_count
    )

    features.comma_rate = prose.count(",") * per_100
    features.semicolon_rate = prose.count(";") * per_100
    features.colon_rate = prose.count(":") * per_100
    features.em_dash_rate = (prose.count("—") + len(re.findall(r"\s--\s", prose))) * per_100
    features.parenthetical_rate = prose.count("(") * per_100
    features.quote_rate = (prose.count('"') + prose.count("“")) * per_100

    features.list_rate = list_count / features.paragraphs if features.paragraphs else 0.0
    features.heading_rate = heading_count / features.paragraphs if features.paragraphs else 0.0

    features.transition_rate = len(_TRANSITION_RE.findall(prose)) / sentence_count
    features.sentence_initial_conjunction_rate = (
        sum(1 for s in sentence_texts if _INITIAL_CONJUNCTION.match(s)) / sentence_count
    )
    features.fragment_rate = sum(1 for s in sentence_texts if _is_fragment(s)) / sentence_count
    features.repetition_rate = _repetition_rate(sentence_texts)

    # Flesch-Kincaid grade level, on the approximate syllable count above.
    syllables = sum(_syllables(w) for w in words)
    features.readability_grade = round(
        0.39 * (word_count / sentence_count) + 11.8 * (syllables / word_count) - 15.59, 2
    ) if word_count else 0.0

    return _round_all(features)


def _round_all(features: DocumentFeatures) -> DocumentFeatures:
    for name, value in list(features.to_dict().items()):
        if isinstance(value, float):
            setattr(features, name, round(value, 4))
    return features


def to_distributions(features: DocumentFeatures) -> VoiceDistributions:
    """Project aggregated features onto the profile's distribution block."""
    return VoiceDistributions(
        sentence_length_mean=features.sentence_length_mean,
        sentence_length_median=features.sentence_length_median,
        sentence_length_stdev=features.sentence_length_stdev,
        sentence_length_p10=features.sentence_length_p10,
        sentence_length_p90=features.sentence_length_p90,
        paragraph_sentences_mean=features.paragraph_sentences_mean,
        paragraph_sentences_stdev=features.paragraph_sentences_stdev,
        paragraph_sentences_p10=features.paragraph_sentences_p10,
        paragraph_sentences_p50=features.paragraph_sentences_p50,
        paragraph_sentences_p90=features.paragraph_sentences_p90,
        paragraph_words_mean=features.paragraph_words_mean,
        paragraph_words_stdev=features.paragraph_words_stdev,
        paragraph_words_p10=features.paragraph_words_p10,
        paragraph_words_p50=features.paragraph_words_p50,
        paragraph_words_p90=features.paragraph_words_p90,
        single_sentence_paragraph_rate=features.single_sentence_paragraph_rate,
        short_sentence_rate=features.short_sentence_rate,
        long_sentence_rate=features.long_sentence_rate,
        lexical_diversity=features.lexical_diversity,
        mean_word_length=features.mean_word_length,
        contraction_rate=features.contraction_rate,
        first_person_rate=features.first_person_rate,
        second_person_rate=features.second_person_rate,
        passive_rate=features.passive_rate,
        question_rate=features.question_rate,
        exclamation_rate=features.exclamation_rate,
        comma_rate=features.comma_rate,
        semicolon_rate=features.semicolon_rate,
        colon_rate=features.colon_rate,
        em_dash_rate=features.em_dash_rate,
        parenthetical_rate=features.parenthetical_rate,
        list_rate=features.list_rate,
        heading_rate=features.heading_rate,
        transition_rate=features.transition_rate,
        sentence_initial_conjunction_rate=features.sentence_initial_conjunction_rate,
        fragment_rate=features.fragment_rate,
        repetition_rate=features.repetition_rate,
        readability_grade=features.readability_grade,
    )
