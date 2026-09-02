"""What actually ran, recorded where it happened.

HowlWriter already records which provider humanized a document and how long it
took. That answers "was a model involved". It does not answer the question a
user actually has when they are about to put their name on something: what was
this system told, by whom, and what did it add that I did not.

The design constraint that makes this trustworthy is that nothing here is
reconstructed. A provenance record assembled after the fact by re-rendering the
prompts that "would have been" sent is a plausible fiction -- it drifts the
moment a prompt builder changes, and it drifts silently. Every prompt in this
record was captured at the dispatch boundary, as the exact string handed to the
provider, in the same call that produced the response.

The second constraint is that unavailable is not the same as absent. HowlPlane
returns `model` as an optional field and returns no token usage or request id at
all. A record that omitted the model would read as "no model"; one that guessed
it from the provider name would be a fabrication with an audit trail. So an
unreported model is recorded as PROVIDER_DID_NOT_REPORT, which is a fact, and
token usage stays None rather than becoming an estimate.

What hashes do and do not establish: they show that a recorded artifact is the
one this record describes and that it has not changed since. They say nothing
about who wrote it. No hash in this file is evidence of human authorship, and
none of them should ever be presented as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from howlwriter.domain.serialization import DataClassSerializationMixin

#: Bumped when the provenance format changes incompatibly.
PROVENANCE_SCHEMA_VERSION = "howlwriter.provenance/v1"

#: The model name was reported by the provider.
MODEL_REPORTED = "REPORTED"
#: The provider ran but did not say which model it used. Recorded as such
#: rather than inferred from the provider name, which would be a guess wearing
#: the costume of a record.
MODEL_NOT_REPORTED = "PROVIDER_DID_NOT_REPORT"

#: How much of a captured prompt each level keeps.
LEVEL_NONE = "none"
LEVEL_SUMMARY = "summary"
LEVEL_FULL = "full"

#: Where content in the artifact came from. Recorded at the level of a claim, a
#: paragraph, or an outline node -- never a token. Token-level attribution would
#: require knowing which spans of output derive from which spans of input, which
#: nothing in this system can establish.
ORIGIN_USER_VERBATIM = "USER_VERBATIM"
ORIGIN_USER_CLAIM = "USER_CLAIM"
ORIGIN_USER_IDEA = "USER_IDEA"
ORIGIN_USER_STRUCTURE = "USER_STRUCTURE"
ORIGIN_USER_EXAMPLE = "USER_EXAMPLE"
ORIGIN_USER_EXPERIENCE = "USER_EXPERIENCE"
ORIGIN_USER_VOICE_SEED = "USER_VOICE_SEED"
ORIGIN_CORPUS_VOICE = "CORPUS_VOICE"
ORIGIN_MODEL_EXPANSION = "MODEL_EXPANSION"
ORIGIN_MODEL_TRANSITION = "MODEL_TRANSITION"
ORIGIN_RESEARCH_SUPPORTED = "RESEARCH_SUPPORTED"
ORIGIN_CITATION_FORMATTING = "CITATION_FORMATTING"
ORIGIN_HUMANIZER_EDIT = "HUMANIZER_EDIT"
ORIGIN_REVIEWER_CORRECTION = "REVIEWER_CORRECTION"


def sha256_text(text: str) -> str:
    """Hash of exactly the bytes given. Establishes integrity, not authorship."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- redaction ----------------------------------------------------------
#
# A full provenance record contains the prompts, and prompts contain whatever
# was in scope when they were built. The patterns below are deliberately broad:
# a false positive costs a redacted string in a local file, a false negative
# writes a live credential to disk.

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"gho_[A-Za-z0-9]{20,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
     "[REDACTED_JWT]"),
    (re.compile(r"-----BEGIN[^-]{0,40}PRIVATE KEY-----.*?-----END[^-]{0,40}PRIVATE KEY-----",
                re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(
        r"""(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|authorization)\b"""
        r"""\s*[:=]\s*["']?([A-Za-z0-9_\-./+]{8,})["']?"""),
     r"\1=[REDACTED]"),
)

_HOME_PATTERN = re.compile(r"/(?:home|Users)/[^/\s\"']+")


def redact(text: str, *, mask_paths: bool = False) -> str:
    """Remove credentials from captured text.

    Path masking is optional because the two audiences differ. A record the
    author reads themselves is more useful with real paths in it; one they
    attach to a bug report or hand to a reviewer is not.
    """
    if not text:
        return text
    cleaned = text
    for pattern, replacement in _SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    if mask_paths:
        cleaned = _HOME_PATTERN.sub("/[HOME]", cleaned)
    return cleaned


# --- records ------------------------------------------------------------

