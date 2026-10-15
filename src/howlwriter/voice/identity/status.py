"""One summary of an identity's state, shared by the CLI and the web UI.

Counts, states, and reasons only. File names and document text are never
part of this summary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from howlwriter.voice.corpus.store import VoiceStore
from howlwriter.voice.identity import review
from howlwriter.voice.identity.profiles import load_calibration
from howlwriter.voice.identity.scanner import mount_status
from howlwriter.voice.identity.store import IdentityStore


def _profile_state(voice: str, voices_root: Path | None) -> dict[str, Any]:
    store = VoiceStore(voice, root=voices_root)
    state: dict[str, Any] = {"voice": voice, "state": "NOT_BUILT"}
    if not store.exists():
        return state
    profile = store.load_profile()
    summary = profile.corpus_summary
    validation = profile.validation
    calibration = load_calibration(voice, voices_root=voices_root) or {}
    vm = calibration.get("voice_match") or {}
    genuine = len(vm.get("genuine_distances") or [])
    pooled = (vm.get("validation") or {}).get("pooled_separation") or {}
    if not vm:
        vm_status = "NOT_CALIBRATED"
    elif (vm.get("validation") or {}).get("validated"):
        vm_status = "VALIDATED"
    elif genuine >= 8:
        vm_status = "CALIBRATED_UNVALIDATED"
    else:
        vm_status = "INSUFFICIENT"
    traits = sorted(profile.traits.items(), key=lambda kv: -kv[1].confidence)[:6]
    state.update(
        {
            "state": "BUILT",
            "built_at": profile.built_at,
            "training_documents": summary.included_documents if summary else 0,
            "holdout_documents": summary.holdout_documents if summary else 0,
            "training_words": summary.training_words if summary else 0,
            "sufficiency": summary.sufficiency if summary else "unknown",
            "confidence": validation.overall_confidence if validation else "UNKNOWN",
            "validation_bands": dict(validation.alignment) if validation else {},
            "characteristics": [
                {"name": name, "value": trait.value, "confidence": round(trait.confidence, 2)}
                for name, trait in traits
            ],
            "sources_by_authorship": (calibration.get("sources") or {}).get("by_authorship", {}),
            "voice_match": {
                "status": vm_status,
                "genuine_documents": genuine,
                "auc": pooled.get("auc"),
                "interval_95": pooled.get("interval_95"),
                "controls": pooled.get("control_n"),
            },
            "drift_windows": (calibration.get("drift") or {}).get("windows", 0),
        }
    )
    return state


def identity_status(
    identity: str, *, store_root: Path | None = None, voices_root: Path | None = None
) -> dict[str, Any]:
    store = IdentityStore(identity, root=store_root)
    config = store.load_config()
    mounts = [
        {"source_index": i, **mount_status(Path(source).expanduser())}
        for i, source in enumerate(config.sources)
    ]
    profiles = []
    for key, spec in config.profiles.items():
        state = _profile_state(spec.voice, voices_root)
        state["profile"] = key
        state["context"] = spec.context
        profiles.append(state)
    review_summary = (
        review.summary(store)
        if store.exists()
        else {"pending": 0, "decisions": 0, "reopened": 0, "by_authorship": {}}
    )
    evidence = store.load_chat_evidence() if store.exists() else None
    return {
        "identity": store.identity,
        "display_name": config.display_name,
        "scanned": store.exists(),
        "mounts": mounts,
        "exclusions": config.exclusions.names,
        "scan": store.load_scan_report() if store.exists() else {},
        "review": review_summary,
        "profiles": profiles,
        "chat_evidence": (
            {
                "status": evidence.get("status"),
                "source": evidence.get("source"),
                "tendencies": len(evidence.get("tendencies", [])),
            }
            if evidence
            else None
        ),
    }
