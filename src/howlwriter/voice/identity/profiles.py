"""Build an identity's context profiles from attested documents only.

For each profile (academic, professional) this selects the documents that
are present, extracted, not duplicates, in one of the profile's categories,
and carry an effective attestation that permits personal-voice use:

    CONFIRMED_HUMAN_AUTHORED         weight 1.0
    HUMAN_AUTHORED_LIGHT_AI_EDITING  weight 0.5
    MIXED_AUTHORSHIP                 only the attested paragraphs

Proposals never qualify. A document the scanner thinks is probably yours
contributes nothing until you say so.

The build itself is `build_voice` with an explicit selection: same
extraction, cleanup, deduplication, holdout split, aggregation, validation,
and atomic commit as every other voice. What this module adds is written into
the same staged directory as `calibration.json`, computed while the cleaned
text still exists in memory:

* the Voice Match calibration (robust centres, leave-one-out and holdout
  distances, comparison-author controls, contamination fingerprints, and a
  sample-size curve);
* the window-level drift baseline;
* the context's Naturalness calibration (also saved in the identity ledger).

Two refusals protect an existing profile. A profile is not rebuilt from
fewer than `MIN_PROFILE_DOCUMENTS` documents, and it is not rebuilt when
documents it was trained on are still present but could not be read this
time (a flaky mount must not silently shrink a profile). In both cases the
previous profile is left exactly as it was.

Model-backed trait analysis is off by default. Turning it on sends cleaned
document text to the configured HowlPlane provider, which is a transmission
of private writing to a third party; it requires an explicit
`allow_remote_content=True`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from howlwriter.evaluation import drift as drift_stage
from howlwriter.evaluation import naturalness as naturalness_stage
from howlwriter.evaluation import voice_match as vm
from howlwriter.evaluation.perturb import PERTURBATIONS
from howlwriter.voice.corpus.build import ArtifactContext, SelectedSource, build_voice
from howlwriter.voice.corpus.store import VoiceStore
from howlwriter.voice.identity import classify, privacy
from howlwriter.voice.identity.store import (
    Decision,
    IdentityConfig,
    IdentityStore,
    ProfileSpec,
    parse_paragraph_ranges,
    utc_now,
)

CALIBRATION_FILE = "calibration.json"
SUPPORTING_EVIDENCE_FILE = "supporting_evidence.json"
MIN_PROFILE_DOCUMENTS = 3

#: Third-party categories that are prose a comparison author actually wrote
#: in the same domain. License texts and templates are excluded: separating
#: a person from a software license proves nothing.
_CONTROL_CATEGORIES = set(classify.CATEGORY_CONTEXT) | {
    classify.ASSIGNMENT_INSTRUCTIONS,
    classify.THIRD_PARTY_DOCUMENT,
}


@dataclass
class SourceChoice:
    doc_id: str
    absolute_path: str
    entry: dict
    decision: Decision
    selection: SelectedSource


@dataclass
class ProfileBuildResult:
    profile: str
    voice: str
    status: str
    reason: str = ""
    eligible_documents: int = 0
    eligible_words: int = 0
    training_documents: int = 0
    holdout_documents: int = 0
    sufficiency: str = ""
    validation_confidence: str = ""
    voice_match: dict[str, Any] = field(default_factory=dict)
    naturalness: dict[str, Any] = field(default_factory=dict)
    drift_windows: int = 0
    pending_reviews_affecting: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _absolute(config: IdentityConfig, relative: str) -> Path:
    index = 0
    if len(config.sources) > 1 and ":" in relative and relative.split(":", 1)[0].isdigit():
        index_text, relative = relative.split(":", 1)
        index = int(index_text)
    return (Path(config.sources[index]).expanduser() / relative).resolve()


def _category(entry: dict, decision: Decision | None) -> str:
    if decision is not None and decision.category:
        return decision.category
    return (entry.get("classification") or {}).get("category", classify.UNKNOWN)


def _in_profile(entry: dict, decision: Decision | None, spec: ProfileSpec) -> bool:
    if decision is not None and decision.context:
        return decision.context == spec.context
    return _category(entry, decision) in spec.categories


def select_sources(
    config: IdentityConfig,
    entries: dict[str, dict],
    decisions: dict[str, Decision],
    spec: ProfileSpec,
) -> tuple[list[SourceChoice], int]:
    """Attested, eligible sources for one profile; and pending reviews that would affect it."""
    chosen: list[SourceChoice] = []
    pending = 0
    for doc_id, entry in sorted(entries.items()):
        if not entry.get("present", True) or entry.get("status") != "extracted":
            continue
        if entry.get("duplicate_role") == "duplicate":
            continue
        decision = decisions.get(doc_id)
        if not _in_profile(entry, decision, spec):
            continue
        if decision is None or not decision.effective:
            if (entry.get("proposal") or {}).get("needs_review"):
                pending += 1
            continue
        weight = classify.PROFILE_WEIGHTS.get(decision.authorship)
        if weight is None:
            continue
        paragraphs: frozenset[int] | None = None
        if decision.authorship == classify.MIXED_AUTHORSHIP:
            if not decision.include_paragraphs:
                continue
            paragraphs = frozenset(parse_paragraph_ranges(decision.include_paragraphs))
        if config.exclusions.path_is_excluded(entry["relative_path"].split(":", 1)[-1].split("/")):
            continue
        chosen.append(
            SourceChoice(
                doc_id=doc_id,
                absolute_path=str(_absolute(config, entry["relative_path"])),
                entry=entry,
                decision=decision,
                selection=SelectedSource(
                    weight=weight,
                    context=spec.context,
                    paragraphs=paragraphs,
                    authorship=decision.authorship,
                ),
            )
        )
    return chosen, pending


def _controls(
    config: IdentityConfig,
    entries: dict[str, dict],
    decisions: dict[str, Decision],
    spec: ProfileSpec,
    chosen_ids: set[str],
) -> dict[str, list[dict]]:
    """Entries usable as comparison documents for this profile."""
    from howlwriter.voice.identity.scanner import effective_authorship

    families: dict[str, list[dict]] = {
        "third_party": [],
        "ai_attested": [],
        "cross_context_self": [],
    }
    for doc_id, entry in entries.items():
        if (
            doc_id in chosen_ids
            or not entry.get("present", True)
            or entry.get("status") != "extracted"
        ):
            continue
        if entry.get("duplicate_role") == "duplicate":
            continue
        if int(entry.get("words") or 0) < vm.MIN_WORDS:
            continue
        decision = decisions.get(doc_id)
        authorship, basis = effective_authorship(entry, decisions)
        category = _category(entry, decision)
        if authorship == classify.THIRD_PARTY and category in _CONTROL_CATEGORIES:
            families["third_party"].append(entry)
        elif authorship == classify.SUBSTANTIALLY_AI_GENERATED and basis == "attested":
            families["ai_attested"].append(entry)
        elif (
            basis == "attested"
            and authorship in classify.PROFILE_WEIGHTS
            and authorship != classify.MIXED_AUTHORSHIP
            and not _in_profile(entry, decision, spec)
            and category in classify.CATEGORY_CONTEXT
        ):
            families["cross_context_self"].append(entry)
    return {k: v for k, v in families.items() if v}


def _sample_size_curve(
    calibration: vm.VoiceMatchCalibration, entries: list[dict]
) -> dict[str, Any]:
    curve: dict[str, Any] = {}
    for limit in ("300", "600", "1000"):
        scores = []
        for entry in entries:
            vector = ((entry.get("derived") or {}).get("truncated_vectors") or {}).get(limit)
            if vector:
                distance, _, _ = vm.distance(vector, calibration.robust_centres)
                scores.append(calibration.score_distance(distance))
        if scores:
            from howlwriter.evaluation.empirical import describe

            curve[limit] = describe(scores)
    curve["note"] = (
        "Voice Match scores of genuine documents truncated to N words (scored against the "
        "full profile, so training documents are in-sample here). Wider spread at shorter "
        "lengths is why scores below the minimum word count are withheld."
    )
    return curve


def _make_artifacts(
    *,
    store: IdentityStore,
    config: IdentityConfig,
    spec: ProfileSpec,
    entries: dict[str, dict],
    decisions: dict[str, Decision],
    choices: list[SourceChoice],
    result: ProfileBuildResult,
):
    by_path = {c.absolute_path: c for c in choices}

    def artifacts(context: ArtifactContext) -> dict[str, str]:
        train_texts = [context.texts[k] for k in context.train_keys if k in context.texts]
        holdout_texts = [context.texts[k] for k in context.holdout_keys if k in context.texts]
        train_vectors = [vm.measure_text(t)[0] for t in train_texts]
        holdout_vectors = [vm.measure_text(t)[0] for t in holdout_texts]

        control_entries = _controls(config, entries, decisions, spec, {c.doc_id for c in choices})
        control_vectors = {
            family: [
                e["derived"]["voice_vector"]
                for e in items
                if (e.get("derived") or {}).get("voice_vector")
            ]
            for family, items in control_entries.items()
        }
        calibration = vm.build_calibration(
            profile=spec.voice,
            context=spec.context,
            training=train_vectors,
            holdout=holdout_vectors,
            controls=control_vectors,
            training_fingerprints=[vm.TextFingerprint.of(t) for t in train_texts],
        )
        trained_entries = [by_path[k].entry for k in context.train_keys if k in by_path]
        held_entries = [by_path[k].entry for k in context.holdout_keys if k in by_path]
        curve = _sample_size_curve(calibration, held_entries + trained_entries)

        baseline = drift_stage.build_baseline(
            spec.voice, [drift_stage.window_metrics(t) for t in train_texts]
        )

        # Naturalness reference: this context's attested writing, measured
        # from the texts actually used. Controls: deterministic mechanical
        # perturbations of those same texts, plus attested AI documents.
        reference = [naturalness_stage.measure_naturalness(t) for t in train_texts + holdout_texts]
        controls: dict[str, list[naturalness_stage.NaturalnessMeasurement]] = {}
        for family, transform in PERTURBATIONS.items():
            controls[f"perturbation:{family}"] = [
                naturalness_stage.measure_naturalness(transform(t), lint=True)
                for t in train_texts + holdout_texts
            ]
        ai_entries = control_entries.get("ai_attested", [])
        if ai_entries:
            controls["attested_ai_documents"] = [
                naturalness_stage.NaturalnessMeasurement.from_dict(e["derived"]["naturalness"])
                for e in ai_entries
                if (e.get("derived") or {}).get("naturalness")
            ]
        natural = naturalness_stage.build_calibration(
            reference,
            context=spec.context,
            source=f"identity:{store.identity} attested {spec.context} writing",
            controls=controls,
        )
        store.save_calibration(f"naturalness-{spec.context}", natural.to_dict())

        result.voice_match = {
            "genuine_calibration_documents": len(calibration.genuine_distances),
            "usable": calibration.usable,
            "validated": calibration.validated(),
            "failed_validation": calibration.validation_failed(),
            "pooled_separation": calibration.validation.get("pooled_separation"),
            "controls": {k: len(v) for k, v in control_vectors.items()},
        }
        result.naturalness = {
            "reference_documents": natural.documents,
            "usable": natural.usable,
            "validated": natural.validation.get("validated"),
            "pooled_separation": natural.validation.get("pooled_separation"),
        }
        result.drift_windows = baseline.windows

        payload = {
            "identity": {
                "identity": store.identity,
                "display_name": config.display_name,
                "profile": result.profile,
                "context": spec.context,
                "profile_type": "personal_voice",
            },
            "built_at": utc_now(),
            "sources": {
                "documents": len(choices),
                "by_authorship": {
                    a: sum(1 for c in choices if c.decision.authorship == a)
                    for a in sorted({c.decision.authorship for c in choices})
                },
            },
            "voice_match": calibration.to_dict(),
            "sample_size_curve": curve,
            "drift": baseline.to_dict(),
            "naturalness_context": spec.context,
        }
        files = {CALIBRATION_FILE: json.dumps(payload, indent=2, sort_keys=True)}
        evidence = store.load_chat_evidence()
        if evidence:
            from howlwriter.voice.identity.chat import supporting_evidence_for

            files[SUPPORTING_EVIDENCE_FILE] = json.dumps(
                supporting_evidence_for(evidence, spec.context), indent=2, sort_keys=True
            )
        return files

    return artifacts


def _incomplete_sources(
    voice: VoiceStore, entries: dict[str, dict], config: IdentityConfig
) -> list[str]:
    """Previously trained sources that are present now but were not readable."""
    if not voice.exists():
        return []
    by_absolute = {str(_absolute(config, e["relative_path"])): e for e in entries.values()}
    problems = []
    for key, record in voice.load_sources().items():
        if record.split != "train" or record.inclusion not in ("include", "include_low_weight"):
            continue
        entry = by_absolute.get(key)
        if entry is not None and entry.get("present", True) and entry.get("status") != "extracted":
            problems.append(entry.get("status", "unknown"))
    return problems


def build_identity(
    identity: str,
    *,
    profiles: list[str] | None = None,
    store_root: Path | None = None,
    voices_root: Path | None = None,
    model_traits: bool = False,
    allow_remote_content: bool = False,
    allow_shrink: bool = False,
    stage_callback=None,
) -> list[ProfileBuildResult]:
    """Build (or rebuild) the identity's profiles. Returns one result per profile."""
    if model_traits and not allow_remote_content:
        raise ValueError(
            "model-backed trait analysis sends cleaned document text to the configured "
            "provider; pass allow_remote_content=True (CLI: --allow-remote-content) to confirm"
        )
    store = IdentityStore(identity, root=store_root)
    if not store.exists():
        raise ValueError(
            f"identity '{store.identity}' has not been scanned yet; run `howlwriter voice scan` first"
        )
    config = store.load_config()
    inventory = store.load_inventory()
    entries = inventory.get("entries", {})
    decisions = store.load_decisions()
    wanted = profiles or list(config.profiles)
    results: list[ProfileBuildResult] = []

    for key in wanted:
        spec = config.profiles.get(key)
        if spec is None:
            raise ValueError(f"identity '{store.identity}' has no profile named {key!r}")
        result = ProfileBuildResult(profile=key, voice=spec.voice, status="pending")
        choices, pending = select_sources(config, entries, decisions, spec)
        result.eligible_documents = len(choices)
        result.eligible_words = sum(int(c.entry.get("words") or 0) for c in choices)
        result.pending_reviews_affecting = pending
        voice = VoiceStore(spec.voice, root=voices_root)

        if len(choices) < MIN_PROFILE_DOCUMENTS:
            result.status = "insufficient"
            result.reason = (
                f"{len(choices)} attested document(s) for the {spec.context} profile; at least "
                f"{MIN_PROFILE_DOCUMENTS} are needed"
                + (f" ({pending} relevant document(s) await your review)" if pending else "")
                + ("; the existing profile was left unchanged" if voice.exists() else "")
            )
            results.append(result)
            continue
        incomplete = _incomplete_sources(voice, entries, config)
        if incomplete and not allow_shrink:
            result.status = "refused_incomplete_scan"
            result.reason = (
                f"{len(incomplete)} document(s) the existing profile was trained on could not be "
                "read in the last scan; the existing profile was kept. Rescan when the mount is "
                "healthy, or pass --allow-shrink."
            )
            results.append(result)
            continue

        previous = None
        if voice.exists():
            build = voice.load_build()
            previous = dict(build.counts)
        try:
            outcome = build_voice(
                spec.voice,
                [c.absolute_path for c in choices],
                store_root=voices_root,
                deterministic_only=not model_traits,
                selection={c.absolute_path: c.selection for c in choices},
                artifacts=_make_artifacts(
                    store=store,
                    config=config,
                    spec=spec,
                    entries=entries,
                    decisions=decisions,
                    choices=choices,
                    result=result,
                ),
                stage_callback=stage_callback,
            )
        except (OSError, RuntimeError, ValueError) as error:
            result.status = "failed"
            result.reason = (
                f"build failed ({type(error).__name__}: {error}); any existing profile was kept"
            )
            results.append(result)
            continue

        privacy.restrict_tree(outcome.directory)
        summary = outcome.profile.corpus_summary
        result.status = "built"
        result.training_documents = summary.included_documents if summary else 0
        result.holdout_documents = summary.holdout_documents if summary else 0
        result.sufficiency = summary.sufficiency if summary else ""
        result.validation_confidence = outcome.validation.overall_confidence
        result.warnings = list(outcome.warnings)
        store.append_profile_change(
            {
                "at": utc_now(),
                "profile": spec.voice,
                "status": result.status,
                "previous_counts": previous,
                "counts": dict(outcome.build.counts),
                "attested_documents": len(choices),
                "voice_match_validated": result.voice_match.get("validated"),
            }
        )
        results.append(result)
    return results


def load_calibration(voice: str, *, voices_root: Path | None = None) -> dict | None:
    store = VoiceStore(voice, root=voices_root)
    path = store.directory / CALIBRATION_FILE
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
