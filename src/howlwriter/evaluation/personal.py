"""`howlwriter evaluate`: Naturalness and Voice Match, side by side.

Resolves which profile a document should be compared with, computes the two
scores independently, adds voice-drift findings, and for a revision compares
original and revised against the same profile with the project's existing
verification safeguards.

Profile resolution, in order:

1. `--voice NAME` names a profile directly.
2. `--identity ID` (or `preferred_identity` in ~/.howlwriter/preferences.yaml
   with `--auto-voice`) selects one of that identity's context profiles: from
   `--mode` when given, otherwise from the document's own content.
3. Nothing: Naturalness can still be computed if a reference exists; Voice
   Match is reported as unavailable with the reason.

No generic behaviour is tied to any one person. An identity is whatever the
user configured, and a missing or unvalidated profile degrades to a stated
reason, never to a different profile chosen silently.

Rewrites are never performed here. Evaluation reports and suggests; a higher
score never justifies a change, and a comparison flags a revision that alters
meaning, numbers, units, citations, or qualifications however it scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from howlwriter.evaluation import drift as drift_stage
from howlwriter.evaluation import naturalness as nat
from howlwriter.evaluation import voice_match as vm
from howlwriter.voice.corpus import context as context_stage
from howlwriter.voice.corpus import quality as quality_stage
from howlwriter.voice.corpus.cleanup import clean_document
from howlwriter.voice.corpus.features import extract_features
from howlwriter.voice.corpus.store import VoiceStore
from howlwriter.voice.identity import classify, privacy
from howlwriter.voice.identity.profiles import load_calibration
from howlwriter.voice.identity.store import IdentityStore

REPORT_VERSION = "personal-evaluation/v1"

#: Which context profile a writing mode routes to. Differs deliberately from
#: the Humanizer's MODE_CONTEXTS: that table picks register RULES (and maps
#: documentation to the formal academic rules), while this one picks whose
#: writing to compare against, and documentation written at work belongs to
#: the professional corpus.
MODE_PROFILE_CONTEXT = {
    "academic": "academic",
    "professional": "professional",
    "linkedin": "professional",
    "technical": "professional",
    "documentation": "professional",
    "email": "professional",
    "article": "professional",
}

_CITATION = re.compile(
    r"\(\s*[A-Z][\w'’-]+(?:\s+et\s+al\.?)?,?\s*(?:\d{4}[a-z]?|n\.d\.)[^)]*\)|\[\d{1,3}(?:[,–-]\s*\d{1,3})*\]"
)


def load_preferences() -> dict[str, Any]:
    path = privacy.preferences_path()
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


@dataclass
class ProfileChoice:
    voice: str | None
    context: str
    identity: str | None
    reason: str
    document_category: str = ""


def classify_document_context(text: str) -> tuple[str, str]:
    """(context, category) of a document from its content."""
    cleaned = clean_document(text)
    features = extract_features(cleaned.text, headings=len(cleaned.headings))
    quality = quality_stage.classify_document(
        filename="document",
        raw_text=text,
        cleanup=cleaned,
        features=features,
    )
    context = context_stage.classify_context(
        path=Path("document"),
        text=cleaned.text,
        cleanup=cleaned,
        features=features,
    )
    result = classify.classify_category(
        quality=quality,
        context=context.context,
        context_confidence=context.confidence,
        text=cleaned.text,
        words=features.words,
        first_person_rate=features.first_person_rate,
        list_rate=features.list_rate,
        heading_rate=features.heading_rate,
        filename="document",
    )
    return classify.CATEGORY_CONTEXT.get(result.category, result.context), result.category


def choose_profile(
    text: str,
    *,
    mode: str | None = None,
    voice: str | None = None,
    identity: str | None = None,
    auto_voice: bool = False,
    identities_root: Path | None = None,
) -> ProfileChoice:
    mode_context = MODE_PROFILE_CONTEXT.get((mode or "").lower(), "")
    if voice:
        calibration = load_calibration(voice) or {}
        context = (calibration.get("identity") or {}).get("context") or mode_context or "general"
        ident = (calibration.get("identity") or {}).get("identity")
        return ProfileChoice(voice, context, ident, f"profile '{voice}' was named explicitly")

    if not identity and auto_voice:
        identity = load_preferences().get("preferred_identity")
        if not identity:
            return ProfileChoice(
                None,
                mode_context or "general",
                None,
                "--auto-voice was requested but no preferred_identity is set in "
                f"{privacy.preferences_path()}; pass --identity or --voice",
            )
    if not identity:
        return ProfileChoice(None, mode_context or "general", None, "no profile was selected")

    store = IdentityStore(identity, root=identities_root)
    config = store.load_config()
    category = ""
    if mode_context:
        context = mode_context
        why = f"--mode {mode} routes to the {context} profile"
    else:
        context, category = classify_document_context(text)
        why = f"document content classified as {category.replace('_', ' ')} ({context})"
    for spec in config.profiles.values():
        if spec.context == context:
            return ProfileChoice(spec.voice, context, store.identity, why, category)
    return ProfileChoice(
        None,
        context,
        store.identity,
        f"{why}, but identity '{store.identity}' has no {context} profile",
        category,
    )


def _naturalness_calibration(
    context: str, identity: str | None, reference_dir: Path | None, identities_root: Path | None
) -> nat.NaturalnessCalibration | None:
    if reference_dir is not None:
        return reference_calibration(reference_dir, context=context)
    if identity:
        data = IdentityStore(identity, root=identities_root).load_calibration(
            f"naturalness-{context}"
        )
        if data:
            return nat.NaturalnessCalibration.from_dict(data)
    return None


def reference_calibration(directory: Path, *, context: str) -> nat.NaturalnessCalibration:
    """Calibrate Naturalness on the fly from a folder of human writing."""
    from howlwriter.voice.corpus.extract import extract

    measurements = []
    for path in sorted(Path(directory).expanduser().rglob("*")):
        if (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in (".txt", ".md", ".docx", ".odt", ".html", ".pdf")
        ):
            result = extract(path)
            if result.ok:
                measurements.append(nat.measure_naturalness(clean_document(result.text).text))
    return nat.build_calibration(
        measurements, context=context, source=f"reference folder ({len(measurements)} files)"
    )


def evaluate_text(
    text: str,
    *,
    mode: str | None = None,
    voice: str | None = None,
    identity: str | None = None,
    auto_voice: bool = False,
    naturalness_reference: Path | None = None,
    voices_root: Path | None = None,
    identities_root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate one document. Deterministic, local, no model calls."""
    choice = choose_profile(
        text,
        mode=mode,
        voice=voice,
        identity=identity,
        auto_voice=auto_voice,
        identities_root=identities_root,
    )
    cleaned = clean_document(text).text

    natural_cal = _naturalness_calibration(
        choice.context, choice.identity, naturalness_reference, identities_root
    )
    naturalness = nat.score_naturalness(
        nat.measure_naturalness(cleaned), natural_cal, context=choice.context
    )

    if choice.voice is None:
        voice_report = vm.VoiceMatchReport(
            status=vm.STATUS_UNAVAILABLE,
            score=None,
            profile="",
            context=choice.context,
            reason=choice.reason,
            words=len(cleaned.split()),
        )
        drift_result = {"status": "UNAVAILABLE", "reason": "no profile selected", "findings": []}
    else:
        store = VoiceStore(choice.voice, root=voices_root)
        payload = (
            load_calibration(choice.voice, voices_root=voices_root) if store.exists() else None
        )
        if not store.exists():
            reason = f"profile '{choice.voice}' has not been built"
            voice_report = vm.VoiceMatchReport(
                status=vm.STATUS_UNAVAILABLE,
                score=None,
                profile=choice.voice,
                context=choice.context,
                reason=reason,
                words=len(cleaned.split()),
            )
            drift_result = {"status": "UNAVAILABLE", "reason": reason, "findings": []}
        else:
            calibration = (
                vm.VoiceMatchCalibration.from_dict(payload["voice_match"]) if payload else None
            )
            voice_report = vm.score_voice_match(
                cleaned, calibration, profile=choice.voice, context=choice.context
            )
            baseline = (
                drift_stage.DriftBaseline.from_dict(payload["drift"])
                if payload and payload.get("drift")
                else None
            )
            drift_result = drift_stage.analyze(cleaned, baseline, context_label=choice.context)
        voice_report.drift = drift_result.get("findings", [])

    return {
        "version": REPORT_VERSION,
        "mode": mode or "",
        "context": choice.context,
        "profile_selection": {
            "voice": choice.voice,
            "identity": choice.identity,
            "reason": choice.reason,
            "document_category": choice.document_category,
        },
        "words": len(cleaned.split()),
        "naturalness": naturalness.to_dict(),
        "voice_match": voice_report.to_dict(),
        "drift": drift_result,
        "independence_note": (
            "The two scores are computed independently from different measurements; a "
            "document can read naturally and still differ from this profile, or the reverse."
        ),
        "model_calls": 0,
    }


