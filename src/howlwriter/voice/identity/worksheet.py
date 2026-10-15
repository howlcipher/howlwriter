"""Separating a student's answers from a publisher's lab worksheet.

Publisher lab manuals (the "(4e)" virtual-lab reports found on a real drive)
are mostly not the student's writing: every page repeats a running header,
numbered prompts carry the publisher's instructions, and section labels and
page markers fill the rest. Measured on nine real worksheets, the student's
own answer lines were between 4% and 48% of the extracted words. Treating
the whole file as the student's prose -- what the legacy profiles did --
trains on the publisher.

The segmenter works on extracted lines, deterministically:

* a line that repeats within the document is a running header or footer;
* a numbered line (``10. Make a screen capture...``) starts a prompt, and the
  prompt continues over following lines until one ends in ``.``, ``?`` or
  ``:``;
* section labels (``Part 2``, ``Section 1:``, ``Page 3``) and lines of three
  words or fewer are structure;
* everything else is a candidate answer line.

What it does not do is decide authorship. The answer text is a PROPOSAL shown
to the person in review; only an attestation (``MIXED_AUTHORSHIP`` with the
``worksheet_answers`` extraction) lets it into a profile, and only the answer
lines are used. When the separation is unconvincing (too few prompts, or
answers that are almost the whole document) the document is not treated as a
worksheet at all.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import re

_PROMPT = re.compile(r"^\s*\d{1,2}[.)]\s+\S")
_STRUCTURE = re.compile(
    r"^\s*(?:part|section|page|lab report|challenge(?: and analysis)?|figure|table|"
    r"step|deliverables?|hands-on demonstration|student lab)\b",
    re.IGNORECASE,
)
_TERMINAL = (".", "?", ":", "!")

#: A document is treated as a template worksheet only when the structure is
#: unmistakable: several numbered prompts, and a running header (one or more
#: lines) repeated on at least three pages. Measured worksheets carry a
#: two-line header (lab title, then student/course line) on every page.
MIN_PROMPTS = 5
MIN_HEADER_REPEATS = 3
MIN_HEADER_OCCURRENCES = 6
#: If "answers" are most of the document, the template detection is wrong.
MAX_ANSWER_SHARE = 0.65
#: Answer lines this short are captions or labels, not prose.
MIN_ANSWER_LINE_WORDS = 4


@dataclass
class WorksheetSegmentation:
    is_worksheet: bool = False
    total_words: int = 0
    answer_words: int = 0
    prompt_lines: int = 0
    header_lines: int = 0
    answer_lines: int = 0

    @property
    def answer_share(self) -> float:
        return self.answer_words / self.total_words if self.total_words else 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["answer_share"] = round(self.answer_share, 3)
        return data


def _classify(text: str) -> tuple[list[tuple[str, str]], int]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    repeats = Counter(lines)
    labelled: list[tuple[str, str]] = []
    in_prompt = False
    for line in lines:
        words = len(line.split())
        if repeats[line] > 1:
            kind = "header"
        elif _PROMPT.match(line):
            kind = "prompt"
            in_prompt = not line.rstrip().endswith(_TERMINAL)
        elif in_prompt:
            kind = "prompt"
            in_prompt = not line.rstrip().endswith(_TERMINAL)
        elif _STRUCTURE.match(line) or words < MIN_ANSWER_LINE_WORDS:
            kind = "structure"
        else:
            kind = "answer"
        labelled.append((kind, line))
    most_repeated = max(repeats.values(), default=0)
    return labelled, most_repeated


def segment(text: str) -> WorksheetSegmentation:
    """Measure a document as a possible template worksheet. Numbers only."""
    labelled, most_repeated = _classify(text)
    result = WorksheetSegmentation()
    for kind, line in labelled:
        words = len(line.split())
        result.total_words += words
        if kind == "answer":
            result.answer_words += words
            result.answer_lines += 1
        elif kind == "prompt":
            if _PROMPT.match(line):
                result.prompt_lines += 1
        elif kind == "header":
            result.header_lines += 1
    result.is_worksheet = (
        result.prompt_lines >= MIN_PROMPTS
        and most_repeated >= MIN_HEADER_REPEATS
        and result.header_lines >= MIN_HEADER_OCCURRENCES
        and result.answer_share <= MAX_ANSWER_SHARE
    )
    return result


def extract_answers(text: str) -> str:
    """The candidate answer text of a worksheet, as paragraphs.

    Consecutive answer lines are joined into one paragraph; any prompt,
    header, or structure line ends the paragraph. Returns an empty string for
    a document that is not a worksheet, so a mis-applied extraction can never
    pass a whole document through.
    """
    if not segment(text).is_worksheet:
        return ""
    labelled, _ = _classify(text)
    paragraphs: list[str] = []
    current: list[str] = []
    for kind, line in labelled:
        if kind == "answer":
            current.append(line)
            continue
        if current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


#: Extractions an attestation may name. Each maps raw extracted text to the
#: authored text that may enter a profile.
EXTRACTIONS = {"worksheet_answers": extract_answers}
