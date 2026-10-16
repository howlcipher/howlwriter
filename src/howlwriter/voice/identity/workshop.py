"""Voice Workshop: short writing samples that fill a profile's evidence gaps.

Historical documents are the primary evidence for a personal profile. Some
contexts have little of it -- professional writing kept in native cloud
documents, or no informal writing at all -- and the Workshop lets a person
add evidence by answering short prompts. It does not replace documents.

Guarantees:

* **Local.** Prompts come from a template bank in this module. No model is
  called to generate or judge anything.
* **The prompt is never training material.** A sample stores the prompt id
  and text as metadata; only the person's answer is ever measured.
* **The answer is kept verbatim.** No spelling, grammar or structure
  correction. An optional *preferred revision* is stored separately and is
  never used as evidence of how the person writes.
* **Explicit approval.** A sample is saved as `pending` and reaches a profile
  only after the person approves it. Samples can be excluded, removed
  (text deleted), or reclassified to another context.
* **No skew from repetition.** A prompt is not offered again once answered;
  only one approved answer per prompt counts; exact and near-duplicate
  answers are flagged and never counted.
* **Training and calibration never share a sample.** Each approved sample is
  assigned once, by its own hash, to `train` or `calibration`, and keeps
  that side forever.
* **Bounded influence.** Approved samples join a profile as bundles of about
  `BUNDLE_WORDS` words at reduced weight, capped at `MAX_WORKSHOP_SHARE` of
  the profile's training words when real documents exist. A profile with no
  documents can be built from samples alone only when the normal sufficiency
  bar is met, and it is labelled workshop-only.

Storage is private: ``<identity>/workshop/samples.json`` (0600) and
regenerated bundle files under ``<identity>/workshop/bundles/`` (0600).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

from howlwriter.voice.corpus.dedup import content_hash, hamming, shingles, simhash
from howlwriter.voice.corpus.split import split_score
from howlwriter.voice.identity import privacy
from howlwriter.voice.identity.store import IdentityStore, utc_now

WORKSHOP_DIR = "workshop"
SAMPLES_FILE = "samples.json"
BUNDLE_DIR = "bundles"

CONTEXTS = ("academic", "professional", "technical", "casual")
#: Which profile context each workshop context feeds. Casual answers are kept
#: and shown in coverage but never train the formal profiles.
PROFILE_CONTEXT = {
    "academic": "academic",
    "professional": "professional",
    "technical": "professional",
}

BUNDLE_WORDS = 300
WORKSHOP_WEIGHT = 0.5
MAX_WORKSHOP_SHARE = 0.25
#: Share of approved samples held for calibration (by stable hash).
CALIBRATION_FRACTION = 0.25
NEAR_DUPLICATE_BITS = 6
MAX_SAMPLE_CHARS = 20_000

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_EXCLUDED = "excluded"
STATUS_REMOVED = "removed"

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    context: str
    kind: str  # short | paragraph
    template: str  # may contain {subject}
    default_subject: str = ""


def _t(pid: str, context: str, kind: str, template: str, subject: str = "") -> PromptTemplate:
    return PromptTemplate(pid, context, kind, template, subject)


#: Varied on purpose: explaining, arguing, reporting, requesting, reflecting.
#: Short prompts ask for 1-3 sentences; paragraph prompts for a paragraph.
PROMPTS: tuple[PromptTemplate, ...] = (
    _t(
        "aca-s1",
        "academic",
        "short",
        "In one to three sentences, state the main argument you would make about {subject}.",
        "a topic you studied recently",
    ),
    _t(
        "aca-s2",
        "academic",
        "short",
        "Summarize a limitation of the evidence on {subject} in two or three sentences.",
        "a study or report you read",
    ),
    _t(
        "aca-s3",
        "academic",
        "short",
        "Explain in a few sentences why {subject} matters to your field.",
        "a concept from your coursework",
    ),
    _t(
        "aca-s4",
        "academic",
        "short",
        "Write a short reply to a classmate who claimed {subject} is settled. Agree or push back.",
        "a debated question in your field",
    ),
    _t(
        "aca-s5",
        "academic",
        "short",
        "Describe, in two or three sentences, what a lab or exercise on {subject} showed you.",
        "a hands-on exercise",
    ),
    _t(
        "aca-p1",
        "academic",
        "paragraph",
        "Write a paragraph analysing {subject}: make a claim, support it, and qualify it.",
        "a topic you know well",
    ),
    _t(
        "aca-p2",
        "academic",
        "paragraph",
        "Write a paragraph comparing two approaches to {subject} and say which you prefer and why.",
        "a problem in your field",
    ),
    _t(
        "pro-s1",
        "professional",
        "short",
        "Write a two- or three-sentence status update to your manager about {subject}.",
        "a task you are working on",
    ),
    _t(
        "pro-s2",
        "professional",
        "short",
        "In a few sentences, ask a colleague for help with {subject}, saying exactly what you need.",
        "a blocker at work",
    ),
    _t(
        "pro-s3",
        "professional",
        "short",
        "Explain a decision you made about {subject} to a stakeholder in two or three sentences.",
        "a recent work decision",
    ),
    _t(
        "pro-s4",
        "professional",
        "short",
        "Write a short message declining or postponing a request about {subject}, with a reason.",
        "a request you cannot take on",
    ),
    _t(
        "pro-s5",
        "professional",
        "short",
        "In two or three sentences, describe what went wrong with {subject} and what you will change.",
        "an incident or mistake",
    ),
    _t(
        "pro-p1",
        "professional",
        "paragraph",
        "Write a paragraph for a team update explaining {subject}, the impact, and the next step.",
        "a project milestone",
    ),
    _t(
        "pro-p2",
        "professional",
        "paragraph",
        "Write a short post sharing one practical lesson about {subject}. Avoid slogans.",
        "something you learned at work",
    ),
    _t(
        "tec-s1",
        "technical",
        "short",
        "In two or three sentences, explain how {subject} works to a new teammate.",
        "a tool you use often",
    ),
    _t(
        "tec-s2",
        "technical",
        "short",
        "Describe the first three things you would check when {subject} fails.",
        "a service or system you maintain",
    ),
    _t(
        "tec-s3",
        "technical",
        "short",
        "Explain a trade-off involved in {subject} in a few sentences.",
        "a design choice",
    ),
    _t(
        "tec-s4",
        "technical",
        "short",
        "Write a short code-review comment about {subject}: what to change and why.",
        "a change you reviewed",
    ),
    _t(
        "tec-p1",
        "technical",
        "paragraph",
        "Write a paragraph of documentation for {subject}: what it does, when to use it, one caveat.",
        "a script, tool or procedure",
    ),
    _t(
        "tec-p2",
        "technical",
        "paragraph",
        "Write a short incident write-up about {subject}: what happened, the cause, the fix.",
        "a problem you debugged",
    ),
    _t(
        "cas-s1",
        "casual",
        "short",
        "Tell a friend, in a couple of sentences, what you thought of {subject}.",
        "something you watched or read",
    ),
    _t(
        "cas-s2",
        "casual",
        "short",
        "Text a friend about plans involving {subject}.",
        "an upcoming weekend",
    ),
    _t(
        "cas-s3",
        "casual",
        "short",
        "In a few sentences, describe {subject} to someone who has never tried it.",
        "a hobby",
    ),
    _t(
        "cas-p1",
        "casual",
        "paragraph",
        "Write a relaxed paragraph about {subject} and why you like it.",
        "something you enjoy",
    ),
)
_BY_ID = {p.prompt_id: p for p in PROMPTS}


@dataclass
class Prompt:
    prompt_id: str
    context: str
    kind: str
    subject: str
    text: str
    reason: str = ""
    follow_up_of: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sample:
    sample_id: str
    prompt_id: str
    prompt_text: str
    prompt_kind: str
    context: str
    subject: str
    text: str
    words: int
    created_at: str
    status: str = STATUS_PENDING
    self_written: bool = False
    source: str = "voice_workshop"
    authorship: str = ""
    side: str = ""  # train | calibration, fixed at first approval
    content_hash: str = ""
    simhash: str = ""
    duplicate_of: str = ""
    same_prompt_as: str = ""
    classified_context: str = ""
    preferred_revision: str = ""
    approved_at: str = ""
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Sample":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})

    @property
    def eligible(self) -> bool:
        """Approved, self-written, with text. Whether it COUNTS also depends
        on the other samples (see `counting_ids`)."""
        return self.status == STATUS_APPROVED and self.self_written and bool(self.text.strip())


def counting_ids(samples) -> set[str]:
    """Which eligible samples count, decided against the current set.

    Earliest approval wins: a later answer to the same prompt and subject, or
    a later exact or near-duplicate answer, does not count. Recomputed every
    time, so excluding or removing an earlier sample lets a later one count.
    """
    accepted: list = []
    keys: set[tuple[str, str]] = set()
    for sample in sorted(
        (s for s in samples if s.eligible), key=lambda s: (s.approved_at, s.sample_id)
    ):
        key = (sample.prompt_id, sample.subject.lower())
        if key in keys:
            continue
        value = int(sample.simhash or "0", 16)
        if any(
            other.content_hash == sample.content_hash
            or (
                sample.words >= 8
                and other.words >= 8
                and hamming(value, int(other.simhash or "0", 16)) <= NEAR_DUPLICATE_BITS
            )
            for other in accepted
        ):
            continue
        accepted.append(sample)
        keys.add(key)
    return {s.sample_id for s in accepted}


class Workshop:
    """One identity's Voice Workshop ledger."""

    def __init__(self, identity: str, *, store_root: Path | None = None) -> None:
        self.store = IdentityStore(identity, root=store_root)
        self.directory = self.store.directory / WORKSHOP_DIR

    # --- persistence --------------------------------------------------

    def _path(self) -> Path:
        return self.directory / SAMPLES_FILE

    def load(self) -> dict[str, Any]:
        path = self._path()
        if not path.is_file():
            return {"samples": {}, "shown_prompts": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("samples", {})
        data.setdefault("shown_prompts", [])
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.store.ensure()
        if not self.store.exists():
            # No scan needed to start: the identity gets its default private
            # configuration the first time a workshop answer is saved.
            self.store.save_config(self.store.load_config())
        privacy.ensure_private_dir(self.directory)
        privacy.write_private_json(self._path(), data)

    def samples(self) -> dict[str, Sample]:
        return {k: Sample.from_dict(v) for k, v in self.load()["samples"].items()}

    def _put(self, data: dict, sample: Sample) -> None:
        data["samples"][sample.sample_id] = sample.to_dict()

    # --- prompts -------------------------------------------------------

    def next_prompt(
        self,
        *,
        context: str | None = None,
        subject: str | None = None,
        kind: str | None = None,
        follow_up_of: str | None = None,
    ) -> Prompt:
        """A prompt not answered before, aimed at the largest evidence gap."""
        if context is not None and context not in CONTEXTS:
            raise ValueError(
                f"unknown workshop context {context!r}; expected one of {', '.join(CONTEXTS)}"
            )
        data = self.load()
        samples = self.samples()
        answered = {
            (s.prompt_id, s.subject.lower()) for s in samples.values() if s.status != STATUS_REMOVED
        }
        reason = "you chose the context" if context else ""
        base_subject = subject
        if follow_up_of:
            previous = samples.get(follow_up_of)
            if previous is None:
                raise ValueError(f"no workshop sample {follow_up_of!r}")
            base_subject = base_subject or previous.subject
            if context is None:
                gaps = [c for c in self.gap_order() if c != previous.context]
                context = gaps[0] if gaps else previous.context
                reason = (
                    "follow-up on the same subject, in the context with the largest evidence "
                    f"gap ({context})"
                )
        if context is None:
            context = self.gap_order()[0]
            reason = f"{context} has the largest evidence gap"
        if kind is None:
            counting = counting_ids(samples.values())
            short = sum(
                1
                for s in samples.values()
                if s.sample_id in counting and s.context == context and s.prompt_kind == "short"
            )
            long_ = sum(
                1
                for s in samples.values()
                if s.sample_id in counting and s.context == context and s.prompt_kind == "paragraph"
            )
            kind = "paragraph" if short >= 3 and long_ * 3 < short else "short"
        shown = data.get("shown_prompts", [])

        def unanswered(kinds: tuple[str, ...]) -> list[PromptTemplate]:
            return [
                p
                for p in PROMPTS
                if p.context == context
                and p.kind in kinds
                and (p.prompt_id, (base_subject or p.default_subject).lower()) not in answered
            ]

        # The requested kind first; when it is used up, the other kind.
        fresh = unanswered((kind,)) or unanswered(("short", "paragraph"))
        if not fresh:
            raise ValueError(
                f"every {context} prompt has been answered"
                + ("" if base_subject else "; choose a new subject to get new prompts")
            )
        # Least recently shown first, then bank order: deterministic, no RNG.
        order = {pid: i for i, pid in enumerate(shown)}
        chosen = min(fresh, key=lambda p: (order.get(p.prompt_id, -1), PROMPTS.index(p)))
        subject_text = (base_subject or chosen.default_subject).strip()[:120]
        data["shown_prompts"] = [pid for pid in shown if pid != chosen.prompt_id] + [
            chosen.prompt_id
        ]
        self.save(data)
        return Prompt(
            prompt_id=chosen.prompt_id,
            context=context,
            kind=chosen.kind,
            subject=subject_text,
            text=chosen.template.format(subject=subject_text),
            reason=reason,
            follow_up_of=follow_up_of or "",
        )

    # --- samples -------------------------------------------------------

    def add(
        self,
        *,
        prompt_id: str,
        subject: str,
        text: str,
        self_written: bool,
        approve: bool = False,
    ) -> Sample:
        """Save an answer verbatim. Approval is separate and explicit."""
        template = _BY_ID.get(prompt_id)
        if template is None:
            raise ValueError(f"unknown prompt {prompt_id!r}")
        if not text or not text.strip():
            raise ValueError("an empty answer cannot be saved")
        if len(text) > MAX_SAMPLE_CHARS:
            raise ValueError(f"answers are limited to {MAX_SAMPLE_CHARS} characters")
        data = self.load()
        existing = self.samples()
        subject = (subject or template.default_subject).strip()[:120]
        created = utc_now()
        # Unique per save. A content-derived id collided when the same answer
        # was saved twice within a second and silently replaced the first.
        sample_id = uuid.uuid4().hex[:12]
        while sample_id in data["samples"]:
            sample_id = uuid.uuid4().hex[:12]
        sample = Sample(
            sample_id=sample_id,
            prompt_id=prompt_id,
            prompt_text=template.template.format(subject=subject),
            prompt_kind=template.kind,
            context=template.context,
            subject=subject,
            text=text,
            words=len(_WORD.findall(text)),
            created_at=created,
            self_written=bool(self_written),
            authorship="CONFIRMED_HUMAN_AUTHORED" if self_written else "UNKNOWN_AUTHORSHIP",
            content_hash=content_hash(text),
            simhash=format(simhash(shingles(text)), "016x"),
            classified_context=_classify(text),
        )
        sample.history.append({"at": created, "event": "saved"})
        _mark_duplicates(sample, existing.values())
        self._put(data, sample)
        self.save(data)
        if approve:
            sample = self.approve(sample.sample_id)
        return sample

    def _update(self, sample_id: str, change) -> Sample:
        data = self.load()
        raw = data["samples"].get(sample_id)
        if raw is None:
            raise ValueError(f"no workshop sample {sample_id!r}")
        sample = Sample.from_dict(raw)
        change(sample)
        self._put(data, sample)
        self.save(data)
        return sample

    def approve(self, sample_id: str) -> Sample:
        def change(sample: Sample) -> None:
            if sample.status == STATUS_REMOVED:
                raise ValueError("a removed sample cannot be approved")
            if not sample.self_written:
                raise ValueError(
                    "only answers you wrote yourself, without AI help, can be approved for a profile"
                )
            sample.status = STATUS_APPROVED
            if not sample.approved_at:
                # Microsecond precision: "earliest approval wins" must not be
                # decided by a tie inside one second.
                sample.approved_at = datetime.now(timezone.utc).isoformat()
            if not sample.side:
                score = split_score(f"workshop:{sample.content_hash}")
                sample.side = "calibration" if score >= 1.0 - CALIBRATION_FRACTION else "train"
            sample.history.append(
                {"at": sample.approved_at, "event": "approved", "side": sample.side}
            )

        return self._update(sample_id, change)

    def exclude(self, sample_id: str) -> Sample:
        def change(sample: Sample) -> None:
            sample.status = STATUS_EXCLUDED
            sample.history.append({"at": utc_now(), "event": "excluded"})

        return self._update(sample_id, change)

    def remove(self, sample_id: str) -> Sample:
        """Delete the answer and any revision; keep a text-free tombstone."""

        def change(sample: Sample) -> None:
            sample.status = STATUS_REMOVED
            sample.text = ""
            sample.preferred_revision = ""
            sample.history.append({"at": utc_now(), "event": "removed"})

        return self._update(sample_id, change)

    def reclassify(self, sample_id: str, context: str) -> Sample:
        if context not in CONTEXTS:
            raise ValueError(f"unknown workshop context {context!r}")

        def change(sample: Sample) -> None:
            sample.history.append(
                {"at": utc_now(), "event": "reclassified", "from": sample.context, "to": context}
            )
            sample.context = context

        return self._update(sample_id, change)

    def set_preferred_revision(self, sample_id: str, text: str) -> Sample:
        """How the person would like it to read. Never used as evidence."""

        def change(sample: Sample) -> None:
            if sample.status == STATUS_REMOVED:
                raise ValueError("a removed sample has no text to revise")
            sample.preferred_revision = text[:MAX_SAMPLE_CHARS]
            sample.history.append({"at": utc_now(), "event": "preferred_revision"})

        return self._update(sample_id, change)

    # --- evidence -------------------------------------------------------

    def counted(self, profile_context: str, side: str | None = None) -> list[Sample]:
        samples = list(self.samples().values())
        counting = counting_ids(samples)
        out = [
            s
            for s in samples
            if s.sample_id in counting
            and PROFILE_CONTEXT.get(s.context) == profile_context
            and (side is None or s.side == side)
        ]
        return sorted(out, key=lambda s: s.sample_id)

    def gap_order(self) -> list[str]:
        """Workshop contexts ordered by how little evidence their profile has."""
        coverage = self.coverage()

        def deficit(context: str) -> tuple:
            profile = PROFILE_CONTEXT.get(context)
            if profile is None:
                # Casual has no target profile; offered last, unless asked for.
                return (2, 0)
            entry = coverage["profiles"].get(profile, {})
            words = entry.get("document_words", 0) + entry.get("workshop_words", 0)
            return (0 if entry.get("documents", 0) < 3 else 1, words)

        return sorted(CONTEXTS, key=deficit)

    def coverage(self) -> dict[str, Any]:
        """Evidence per target profile and per workshop context. No percentages."""
        from howlwriter.voice.corpus.aggregate import MIN_DOCUMENTS, MIN_WORDS
        from howlwriter.voice.identity.profiles import select_sources

        store = self.store
        samples = list(self.samples().values())
        counting = counting_ids(samples)
        result: dict[str, Any] = {"profiles": {}, "contexts": {}, "notes": []}
        documents: dict[str, tuple[int, int]] = {}
        if store.exists():
            config = store.load_config()
            entries = store.load_inventory().get("entries", {})
            decisions = store.load_decisions()
            for spec in config.profiles.values():
                choices, pending = select_sources(config, entries, decisions, spec)
                documents[spec.context] = (
                    len(choices),
                    sum(int(c.entry.get("words") or 0) for c in choices),
                )
        for profile in ("academic", "professional"):
            counted = [
                s
                for s in samples
                if s.sample_id in counting and PROFILE_CONTEXT.get(s.context) == profile
            ]
            doc_count, doc_words = documents.get(profile, (0, 0))
            workshop_words = sum(s.words for s in counted)
            gaps = []
            if doc_count == 0:
                gaps.append("no attested documents in this context")
            if not any(s.prompt_kind == "paragraph" for s in counted):
                gaps.append("no paragraph-length workshop answers")
            kinds = {s.context for s in counted}
            if profile == "professional" and "technical" not in kinds:
                gaps.append("no technical-explanation answers")
            total_words = (
                doc_words
                + min(
                    workshop_words, int(doc_words * MAX_WORKSHOP_SHARE / (1 - MAX_WORKSHOP_SHARE))
                )
                if doc_count
                else workshop_words
            )
            if doc_count + len(counted) == 0:
                sufficiency = "none"
            elif doc_count >= MIN_DOCUMENTS and total_words >= MIN_WORDS:
                sufficiency = "sufficient for a profile"
            elif doc_count == 0 and workshop_words >= MIN_WORDS and len(counted) >= 10:
                sufficiency = "sufficient for a provisional workshop-only profile"
            else:
                sufficiency = "insufficient"
            result["profiles"][profile] = {
                "documents": doc_count,
                "document_words": doc_words,
                "workshop_samples": len(counted),
                "workshop_train": sum(1 for s in counted if s.side == "train"),
                "workshop_calibration": sum(1 for s in counted if s.side == "calibration"),
                "workshop_words": workshop_words,
                "sufficiency": sufficiency,
                "gaps": gaps,
            }
        for context in CONTEXTS:
            ctx = [s for s in samples if s.context == context and s.status != STATUS_REMOVED]
            result["contexts"][context] = {
                "approved": sum(1 for s in ctx if s.sample_id in counting),
                "pending": sum(1 for s in ctx if s.status == STATUS_PENDING),
                "excluded_or_not_counted": sum(
                    1
                    for s in ctx
                    if s.status == STATUS_EXCLUDED or (s.eligible and s.sample_id not in counting)
                ),
                "words": sum(s.words for s in ctx if s.sample_id in counting),
            }
        result["notes"].append(
            "Workshop answers add sentence- and word-level evidence. Historical documents remain "
            f"the primary evidence: workshop text is capped at {MAX_WORKSHOP_SHARE:.0%} of a "
            "profile's training words when documents exist, and casual answers never train the "
            "academic or professional profiles."
        )
        return result

    def bundles(self, profile_context: str, *, document_words: int) -> list[tuple[Path, str, int]]:
        """Write bundle files for a profile; return (path, side, words).

        Train bundles are capped so workshop text stays below
        `MAX_WORKSHOP_SHARE` of training words when documents exist. Bundle
        files are private and regenerated on every build.
        """
        directory = self.directory / BUNDLE_DIR
        privacy.ensure_private_dir(directory)
        for old in directory.glob(f"{profile_context}-*.txt"):
            old.unlink()
        out: list[tuple[Path, str, int]] = []
        cap = (
            int(document_words * MAX_WORKSHOP_SHARE / (1 - MAX_WORKSHOP_SHARE))
            if document_words
            else None
        )
        for side in ("train", "calibration"):
            budget = cap if side == "train" else None
            chunks: list[list[Sample]] = [[]]
            used = 0
            for sample in self.counted(profile_context, side):
                if budget is not None and used + sample.words > budget:
                    break
                chunks[-1].append(sample)
                used += sample.words
                if sum(s.words for s in chunks[-1]) >= BUNDLE_WORDS:
                    chunks.append([])
            chunks = [c for c in chunks if c]
            if len(chunks) > 1 and sum(s.words for s in chunks[-1]) < BUNDLE_WORDS // 2:
                chunks[-2].extend(chunks.pop())
            for index, chunk in enumerate(chunks):
                text = "\n\n".join(s.text.strip() for s in chunk)
                digest = hashlib.sha256("|".join(s.sample_id for s in chunk).encode()).hexdigest()[
                    :10
                ]
                path = directory / f"{profile_context}-{side}-{index:02d}-{digest}.txt"
                privacy.write_private_text(path, text)
                out.append(
                    (path, "train" if side == "train" else "holdout", sum(s.words for s in chunk))
                )
        return out


def _classify(text: str) -> str:
    """The corpus context classifier's opinion of an answer (informational)."""
    from howlwriter.voice.corpus import context as context_stage
    from howlwriter.voice.corpus.cleanup import clean_document
    from howlwriter.voice.corpus.features import extract_features

    cleaned = clean_document(text)
    features = extract_features(cleaned.text)
    return context_stage.classify_context(
        path=Path("workshop-answer"),
        text=cleaned.text,
        cleanup=cleaned,
        features=features,
    ).context


def _mark_duplicates(sample: Sample, existing) -> None:
    value = int(sample.simhash, 16)
    for other in existing:
        if other.status == STATUS_REMOVED or not other.text:
            continue
        if other.content_hash == sample.content_hash:
            sample.duplicate_of = other.sample_id
            return
        if (
            sample.words >= 8
            and other.words >= 8
            and hamming(value, int(other.simhash or "0", 16)) <= NEAR_DUPLICATE_BITS
        ):
            sample.duplicate_of = other.sample_id
            return
    for other in existing:
        if (
            other.prompt_id == sample.prompt_id
            and other.subject.lower() == sample.subject.lower()
            and other.status != STATUS_REMOVED
        ):
            sample.same_prompt_as = other.sample_id
            return