def _citations(text: str) -> list[str]:
    return sorted(m.group(0) for m in _CITATION.finditer(text))


def _requirements(text: str, requirements: dict[str, Any] | None) -> dict[str, Any]:
    if not requirements:
        return {
            "status": "NOT_EVALUATED",
            "reason": "no requirements were supplied (--requirements FILE)",
        }
    words = len(text.split())
    problems = []
    if requirements.get("min_words") and words < int(requirements["min_words"]):
        problems.append(f"{words} words is below the minimum of {requirements['min_words']}")
    if requirements.get("max_words") and words > int(requirements["max_words"]):
        problems.append(f"{words} words exceeds the maximum of {requirements['max_words']}")
    lowered = text.lower()
    for term in requirements.get("required_terms", []) or []:
        if str(term).lower() not in lowered:
            problems.append(f"required term missing: {term}")
    for heading in requirements.get("required_sections", []) or []:
        if not re.search(
            rf"^\s*#*\s*{re.escape(str(heading))}\s*$", text, re.IGNORECASE | re.MULTILINE
        ):
            problems.append(f"required section missing: {heading}")
    return {"status": "FAIL" if problems else "PASS", "problems": problems}


def _changed_dimensions(before: dict, after: dict) -> list[dict]:
    changes = []
    before_dims = {d["name"]: d for d in before["naturalness"]["dimensions"]}
    for dim in after["naturalness"]["dimensions"]:
        old = before_dims.get(dim["name"])
        if old and old.get("score") is not None and dim.get("score") is not None:
            delta = dim["score"] - old["score"]
            if abs(delta) >= 10:
                changes.append(
                    {
                        "family": "naturalness",
                        "dimension": dim["name"],
                        "label": dim["label"],
                        "delta": round(delta, 1),
                    }
                )
    before_voice = {d["name"]: d for d in before["voice_match"]["dimensions"]}
    for dim in after["voice_match"]["dimensions"]:
        old = before_voice.get(dim["name"])
        if old:
            delta = dim["distance"] - old["distance"]
            if abs(delta) >= 0.5:
                changes.append(
                    {
                        "family": "voice_match",
                        "dimension": dim["name"],
                        "label": dim["label"],
                        "distance_delta": round(delta, 2),
                        "direction": "further from profile" if delta > 0 else "closer to profile",
                    }
                )
    return changes


