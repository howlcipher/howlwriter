"""Voice Profile: a reusable representation of an author's writing style.

Two generations of the schema live here, deliberately in one dataclass.

The v0 fields (author_name through generated_from) are the original
hand-authored / `voice learn` shape. They are kept verbatim so profiles
written before Voice Corpus Profiling still load and still render into the
Humanizer prompt unchanged. `representative_examples` belongs to that
generation: matching a voice from adjectives alone loses the quirks a
hand-written profile was trying to pin down, so a small number of literal
passages earned their place there.

The v1 fields (version through validation) are what `voice build` produces
from a real corpus, and they take the opposite position on literal text: a
corpus-derived profile is a DISTRIBUTION, not a stencil. Nothing in the v1
half can hold a phrase lifted from the corpus. There is no favourite-opening
list, no characteristic-phrase bank, no reusable stem. A trait is an abstract
label plus the evidence behind it, and the corpus builder never populates
`representative_examples`, `preferred_phrases`, or `disliked_phrases` --
those stay reachable only through legacy profiles and explicit user
overrides. See docs/voice.md for why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from howlwriter.domain.serialization import DataClassSerializationMixin

GeneratedFrom = Literal["corpus_stats", "model_hook", "manual", "corpus_build"]

#: A personal voice is derived from one individual's writing and is private
#: user data. A shared style is generic editorial guidance that is safe to
#: distribute and must never claim to imitate a specific person. A personal
#: voice never becomes a shared style automatically.
ProfileType = Literal["personal_voice", "shared_style"]

#: Where a trait value came from. Deterministic traits are computed from
#: measurable text statistics; model traits come from abstract stylistic
#: analysis; user traits are explicit overrides and always win.
TraitSource = Literal["deterministic", "model", "user"]

#: The serialization version this build writes. Bumped to 2 when rate
#: distributions were added.
VOICE_PROFILE_VERSION = 2

#: The oldest version still recognised as corpus-built. A v1 profile predates
#: rate distributions but is otherwise a real corpus build, so it must keep
#: rendering through the corpus path rather than silently falling back to the
#: legacy renderer and losing its traits, contexts and spread.
MIN_CORPUS_BUILT_VERSION = 1

#: Context names the builder knows how to aggregate. `unknown` and `mixed`
#: are classification outcomes, not profile contexts -- documents landing
#: there contribute to the global profile only.
KNOWN_CONTEXTS = ("academic", "professional", "general", "social")


@dataclass
class VoiceExample(DataClassSerializationMixin):
    """A literal passage. Legacy only -- `voice build` never emits these."""

    text: str
    source_label: str = ""


@dataclass
class TraitValue(DataClassSerializationMixin):
    """One abstract stylistic tendency, with the evidence supporting it.

    `value` is a label ("high", "medium_low", "occasional"), never a phrase
    from the corpus. The evidence fields are what let `voice inspect` say how
    much a trait can be trusted, and what makes a low-evidence trait visibly
    low-evidence instead of silently equal to a well-supported one.
    """

    value: str
    confidence: float = 0.0
    supporting_documents: int = 0
    supporting_words: int = 0
    agreement: float = 0.0
    #: The next most common label, when the corpus does not agree with itself.
    #: `value` is a plurality winner, not a property of the author: a corpus
    #: split fourteen-to-fourteen still yields a single winning label. Keeping
    #: the runner-up is what lets the application layer say the tendency varies
    #: instead of stating the plurality as an absolute.
    secondary: str = ""
    secondary_agreement: float = 0.0
    #: True when `value` and `secondary` carry effectively the same weight, so
    #: `value` won on a tie-break rather than on evidence. The tie-break is
    #: lexicographic and deterministic, which keeps rebuilds stable but makes
    #: the winner arbitrary: reporting it as the author's tendency would state
    #: a coin-flip as a property. The application layer renders a tied trait as
    #: split without naming a winner.
    tied: bool = False
    source: TraitSource = "deterministic"
    note: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "TraitValue":
        if not isinstance(data, dict):
            return cls(value=str(data))
        return super().from_dict(data)


@dataclass
class RateDistribution(DataClassSerializationMixin):
    """How one behaviour is distributed ACROSS documents, not averaged over them.

    A corpus mean answers "how much of this is there per hundred words of
    corpus". For a behaviour that many documents simply do not use, that is the
    wrong question, and the answer describes no real document. Measured on the
    corpus this was built for, 42% of documents contain no first person at all;
    the mean rate is 1.01 while the median among documents that do use it is
    1.36. Writing to the mean produces prose that is neither impersonal like the
    42% nor personal like the rest.

    So presence and intensity are stored separately: how often the behaviour
    appears at all, and how strongly it appears in the documents that have it.
    The percentiles deliberately exclude absent documents -- including them
    would drag every percentile toward zero and re-create the flattening this
    exists to prevent.

    `corpus_mean` is retained for continuity with the scalar fields on
    `VoiceDistributions` and for diagnostics. It is never rendered on its own.
    """

    #: Share of measured documents where the behaviour appears at all (rate > 0).
    document_presence_rate: float = 0.0
    documents_measured: int = 0
    documents_present: int = 0
    #: Percentiles among documents where the behaviour is PRESENT. None when too
    #: few documents carry it to describe a spread without inventing precision.
    when_present_p10: float | None = None
    when_present_p50: float | None = None
    when_present_p90: float | None = None
    #: The plain corpus-wide mean, kept for continuity. Never rendered alone.
    corpus_mean: float = 0.0

    @property
    def is_universal(self) -> bool:
        """Every measured document uses it, so presence carries no information."""
        return self.documents_measured > 0 and self.documents_present == self.documents_measured

    @property
    def has_spread(self) -> bool:
        """Whether the when-present percentiles describe a real range."""
        low, high = self.when_present_p10, self.when_present_p90
        return low is not None and high is not None and high > low > 0


@dataclass
class VoiceContext(DataClassSerializationMixin):
    """Context-specific tendencies layered on top of the global profile.

    A context MODIFIES the global voice; it does not replace it. A context
    built from thin evidence must not be able to overpower a well-supported
    global tendency, which is what `confidence` and `document_count` are for
    at application time.
    """

    name: str = ""
    traits: dict[str, TraitValue] = field(default_factory=dict)
    distributions: dict[str, float] = field(default_factory=dict)
    #: Zero-inflated behaviours measured within this context only. Same shape as
    #: the global map; empty when the slice holds too few documents to support it.
    rate_distributions: dict[str, RateDistribution] = field(default_factory=dict)
    document_count: int = 0
    word_count: int = 0
    confidence: float = 0.0
    sufficiency: str = "unknown"

    @classmethod
    def from_dict(cls, data: dict) -> "VoiceContext":
        rebuilt = super().from_dict(data)
        rebuilt.traits = {
            key: TraitValue.from_dict(value) if isinstance(value, dict) else value
            for key, value in (rebuilt.traits or {}).items()
        }
        rebuilt.rate_distributions = {
            key: RateDistribution.from_dict(value) if isinstance(value, dict) else value
            for key, value in (rebuilt.rate_distributions or {}).items()
        }
        return rebuilt


@dataclass
class VoiceDistributions(DataClassSerializationMixin):
    """Deterministic aggregate statistics over the training documents.

    Every value here is a number computed from text, so none of it can carry
    a corpus phrase. Percentiles and standard deviations matter as much as
    the means: the spread is the part that keeps profile application from
    collapsing an author into one sentence length.
    """

    sentence_length_mean: float | None = None
    sentence_length_median: float | None = None
    sentence_length_stdev: float | None = None
    sentence_length_p10: float | None = None
    sentence_length_p90: float | None = None
    paragraph_sentences_mean: float | None = None
    paragraph_sentences_stdev: float | None = None
    paragraph_sentences_p10: float | None = None
    paragraph_sentences_p50: float | None = None
    paragraph_sentences_p90: float | None = None
    paragraph_words_mean: float | None = None
    paragraph_words_stdev: float | None = None
    paragraph_words_p10: float | None = None
    paragraph_words_p50: float | None = None
    paragraph_words_p90: float | None = None
    single_sentence_paragraph_rate: float | None = None
    short_sentence_rate: float | None = None
    long_sentence_rate: float | None = None
    lexical_diversity: float | None = None
    mean_word_length: float | None = None
    contraction_rate: float | None = None
    first_person_rate: float | None = None
    second_person_rate: float | None = None
    passive_rate: float | None = None
    question_rate: float | None = None
    exclamation_rate: float | None = None
    comma_rate: float | None = None
    semicolon_rate: float | None = None
    colon_rate: float | None = None
    em_dash_rate: float | None = None
    parenthetical_rate: float | None = None
    list_rate: float | None = None
    heading_rate: float | None = None
    transition_rate: float | None = None
    sentence_initial_conjunction_rate: float | None = None
    fragment_rate: float | None = None
    repetition_rate: float | None = None
    readability_grade: float | None = None


@dataclass
class VoiceOverrides(DataClassSerializationMixin):
    """Explicit user corrections, kept separate from generated traits.

    Generated traits are observations and can be wrong; these are the user's
    stated intent and survive every rebuild untouched. `traits` lets a user
    pin a specific trait value, which then reports `source: "user"`.
    """

    preserve: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    traits: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass
class CorpusSummary(DataClassSerializationMixin):
    """Counts describing the corpus a profile was built from.

    Counts only. No filenames, no paths, no excerpts -- this half of the
    profile is the part that could plausibly be shown in a UI or pasted into
    a bug report, so it must stay free of anything private. The private
    per-source metadata needed for incremental rebuild lives in sources.json
    inside the voice directory instead.
    """

    documents_discovered: int = 0
    unique_canonical_files: int = 0
    candidate_prose_files: int = 0
    included_documents: int = 0
    holdout_documents: int = 0
    excluded_documents: int = 0
    #: Neither used nor excluded: authorship was too uncertain to include
    #: and not clear enough to reject. Counted separately so that
    #: included + holdout + excluded + held reconciles with candidates.
    held_for_review_documents: int = 0
    exact_duplicates: int = 0
    cross_format_duplicates: int = 0
    revision_groups: int = 0
    extraction_failures: int = 0
    scanned_or_unreadable: int = 0
    training_words: int = 0
    holdout_words: int = 0
    words_by_context: dict[str, int] = field(default_factory=dict)
    documents_by_context: dict[str, int] = field(default_factory=dict)
    exclusion_reasons: dict[str, int] = field(default_factory=dict)
    quality_classifications: dict[str, int] = field(default_factory=dict)
    sufficiency: str = "unknown"
    sufficiency_warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationSummary(DataClassSerializationMixin):
    """How well the profile predicted writing it was never trained on.

    `alignment` maps a dimension name to a band (STRONG / MODERATE / WEAK /
    NOT_EVALUATED). Deliberately not a probability: this measures whether the
    profile describes unseen documents from the same corpus, which is not an
    authorship test and must never be reported as one.
    """

    alignment: dict[str, str] = field(default_factory=dict)
    overall_confidence: str = "UNKNOWN"
    holdout_documents: int = 0
    holdout_words: int = 0
    diversity_preservation: str = "NOT_EVALUATED"
    diversity_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class VoiceProfile(DataClassSerializationMixin):
    # --- v0: legacy hand-authored / `voice learn` shape, unchanged ---
    author_name: str
    formality: float | None = None
    sentence_length_mean: float | None = None
    sentence_length_stdev: float | None = None
    paragraph_length_mean: float | None = None
    contraction_rate: float | None = None
    rhetorical_question_rate: float | None = None
    fragment_rate: float | None = None
    preferred_phrases: list[str] = field(default_factory=list)
    disliked_phrases: list[str] = field(default_factory=list)
    representative_examples: list[VoiceExample] = field(default_factory=list)
    structural_notes: str = ""
    generated_from: GeneratedFrom = "manual"

    # --- v1: corpus-derived, contextual, evidence-backed ---
    version: int = 0
    profile_type: ProfileType = "personal_voice"
    profile_name: str = ""
    traits: dict[str, TraitValue] = field(default_factory=dict)
    contexts: dict[str, VoiceContext] = field(default_factory=dict)
    distributions: VoiceDistributions | None = None
    #: Cross-document presence and intensity for behaviours a corpus mean
    #: misdescribes. Keyed by the DocumentFeatures field name. Empty on a v1
    #: profile built before this existed, which is why every reader treats an
    #: absent entry as "not measured" rather than as "never occurs".
    rate_distributions: dict[str, RateDistribution] = field(default_factory=dict)
    overrides: VoiceOverrides | None = None
    corpus_summary: CorpusSummary | None = None
    validation: ValidationSummary | None = None
    built_at: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def is_corpus_built(self) -> bool:
        """True when this profile came from `voice build` rather than a hand
        written file or the legacy corpus-stats learner."""
        return self.version >= MIN_CORPUS_BUILT_VERSION and self.generated_from == "corpus_build"

    def effective_trait(self, name: str, context: str | None = None) -> TraitValue | None:
        """Resolve one trait under the layering rule the whole feature rests on:
        user override, then context, then global.

        A context trait modifies the global tendency rather than replacing the
        profile, and a user override beats both because a generated trait is
        an observation while an override is a stated intent.
        """
        override = (self.overrides.traits if self.overrides else {}).get(name)
        if override:
            return TraitValue(value=override, confidence=1.0, source="user")
        if context:
            ctx = self.contexts.get(context)
            if ctx is not None:
                found = ctx.traits.get(name)
                if found is not None:
                    return found
        return self.traits.get(name)

    @classmethod
    def from_dict(cls, data: dict) -> "VoiceProfile":
        """Rebuild nested v1 structures.

        DataClassSerializationMixin.from_dict does a flat field-name match and
        leaves nested values as plain dicts, which would hand the Humanizer
        dicts where it expects dataclasses. Unknown keys are still dropped and
        missing keys still take defaults, so a v0 profile loads unchanged.
        """
        rebuilt = super().from_dict(data)

        rebuilt.representative_examples = [
            VoiceExample.from_dict(item) if isinstance(item, dict) else item
            for item in (rebuilt.representative_examples or [])
        ]
        rebuilt.traits = {
            key: TraitValue.from_dict(value) if isinstance(value, dict) else value
            for key, value in (rebuilt.traits or {}).items()
        }
        rebuilt.contexts = {
            key: VoiceContext.from_dict(value) if isinstance(value, dict) else value
            for key, value in (rebuilt.contexts or {}).items()
        }
        rebuilt.rate_distributions = {
            key: RateDistribution.from_dict(value) if isinstance(value, dict) else value
            for key, value in (rebuilt.rate_distributions or {}).items()
        }
        rebuilt.distributions = _rebuild(VoiceDistributions, rebuilt.distributions)
        rebuilt.overrides = _rebuild(VoiceOverrides, rebuilt.overrides)
        rebuilt.corpus_summary = _rebuild(CorpusSummary, rebuilt.corpus_summary)
        rebuilt.validation = _rebuild(ValidationSummary, rebuilt.validation)
        return rebuilt


def _rebuild(cls: type, value: Any) -> Any:
    return cls.from_dict(value) if isinstance(value, dict) else value