@dataclass
class ModelCallRecord(DataClassSerializationMixin):
    """One model invocation, captured where it left the system."""

    sequence: int = 0
    role: str = ""
    provider: str = ""
    model: str | None = None
    #: REPORTED or PROVIDER_DID_NOT_REPORT. Never inferred from the provider.
    model_status: str = MODEL_NOT_REPORTED
    started_at: str = ""
    duration_seconds: float | None = None
    success: bool = True
    timed_out: bool = False
    error_message: str | None = None
    independence_status: str | None = None
    #: Provider this call was asked to avoid, when reviewer independence was
    #: requested. None means independence was not requested for this call.
    avoid_provider: str | None = None
    #: Set when this call retried an earlier one, naming that call's sequence.
    retry_of: int | None = None

    #: The exact strings sent. Populated at capture; emptied by the writer when
    #: the requested provenance level does not include full prompts.
    system_instruction: str = ""
    user_prompt: str = ""
    system_instruction_sha256: str = ""
    user_prompt_sha256: str = ""
    system_instruction_chars: int = 0
    user_prompt_chars: int = 0

    response_sha256: str = ""
    response_chars: int = 0

    #: None means the provider did not report usage, not that none was used.
    token_usage: dict[str, Any] | None = None
    request_id: str | None = None
    response_id: str | None = None

    def redacted(self, *, level: str, mask_paths: bool = False) -> "ModelCallRecord":
        """A copy carrying only what this provenance level should persist."""
        copy = ModelCallRecord(**self.to_dict())
        if level == LEVEL_FULL:
            copy.system_instruction = redact(self.system_instruction, mask_paths=mask_paths)
            copy.user_prompt = redact(self.user_prompt, mask_paths=mask_paths)
        else:
            # Hashes and lengths survive at every level, so a summary record can
            # still be checked against a full one taken from the same run.
            copy.system_instruction = ""
            copy.user_prompt = ""
        copy.error_message = redact(self.error_message or "", mask_paths=mask_paths) or None
        return copy


@dataclass
class StageRecord(DataClassSerializationMixin):
    """One pipeline stage, whether or not a model was involved."""

    name: str = ""
    sequence: int = 0
    started_at: str = ""
    duration_seconds: float | None = None
    status: str = "OK"
    model_backed: bool = False
    #: Sequence numbers of the model calls this stage made.
    call_sequences: list[int] = field(default_factory=list)
    input_sha256: str = ""
    output_sha256: str = ""
    changes: int = 0
    detail: str = ""


@dataclass
class OriginRecord(DataClassSerializationMixin):
    """Where one piece of the artifact came from.

    Granularity is a claim, a paragraph, or an outline node. Never a token.
    """

    origin: str = ORIGIN_MODEL_EXPANSION
    #: Outline node id when the content traces to one.
    node_id: str = ""
    #: Short excerpt for the human reader. Local records only.
    excerpt: str = ""
    detail: str = ""


@dataclass
class ContributionSummary(DataClassSerializationMixin):
    """Counts of what the user supplied and what survived.

    Counts only, and deliberately so. A percentage here would be read as an
    authorship measurement -- "83% human" -- and nothing in this system can
    establish that. Six claims supplied and six represented is a fact.
    """

    claims_supplied: int = 0
    claims_represented: int = 0
    required_points_supplied: int = 0
    required_points_represented: int = 0
    preserved_supplied: int = 0
    preserved_retained: int = 0
    examples_supplied: int = 0
    examples_represented: int = 0
    voice_seeds_supplied: int = 0
    user_words_supplied: int = 0
    artifact_words: int = 0
    model_added_claims: int = 0
    research_grounded_additions: int = 0
    unsupported_additions: int = 0
    gaps_reported: int = 0


@dataclass
class GenerationProvenance(DataClassSerializationMixin):
    """The complete record of one generation run."""

    schema: str = PROVENANCE_SCHEMA_VERSION
    run_id: str = ""
    workflow: str = ""
    writing_mode: str | None = None
    generation_freedom: str | None = None
    started_at: str = field(default_factory=_utc_now)
    completed_at: str = ""
    provenance_level: str = LEVEL_SUMMARY

    howlwriter_version: str | None = None
    git_revision: str | None = None

    outline_present: bool = False
    outline_sha256: str = ""
    outline_summary: dict[str, Any] = field(default_factory=dict)
    voice_profile: str | None = None
    voice_block_sha256: str = ""

    input_sha256: str = ""
    draft_sha256: str = ""
    humanized_sha256: str = ""
    reviewed_sha256: str = ""
    artifact_sha256: str = ""

    calls: list[ModelCallRecord] = field(default_factory=list)
    stages: list[StageRecord] = field(default_factory=list)
    origins: list[OriginRecord] = field(default_factory=list)
    contribution: ContributionSummary = field(default_factory=ContributionSummary)
    coverage: dict[str, Any] = field(default_factory=dict)
    research: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    added_claims: list[dict[str, Any]] = field(default_factory=list)
    structural_realization: dict[str, Any] | None = None
    reviewer_independence_by_stage: dict[str, str] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: True only when every stage that ran was captured. A run that failed part
    #: way through says so rather than presenting a partial record as complete.
    complete: bool = False

    # --- views -----------------------------------------------------------

    def providers_used(self) -> list[str]:
        return sorted({c.provider for c in self.calls if c.provider})

    def models_used(self) -> list[str]:
        return sorted({c.model for c in self.calls if c.model})

    def reviewer_independence(self) -> str | None:
        for call in self.calls:
            if call.role in ("final_reviewer", "voice_reviewer") and call.independence_status:
                return call.independence_status
        return None

    def unknown_model_calls(self) -> list[ModelCallRecord]:
        return [c for c in self.calls if c.model_status == MODEL_NOT_REPORTED]

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationProvenance":
        rebuilt = super().from_dict(data)
        rebuilt.calls = [
            ModelCallRecord.from_dict(c) if isinstance(c, dict) else c
            for c in (rebuilt.calls or [])
        ]
        rebuilt.stages = [
            StageRecord.from_dict(s) if isinstance(s, dict) else s
            for s in (rebuilt.stages or [])
        ]
        rebuilt.origins = [
            OriginRecord.from_dict(o) if isinstance(o, dict) else o
            for o in (rebuilt.origins or [])
        ]
        if isinstance(rebuilt.contribution, dict):
            rebuilt.contribution = ContributionSummary.from_dict(rebuilt.contribution)
        return rebuilt
