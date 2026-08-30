"""Citation style registry.

Only APA7 has a real implementation for v1, matching the spec's "start with
APA 7 (future: MLA, Chicago, IEEE, Harvard)" instruction. The other names
are reserved so callers can refer to them without guessing a string; asking
for one raises NotImplementedError rather than silently falling back to
APA7 or fabricating a different format.
"""

from __future__ import annotations

import enum


class CitationStyle(enum.Enum):
    APA7 = "apa7"
    MLA = "mla"
    CHICAGO = "chicago"
    IEEE = "ieee"
    HARVARD = "harvard"


def get_formatter(style: CitationStyle):
    if style is CitationStyle.APA7:
        from howlwriter.citations.apa7 import APA7Formatter

        return APA7Formatter()
    raise NotImplementedError(
        f"citation style {style.value!r} is reserved but not implemented yet; only APA7 is available."
    )
