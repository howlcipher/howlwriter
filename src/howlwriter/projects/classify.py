"""What role each project file plays.

Content decides where there is content; the file name is a weak hint, used
mostly for formats without text (an image named "scoring matrix" is a rubric
image). A user correction always wins and is never overwritten by a rescan.

The categories that matter most are kept strictly apart: instructions and
rubrics say what must be produced; references explain; experimental
evidence, screenshots and packet captures record what was observed; drafts
and output documents are the user's own work in progress.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from howlwriter.projects import models as m

PCAP_SUFFIXES = {".pcap", ".pcapng", ".cap"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".odt", ".rtf", ".txt", ".md", ".markdown", ".html", ".htm"}
DATA_SUFFIXES = {".csv", ".tsv", ".log", ".json", ".eve", ".jsonl"}

_RUBRIC_NAME = re.compile(r"rubric|scoring|grading|criteria|matrix", re.I)
_INSTRUCTION_NAME = re.compile(r"instruction|assignment|lab\s*\d|task|prompt|guide|overview", re.I)
_DRAFT_NAME = re.compile(r"draft|notes|working", re.I)
_OUTPUT_DIR = re.compile(r"(^|/)(output|outputs|turn ?in|submission|final|deliverables?)(/|$)", re.I)
_EVIDENCE_DIR = re.compile(r"(^|/)(evidence|screenshots?|captures?|pcaps?|results?|logs?)(/|$)", re.I)

_INSTRUCTION_TEXT = re.compile(
    r"\byou will\b|\byou must\b|\bsubmit\b|\bdeliverables?\b|\bin this lab\b|\byour task\b|"
    r"\bcomplete the following\b|\bdue (?:date|by)\b|\bstudents? (?:will|should|must)\b|"
    r"\binclude (?:a|the|your)\b|\btake a screenshot\b|\bscreen ?capture\b",
    re.I,
)
_RUBRIC_TEXT = re.compile(
    r"\bpoints?\b|\bcriteria\b|\brubric\b|\bexemplary\b|\bproficient\b|\bdeveloping\b|"
    r"\bexceeds expectations\b|\bmeets expectations\b|\bscor(?:e|ing)\b",
    re.I,
)


def classify(relative_path: str, suffix: str, text_sample: str = "") -> tuple[str, str]:
    """(category, reason) for one file."""
    name = PurePosixPath(relative_path).name
    folder = str(PurePosixPath(relative_path).parent)
    if suffix in PCAP_SUFFIXES:
        return m.PACKET_CAPTURE, "packet capture format"
    if suffix in IMAGE_SUFFIXES:
        if _RUBRIC_NAME.search(name):
            return m.RUBRIC, "image whose name marks it as a rubric or scoring matrix"
        return m.SCREENSHOT, "image format"
    if suffix in VIDEO_SUFFIXES or suffix in AUDIO_SUFFIXES:
        return m.MULTIMEDIA, "audio or video format"
    if suffix in DATA_SUFFIXES:
        return m.EXPERIMENTAL, "structured data or log output"
    if suffix not in DOCUMENT_SUFFIXES:
        return m.UNKNOWN, f"no adapter for {suffix or 'extensionless files'}"

    sample = text_sample[:12000]
    instruction_hits = len(_INSTRUCTION_TEXT.findall(sample))
    rubric_hits = len(_RUBRIC_TEXT.findall(sample))
    if _OUTPUT_DIR.search(folder) and not instruction_hits >= 6:
        return m.OUTPUT_DOCUMENT, "in an output or submission folder"
    if _DRAFT_NAME.search(name):
        return m.USER_DRAFT, "named as a draft or working notes"
    if rubric_hits >= 6 and rubric_hits >= instruction_hits:
        return m.RUBRIC, f"rubric vocabulary ({rubric_hits} markers)"
    if instruction_hits >= 3:
        return m.INSTRUCTIONS, f"instruction vocabulary ({instruction_hits} markers)"
    if _RUBRIC_NAME.search(name):
        return m.RUBRIC, "named as a rubric"
    if _INSTRUCTION_NAME.search(name) and instruction_hits:
        return m.INSTRUCTIONS, "named as instructions, with some instruction vocabulary"
    if _EVIDENCE_DIR.search(folder):
        return m.EXPERIMENTAL, "in an evidence or results folder"
    if not sample.strip():
        return m.UNKNOWN, "no text could be read"
    return m.REFERENCE, "explanatory document with no instruction or rubric vocabulary"