def compare_texts(
    original: str,
    revised: str,
    *,
    requirements: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Evaluate a revision against its original, with integrity checks."""
    from howlwriter.domain.document import Document
    from howlwriter.native.fidelity import compare as fidelity_compare
    from howlwriter.review.meaning import MeaningPreservationReviewer

    # The profile is resolved once, on the original, so both versions are
    # compared with the same reference.
    choice = choose_profile(
        original,
        mode=kwargs.get("mode"),
        voice=kwargs.get("voice"),
        identity=kwargs.get("identity"),
        auto_voice=kwargs.get("auto_voice", False),
        identities_root=kwargs.get("identities_root"),
    )
    shared = dict(kwargs)
    shared["voice"] = choice.voice or kwargs.get("voice")
    shared["identity"] = choice.identity or kwargs.get("identity")
    shared["auto_voice"] = False
    if choice.voice is None:
        shared["mode"] = kwargs.get("mode") or next(
            (m for m, c in MODE_PROFILE_CONTEXT.items() if c == choice.context), None
        )
    before = evaluate_text(original, **shared)
    after = evaluate_text(revised, **shared)

    meaning = MeaningPreservationReviewer().compare(
        Document.parse(original), Document.parse(revised)
    )
    fidelity = fidelity_compare(original, revised)
    citations_before, citations_after = _citations(original), _citations(revised)
    citations_changed = citations_before != citations_after

    def delta(key: str) -> float | None:
        a, b = before[key]["score"], after[key]["score"]
        return None if a is None or b is None else round(b - a, 1)

    integrity_problems = []
    if meaning.status != "PASS":
        integrity_problems.append("meaning preservation flagged substantive differences")
    if fidelity.factual_change:
        integrity_problems.append(f"factual fidelity: {fidelity.status}")
    if citations_changed:
        integrity_problems.append("citations differ between versions")
    req = _requirements(revised, requirements)
    if req["status"] == "FAIL":
        integrity_problems.append("revision fails a stated requirement")

    return {
        "version": REPORT_VERSION,
        "profile_selection": before["profile_selection"],
        "context": before["context"],
        "original": before,
        "revised": after,
        "naturalness": {
            "original": before["naturalness"]["score"],
            "revised": after["naturalness"]["score"],
            "delta": delta("naturalness"),
        },
        "voice_match": {
            "original": before["voice_match"]["score"],
            "revised": after["voice_match"]["score"],
            "delta": delta("voice_match"),
        },
        "changed_dimensions": _changed_dimensions(before, after),
        "remaining_drift": after["drift"].get("findings", []),
        "meaning_preservation": {
            "status": meaning.status,
            "differences": [
                {"kind": d.kind, "description": d.description} for d in meaning.diffs[:20]
            ],
        },
        "factual_integrity": fidelity.to_dict(),
        "citations": {
            "status": "CHANGED" if citations_changed else "PRESERVED",
            "removed": sorted(set(citations_before) - set(citations_after)),
            "added": sorted(set(citations_after) - set(citations_before)),
        },
        "requirements": req,
        "verdict": "REVISION_CHANGES_SUBSTANCE" if integrity_problems else "SUBSTANCE_PRESERVED",
        "integrity_problems": integrity_problems,
        "policy": (
            "A higher score never justifies a change to meaning, numbers, units, citations, "
            "qualifications, or requirements. Keeping the original is always a valid outcome."
        ),
        "model_calls": 0,
    }


def attach_voice_match(report: Any, voice_profile_ref: str | None, text: str) -> None:
    """Fill `WritingReport.voice_match` from a calibrated identity profile.

    `voice_profile_ref` is the `config.voice_profile` value the pipelines
    already carry (a profile.json path for `--voice NAME`). Profiles without a
    calibration leave the field untouched, preserving the "omit, don't fake"
    rule. Never raises: a diagnostic must not fail the run it describes.
    """
    try:
        if not voice_profile_ref:
            return
        path = Path(voice_profile_ref).expanduser()
        if path.name != "profile.json" or not (path.parent / "calibration.json").is_file():
            return
        payload = load_calibration(path.parent.name, voices_root=path.parent.parent) or {}
        if not payload.get("voice_match"):
            return
        calibration = vm.VoiceMatchCalibration.from_dict(payload["voice_match"])
        context = (payload.get("identity") or {}).get("context", "")
        result = vm.score_voice_match(
            clean_document(text).text, calibration, profile=path.parent.name, context=context,
        )
        if result.status == vm.STATUS_SCORED and result.score is not None:
            report.voice_match = round(result.score / 100.0, 3)
            report.voice_match_band = result.band
            report.voice_match_basis = (
                f"percentile against {path.parent.name}'s held-out writing "
                f"({result.calibration_status}); a similarity measure, not authorship"
            )
        else:
            report.voice_match_basis = f"{path.parent.name}: {result.reason}"
    except Exception:
        return

