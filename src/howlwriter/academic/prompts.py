"""Shared prompt guidance reused across academic WRITER/reviewer roles.

A single constant rather than per-role duplicated text, since draft_paper,
correct_length, and the consistency reviewer all need the same priority
ordering. See academic/writer.py and academic/consistency.py for call sites.
"""

from __future__ import annotations

ACADEMIC_PRIORITY_ORDERING_GUIDANCE = """\
PRIORITY ORDERING (highest to lowest -- when these are in tension, the higher one wins):
1. Explicit user/assignment constraints (length limits, page targets, scope
   instructions) outrank optional detail or thoroughness.
2. Satisfy each required criterion once, clearly. Do not repeat the same
   evidence across a table and multiple paragraphs, and do not add further
   examples once a requirement is already demonstrated.
3. Prefer a concise, grounded, generalized statement over an impressive-
   looking but unverifiable exact figure or identifier. If a precise number,
   code, or name is not grounded in the supplied source material, generalize
   it rather than inventing a plausible-looking exact value.
4. Validate that any staged, sequential, or procedural content is causally
   consistent -- a step must not use a capability the actor has not yet
   acquired, and labels/headings must accurately describe what the section
   actually contains.
5. A shorter artifact that fully and cleanly satisfies the task is superior
   to a longer one padded with redundant elaboration."""
