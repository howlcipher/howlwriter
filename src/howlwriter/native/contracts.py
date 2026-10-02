"""Native Writer contracts: a structured request in, a copy package out.

``howlwriter.request/v1`` carries everything a bounded copy rewrite needs:
where the idea came from (Dream or an operator), the canonical evidence,
the factual constraints, and the copy slots to rewrite. It is plain data,
so a Dream export becomes a Writer request without a handwritten adapter.

``howlwriter.copy_package/v1`` is what Writer emits and what HowlCreate
consumes. Each proposal keeps its current text, its proposed text, the
evidence it rests on, and the deterministic factual verdict, and the
package records the provider and model that actually ran.

The JSON Schemas under ``howlwriter/schemas`` describe the same shapes for
consumers that validate without importing Writer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any

REQUEST_SCHEMA = "howlwriter.request/v1"
PACKAGE_SCHEMA = "howlwriter.copy_package/v1"

# Bounds keep a request a bounded text-generation job, not a document dump.
MAX_ITEMS = 40
MAX_TEXT_CHARS = 8000
MAX_EVIDENCE_PER_ITEM = 12
MAX_CONSTRAINTS = 50

SOURCE_COMPONENTS = frozenset({"howldream", "operator", "howlplane", "howlcreate"})
SOURCE_ROLES = frozenset({
    "GENERATED", "CLUSTERED", "RANKED", "REVIEWED", "VALIDATED", "SELECTED",
    "TRANSFORMED", "OPERATOR_SUPPLIED",
})


class ContractError(ValueError):
    """A request or package does not satisfy its contract."""


def _text(value: Any, name: str, *, required: bool = True, limit: int = MAX_TEXT_CHARS) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ContractError(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise ContractError(f"{name} exceeds {limit} characters ({len(value)})")
    return value


def _strings(value: Any, name: str, *, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ContractError(f"{name} must be a list of non-empty strings")
    if len(value) > limit:
        raise ContractError(f"{name} has {len(value)} entries; the limit is {limit}")
    return list(value)


@dataclass(frozen=True)
class EvidenceItem:
    ref: str
    text: str

    @classmethod
    def from_dict(cls, value: Any, name: str) -> "EvidenceItem":
        if not isinstance(value, dict):
            raise ContractError(f"{name} must be an object with ref and text")
        return cls(ref=_text(value.get("ref"), f"{name}.ref", limit=200),
                   text=_text(value.get("text"), f"{name}.text"))


@dataclass(frozen=True)
class CopyItem:
    """One slot of copy to rewrite."""

    item_id: str
    current_copy: str
    desired_copy_role: str
    evidence: tuple[EvidenceItem, ...] = ()
    max_words: int | None = None

    @classmethod
    def from_dict(cls, value: Any, index: int) -> "CopyItem":
        name = f"items[{index}]"
        if not isinstance(value, dict):
            raise ContractError(f"{name} must be an object")
        evidence = value.get("evidence") or []
        if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE_PER_ITEM:
            raise ContractError(f"{name}.evidence must be a list of at most {MAX_EVIDENCE_PER_ITEM}")
        max_words = value.get("max_words")
        if max_words is not None and (type(max_words) is not int or not 1 <= max_words <= 2000):
            raise ContractError(f"{name}.max_words must be an integer between 1 and 2000")
        return cls(
            item_id=_text(value.get("item_id"), f"{name}.item_id", limit=200),
            current_copy=_text(value.get("current_copy"), f"{name}.current_copy"),
            desired_copy_role=_text(value.get("desired_copy_role"), f"{name}.desired_copy_role", limit=500),
            evidence=tuple(
                EvidenceItem.from_dict(e, f"{name}.evidence[{i}]") for i, e in enumerate(evidence)
            ),
            max_words=max_words,
        )


@dataclass(frozen=True)
class WriterRequest:
    source_idea_id: str
    source_run_id: str
    source_component: str
    source_component_role: str
    title: str
    problem: str
    proposal: str
    audience: str
    items: tuple[CopyItem, ...]
    canonical_evidence_refs: tuple[str, ...] = ()
    factual_constraints: tuple[str, ...] = ()
    tone: str = "technical, direct, concise"
    length_constraints: str = ""
    copy_implications: tuple[str, ...] = ()
    schema_version: str = REQUEST_SCHEMA

    @property
    def request_id(self) -> str:
        digest = hashlib.sha256(
            json.dumps(self.to_dict(include_id=False), sort_keys=True).encode()
        ).hexdigest()
        return f"wreq-{digest[:12]}"

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        value = asdict(self)
        value["items"] = [
            {**asdict(item), "evidence": [asdict(e) for e in item.evidence]} for item in self.items
        ]
        for key in ("canonical_evidence_refs", "factual_constraints", "copy_implications"):
            value[key] = list(value[key])
        if include_id:
            value["request_id"] = self.request_id
        return value

    @classmethod
    def from_dict(cls, value: Any) -> "WriterRequest":
        if not isinstance(value, dict):
            raise ContractError("request must be a JSON object")
        if value.get("schema_version", REQUEST_SCHEMA) != REQUEST_SCHEMA:
            raise ContractError(f"unsupported request schema {value.get('schema_version')!r}")
        component = _text(value.get("source_component"), "source_component", limit=100)
        if component not in SOURCE_COMPONENTS:
            raise ContractError(f"source_component must be one of {sorted(SOURCE_COMPONENTS)}")
        role = _text(value.get("source_component_role"), "source_component_role", limit=100)
        if role not in SOURCE_ROLES:
            raise ContractError(f"source_component_role must be one of {sorted(SOURCE_ROLES)}")
        items = value.get("items")
        if not isinstance(items, list) or not items:
            raise ContractError("items must be a non-empty list")
        if len(items) > MAX_ITEMS:
            raise ContractError(f"items has {len(items)} entries; the limit is {MAX_ITEMS}")
        parsed = tuple(CopyItem.from_dict(item, i) for i, item in enumerate(items))
        ids = [item.item_id for item in parsed]
        if len(set(ids)) != len(ids):
            raise ContractError("items[].item_id values must be unique")
        request = cls(
            source_idea_id=_text(value.get("source_idea_id"), "source_idea_id", limit=300),
            source_run_id=_text(value.get("source_run_id"), "source_run_id", limit=300),
            source_component=component,
            source_component_role=role,
            title=_text(value.get("title"), "title", limit=500),
            problem=_text(value.get("problem"), "problem", required=False),
            proposal=_text(value.get("proposal"), "proposal", required=False),
            audience=_text(value.get("audience"), "audience", limit=500),
            items=parsed,
            canonical_evidence_refs=tuple(_strings(value.get("canonical_evidence_refs"),
                                                   "canonical_evidence_refs", limit=200)),
            factual_constraints=tuple(_strings(value.get("factual_constraints"),
                                               "factual_constraints", limit=MAX_CONSTRAINTS)),
            tone=_text(value.get("tone", "technical, direct, concise"), "tone", limit=500),
            length_constraints=_text(value.get("length_constraints"), "length_constraints",
                                     required=False, limit=500),
            copy_implications=tuple(_strings(value.get("copy_implications"),
                                             "copy_implications", limit=MAX_CONSTRAINTS)),
        )
        supplied_id = value.get("request_id")
        if supplied_id is not None and supplied_id != request.request_id:
            raise ContractError("request_id does not match the request content")
        return request


@dataclass
class CopyProposal:
    proposal_item_id: str
    item_id: str
    current_text: str
    proposed_text: str
    reason: str
    desired_copy_role: str
    evidence_refs: list[str]
    factual_status: str
    factual_change: bool
    fidelity: dict[str, Any]
    design_judgment: str = ""
    uncertainty: str = ""
    # MODEL when the provider proposed this text, UNCHANGED when it returned
    # nothing usable for the slot and the current copy was kept.
    origin: str = "MODEL"
    word_count: int = 0
    max_words: int | None = None
    length_ok: bool = True


@dataclass
class CopyPackage:
    writer_proposal_id: str
    request_id: str
    source_idea_id: str
    source_run_id: str
    source_component: str
    source_component_role: str
    title: str
    audience: str
    created_at: str
    proposals: list[CopyProposal]
    factual_status: str
    execution: dict[str, Any]
    contribution: dict[str, Any]
    canonical_evidence_refs: list[str] = field(default_factory=list)
    factual_constraints: list[str] = field(default_factory=list)
    schema_version: str = PACKAGE_SCHEMA
    authority: dict[str, Any] = field(
        default_factory=lambda: {"type": "ADVISORY", "executable": False}
    )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["lineage"] = {
            "source_component": self.source_component,
            "source_idea_id": self.source_idea_id,
            "source_run_id": self.source_run_id,
            "writer_request_id": self.request_id,
            "writer_proposal_id": self.writer_proposal_id,
        }
        return value
