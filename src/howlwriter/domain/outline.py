"""The authorship outline: what the user supplied, and how much is left to invent.

An outline here is not a table of contents. It is a record of authorship --
which sentences the user wrote, which claims are theirs, which structure they
chose, and which gaps they are explicitly delegating. That distinction is the
whole feature: a system that expands three bullet points and a system that
stitches together nine user-authored claims are doing very different things,
and the output should say which one happened.

Two properties follow from that and are load-bearing everywhere below.

The first is that MORE USER INPUT MEANS LESS MODEL FREEDOM. A sparse idea
leaves almost everything open; a near-complete draft leaves almost nothing.
`GenerationFreedom` names that as a state derived from what was supplied,
rather than a knob someone sets, so it cannot drift away from the evidence.

The second is that AUTHORITY IS ORDERED. When the profile says one thing and
the user's own sentence says another, the sentence wins -- and when evidence
contradicts the user's claim, the evidence wins. `AuthorityLayer` writes that
order down once so the writer prompt, the coverage checks, and the provenance
record all appeal to the same ranking instead of three similar ones.

One schema serves every medium. A LinkedIn post and a dissertation differ in
which node kinds they use and which checks run afterwards, not in the shape of
the outline, so there is deliberately no per-medium outline type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
import json
from pathlib import Path
from typing import Any

import yaml

from howlwriter.domain.serialization import DataClassSerializationMixin

#: Bumped when the outline format changes in a way older files cannot satisfy.
#: HowlWriter's other domain objects carry no version, which is why an
#: AssignmentSpec written a year ago cannot be told apart from a current one.
#: A user-authored file that a pipeline makes authorship claims about should
#: not have that problem.
OUTLINE_SCHEMA_VERSION = "outline/v1"

#: Accepted on load so a file written against a future minor revision still
#: reports something better than a parse error.
_SUPPORTED_SCHEMAS = {OUTLINE_SCHEMA_VERSION, "outline/v1.0", "outline"}


class NodeKind(enum.Enum):
    """What one outline entry IS, which decides how it may be used.

    The kinds are not interchangeable labels. `PRESERVE` text may not be
    rewritten; `CLAIM` text is the user's assertion and may be rephrased but
    not contradicted; `IDEA` is an invitation to expand. Collapsing them into
    one "content" type is what makes a system quietly promote a rough note into
    an authoritative-sounding claim.
    """

    #: What the piece is about. One per outline, usually.
    TOPIC = "topic"
    #: The central argument. Outranks any structural preference.
    THESIS = "thesis"
    #: An assertion the user is making and stands behind.
    CLAIM = "claim"
    #: A rough note, deliberately open to expansion.
    IDEA = "idea"
    #: Text to reproduce character for character.
    PRESERVE = "preserve"
    #: An explicit instruction to develop something.
    EXPAND = "expand"
    #: A concrete illustration the user supplied.
    EXAMPLE = "example"
    #: Something that happened to the user. Never invented, never embellished.
    EXPERIENCE = "experience"
    #: Must appear in the output.
    REQUIRED_POINT = "required_point"
    #: May appear if it earns its place.
    OPTIONAL_POINT = "optional_point"
    #: A movement between sections the user wants made.
    TRANSITION = "transition"
    #: A section heading.
    HEADING = "heading"
    #: A source assigned to this part of the argument.
    SOURCE = "source"
    #: A question research must answer before this can be written.
    RESEARCH = "research"
    #: How the piece should close.
    ENDING = "ending"
    #: A note about register or handling, not content.
    STYLE_NOTE = "style_note"
    #: A sentence offered as evidence of the intended voice for this piece.
    VOICE_SEED = "voice_seed"


class NodeOrigin(str, enum.Enum):
    """Where content in an outline node came from.
    
    Prevents model-derived outline material from being silently credited
    as user-supplied merely because it entered as input to a later stage.
    """
    USER_AUTHORED = "USER_AUTHORED"
    ASSIGNMENT_SOURCE = "ASSIGNMENT_SOURCE"
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    MODEL_DERIVED_OUTLINE = "MODEL_DERIVED_OUTLINE"
    MODEL_RESEARCH_SYNTHESIS = "MODEL_RESEARCH_SYNTHESIS"
    MODEL_GENERATED_CLAIM = "MODEL_GENERATED_CLAIM"
    MODEL_DRAFTING = "MODEL_DRAFTING"
    HUMANIZER_EDIT = "HUMANIZER_EDIT"
    REVIEWER_CORRECTION = "REVIEWER_CORRECTION"


#: Kinds whose text is candidate user writing rather than an instruction about
#: writing. A node must ALSO have origin == USER_AUTHORED to be counted as human writing.
USER_AUTHORED_KINDS = frozenset(
    {
        NodeKind.THESIS,
        NodeKind.CLAIM,
        NodeKind.PRESERVE,
        NodeKind.EXAMPLE,
        NodeKind.EXPERIENCE,
        NodeKind.VOICE_SEED,
    }
)

#: Kinds that describe what to write rather than supplying writing. Their text
#: is an instruction and must not appear verbatim in the artifact.
INSTRUCTION_KINDS = frozenset(
    {
        NodeKind.EXPAND,
        NodeKind.RESEARCH,
        NodeKind.STYLE_NOTE,
        NodeKind.TRANSITION,
        NodeKind.ENDING,
    }
)

#: Kinds that assert something about the world and therefore need support in
#: research-backed modes.
FACTUAL_KINDS = frozenset({NodeKind.THESIS, NodeKind.CLAIM})


#: Kinds the finished artifact is not expected to contain verbatim. See
#: `OutlineNode.is_required` for why each one is here.
NON_REPRESENTED_KINDS = frozenset(
    {
        NodeKind.OPTIONAL_POINT,
        NodeKind.SOURCE,
        NodeKind.VOICE_SEED,
        # An IDEA is a seed the user handed over precisely so it could be
        # transformed. Holding it to a lexical-overlap test punishes the
        # expansion it asked for: measured live, "Code becomes less of a moat"
        # became a post whose entire thesis was that point, and scored 0.50 --
        # below the threshold, and reported MISSING. Ideas are still tracked
        # and reported; they just do not fail a run that did what they asked.
        NodeKind.IDEA,
    }
) | INSTRUCTION_KINDS

#: Kinds reported in the coverage findings for information, without a missing
#: one failing the run.
ADVISORY_KINDS = frozenset({NodeKind.IDEA, NodeKind.OPTIONAL_POINT})


class GenerationFreedom(enum.Enum):
    """How much of the finished piece the model was left to invent.

    Deliberately four named states rather than a score. A percentage here would
    be read as a measurement -- "the model wrote 43% of this" -- and nothing in
    the system can establish that. What the system CAN establish is how much
    authorship the user supplied before generation started, which is a fact
    about the input and is what this reports.
    """

    #: A prompt or a few notes. Almost everything is the model's.
    HIGH = "HIGH"
    #: Structure and direction given; prose and connective tissue are open.
    MEDIUM = "MEDIUM"
    #: Claims, order, and some wording fixed. The model joins and develops.
    LOW = "LOW"
    #: A near-complete draft. Minimum necessary editing only.
    MINIMAL = "MINIMAL"


class AuthorityLayer(enum.IntEnum):
    """Who wins when two inputs disagree. Lower value means higher authority.

    Written down once, in order, because the failure it prevents is subtle: a
    voice profile built mostly from academic writing will happily strip the
    first person out of a personal anecdote, and every individual step in that
    chain looks reasonable. It is only wrong relative to a ranking, so the
    ranking has to exist somewhere explicit rather than being implied by the
    order in which prompt sections happen to be concatenated.
    """

    EVIDENCE = 1
    ASSIGNMENT_CONSTRAINT = 2
    USER_VERBATIM = 3
    USER_CLAIM = 4
    USER_CONCLUSION = 5
    USER_STRUCTURE = 6
    USER_EXAMPLE = 7
    USER_VOICE_SEED = 8
    WRITING_MODE = 9
    CONTEXTUAL_PROFILE = 10
    GLOBAL_PROFILE = 11
    STRUCTURAL_REALIZATION = 12
    MODEL_CONNECTIVE_PROSE = 13
    MODEL_STYLE_PREFERENCE = 14


#: Which layer each node kind speaks with. Used by the writer prompt and by the
#: contradiction check that refuses to let a lower layer rewrite a higher one.
KIND_AUTHORITY: dict[NodeKind, AuthorityLayer] = {
    NodeKind.PRESERVE: AuthorityLayer.USER_VERBATIM,
    NodeKind.THESIS: AuthorityLayer.USER_CLAIM,
    NodeKind.CLAIM: AuthorityLayer.USER_CLAIM,
    NodeKind.ENDING: AuthorityLayer.USER_CONCLUSION,
    NodeKind.HEADING: AuthorityLayer.USER_STRUCTURE,
    NodeKind.REQUIRED_POINT: AuthorityLayer.USER_STRUCTURE,
    NodeKind.TRANSITION: AuthorityLayer.USER_STRUCTURE,
    NodeKind.TOPIC: AuthorityLayer.USER_STRUCTURE,
    NodeKind.EXAMPLE: AuthorityLayer.USER_EXAMPLE,
    NodeKind.EXPERIENCE: AuthorityLayer.USER_EXAMPLE,
    NodeKind.VOICE_SEED: AuthorityLayer.USER_VOICE_SEED,
    NodeKind.OPTIONAL_POINT: AuthorityLayer.MODEL_CONNECTIVE_PROSE,
    NodeKind.IDEA: AuthorityLayer.MODEL_CONNECTIVE_PROSE,
    NodeKind.EXPAND: AuthorityLayer.MODEL_CONNECTIVE_PROSE,
    NodeKind.SOURCE: AuthorityLayer.EVIDENCE,
    NodeKind.RESEARCH: AuthorityLayer.EVIDENCE,
    NodeKind.STYLE_NOTE: AuthorityLayer.ASSIGNMENT_CONSTRAINT,
}


@dataclass
class ResearchRequest(DataClassSerializationMixin):
    """A question the outline says must be answered before writing.

    Kept as a first-class node rather than a comment so that the query actually
    issued, the sources considered, and the sources accepted can all be tied
    back to the thing that asked for them.
    """

    question: str
    required: bool = True
    #: Outline claim ids this research is meant to support.
    supports_claims: list[str] = field(default_factory=list)
    node_id: str = ""


@dataclass
class OutlineNode(DataClassSerializationMixin):
    """One authored element.

    `text` means different things per kind, and that is intentional: for
    PRESERVE it is the exact prose to keep, for EXPAND it is an instruction
    about prose that does not exist yet. `kind` is what tells them apart, so it
    is never optional and never inferred.
    """

    kind: NodeKind = NodeKind.IDEA
    text: str = ""
    #: Stable handle so claims, sources, research and coverage can refer to
    #: this node. Generated on load when the file does not supply one.
    id: str = ""
    #: Source ids assigned to this node, for claim-to-evidence tracing.
    sources: list[str] = field(default_factory=list)
    #: Claim ids this node supports or depends on.
    claims: list[str] = field(default_factory=list)
    #: Soft length hint for this section only.
    target_words: int | None = None
    #: Nested structure, for outlines with sections and sub-points.
    children: list["OutlineNode"] = field(default_factory=list)
    #: Free-form note carried into provenance but never into the artifact.
    note: str = ""
    #: Origin of this node: USER_AUTHORED, ASSIGNMENT_SOURCE, MODEL_DERIVED_OUTLINE, etc.
    origin: str = NodeOrigin.USER_AUTHORED.value

    @property
    def authority(self) -> AuthorityLayer:
        return KIND_AUTHORITY.get(self.kind, AuthorityLayer.MODEL_CONNECTIVE_PROSE)

    @property
    def is_user_authored(self) -> bool:
        return (
            self.origin == NodeOrigin.USER_AUTHORED.value
            and self.kind in USER_AUTHORED_KINDS
        )

    @property
    def is_required(self) -> bool:
        """Whether the finished artifact must represent this node.

        Three kinds are excluded, for three different reasons. OPTIONAL_POINT
        is explicitly dispensable. Instruction kinds are directions -- "expand
        on X" describes work, and cannot itself appear in the output. And a
        VOICE_SEED is evidence about register, offered so the writer can hear
        the intended voice; requiring it to appear would turn it into a phrase
        to reproduce, which is the opposite of what it is for.
        """
        return self.kind not in NON_REPRESENTED_KINDS

    def walk(self) -> "list[OutlineNode]":
        """This node and every descendant, depth first, in document order."""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found

    @classmethod
    def from_dict(cls, data: dict) -> "OutlineNode":
        rebuilt = super().from_dict(data)
        if not isinstance(rebuilt.kind, NodeKind):
            rebuilt.kind = _parse_kind(rebuilt.kind)
        rebuilt.children = [
            OutlineNode.from_dict(child) if isinstance(child, dict) else child
            for child in (rebuilt.children or [])
        ]
        return rebuilt


@dataclass
class Outline(DataClassSerializationMixin):
    """A complete authorship specification for one artifact."""

    schema: str = OUTLINE_SCHEMA_VERSION
    title: str = ""
    topic: str = ""
    #: WritingMode name. Parsed by the caller so this module stays independent
    #: of mode semantics.
    mode: str = ""
    nodes: list[OutlineNode] = field(default_factory=list)
    research: list[ResearchRequest] = field(default_factory=list)
    #: Soft target. `max_words` is the hard ceiling and is checked separately,
    #: matching the distinction the academic pipeline already draws.
    target_words: int | None = None
    max_words: int | None = None
    #: When true, required points must appear in the order they are listed.
    #: Structural variance may not reorder them to manufacture variation.
    enforce_order: bool = True
    #: Voice profile name or path, if the outline pins one.
    voice_profile: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # --- convenient views -------------------------------------------------

    def all_nodes(self) -> list[OutlineNode]:
        """Every node including nested children, in document order."""
        found: list[OutlineNode] = []
        for node in self.nodes:
            found.extend(node.walk())
        return found

    def nodes_of(self, *kinds: NodeKind) -> list[OutlineNode]:
        return [node for node in self.all_nodes() if node.kind in kinds]

    def preserved(self) -> list[OutlineNode]:
        return self.nodes_of(NodeKind.PRESERVE)

    def claims(self) -> list[OutlineNode]:
        return self.nodes_of(NodeKind.THESIS, NodeKind.CLAIM)

    def required_points(self) -> list[OutlineNode]:
        return [node for node in self.all_nodes() if node.is_required]

    def voice_seeds(self) -> list[OutlineNode]:
        return self.nodes_of(NodeKind.VOICE_SEED)

    def supplied_words(self) -> int:
        """Words of actual user prose, excluding instructions about prose."""
        return sum(
            len(node.text.split())
            for node in self.all_nodes()
            if node.is_user_authored
        )

    def human_claims(self) -> list[OutlineNode]:
        return [node for node in self.claims() if node.is_user_authored]

    def model_derived_nodes(self) -> list[OutlineNode]:
        return [
            node for node in self.all_nodes()
            if node.origin in (
                NodeOrigin.MODEL_DERIVED_OUTLINE.value,
                NodeOrigin.MODEL_RESEARCH_SYNTHESIS.value,
                NodeOrigin.MODEL_GENERATED_CLAIM.value,
                NodeOrigin.MODEL_DRAFTING.value,
            )
        ]

    @classmethod
    def from_dict(cls, data: dict) -> "Outline":
        rebuilt = super().from_dict(data)
        rebuilt.nodes = [
            OutlineNode.from_dict(node) if isinstance(node, dict) else node
            for node in (rebuilt.nodes or [])
        ]
        rebuilt.research = [
            ResearchRequest.from_dict(item) if isinstance(item, dict) else item
            for item in (rebuilt.research or [])
        ]
        return rebuilt


def _parse_kind(value: Any) -> NodeKind:
    if isinstance(value, NodeKind):
        return value
    try:
        return NodeKind(str(value).strip().lower())
    except ValueError:
        raise ValueError(
            f"unknown outline node kind: {value!r}. "
            f"Valid kinds: {', '.join(sorted(k.value for k in NodeKind))}"
        )


def _assign_ids(outline: Outline) -> None:
    """Give every node a stable handle.

    Ids are how coverage findings, provenance entries and claim-to-source links
    refer back to what the user wrote. Generating them on load rather than
    requiring them keeps a three-line outline three lines long.
    """
    used = {node.id for node in outline.all_nodes() if node.id}
    counters: dict[str, int] = {}
    for node in outline.all_nodes():
        if node.id:
            continue
        prefix = node.kind.value
        while True:
            counters[prefix] = counters.get(prefix, 0) + 1
            candidate = f"{prefix}_{counters[prefix]}"
            if candidate not in used:
                break
        node.id = candidate
        used.add(candidate)
    for index, request in enumerate(outline.research, start=1):
        if not request.node_id:
            request.node_id = f"research_{index}"


def validate_outline(outline: Outline) -> list[str]:
    """Everything wrong with this outline, in one pass.

    Returns problems rather than raising on the first one so a user fixing a
    file sees the whole list instead of discovering it one run at a time.
    """
    errors: list[str] = []

    if outline.schema not in _SUPPORTED_SCHEMAS:
        errors.append(
            f"unsupported outline schema {outline.schema!r}; "
            f"this build understands {OUTLINE_SCHEMA_VERSION!r}"
        )

    nodes = outline.all_nodes()
    if not nodes and not outline.topic and not outline.title:
        errors.append("outline is empty: supply at least a topic or one node")

    seen: set[str] = set()
    for node in nodes:
        if node.id in seen:
            errors.append(f"duplicate node id {node.id!r}")
        seen.add(node.id)
        if not node.text.strip() and node.kind is not NodeKind.HEADING:
            errors.append(f"node {node.id!r} ({node.kind.value}) has no text")
        if node.target_words is not None and node.target_words <= 0:
            errors.append(f"node {node.id!r} has a non-positive target_words")

    # Preserved text is the one kind where an accident is unrecoverable: a
    # sentence the user expected verbatim, silently dropped because it was
    # empty or duplicated, looks identical to one that was never supplied.
    preserved_texts = [node.text.strip() for node in outline.preserved()]
    duplicates = {text for text in preserved_texts if preserved_texts.count(text) > 1}
    for text in sorted(duplicates):
        errors.append(
            "preserved text appears more than once, which makes retention "
            f"impossible to verify: {text[:60]!r}"
        )

    if (
        outline.target_words is not None
        and outline.max_words is not None
        and outline.max_words < outline.target_words
    ):
        errors.append(
            f"max_words ({outline.max_words}) is below target_words "
            f"({outline.target_words})"
        )

    for request in outline.research:
        if not request.question.strip():
            errors.append(f"research request {request.node_id!r} has no question")

    claim_ids = {node.id for node in outline.claims()}
    for request in outline.research:
        for claim_id in request.supports_claims:
            if claim_id not in claim_ids:
                errors.append(
                    f"research {request.node_id!r} references unknown claim {claim_id!r}"
                )

    return errors


def load_outline(source: str | Path | dict[str, Any]) -> Outline:
    """Load an outline from a YAML or JSON file, string, or dict.

    YAML is tried first and JSON second, matching `load_assignment_spec`, since
    every JSON document is also valid YAML and the reverse is not true.
    """
    if isinstance(source, dict):
        raw: Any = dict(source)
    else:
        path = Path(source)
        text = path.read_text(encoding="utf-8") if path.is_file() else str(source)
        try:
            raw = yaml.safe_load(text)
        except Exception:
            try:
                raw = json.loads(text)
            except Exception as exc:
                raise ValueError(f"failed to parse outline YAML/JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("outline must be a mapping at the top level")

    outline = Outline.from_dict(raw)
    _assign_ids(outline)
    errors = validate_outline(outline)
    if errors:
        raise ValueError("invalid outline: " + "; ".join(errors))
    return outline
