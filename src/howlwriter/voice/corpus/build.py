"""The orchestrator: roots in, private profile out.

Runs the stages in order, reports each one truthfully as it starts and
finishes, and guarantees the two properties the whole feature rests on.

Raw text never lands on disk. Extracted prose lives in a local dictionary for
the duration of the call and is dropped when it returns, on the success path
and on every failure path. What persists is derived: hashes, feature vectors,
abstract labels, counts.

An existing profile survives a failed build. Everything is assembled in a
staging directory and swapped in at the end, so a provider outage during
trait analysis costs the run, not the profile that was already there.

Progress is reported as named stages rather than a percentage. A corpus scan
cannot honestly estimate how long extraction will take before it knows what
it found, and a made-up progress bar is worse than none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
import hashlib
from pathlib import Path
import time
from typing import Any, Callable

from howlwriter.diagnostic.run_record import RunRecord, generate_run_id
from howlwriter.domain.voice import (
    VOICE_PROFILE_VERSION,
    CorpusSummary,
    VoiceOverrides,
    VoiceProfile,
)
from howlwriter.voice.corpus import context as context_stage
from howlwriter.voice.corpus import dedup as dedup_stage
from howlwriter.voice.corpus import diversity as diversity_stage
from howlwriter.voice.corpus import quality as quality_stage
from howlwriter.voice.corpus import traits as traits_stage
from howlwriter.voice.corpus import validation as validation_stage
from howlwriter.voice.corpus.aggregate import DocumentEvidence, aggregate, build_corpus_summary
from howlwriter.voice.corpus.cleanup import clean_document
from howlwriter.voice.corpus.discovery import discover
from howlwriter.voice.corpus.extract import STATUS_SCANNED, STATUS_UNAVAILABLE, extract
from howlwriter.voice.corpus.features import DocumentFeatures, extract_features
from howlwriter.voice.corpus.split import HOLDOUT, TRAIN, assign_split
from howlwriter.voice.corpus.store import (
    OVERRIDES_FILE,
    BuildRecord,
    SourceRecord,
    VoiceStore,
    utc_now,
)

StageCallback = Callable[[str, str, dict[str, Any]], None]

#: The stages a build reports, in order.
STAGES: tuple[tuple[str, str], ...] = (
    ("discovering", "Discovering documents"),
    ("extracting", "Extracting text"),
    ("deduplicating", "Deduplicating"),
    ("classifying", "Classifying context and authorship"),
    ("features", "Analyzing deterministic features"),
    ("traits", "Analyzing higher-order traits"),
    ("synthesis", "Building profile"),
    ("validating", "Validating against holdout"),
    ("saving", "Saving profile"),
)


@dataclass
class CorpusReport:
    """Everything the build saw, as counts and reasons. No excerpts."""

    roots_supplied: int = 0
    roots_after_canonicalization: int = 0
    paths_visited: int = 0
    duplicate_root_hits: int = 0
    files_discovered: int = 0
    unique_canonical_files: int = 0
    file_types: dict[str, int] = field(default_factory=dict)
    candidate_prose_files: int = 0
    readable_files: int = 0
    extraction_failures: int = 0
    scanned_or_unavailable: int = 0
    exact_duplicates: int = 0
    cross_format_duplicates: int = 0
    revision_duplicates: int = 0
    revision_groups: int = 0
    included_documents: int = 0
    holdout_documents: int = 0
    excluded_documents: int = 0
    training_words: int = 0
    holdout_words: int = 0
    words_by_context: dict[str, int] = field(default_factory=dict)
    documents_by_context: dict[str, int] = field(default_factory=dict)
    classifications: dict[str, int] = field(default_factory=dict)
    inclusion_states: dict[str, int] = field(default_factory=dict)
    exclusion_reasons: dict[str, int] = field(default_factory=dict)
    discovery_exclusions: dict[str, int] = field(default_factory=dict)
    uncertain_authorship: int = 0
    held_for_review: int = 0
    possible_ai_assisted: int = 0
    sensitive_excluded: int = 0


@dataclass
class BuildOutcome:
    profile: VoiceProfile
    report: CorpusReport
    build: BuildRecord
    validation: validation_stage.ValidationResult
    directory: Path
    warnings: list[str] = field(default_factory=list)


#: Bump when an existing measurement changes meaning.
#:
#: The field-name fingerprint below is self-maintaining for ADDED or REMOVED
#: fields, which is what it was built for. It is blind to the other half of the
#: problem: redefining how an existing field is computed -- counting em dashes
#: differently, changing what a fragment is -- leaves the field names identical,
#: so every unchanged document is restored from a cache holding numbers the
#: current code would never produce. The profile then mixes two measurement
#: regimes and nothing reports it. This constant is the manual half, and it is
#: the only part anyone has to remember.
FEATURE_MEASUREMENT_REVISION = 1


def _feature_schema_fingerprint() -> str:
    """Identity of the DocumentFeatures schema AND of the code that fills it.

    The content hash answers "is this the same document?". It cannot answer
    "were these numbers produced by the current measurement code?". When a new
    feature is added, every unchanged document would otherwise be restored from
    a cache that predates the field, `from_dict` would fill it with the
    dataclass default, and the build would persist a corpus-wide zero for a
    feature that was never measured. Deriving the fingerprint from the field
    names means adding a field invalidates the cache on its own, with nothing
    to remember to bump.

    Field names cannot see a changed measurement, so the revision constant is
    folded in as well: bumping it invalidates every cached vector the same way
    adding a field does.
    """
    names = ",".join(sorted(f.name for f in dataclass_fields(DocumentFeatures)))
    identity = f"{names}|revision={FEATURE_MEASUREMENT_REVISION}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _fingerprint(path: Path, content_hash: str) -> str:
    """Stable identity for a document across rebuilds.

    Keyed on content rather than path so that renaming a file does not move it
    between train and holdout, and editing one does.
    """
    return hashlib.sha256(f"{path.name}:{content_hash}".encode("utf-8")).hexdigest()[:32]


def _outlier_documents(
    evidence: list[DocumentEvidence],
) -> dict[str, str]:
    """Flag documents whose style sits far from the rest of the corpus.

    Explicitly NOT an AI detector, and it does not claim one. It measures
    distance from the corpus centre on a few structural axes, which catches
    abrupt shifts in register whatever caused them -- a different author, a
    heavily edited draft, a document that was pasted in. The result is a
    downweight and a stated reason, never a verdict about how a document was
    produced.
    """
    if len(evidence) < 6:
        return {}

    axes = (
        "sentence_length_mean", "sentence_length_stdev", "paragraph_words_mean",
        "transition_rate", "long_word_rate", "contraction_rate", "repetition_rate",
    )
    import statistics

    centres: dict[str, tuple[float, float]] = {}
    for axis in axes:
        values = [float(getattr(doc.features, axis, 0.0) or 0.0) for doc in evidence]
        mean = statistics.mean(values)
        spread = statistics.pstdev(values)
        centres[axis] = (mean, spread)

    flagged: dict[str, str] = {}
    for doc in evidence:
        distances = []
        for axis in axes:
            mean, spread = centres[axis]
            if spread < 1e-6:
                continue
            distances.append(abs(float(getattr(doc.features, axis, 0.0) or 0.0) - mean) / spread)
        if not distances:
            continue
        far = [d for d in distances if d > 2.0]
        if len(far) >= 3:
            flagged[doc.key] = (
                f"style sits far from the rest of the corpus on {len(far)} structural "
                "measures; downweighted as an outlier (this is a corpus-consistency "
                "signal, not a judgement about how the document was written)"
            )
    return flagged


def build_voice(
    name: str,
    roots: list[str | Path],
    *,
    store_root: Path | None = None,
    recursive: bool = True,
    deterministic_only: bool = False,
    custom_backend: Any | None = None,
    cwd: Path | str | None = None,
    run_id: str | None = None,
    stage_callback: StageCallback | None = None,
    reuse_cache: bool = True,
    profile_type: str = "personal_voice",
) -> BuildOutcome:
    """Build or rebuild a named personal voice from a corpus."""
    started = time.time()
    store = VoiceStore(name, root=store_root)
    report = CorpusReport()
    warnings: list[str] = []
    stage_times: dict[str, float] = {}

    def notify(stage_id: str, status: str, data: dict[str, Any] | None = None) -> None:
        if stage_callback is None:
            return
        label = dict(STAGES).get(stage_id, stage_id)
        try:
            stage_callback(stage_id, status, {"label": label, **(data or {})})
        except Exception:
            pass

    # Overrides are read before anything else so a failure later cannot cost
    # the user their corrections.
    overrides = store.load_overrides() if store.exists() else VoiceOverrides()
    overrides_raw: str | None = None
    existing_overrides = store.directory / OVERRIDES_FILE
    if existing_overrides.is_file():
        overrides_raw = existing_overrides.read_text(encoding="utf-8")

    cached_features = store.load_features() if reuse_cache and store.exists() else {}
    schema_fingerprint = _feature_schema_fingerprint()
    cached_sources = store.load_sources() if reuse_cache and store.exists() else {}

    # --- 1. discovery ---
    notify("discovering", "RUNNING")
    stage_start = time.time()
    discovery = discover(roots, recursive=recursive)
    stage_times["discovering"] = round(time.time() - stage_start, 2)

    report.roots_supplied = discovery.roots_supplied
    report.roots_after_canonicalization = discovery.roots_after_canonicalization
    report.paths_visited = discovery.paths_visited
    report.duplicate_root_hits = discovery.duplicate_root_hits
    report.files_discovered = discovery.paths_visited
    report.unique_canonical_files = len(discovery.files)
    report.candidate_prose_files = len(discovery.candidates)
    report.discovery_exclusions = discovery.exclusion_reasons()
    for entry in discovery.files:
        key = entry.suffix or "(none)"
        report.file_types[key] = report.file_types.get(key, 0) + 1
    for root in discovery.unreadable_roots:
        warnings.append(f"source root could not be read and was skipped: {root}")
    notify("discovering", "DONE", {
        "roots_supplied": report.roots_supplied,
        # Nested roots are collapsed before the walk, so most overlap never
        # produces a repeat visit at all; duplicate_root_hits catches what is
        # left (symlinks, and files reachable through two unrelated roots).
        "roots_after_canonicalization": report.roots_after_canonicalization,
        "unique_files": report.unique_canonical_files,
        "candidates": report.candidate_prose_files,
        "repeat_paths_collapsed": report.duplicate_root_hits,
    })

    # --- 2. extraction, cleanup, features, classification ---
    # `texts` is the only place cleaned prose exists. It is local to this
    # function and is never written anywhere.
    notify("extracting", "RUNNING", {"files": report.candidate_prose_files})
    stage_start = time.time()

    texts: dict[str, str] = {}
    records: dict[str, SourceRecord] = {}
    feature_cache: dict[str, dict] = {}
    features_by_key: dict[str, DocumentFeatures] = {}
    contexts: dict[str, str] = {}
    weights: dict[str, float] = {}
    cached_traits: dict[str, dict[str, str]] = {}

    for entry in discovery.candidates:
        key = str(entry.path)
        cached = cached_sources.get(key)
        extraction = extract(entry.path)

        if not extraction.ok:
            if extraction.status in (STATUS_SCANNED, STATUS_UNAVAILABLE):
                report.scanned_or_unavailable += 1
            else:
                report.extraction_failures += 1
            records[key] = SourceRecord(
                key=key, path=key, size=entry.size, mtime=entry.mtime,
                parser=extraction.parser, extraction_status=extraction.status,
                classification="unreadable", inclusion=quality_stage.EXCLUDE,
                reason=extraction.reason,
            )
            report.exclusion_reasons[extraction.status] = (
                report.exclusion_reasons.get(extraction.status, 0) + 1
            )
            continue

        report.readable_files += 1
        content_hash = dedup_stage.content_hash(extraction.text)

        # The credential guard runs before any derived value is computed or
        # cached, so nothing from a secret-bearing file is retained at all.
        if quality_stage.looks_sensitive(entry.path.name, extraction.text):
            report.sensitive_excluded += 1
            report.classifications[quality_stage.SENSITIVE_CONTENT] = (
                report.classifications.get(quality_stage.SENSITIVE_CONTENT, 0) + 1
            )
            report.exclusion_reasons["sensitive_content"] = (
                report.exclusion_reasons.get("sensitive_content", 0) + 1
            )
            records[key] = SourceRecord(
                key=key, path=key, size=entry.size, mtime=entry.mtime,
                parser=extraction.parser, extraction_status=extraction.status,
                classification=quality_stage.SENSITIVE_CONTENT,
                inclusion=quality_stage.EXCLUDE,
                reason="excluded before analysis: appears to contain credentials",
            )
            continue

        cleaned = clean_document(extraction.text)

        unchanged = (
            cached is not None
            and cached.content_hash == content_hash
            and str(key) in cached_features
            and cached_features[key].get("feature_schema") == schema_fingerprint
        )
        if unchanged:
            features = DocumentFeatures.from_dict(cached_features[key].get("features", {}))
            # Abstract trait labels are privacy-safe derived data, so an
            # unchanged document does not need re-analyzing. Without this a
            # rebuild re-ran every provider batch to reach the same answer.
            previous = cached_features[key].get("model_traits")
            if isinstance(previous, dict) and previous:
                cached_traits[key] = {
                    str(name): str(value) for name, value in previous.items()
                }
        else:
            features = extract_features(cleaned.text, headings=len(cleaned.headings))

        assessment = quality_stage.classify_document(
            filename=entry.path.name,
            raw_text=extraction.text,
            cleanup=cleaned,
            features=features,
        )
        context_result = context_stage.classify_context(
            path=entry.path, text=cleaned.text, cleanup=cleaned, features=features,
        )

        texts[key] = cleaned.text
        features_by_key[key] = features
        contexts[key] = context_result.context
        weights[key] = assessment.weight

        report.classifications[assessment.classification] = (
            report.classifications.get(assessment.classification, 0) + 1
        )
        report.inclusion_states[assessment.inclusion] = (
            report.inclusion_states.get(assessment.inclusion, 0) + 1
        )
        if assessment.inclusion == quality_stage.EXCLUDE:
            report.exclusion_reasons[assessment.classification] = (
                report.exclusion_reasons.get(assessment.classification, 0) + 1
            )
        if assessment.classification == quality_stage.UNKNOWN_AUTHORSHIP:
            report.uncertain_authorship += 1
        if assessment.inclusion == quality_stage.HOLD_FOR_REVIEW:
            report.held_for_review += 1

        records[key] = SourceRecord(
            key=key, path=key, size=entry.size, mtime=entry.mtime,
            content_hash=content_hash,
            feature_hash=hashlib.sha256(
                repr(sorted(features.to_dict().items())).encode("utf-8")
            ).hexdigest()[:32],
            parser=extraction.parser, extraction_status=extraction.status,
            classification=assessment.classification, inclusion=assessment.inclusion,
            weight=assessment.weight, context=context_result.context,
            context_confidence=context_result.confidence, words=features.words,
            reason=assessment.reason,
        )
        feature_cache[key] = {
            "content_hash": content_hash,
            "feature_schema": schema_fingerprint,
            "features": features.to_dict(),
            "context": context_result.context,
            "classification": assessment.classification,
            "reused": unchanged,
            "model_traits": cached_traits.get(key, {}),
        }

    stage_times["extracting"] = round(time.time() - stage_start, 2)
    notify("extracting", "DONE", {
        "extracted": report.readable_files,
        "failures": report.extraction_failures,
        "unavailable": report.scanned_or_unavailable,
    })

    # --- 3. deduplication ---
    notify("deduplicating", "RUNNING")
    stage_start = time.time()
    usable_keys = [
        key for key, record in records.items()
        if record.inclusion in (quality_stage.INCLUDE, quality_stage.INCLUDE_LOW_WEIGHT)
    ]
    dedup_result = dedup_stage.deduplicate([
        dedup_stage.DedupCandidate(
            key=key, path=Path(key), text=texts[key],
            words=features_by_key[key].words, mtime=records[key].mtime,
        )
        for key in usable_keys
    ])
    stage_times["deduplicating"] = round(time.time() - stage_start, 2)

    report.exact_duplicates = dedup_result.exact_duplicates
    report.cross_format_duplicates = dedup_result.cross_format_duplicates
    report.revision_duplicates = dedup_result.revision_duplicates
    report.revision_groups = dedup_result.revision_groups

    for key, member in dedup_result.members.items():
        records[key].group_id = member.group_id
        records[key].duplicate_role = member.role
        records[key].duplicate_relation = member.relation
        if member.role == "duplicate":
            records[key].inclusion = quality_stage.EXCLUDE
            records[key].weight = 0.0
            records[key].reason = member.reason
            report.exclusion_reasons[f"duplicate_{member.relation or 'copy'}"] = (
                report.exclusion_reasons.get(f"duplicate_{member.relation or 'copy'}", 0) + 1
            )
    notify("deduplicating", "DONE", {
        "exact": report.exact_duplicates,
        "cross_format": report.cross_format_duplicates,
        "revisions": report.revision_duplicates,
        "groups": report.revision_groups,
    })

    # --- 4. classification summary + evidence assembly ---
    notify("classifying", "RUNNING")
    stage_start = time.time()
    included_keys = sorted(dedup_result.representatives())
    evidence = [
        DocumentEvidence(
            key=key,
            features=features_by_key[key],
            context=contexts[key],
            weight=weights[key],
        )
        for key in included_keys
    ]

    outliers = _outlier_documents(evidence)
    for doc in evidence:
        if doc.key in outliers:
            doc.weight = min(doc.weight, quality_stage.weight_for(quality_stage.INCLUDE_LOW_WEIGHT))
            records[doc.key].classification = quality_stage.POSSIBLE_AI_ASSISTED_OUTLIER
            records[doc.key].inclusion = quality_stage.INCLUDE_LOW_WEIGHT
            records[doc.key].weight = doc.weight
            records[doc.key].reason = outliers[doc.key]
            report.possible_ai_assisted += 1
    stage_times["classifying"] = round(time.time() - stage_start, 2)
    notify("classifying", "DONE", {
        "included": len(evidence),
        "outliers_downweighted": len(outliers),
        "uncertain_authorship": report.uncertain_authorship,
    })

    # --- 5. train / holdout split ---
    notify("features", "RUNNING")
    stage_start = time.time()
    split = assign_split([
        (doc.key, _fingerprint(Path(doc.key), records[doc.key].content_hash), doc.context)
        for doc in evidence
    ])
    for doc in evidence:
        records[doc.key].split = split.side_of(doc.key)
    train = [doc for doc in evidence if split.side_of(doc.key) == TRAIN]
    holdout = [doc for doc in evidence if split.side_of(doc.key) == HOLDOUT]
    if not split.performed and split.reason:
        warnings.append(split.reason)
    stage_times["features"] = round(time.time() - stage_start, 2)
    notify("features", "DONE", {"train": len(train), "holdout": len(holdout)})

    # --- 6. higher-order traits (training documents only) ---
    notify("traits", "RUNNING", {"documents": len(train)})
    stage_start = time.time()
    trait_result = traits_stage.TraitAnalysisResult()
    if deterministic_only:
        warnings.append(
            "deterministic-only build: higher-order traits were not analyzed"
        )
    elif train:
        # Reuse cached labels for documents that have not changed; only the
        # rest reach a provider.
        for doc in train:
            if doc.key in cached_traits:
                doc.model_traits = dict(cached_traits[doc.key])
        pending = [doc for doc in train if not doc.model_traits]
        reused = len(train) - len(pending)
        if reused:
            notify("traits", "RUNNING", {"reused_from_cache": reused})

        if pending:
            trait_result = traits_stage.analyze_documents(
                [(doc.key, texts[doc.key]) for doc in pending],
                cwd=cwd, custom_backend=custom_backend, run_id=run_id,
                progress=lambda done, total: notify(
                    "traits", "RUNNING", {"batch": done, "batches": total}
                ),
            )
            for doc in pending:
                analyzed = trait_result.documents.get(doc.key)
                if analyzed and analyzed.traits:
                    doc.model_traits = analyzed.traits
            warnings.extend(trait_result.warnings)

        # Persist whatever labels survived, so the next rebuild can skip them.
        for doc in train:
            if doc.model_traits and doc.key in feature_cache:
                feature_cache[doc.key]["model_traits"] = dict(doc.model_traits)
    stage_times["traits"] = round(time.time() - stage_start, 2)
    notify("traits", "DONE", {
        "batches": trait_result.batches_attempted,
        "failed": trait_result.batches_failed,
        "provider": trait_result.provider,
        "documents_with_traits": sum(1 for doc in train if doc.model_traits),
    })

    # --- 7. synthesis (holdout has not been touched) ---
    notify("synthesis", "RUNNING")
    stage_start = time.time()
    aggregated = aggregate(train)
    for context, reason in aggregated.skipped_contexts.items():
        warnings.append(f"context '{context}' was not built: {reason}")

    summary = build_corpus_summary(train=train, holdout=holdout, aggregated=aggregated)
    _fill_summary(summary, report)

    profile = VoiceProfile(
        author_name="",
        version=VOICE_PROFILE_VERSION,
        profile_type=profile_type,          # type: ignore[arg-type]
        profile_name=store.name,
        generated_from="corpus_build",
        traits=aggregated.traits,
        contexts=aggregated.contexts,
        distributions=aggregated.distributions,
        rate_distributions=aggregated.rate_distributions,
        overrides=overrides,
        corpus_summary=summary,
        built_at=utc_now(),
    )
    # Mirror the legacy scalar fields so a profile built here still renders
    # through the pre-existing Humanizer path unchanged.
    if aggregated.distributions is not None:
        profile.sentence_length_mean = aggregated.distributions.sentence_length_mean
        profile.sentence_length_stdev = aggregated.distributions.sentence_length_stdev
        profile.paragraph_length_mean = aggregated.distributions.paragraph_sentences_mean
        profile.contraction_rate = aggregated.distributions.contraction_rate
        profile.rhetorical_question_rate = aggregated.distributions.question_rate
        profile.fragment_rate = aggregated.distributions.fragment_rate
    stage_times["synthesis"] = round(time.time() - stage_start, 2)
    notify("synthesis", "DONE", {
        "traits": len(profile.traits),
        "contexts": sorted(profile.contexts),
        "sufficiency": aggregated.sufficiency,
    })

    # --- 8. holdout validation ---
    notify("validating", "RUNNING", {"holdout": len(holdout)})
    stage_start = time.time()
    validation = validation_stage.validate(
        train=train, holdout=holdout, corpus_sufficiency=aggregated.sufficiency,
    )
    profile.validation = validation_stage.to_summary(
        validation, diversity=diversity_stage.NOT_EVALUATED
    )
    warnings.extend(validation.warnings)
    stage_times["validating"] = round(time.time() - stage_start, 2)
    notify("validating", "DONE", {
        "performed": validation.performed,
        "confidence": validation.overall_confidence,
    })

    # --- 9. save ---
    notify("saving", "RUNNING")
    stage_start = time.time()
    profile.warnings = list(dict.fromkeys(warnings))

    build_record = BuildRecord(
        built_at=profile.built_at,
        duration_seconds=round(time.time() - started, 2),
        status="ok",
        roots=[str(Path(r).expanduser()) for r in roots],
        stages=stage_times,
        providers=[trait_result.provider] if trait_result.provider else [],
        counts={
            "unique_canonical_files": report.unique_canonical_files,
            "candidate_prose_files": report.candidate_prose_files,
            "readable_files": report.readable_files,
            "included_documents": len(train),
            "holdout_documents": len(holdout),
            "excluded_documents": report.excluded_documents,
            "training_words": summary.training_words,
            "holdout_words": summary.holdout_words,
        },
        warnings=profile.warnings,
        trait_analysis={
            "batches_attempted": trait_result.batches_attempted,
            "batches_failed": trait_result.batches_failed,
            "complete": trait_result.complete,
        },
    )

    with store.stage() as staged:
        staged.write_profile(profile)
        staged.write_sources(records)
        staged.write_features(feature_cache)
        staged.write_overrides(overrides, raw=overrides_raw)
        staged.write_build(build_record)
        directory = staged.commit()
    stage_times["saving"] = round(time.time() - stage_start, 2)
    notify("saving", "DONE", {"directory": str(directory)})

    # A voice build belongs in the same local ledger as every other run, so
    # `howlwriter runs list` shows it. Counts, durations, providers and
    # status only -- never a source path, a filename, or a word of prose.
    _record_run(
        run_id=run_id,
        name=store.name,
        build_record=build_record,
        report=report,
        trait_result=trait_result,
        warnings=profile.warnings,
    )

    # Cleaned prose is dropped here. It only ever lived in this function.
    texts.clear()

    return BuildOutcome(
        profile=profile, report=report, build=build_record,
        validation=validation, directory=directory, warnings=profile.warnings,
    )


def _fill_summary(summary: CorpusSummary, report: CorpusReport) -> None:
    """Copy corpus counts into the profile's privacy-safe summary block."""
    summary.documents_discovered = report.files_discovered
    summary.unique_canonical_files = report.unique_canonical_files
    summary.candidate_prose_files = report.candidate_prose_files
    summary.exact_duplicates = report.exact_duplicates
    summary.cross_format_duplicates = report.cross_format_duplicates
    summary.revision_groups = report.revision_groups
    summary.extraction_failures = report.extraction_failures
    summary.scanned_or_unreadable = report.scanned_or_unavailable
    summary.quality_classifications = dict(report.classifications)
    summary.exclusion_reasons = dict(report.exclusion_reasons)
    summary.excluded_documents = sum(report.exclusion_reasons.values())
    summary.held_for_review_documents = report.held_for_review
    report.included_documents = summary.included_documents
    report.holdout_documents = summary.holdout_documents
    report.excluded_documents = summary.excluded_documents
    report.training_words = summary.training_words
    report.holdout_words = summary.holdout_words
    report.words_by_context = dict(summary.words_by_context)
    report.documents_by_context = dict(summary.documents_by_context)


