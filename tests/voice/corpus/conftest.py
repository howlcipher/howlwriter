"""Shared fixtures for the voice-corpus tests.

Everything here builds synthetic documents. No test reads a real corpus, and
no fixture is derived from anyone's actual writing -- the sample prose below
was written for these tests.
"""

from __future__ import annotations

from pathlib import Path
import random
import zipfile

import pytest

_DOCX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(path: Path, blocks: list[tuple[str, str]]) -> Path:
    """Write a minimal but real .docx.

    `blocks` is a list of (kind, text) where kind is "p", "h1".."h6", or "li".
    Building the archive directly keeps the tests dependency-free and exercises
    exactly the parts of the format the stdlib extractor reads.
    """
    paragraphs = []
    for kind, text in blocks:
        escaped = (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        if kind.startswith("h"):
            props = f'<w:pPr><w:pStyle w:val="Heading{kind[1]}"/></w:pPr>'
        elif kind == "li":
            props = "<w:pPr><w:numPr><w:ilvl w:val=\"0\"/></w:numPr></w:pPr>"
        else:
            props = ""
        paragraphs.append(f"<w:p>{props}<w:r><w:t>{escaped}</w:t></w:r></w:p>")

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}"><w:body>{"".join(paragraphs)}</w:body></w:document>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
    return path


def make_odt(path: Path, paragraphs: list[str]) -> Path:
    text_ns = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    office_ns = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    body = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content xmlns:office="{office_ns}" xmlns:text="{text_ns}">'
        f"<office:body><office:text>{body}</office:text></office:body>"
        "</office:document-content>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", content)
    return path


def synthetic_prose(seed: int, paragraphs: int = 6, topic: str = "systems") -> str:
    """Generate varied synthetic prose with a stable shape for a given seed.

    Varied on purpose: a corpus of identical documents would make the
    deduplication and diversity tests pass for the wrong reason.
    """
    rng = random.Random(seed)
    # Deliberately neutral vocabulary. Words that appear in the context
    # classifier's marker lists (deployment, stakeholder, the literature, ...)
    # would make otherwise-contextless filler classify as professional or
    # academic, and a fixture must not smuggle in the signal under test.
    vocabulary = [
        "meadow", "lantern", "gravel", "harbour", "thicket", "kettle",
        "ribbon", "orchard", "pebble", "willow", "cinder", "marsh",
        "bramble", "quarry", "hollow", "drizzle", "furrow", "brindle",
        "sable", "tallow",
    ]
    # Sentence openings vary too. A fixture where every sentence began the
    # same way looked converged to the diversity checker -- correctly, which
    # made it useless as a "normal writing" baseline.
    openers = [
        "The", "A", "Every", "Each", "Some", "Most", "One", "Another",
        "This", "That", "Several", "Many", "Few", "Any", "Both",
    ]
    out: list[str] = []
    for _ in range(paragraphs):
        sentences = []
        for _ in range(rng.randint(3, 6)):
            length = rng.randint(7, 24)
            words = [rng.choice(vocabulary) for _ in range(length)]
            sentences.append(f"{rng.choice(openers)} {topic} {' '.join(words)}.")
        out.append(" ".join(sentences))
    return "\n\n".join(out)


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    return root


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    root = tmp_path / "voices"
    root.mkdir()
    return root


@pytest.fixture
def build_corpus(corpus_dir: Path):
    """Write N varied synthetic markdown documents into the corpus."""

    def _build(count: int = 14, prefix: str = "doc", paragraphs: int = 6) -> Path:
        for index in range(count):
            (corpus_dir / f"{prefix}{index:02d}.md").write_text(
                f"# Note {index}\n\n{synthetic_prose(index, paragraphs)}\n",
                encoding="utf-8",
            )
        return corpus_dir

    return _build
