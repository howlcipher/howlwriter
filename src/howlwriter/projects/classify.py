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
#: Code and configuration: read as text lines, never executed.
CODE_SUFFIXES = {
    ".rules",
    ".conf",
    ".cfg",
    ".ini",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
    ".bash",
    ".py",
    ".ps1",
    ".bat",
    ".cmd",
    ".diff",
    ".patch",
    ".sql",
    ".rb",
    ".js",
    ".ts",
    ".go",
    ".c",
    ".h",
    ".rs",
    ".java",
}
SUBTITLE_SUFFIXES = {".srt", ".vtt"}
#: Key, certificate, and credential-store formats. Inventoried, never read.
SECRET_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".kdbx",
    ".ppk",
    ".gpg",
    ".asc",
    ".crt",
    ".der",
}
SECRET_NAMES = re.compile(r"^(id_rsa|id_dsa|id_ecdsa|id_ed25519)(\.pub)?$|^\.?env$|credentials?", re.I)
_EVIDENCE_OR_OUTPUT_DIR = re.compile(
    r"(^|/)(evidence|screenshots?|captures?|pcaps?|results?|logs?|rules|output|outputs|turn ?in|"
    r"submission|final)(/|$)",
    re.I,
)

#: Bump when classification rules change; existing records are reclassified from stored text.
CLASSIFIER_VERSION = 3
_FRAME_DIR = re.compile(r"(^|/)(video[ _-]?frames|frames|keyframes|thumbnails?)(/|$)", re.I)
_RENDERED_DIR = re.compile(
    r"(^|/)(rendered[^/]*|renders?|pdf[ _-]?pages|page[ _-]?images|previews?)(/|$)", re.I
)
_RENDERED_NAME = re.compile(r"(^|[-_ .])(page|pg)[ _-]?\d{1,4}\.(png|jpe?g|webp)$", re.I)
#: ffmpeg-style frame dumps: overview-0001.png, clip_000123.jpg
_FRAME_NAME = re.compile(r"^.+[-_]\d{4,6}\.(png|jpe?g|webp)$", re.I)
_WORKING_DIR = re.compile(r"(^|/)(work|working|tmp|temp|scratch|build|output|outputs)(/|$)", re.I)
_PAGE_OF = re.compile(r"\bPage\s*\d{1,4}\s*of\s*\d{1,4}\b", re.I)

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
        if _FRAME_DIR.search(folder) or _FRAME_NAME.search(name):
            return m.MULTIMEDIA, "a frame extracted from a video, not an observation"
        if _RENDERED_DIR.search(folder) or _RENDERED_NAME.search(name) or _PAGE_OF.search(text_sample[:4000]):
            return m.OUTPUT_DOCUMENT, "a rendered page of a document, not an observation"
        return m.SCREENSHOT, "image format"
    if suffix in VIDEO_SUFFIXES or suffix in AUDIO_SUFFIXES:
        return m.MULTIMEDIA, "audio or video format"
    if suffix in SECRET_SUFFIXES or SECRET_NAMES.search(name):
        return m.UNKNOWN, "key, certificate, or credential material; never read"
    if suffix in DATA_SUFFIXES:
        if _EVIDENCE_DIR.search(folder) or not _WORKING_DIR.search(folder):
            return m.EXPERIMENTAL, "structured data or log output"
        return m.OUTPUT_DOCUMENT, "a generated working file, not captured evidence"
    if suffix in SUBTITLE_SUFFIXES:
        return m.MULTIMEDIA, "subtitles (a timed transcript)"
    if suffix in CODE_SUFFIXES:
        # Rules, scripts and configs are work products or supplied tooling, never observations.
        if _EVIDENCE_OR_OUTPUT_DIR.search(folder) or _WORKING_DIR.search(folder):
            return m.OUTPUT_DOCUMENT, "code or configuration produced in the work (rules, scripts, configs)"
        return m.REFERENCE, "code or configuration supplied with the materials"
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
