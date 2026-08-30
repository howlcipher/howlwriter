"""Voice Profile: a reusable representation of an author's writing style.

Deliberately not just a set of vague descriptors ("conversational",
"professional"). representative_examples is required, not optional, because
matching a voice from adjectives alone loses exactly the quirks (fragments,
uneven sentence lengths, personal phrasing) the spec asks HowlWriter to
preserve rather than smooth away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from howlwriter.domain.serialization import DataClassSerializationMixin

GeneratedFrom = Literal["corpus_stats", "model_hook", "manual"]


@dataclass
class VoiceExample(DataClassSerializationMixin):
    text: str
    source_label: str = ""


@dataclass
class VoiceProfile(DataClassSerializationMixin):
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
