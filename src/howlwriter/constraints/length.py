"""Page-length approximation helpers for constraint planning.

Exact rendered pagination depends on font, margins, tables, and figures.
For APA-style 12-point double-spaced academic prose a rough estimate of
250–300 words per page is reasonable. This module uses 275 as the default
planning value but treats the result as guidance, not a guarantee.
"""

from __future__ import annotations

DEFAULT_WORDS_PER_PAGE = 275
TABLE_PAGE_MULTIPLIER = 1.2


def estimate_pages(
    word_count: int,
    has_tables: bool = False,
    words_per_page: int = DEFAULT_WORDS_PER_PAGE,
) -> float:
    """Return an approximate page count for a given body word count."""
    if words_per_page <= 0:
        return 0.0
    pages = word_count / words_per_page
    if has_tables:
        pages *= TABLE_PAGE_MULTIPLIER
    return pages


def words_for_pages(pages: int, words_per_page: int = DEFAULT_WORDS_PER_PAGE) -> int:
    """Return an approximate word count for a given page target."""
    return pages * words_per_page
