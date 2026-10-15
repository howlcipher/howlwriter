"""Everything derived from one document's text, computed once per version.

The scanner reads a file, extracts its prose, and hands the text here. What
comes back is numbers, labels, and hashes -- the only things the private
inventory ever holds. The text itself goes out of scope when this returns.

Deriving everything at scan time is what makes the rest incremental. A
profile build, a calibration, and a drift baseline all need measurements of
documents that have not changed since the last scan; caching them here means
those steps never have to re-read an unchanged file from a cloud mount.

Two orderings are load-bearing:

1. The credential guard runs before anything is measured. A file that looks
   like it holds secrets gets a record saying so and nothing else.
2. Classification comes before any profile-relevant measurement is trusted;
   the measurements are cached for every readable document, because a later
   attestation can move a document into a profile without a rescan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from howlwriter.evaluation.drift import window_metrics
from howlwriter.evaluation.naturalness import measure_naturalness
from howlwriter.evaluation.perturb import PERTURBATIONS
from howlwriter.evaluation.voice_match import (
    TextFingerprint,
    extra_features,
    measure_text,
    vector_from,
)
from howlwriter.voice.corpus import context as context_stage
from howlwriter.voice.corpus import quality as quality_stage
from howlwriter.voice.corpus.cleanup import clean_document
from howlwriter.voice.corpus.features import extract_features
from howlwriter.voice.identity import classify, provenance

#: Bump when any derived measurement changes meaning; every cached entry is
#: then re-derived on the next scan.
ANALYSIS_VERSION = 2

#: Prefix lengths at which a document's voice vector is also recorded, for
#: the sample-size sensitivity part of calibration.
TRUNCATION_WORDS = (300, 600, 1000)


def _truncate(text: str, words: int) -> str:
    kept: list[str] = []
    count = 0
    for paragraph in text.split("\n\n"):
        tokens = paragraph.split()
        if count + len(tokens) > words:
            kept.append(" ".join(tokens[: max(0, words - count)]))
            break
        kept.append(paragraph)
        count += len(tokens)
    return "\n\n".join(p for p in kept if p.strip())


def paragraphs_of(cleaned_text: str) -> list[str]:
    """Paragraphs as numbered for review and passage selection (0-based)."""
    return [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]


def analyze(
    *,
    text: str,
    raw: bytes,
    relative_path: str,
    suffix: str,
    mtime: float,
    aliases: list[str],
    ownership: str,
    auto_accept_pre_llm_bylined: bool = False,
    perturbations: bool = True,
) -> dict[str, Any]:
    """Derive the cached record for one extracted document."""
    filename = Path(relative_path).name
    if quality_stage.looks_sensitive(filename, text):
        return {
            "status": "sensitive_excluded",
            "analysis_version": ANALYSIS_VERSION,
            "classification": classify.Classification(
                category=classify.CONFIDENTIAL,
                category_confidence=1.0,
                quality_classification=quality_stage.SENSITIVE_CONTENT,
                quality_inclusion=quality_stage.EXCLUDE,
                quality_reason="excluded before analysis: appears to contain credentials",
            ).to_dict(),
            "proposal": classify.AuthorshipProposal(
                needs_review=False,
                reasons=["excluded before analysis: credential-shaped content"],
            ).to_dict(),
        }

    cleaned = clean_document(text)
    features = extract_features(cleaned.text, headings=len(cleaned.headings))
    quality = quality_stage.classify_document(
        filename=filename,
        raw_text=text,
        cleanup=cleaned,
        features=features,
    )
    context = context_stage.classify_context(
        path=Path(relative_path),
        text=cleaned.text,
        cleanup=cleaned,
        features=features,
    )
    naturalness = measure_naturalness(cleaned.text)
    signals = provenance.collect(
        suffix=suffix,
        raw=raw,
        text=text,
        mtime=mtime,
        aliases=aliases,
        ownership=ownership,
    )
    classification = classify.classify_category(
        quality=quality,
        context=context.context,
        context_confidence=context.confidence,
        text=cleaned.text,
        words=features.words,
        first_person_rate=features.first_person_rate,
        list_rate=features.list_rate,
        heading_rate=features.heading_rate,
        filename=filename,
    )
    proposal = classify.propose_authorship(
        classification=classification,
        provenance=signals,
        filename=filename,
        naturalness_values=naturalness.values,
        auto_accept_pre_llm_bylined=auto_accept_pre_llm_bylined,
    )

    extras = extra_features(cleaned.text)
    truncated: dict[str, dict[str, float]] = {}
    for limit in TRUNCATION_WORDS:
        if features.words > limit * 1.2:
            vector, _ = measure_text(_truncate(cleaned.text, limit))
            truncated[str(limit)] = vector

    perturbed: dict[str, dict] = {}
    if perturbations and naturalness.sufficient:
        for family, transform in PERTURBATIONS.items():
            perturbed[family] = measure_naturalness(transform(cleaned.text)).to_dict(
                include_locations=False
            )

    fingerprint = TextFingerprint.of(cleaned.text)
    return {
        "status": "extracted",
        "words": features.words,
        "prose_words": cleaned.kept_words,
        "paragraph_count": len(paragraphs_of(cleaned.text)),
        "fingerprint": fingerprint.to_dict(),
        "provenance": signals.to_dict(),
        "classification": classification.to_dict(),
        "proposal": proposal.to_dict(),
        "derived": {
            "features": features.to_dict(),
            "voice_vector": vector_from(features, extras),
            "naturalness": naturalness.to_dict(include_locations=False),
            "windows": window_metrics(cleaned.text),
            "truncated_vectors": truncated,
            "perturbed_naturalness": perturbed,
            "apparatus_removed": dict(cleaned.removed_kinds),
        },
        "analysis_version": ANALYSIS_VERSION,
    }
