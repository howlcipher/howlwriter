"""The private, per-identity ledger.

    ~/.howlwriter/identities/<identity>/
        identity.yaml          configuration: sources, exclusions, profiles
        inventory.json         every file seen, with derived measurements
        decisions.json         authorship attestations (the user's, never regenerated)
        decisions.log.jsonl    append-only history of every decision change
        review_queue.yaml      generated worksheet of documents awaiting review
        scan_report.json       counts from the last scan (no titles)
        profile_changes.jsonl  what each profile build changed
        chat_evidence.json     optional informal-communication evidence
        calibration/           naturalness calibration per context

The inventory names files (relative paths) because incremental rescans and
review need to, and because this directory is local private data with
owner-only permissions. It holds no document text: extracted prose is
measured in memory and discarded.

Decisions are keyed by a stable document id, not by path. A renamed file
keeps its id (the scanner matches it by content fingerprint), so an
attestation follows the document rather than its old location.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

import yaml

from howlwriter.voice.identity import privacy
from howlwriter.voice.identity.classify import AUTHORSHIP_STATES
from howlwriter.voice.identity.exclusions import WILLIAM_REQUIRED_EXCLUSIONS, ExclusionPolicy

CONFIG_FILE = "identity.yaml"
INVENTORY_FILE = "inventory.json"
DECISIONS_FILE = "decisions.json"
DECISION_LOG_FILE = "decisions.log.jsonl"
REVIEW_QUEUE_FILE = "review_queue.yaml"
SCAN_REPORT_FILE = "scan_report.json"
PROFILE_CHANGES_FILE = "profile_changes.jsonl"
CHAT_EVIDENCE_FILE = "chat_evidence.json"
CALIBRATION_DIR = "calibration"

INVENTORY_VERSION = 1

_VALID_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


_ROOT_INDEX = re.compile(r"^(\d{1,3}):")


def source_path_of(entry_or_relative) -> str:
    """The path of a document relative to its own source root.

    Inventory keys carry an ``N:`` prefix only when an identity has several
    source roots. Splitting on the first colon (the earlier idiom) mangled
    real file names containing one -- "Lab: B7" became " B7" -- so the
    scanner now records the source-relative path explicitly, and this falls
    back to stripping only a numeric prefix for entries written before that.
    """
    if isinstance(entry_or_relative, dict):
        if entry_or_relative.get("source_path"):
            return entry_or_relative["source_path"]
        entry_or_relative = entry_or_relative.get("relative_path", "")
    return _ROOT_INDEX.sub("", str(entry_or_relative), count=1)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_identity(name: str) -> str:
    normalized = (name or "").strip().lower()
    if not _VALID_IDENTITY.match(normalized):
        raise ValueError(
            f"invalid identity {name!r}: use lowercase letters, digits, hyphens and "
            "underscores (max 48 characters)"
        )
    return normalized


@dataclass
class ProfileSpec:
    """One context profile of an identity."""

    voice: str
    context: str
    categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _default_profiles(identity: str) -> dict[str, ProfileSpec]:
    return {
        "academic": ProfileSpec(
            voice=f"{identity}-academic",
            context="academic",
            categories=[
                "academic_paper",
                "academic_discussion",
                "academic_lab",
                "research_analysis",
            ],
        ),
        "professional": ProfileSpec(
            voice=f"{identity}-professional",
            context="professional",
            categories=[
                "technical_documentation",
                "professional_engineering_document",
                "professional_article",
                "linkedin_or_public_commentary",
            ],
        ),
    }


@dataclass
class IdentityConfig:
    identity: str
    display_name: str = ""
    aliases: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    exclusions: ExclusionPolicy = field(default_factory=ExclusionPolicy)
    profiles: dict[str, ProfileSpec] = field(default_factory=dict)
    chat_sources: list[str] = field(default_factory=list)
    auto_accept_pre_llm_bylined: bool = False
    #: Directory components under a source root that mean "owned by another
    #: account" for this provider. Recorded as provenance, not as exclusion.
    shared_with_me_dirs: list[str] = field(default_factory=lambda: ["shared with me"])
    max_workers: int = 4

    def to_dict(self) -> dict:
        return {
            "identity": self.identity,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "sources": list(self.sources),
            "exclusions": self.exclusions.to_dict(),
            "profiles": {k: v.to_dict() for k, v in self.profiles.items()},
            "chat_sources": list(self.chat_sources),
            "auto_accept_pre_llm_bylined": self.auto_accept_pre_llm_bylined,
            "shared_with_me_dirs": list(self.shared_with_me_dirs),
            "max_workers": self.max_workers,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IdentityConfig":
        identity = validate_identity(str(data.get("identity", "")))
        profiles_raw = data.get("profiles") or {}
        profiles = {
            str(key): ProfileSpec(
                voice=str(value.get("voice", f"{identity}-{key}")),
                context=str(value.get("context", key)),
                categories=[str(c) for c in value.get("categories", []) or []],
            )
            for key, value in profiles_raw.items()
        } or _default_profiles(identity)
        return cls(
            identity=identity,
            display_name=str(data.get("display_name", "")),
            aliases=[str(a) for a in data.get("aliases", []) or []],
            sources=[str(s) for s in data.get("sources", []) or []],
            exclusions=ExclusionPolicy.from_dict(data.get("exclusions")),
            profiles=profiles,
            chat_sources=[str(s) for s in data.get("chat_sources", []) or []],
            auto_accept_pre_llm_bylined=bool(data.get("auto_accept_pre_llm_bylined", False)),
            shared_with_me_dirs=[
                str(s) for s in data.get("shared_with_me_dirs", ["shared with me"]) or []
            ],
            max_workers=max(1, min(16, int(data.get("max_workers", 4) or 4))),
        )

    @classmethod
    def default(cls, identity: str) -> "IdentityConfig":
        identity = validate_identity(identity)
        config = cls(identity=identity, profiles=_default_profiles(identity))
        if identity == "william":
            # The person this identity was first configured for asked for
            # exactly these three directories never to be traversed, and gave
            # his name for byline detection. Another identity starts empty.
            config.display_name = "William Elias"
            config.aliases = ["William Elias", "Elias, William", "W. Elias", "Will Elias"]
            config.exclusions = ExclusionPolicy(required=WILLIAM_REQUIRED_EXCLUSIONS)
        return config


@dataclass
class Decision:
    """A person's attestation about one document. Survives every rescan."""

    doc_id: str
    authorship: str
    path: str = ""
    category: str = ""
    context: str = ""
    include_paragraphs: str = ""
    #: A named extraction (worksheet.EXTRACTIONS) isolating the attested text.
    extraction: str = ""
    note: str = ""
    decided_at: str = ""
    source: str = "user_attestation"
    content_hash: str = ""
    simhash: str = ""
    words: int = 0
    status: str = "active"  # active | carried_forward | reopened
    status_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Decision":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})

    @property
    def effective(self) -> bool:
        return self.status in ("active", "carried_forward")


