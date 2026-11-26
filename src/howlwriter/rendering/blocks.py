"""Block boundaries shared by the document renderers."""

from collections.abc import Iterator
import re

_FENCE = re.compile(r" {0,3}(`{3,})([^`]*)")


def _closes_fence(line: str, width: int) -> bool:
    marker = _FENCE.fullmatch(line)
    return bool(marker and len(marker[1]) >= width and not marker[2].strip())


def is_fenced_code(lines: list[str]) -> bool:
    """Recognize a complete backtick fence, including longer closing markers."""
    opener = _FENCE.fullmatch(lines[0])
    return bool(len(lines) > 1 and opener and _closes_fence(lines[-1], len(opener[1])))


def markdown_blocks(text: str, *, max_heading_level: int) -> Iterator[str]:
    """Separate headings and page breaks while keeping fenced blocks intact."""
    heading = re.compile(rf"^#{{1,{max_heading_level}}} ")
    current: list[str] = []
    fence_width = 0
    for line in text.splitlines():
        if fence_width:
            current.append(line)
            if _closes_fence(line, fence_width):
                yield "\n".join(current)
                current = []
                fence_width = 0
        elif opener := _FENCE.fullmatch(line):
            if current:
                yield "\n".join(current)
            current = [line]
            fence_width = len(opener[1])
        elif not line.strip() or line.strip() == "<!-- pagebreak -->" or heading.match(line.strip()):
            if current:
                yield "\n".join(current)
                current = []
            if line.strip():
                yield line
        else:
            current.append(line)
    if current:
        yield "\n".join(current)