def _record_run(
    *,
    run_id: str | None,
    name: str,
    build_record: BuildRecord,
    report: CorpusReport,
    trait_result: traits_stage.TraitAnalysisResult,
    warnings: list[str],
) -> None:
    """Write a privacy-safe run record for a completed voice build.

    Deliberately carries no path, no filename, and no document content --
    only the operational facts (counts, durations, providers, status) that
    make the build visible in `howlwriter runs list` alongside every other
    HowlWriter execution.

    Never allowed to fail a build: a diagnostic artifact that could break the
    thing it observes would be worse than no artifact.
    """
    try:
        RunRecord(
            run_id=run_id or generate_run_id(),
            command="voice build",
            success=build_record.status == "ok",
            status="READY" if build_record.status == "ok" else "NEEDS_REVIEW",
            humanizer_provider=None,
            total_duration_seconds=build_record.duration_seconds,
            changes_count=report.included_documents,
            fallback_occurred=trait_result.batches_failed > 0,
            metadata={
                "voice_name": name,
                "unique_canonical_files": report.unique_canonical_files,
                "candidate_prose_files": report.candidate_prose_files,
                "readable_files": report.readable_files,
                "included_documents": report.included_documents,
                "holdout_documents": report.holdout_documents,
                "excluded_documents": report.excluded_documents,
                "training_words": report.training_words,
                "holdout_words": report.holdout_words,
                "exact_duplicates": report.exact_duplicates,
                "cross_format_duplicates": report.cross_format_duplicates,
                "revision_groups": report.revision_groups,
                "extraction_failures": report.extraction_failures,
                "scanned_or_unavailable": report.scanned_or_unavailable,
                "sensitive_excluded": report.sensitive_excluded,
                "trait_batches_attempted": trait_result.batches_attempted,
                "trait_batches_failed": trait_result.batches_failed,
                "trait_provider": trait_result.provider or "none",
                "stages": build_record.stages,
                "warning_count": len(warnings),
            },
        ).save()
    except Exception:
        pass
