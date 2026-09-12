"""Constraint-aware writing pass for HowlWriter.

This package extracts explicit output constraints from assignments and
configuration, then enforces them through a model-backed pass that
prioritizes user constraints over optional elaboration.
"""

from howlwriter.constraints.enforcer import ConstraintEnforcer, ConstraintEnforcementResult
from howlwriter.constraints.length import estimate_pages, words_for_pages
from howlwriter.constraints.specs import ConstraintSet
from howlwriter.constraints.validators import (
    RedundancyDetector,
    RedundancyFinding,
    SequenceFinding,
    SequenceValidator,
    SpecificityFinding,
    UnsupportedSpecificityValidator,
)

__all__ = [
    "ConstraintEnforcer",
    "ConstraintEnforcementResult",
    "ConstraintSet",
    "RedundancyDetector",
    "RedundancyFinding",
    "SequenceValidator",
    "SequenceFinding",
    "UnsupportedSpecificityValidator",
    "SpecificityFinding",
    "estimate_pages",
    "extract_constraints",
    "words_for_pages",
]
