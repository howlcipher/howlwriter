"""Provenance signals: what a document's own metadata says about its origin.

None of these decides authorship. They are evidence, recorded with the
document, shown to the person reviewing it, and used to order the review
queue. The cases they help with are real ones found on a real drive:

* `dc:creator` in a Word file is often the instructor whose template the
  student opened, not the student. It is reported as "file created by
  another account", never as "written by someone else".
* Google Docs exports carry no creator or editing-time metadata at all, so
  absence of metadata is recorded as absence, not as a signal either way.
* `TotalTime` (minutes of editing recorded by Word) far below what typing the
  text would take means the text arrived mostly by paste. That is common
  for legitimate reasons and is reported as exactly that.
* A file produced by a document-generation library (python-docx, ReportLab,
  pandoc) was assembled by a program. Whose words the program assembled is
  a question only the person can answer.
* A modification date before public LLM availability (30 November 2022)
  makes substantial generation by those tools implausible. It says nothing
  about who wrote the document, and it is the only date-based signal used.

Metadata is read from bytes already in memory, through the same bounded
archive reader the extractors use. Nothing is executed and nothing is written.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import io
import re
import xml.etree.ElementTree as ET
import zipfile

from howlwriter.voice.corpus.extract import ArchiveLimitError, read_archive_member

#: Public release of ChatGPT. Documents last modified before this predate
#: broadly available LLM drafting tools.
LLM_ERA_START = datetime(2022, 11, 30, tzinfo=timezone.utc)

_GENERATOR_LIBRARIES = re.compile(
    r"python-docx|docx4j|openpyxl|reportlab|pandoc|wkhtmltopdf|weasyprint|"
    r"fpdf|pdfkit|phpword|aspose|docxtemplater|officegen",
    re.IGNORECASE,
)

_BYLINE_FIELD = re.compile(
    r"(?:^|\n)\s*(?i:name|student(?: name)?|author|by|submitted by|prepared by|written by)"
    r"\s*[:\-–]?\s*([A-Z][a-z]+(?:[ \t]+[A-Z][a-z.'’-]+){1,2})",
)


@dataclass
class ProvenanceSignals:
    """Metadata facts about one file. No document content."""

    creator_account: str = ""
    last_modified_by: str = ""
    application: str = ""
    producer: str = ""
    created: str = ""
    modified: str = ""
    revision: int | None = None
    edit_minutes: int | None = None
    template: str = ""
    generated_by_library: bool = False
    predates_llm_era: bool | None = None
    byline_identity: bool = False
    byline_other_person: bool = False
    ownership: str = "owned"
    metadata_available: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProvenanceSignals":
        data = data or {}
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


def _text(root: ET.Element, suffix: str) -> str:
    for node in root.iter():
        if node.tag.endswith(suffix) and node.text:
            return node.text.strip()
    return ""


def _office_metadata(raw: bytes, signals: ProvenanceSignals) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(archive.namelist())
            core = (
                read_archive_member(archive, "docProps/core.xml")
                if "docProps/core.xml" in names
                else b""
            )
            app = (
                read_archive_member(archive, "docProps/app.xml")
                if "docProps/app.xml" in names
                else b""
            )
            meta = read_archive_member(archive, "meta.xml") if "meta.xml" in names else b""
    except (zipfile.BadZipFile, KeyError, ArchiveLimitError, OSError):
        return
    try:
        if core:
            root = ET.fromstring(core)
            signals.creator_account = _text(root, "}creator")[:80]
            signals.last_modified_by = _text(root, "}lastModifiedBy")[:80]
            signals.created = _text(root, "}created")[:32]
            signals.modified = _text(root, "}modified")[:32]
            revision = _text(root, "}revision")
            signals.revision = int(revision) if revision.isdigit() else None
            signals.metadata_available = True
        if app:
            root = ET.fromstring(app)
            signals.application = _text(root, "}Application")[:80]
            total = _text(root, "}TotalTime")
            signals.edit_minutes = int(total) if total.isdigit() else None
            signals.template = _text(root, "}Template")[:80]
            signals.metadata_available = True
        if meta:
            root = ET.fromstring(meta)
            signals.application = _text(root, "}generator")[:80] or signals.application
            signals.creator_account = (
                _text(root, "}initial-creator")[:80] or signals.creator_account
            )
            signals.created = _text(root, "}creation-date")[:32] or signals.created
            cycles = _text(root, "}editing-cycles")
            signals.revision = int(cycles) if cycles.isdigit() else signals.revision
            signals.metadata_available = True
    except ET.ParseError:
        signals.notes.append("document metadata part was not well-formed XML")


def _pdf_metadata(raw: bytes, signals: ProvenanceSignals) -> None:
    try:
        import pypdf
    except ImportError:
        return
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        info = reader.metadata or {}
        signals.producer = str(info.get("/Producer", "") or "")[:80]
        signals.application = str(info.get("/Creator", "") or "")[:80]
        signals.creator_account = str(info.get("/Author", "") or "")[:80]
        signals.created = str(info.get("/CreationDate", "") or "")[:32]
        signals.modified = str(info.get("/ModDate", "") or "")[:32]
        signals.metadata_available = bool(info)
    except Exception:
        return


def _parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith("D:"):
        digits = re.sub(r"[^0-9]", "", value[2:])[:14]
        try:
            return datetime.strptime(digits.ljust(14, "0"), "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def collect(
    *,
    suffix: str,
    raw: bytes,
    text: str,
    mtime: float,
    aliases: list[str],
    ownership: str = "owned",
) -> ProvenanceSignals:
    """Gather provenance signals for one extracted document."""
    signals = ProvenanceSignals(ownership=ownership)
    if suffix in (".docx", ".odt"):
        _office_metadata(raw, signals)
    elif suffix == ".pdf":
        _pdf_metadata(raw, signals)

    tooling = " ".join((signals.application, signals.producer, signals.creator_account))
    signals.generated_by_library = bool(_GENERATOR_LIBRARIES.search(tooling))

    # The latest date the file itself reports, or the filesystem's.
    dates = [d for d in (_parse_date(signals.modified), _parse_date(signals.created)) if d]
    try:
        dates.append(datetime.fromtimestamp(mtime, tz=timezone.utc))
    except (OverflowError, OSError, ValueError):
        pass
    if dates:
        signals.predates_llm_era = max(dates) < LLM_ERA_START

    head = text[:1500]
    lowered = head.lower()
    alias_hit = any(alias.lower() in lowered for alias in aliases if alias.strip())
    signals.byline_identity = alias_hit
    alias_tokens = {t.lower() for alias in aliases for t in alias.replace(",", " ").split()}
    for match in _BYLINE_FIELD.finditer(head):
        named = {t.lower().strip(".") for t in match.group(1).split()}
        if not named & alias_tokens:
            signals.byline_other_person = True
            break

    if signals.creator_account and aliases:
        creator_tokens = {t.lower() for t in re.split(r"[\s,]+", signals.creator_account) if t}
        if not creator_tokens & alias_tokens:
            signals.notes.append(
                "file was created by another account (often a template owner); "
                "this is not evidence about who wrote the text"
            )
    if signals.edit_minutes is not None and signals.edit_minutes >= 0:
        words = len(text.split())
        if words >= 400 and signals.edit_minutes < max(3, words // 120):
            signals.notes.append(
                f"recorded editing time ({signals.edit_minutes} min) is far below typing time "
                "for its length; most text arrived by paste or import"
            )
    if signals.generated_by_library:
        signals.notes.append("file was produced by a document-generation library")
    if not signals.metadata_available and suffix in (".docx", ".odt", ".pdf"):
        signals.notes.append("no authoring metadata (typical of Google Docs exports)")
    return signals
