"""Stage 8: hold some documents back so the profile can be checked.

A profile that was fitted to every document it is then measured against
proves nothing. So roughly a fifth of the corpus is set aside before
synthesis, never shown to the aggregation or trait stages, and used
afterwards to ask whether the profile actually describes writing it has not
seen.

The split is a function of each document's content fingerprint rather than a
shuffle. That matters for rebuilds: adding one new source must not reassign
every existing document, which would invalidate the previous validation
result and make two builds of the same corpus incomparable. A document's side
of the split is decided by its own hash and nothing else, so it stays put
forever unless its content changes.

Small contexts are not split at all. Holding one document out of three
teaches nothing and costs a third of the evidence, so a context below the
minimum contributes everything to training and is reported as unvalidated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

TRAIN = "train"
HOLDOUT = "holdout"

#: Target share of documents held back.
HOLDOUT_FRACTION = 0.20

#: A context needs at least this many documents before any are held out.
MIN_DOCUMENTS_TO_SPLIT = 5

#: Total corpus size below which nothing is held out at all: every document
#: is needed to say anything, and validation is reported as not performed.
MIN_CORPUS_TO_SPLIT = 8

_BUCKETS = 10_000


@dataclass
class SplitAssignment:
    key: str
    side: str = TRAIN
    context: str = "unknown"
    reason: str = ""


@dataclass
class SplitResult:
    assignments: dict[str, SplitAssignment] = field(default_factory=dict)
    train_keys: list[str] = field(default_factory=list)
    holdout_keys: list[str] = field(default_factory=list)
    unsplit_contexts: list[str] = field(default_factory=list)
    performed: bool = True
    reason: str = ""

    def side_of(self, key: str) -> str:
        assignment = self.assignments.get(key)
        return assignment.side if assignment else TRAIN


def split_score(fingerprint: str) -> float:
    """Map a document fingerprint to a stable value in [0, 1).

    Uses the fingerprint alone -- no corpus size, no index, no seed -- which
    is what makes the assignment survive documents being added or removed.
    """
    digest = hashlib.sha256(f"holdout:{fingerprint}".encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") % _BUCKETS) / _BUCKETS


def assign_split(
    documents: list[tuple[str, str, str]],
    *,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> SplitResult:
    """Assign each document to train or holdout.

    `documents` is a list of (key, fingerprint, context). Stratification is
    implicit: the threshold is applied within each context, so a context that
    is 20% of the corpus contributes about 20% of the holdout rather than
    being swallowed by whichever context happens to be largest.
    """
    result = SplitResult()
    if not documents:
        result.performed = False
        result.reason = "no documents to split"
        return result

    if len(documents) < MIN_CORPUS_TO_SPLIT:
        for key, _fingerprint, context in documents:
            result.assignments[key] = SplitAssignment(
                key=key, side=TRAIN, context=context,
                reason=(
                    f"corpus of {len(documents)} documents is below the "
                    f"{MIN_CORPUS_TO_SPLIT}-document minimum for a holdout split"
                ),
            )
            result.train_keys.append(key)
        result.performed = False
        result.reason = (
            f"only {len(documents)} usable documents; every one was needed for the "
            "profile, so no holdout validation was performed"
        )
        return result

    by_context: dict[str, list[tuple[str, str]]] = {}
    for key, fingerprint, context in documents:
        by_context.setdefault(context, []).append((key, fingerprint))

    for context, entries in sorted(by_context.items()):
        if len(entries) < MIN_DOCUMENTS_TO_SPLIT:
            result.unsplit_contexts.append(context)
            for key, _fingerprint in entries:
                result.assignments[key] = SplitAssignment(
                    key=key, side=TRAIN, context=context,
                    reason=(
                        f"context '{context}' has only {len(entries)} document(s); "
                        "too few to hold any back"
                    ),
                )
                result.train_keys.append(key)
            continue

        for key, fingerprint in entries:
            score = split_score(fingerprint)
            side = HOLDOUT if score >= (1.0 - holdout_fraction) else TRAIN
            result.assignments[key] = SplitAssignment(
                key=key, side=side, context=context,
                reason=f"stable hash split (score {score:.3f})",
            )
            (result.holdout_keys if side == HOLDOUT else result.train_keys).append(key)

    # A split that held everything back, or nothing, is not a usable split.
    if not result.holdout_keys:
        result.performed = False
        result.reason = (
            "the stable hash split placed no document in the holdout; validation "
            "was not performed"
        )
    elif not result.train_keys:
        for key in result.holdout_keys:
            result.assignments[key].side = TRAIN
            result.assignments[key].reason = "restored to training: holdout claimed every document"
        result.train_keys = result.holdout_keys
        result.holdout_keys = []
        result.performed = False
        result.reason = "the split left no training documents; holdout was returned to training"

    result.train_keys.sort()
    result.holdout_keys.sort()
    return result