def parse_paragraph_ranges(spec: str) -> set[int]:
    """'1-3,7' -> {0,1,2,6}. User-facing numbering is 1-based."""
    chosen: set[int] = set()
    for part in (spec or "").replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start, _, end = part.partition("-")
            if start.isdigit() and end.isdigit() and int(start) >= 1 and int(end) >= int(start):
                chosen.update(range(int(start) - 1, int(end)))
            else:
                raise ValueError(f"invalid paragraph range {part!r}")
        elif part.isdigit() and int(part) >= 1:
            chosen.add(int(part) - 1)
        else:
            raise ValueError(f"invalid paragraph number {part!r}")
    return chosen


class IdentityStore:
    """Read and write one identity's private ledger."""

    def __init__(self, identity: str, root: Path | None = None) -> None:
        self.identity = validate_identity(identity)
        self.root = Path(root) if root is not None else privacy.identities_root()
        self.directory = self.root / self.identity

    def exists(self) -> bool:
        return (self.directory / CONFIG_FILE).is_file()

    def ensure(self) -> Path:
        privacy.ensure_private_dir(self.root)
        return privacy.ensure_private_dir(self.directory)

    @classmethod
    def list_identities(cls, root: Path | None = None) -> list[str]:
        base = Path(root) if root is not None else privacy.identities_root()
        if not base.is_dir():
            return []
        return sorted(e.name for e in base.iterdir() if (e / CONFIG_FILE).is_file())

    # --- config -------------------------------------------------------

    def load_config(self) -> IdentityConfig:
        path = self.directory / CONFIG_FILE
        if not path.is_file():
            return IdentityConfig.default(self.identity)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("identity", self.identity)
        return IdentityConfig.from_dict(data)

    def save_config(self, config: IdentityConfig) -> None:
        self.ensure()
        header = (
            f"# Private configuration for identity '{config.identity}'.\n"
            "# Lives outside any repository. Exclusions are enforced before a\n"
            "# directory is entered, case-insensitively, at every depth.\n"
        )
        privacy.write_private_text(
            self.directory / CONFIG_FILE,
            header + yaml.safe_dump(config.to_dict(), sort_keys=False, allow_unicode=True),
        )

    # --- inventory ----------------------------------------------------

    def load_inventory(self) -> dict[str, Any]:
        path = self.directory / INVENTORY_FILE
        if not path.is_file():
            return {"version": INVENTORY_VERSION, "entries": {}, "scans": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"the private inventory at {path} is not valid JSON ({error}); it was not "
                "overwritten. Move it aside to start a fresh scan."
            ) from error
        data.setdefault("entries", {})
        data.setdefault("scans", [])
        return data

    def save_inventory(self, inventory: dict[str, Any]) -> None:
        self.ensure()
        inventory["version"] = INVENTORY_VERSION
        privacy.write_private_json(self.directory / INVENTORY_FILE, inventory)

    # --- decisions ----------------------------------------------------

    def load_decisions(self) -> dict[str, Decision]:
        path = self.directory / DECISIONS_FILE
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            key: Decision.from_dict(value) for key, value in (data.get("decisions") or {}).items()
        }

    def save_decisions(self, decisions: dict[str, Decision]) -> None:
        self.ensure()
        privacy.write_private_json(
            self.directory / DECISIONS_FILE,
            {"decisions": {k: v.to_dict() for k, v in sorted(decisions.items())}},
        )

    def record_decision(self, decision: Decision) -> Decision:
        """Set one attestation and append it to the history log."""
        if decision.authorship not in AUTHORSHIP_STATES:
            raise ValueError(
                f"unknown authorship {decision.authorship!r}; expected one of "
                + ", ".join(AUTHORSHIP_STATES)
            )
        if decision.include_paragraphs:
            parse_paragraph_ranges(decision.include_paragraphs)
        if decision.extraction:
            from howlwriter.voice.identity.worksheet import EXTRACTIONS

            if decision.extraction not in EXTRACTIONS:
                raise ValueError(
                    f"unknown extraction {decision.extraction!r}; expected one of "
                    + ", ".join(sorted(EXTRACTIONS))
                )
        decisions = self.load_decisions()
        previous = decisions.get(decision.doc_id)
        decision.decided_at = decision.decided_at or utc_now()
        decisions[decision.doc_id] = decision
        self.save_decisions(decisions)
        self._append(
            DECISION_LOG_FILE,
            {
                "at": decision.decided_at,
                "doc_id": decision.doc_id,
                "from": previous.authorship if previous else None,
                "to": decision.authorship,
                "source": decision.source,
                "status": decision.status,
            },
        )
        return decision

    # --- other artifacts ----------------------------------------------

    def _append(self, filename: str, record: dict) -> None:
        self.ensure()
        path = self.directory / filename
        line = json.dumps(record, sort_keys=True, default=str) + "\n"
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        privacy.write_private_text(path, existing + line)

    def append_profile_change(self, record: dict) -> None:
        self._append(PROFILE_CHANGES_FILE, record)

    def write_scan_report(self, report: dict) -> None:
        self.ensure()
        privacy.write_private_json(self.directory / SCAN_REPORT_FILE, report)

    def load_scan_report(self) -> dict:
        path = self.directory / SCAN_REPORT_FILE
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def write_review_queue(self, text: str) -> Path:
        self.ensure()
        path = self.directory / REVIEW_QUEUE_FILE
        privacy.write_private_text(path, text)
        return path

    def calibration_path(self, name: str) -> Path:
        return self.directory / CALIBRATION_DIR / f"{name}.json"

    def save_calibration(self, name: str, payload: dict) -> None:
        privacy.write_private_json(self.calibration_path(name), payload)

    def load_calibration(self, name: str) -> dict | None:
        path = self.calibration_path(name)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def save_chat_evidence(self, payload: dict) -> None:
        privacy.write_private_json(self.directory / CHAT_EVIDENCE_FILE, payload)

    def load_chat_evidence(self) -> dict | None:
        path = self.directory / CHAT_EVIDENCE_FILE
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
