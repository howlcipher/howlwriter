"""Three different things that all get called "citing the AI", kept apart.

A. SCHOLARLY REFERENCES are the evidence the paper rests on. Nothing in this
   module ever writes to them. A prompt is not a source, a run id is not
   evidence, and putting either on the References page misrepresents both.

B. GENERATIVE-AI DISCLOSURE is what current APA guidance asks for: describe how
   the tool was used, in the Method section (or the introduction for essays and
   literature reviews), and cite the tool. The reference template is
   `Company. (Year). *Tool* (Version) [Large language model]. URL`, with the
   COMPANY as author -- an AI cannot be an author, since it cannot consent.

C. HOWLWRITER GENERATION PROVENANCE is the run record: routing, prompts,
   hashes, transformations. It belongs in an appendix or a sidecar, never in
   either of the above.

The awkward finding this module has to handle honestly: HowlWriter dispatches
through HowlPlane, and HowlPlane's providers frequently do not report a model
name. APA's reference template requires the tool and its version. When the
provider did not say what ran, a compliant reference entry cannot be built --
and the correct behaviour is to say so, not to fill in the provider's CLI name
where a vendor and model belong. `agy` is not a company and not a model.

The statement itself is always derivable, because it describes what HowlWriter
did rather than what the model was. If only linting ran, it says no generative
model produced text. If a sparse outline became most of the prose, it says
that too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from howlwriter.domain.generation_provenance import GenerationProvenance

#: How each model-backed role is described in a disclosure. Deliberately plain:
#: "assisted with" claims less than "wrote", and the distinction is the point.
_ROLE_DESCRIPTIONS = {
    "writer": "expanded the author's outline into prose",
    "humanizer": "refined prose style without changing claims or evidence",
    "final_reviewer": "reviewed the transformed text for preserved meaning",
    "voice_analyst": "analysed the author's own corpus for stylistic tendencies",
    "researcher": "organised source retrieval",
    "editor": "applied editorial corrections",
}

#: Where APA asks for the disclosure to live.
DISCLOSURE_SECTION = "Method"


@dataclass
class AIReferenceEntry:
    """An APA reference for the tool, or an honest account of why there isn't one."""

    available: bool = False
    entry: str = ""
    in_text: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "entry": self.entry,
            "in_text": self.in_text,
            "reason": self.reason,
        }


@dataclass
class AIUseStatement:
    """A disclosure generated from what actually ran."""

    used_generative_ai: bool = False
    section: str = DISCLOSURE_SECTION
    statement: str = ""
    roles: list[str] = field(default_factory=list)
    reference: AIReferenceEntry = field(default_factory=AIReferenceEntry)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "used_generative_ai": self.used_generative_ai,
            "section": self.section,
            "statement": self.statement,
            "roles": list(self.roles),
            "reference": self.reference.to_dict(),
            "notes": list(self.notes),
        }

    def render(self) -> str:
        lines = ["Generative AI Use", ""]
        lines.append(self.statement)
        if self.roles:
            lines.append("")
            lines.append("Model-backed roles used:")
            lines.extend(f"  - {role}" for role in self.roles)
        lines.append("")
        if self.reference.available:
            lines.append("Reference entry for the tool:")
            lines.append(f"  {self.reference.entry}")
            lines.append(f"  In-text: {self.reference.in_text}")
        elif self.used_generative_ai:
            lines.append(f"Tool reference: {self.reference.reason}")
        for note in self.notes:
            lines.append(f"Note: {note}")
        return "\n".join(lines).rstrip()


#: Share of the finished text the author must have supplied before a claim
#: that the model was "limited to" connective prose is defensible.
_SUBSTANTIAL_AUTHOR_SHARE = 0.25


def _wrote_most_of_the_words(contribution) -> bool:
    """Whether the model produced the bulk of the sentences, regardless of label.

    Freedom measures how constrained the model was. It does not measure how
    much of the text the model wrote, and a densely structured academic outline
    can score LOW while still leaving 95% of the words to the model.
    """
    if not contribution.artifact_words:
        return False
    share = contribution.user_words_supplied / contribution.artifact_words
    return share < _SUBSTANTIAL_AUTHOR_SHARE


def _build_reference(provenance: GenerationProvenance) -> AIReferenceEntry:
    """An APA tool reference, when the run supplies what the template needs."""
    models = provenance.models_used()
    if not models:
        return AIReferenceEntry(
            available=False,
            reason=(
                "no reference entry could be generated: the provider(s) used did "
                "not report a model name or version, and APA's template requires "
                "the tool and version. The provider identifier is recorded in the "
                "provenance record instead. It is not a substitute -- a CLI name "
                "is neither the company nor the model, and supplying it where a "
                "vendor belongs would misattribute the work."
            ),
        )

    # A model name alone is still not the whole template: APA wants the company
    # as author and a URL for the tool. HowlWriter learns neither from the
    # dispatch layer, so the entry is offered as a partial draft the author
    # completes, and says which parts it could not fill.
    year = datetime.now(timezone.utc).year
    model = models[0]
    return AIReferenceEntry(
        available=True,
        entry=(
            f"[Provider organization]. ({year}). {model} "
            f"[Large language model]. [URL of the tool]"
        ),
        in_text=f"([Provider organization], {year})",
        reason=(
            "the model name was reported, but the publishing organization and "
            "tool URL are not visible to HowlWriter and are left as placeholders "
            "for the author to complete rather than guessed"
        ),
    )


def build_ai_use_statement(
    provenance: GenerationProvenance,
    *,
    lint_only: bool = False,
) -> AIUseStatement:
    """Describe the generative AI use this run actually made.

    Every branch below is decided by the record, so a run that did less
    produces a smaller claim without anyone remembering to weaken the wording.
    """
    statement = AIUseStatement()
    calls = [c for c in provenance.calls if c.success]

    if not calls:
        statement.used_generative_ai = False
        statement.statement = (
            "No generative AI model produced or altered the text of this "
            "document. "
            + (
                "Deterministic style linting was applied; linting reports "
                "findings and does not rewrite."
                if lint_only
                else "No model-backed stage ran."
            )
        )
        return statement

    statement.used_generative_ai = True
    roles = []
    for call in calls:
        description = _ROLE_DESCRIPTIONS.get(call.role, f"performed the {call.role} role")
        label = f"{call.role}: {description}"
        if label not in roles:
            roles.append(label)
    statement.roles = roles

    wrote = any(c.role == "writer" for c in calls)
    freedom = (provenance.generation_freedom or "").upper()
    contribution = provenance.contribution

    parts: list[str] = []
    if wrote and provenance.outline_present:
        if freedom in ("HIGH", "MEDIUM"):
            # The honest reading of a sparse outline: most sentences are the
            # model's, and a statement that implied otherwise would be false.
            parts.append(
                "HowlWriter expanded the author's outline into prose. The "
                "author supplied the topic, structure, and required points; "
                "most of the connective prose and sentence-level wording was "
                "produced by a generative model under those constraints."
            )
        else:
            # "Limited to development and transitions" is only true when the
            # author actually supplied a substantial share of the prose. A
            # heavily structured outline can still leave the model writing
            # almost every sentence, and claiming otherwise because the
            # freedom label says LOW would be exactly the overstatement this
            # function exists to prevent.
            if _wrote_most_of_the_words(contribution):
                parts.append(
                    "HowlWriter expanded the author's outline into prose. The "
                    "author supplied the thesis, the argument structure, the "
                    "required claims, and selected wording, but most of the "
                    "sentence-level wording in the final text was produced by "
                    "a generative model working inside those constraints."
                )
            else:
                parts.append(
                    "HowlWriter expanded the author's outline into prose. The "
                    "author supplied the thesis, the argument structure, the "
                    "required claims, and selected wording; the model's role "
                    "was limited to development, transitions, and connective "
                    "prose."
                )
        parts.append(
            f"The author supplied {contribution.claims_supplied} claim(s), "
            f"{contribution.preserved_supplied} passage(s) reproduced verbatim, "
            f"and {contribution.required_points_supplied} required point(s), of "
            f"which {contribution.required_points_represented} are represented "
            "in the final text."
        )
        if contribution.user_words_supplied and contribution.artifact_words:
            # The plainest fact available, and the one a reader most needs: how
            # many words the author wrote against how many are in the document.
            parts.append(
                f"Of roughly {contribution.artifact_words} words in the final "
                f"text, {contribution.user_words_supplied} were supplied "
                "directly by the author as claims, preserved passages, or "
                "examples. This is a word count, not a measure of authorship."
            )
    elif wrote:
        parts.append(
            "HowlWriter drafted this document from an assignment specification "
            "supplied by the author."
        )
    else:
        # No writer ran. Claiming generation here would be the exact
        # overstatement this function exists to prevent.
        parts.append(
            "No text was generated from scratch by a model. HowlWriter applied "
            "prose refinement and review to text the author supplied; claims, "
            "evidence, and structure came from the author."
        )

    if contribution.model_added_claims:
        parts.append(
            f"{contribution.model_added_claims} factual assertion(s) added "
            "during expansion are recorded in the accompanying provenance record."
        )
    if provenance.gaps:
        parts.append(
            f"{len(provenance.gaps)} point(s) were flagged as requiring detail "
            "only the author could supply, and were not invented."
        )

    parts.append(
        "A detailed generation provenance record accompanies this artifact."
    )
    statement.statement = " ".join(parts)
    statement.reference = _build_reference(provenance)

    unknown = provenance.unknown_model_calls()
    if unknown:
        statement.notes.append(
            f"{len(unknown)} of {len(provenance.calls)} model call(s) ran on a "
            "provider that did not report a model name; the name is omitted "
            "rather than inferred."
        )
    independence = provenance.reviewer_independence()
    if independence:
        statement.notes.append(f"Reviewer independence: {independence}.")

    return statement


def render_provenance_appendix(provenance: GenerationProvenance) -> str:
    """An appendix describing the run, kept out of the References page.

    Never includes hidden model reasoning. HowlWriter records what it sent and
    what came back; it has no access to a model's internal deliberation and
    does not pretend otherwise.
    """
    from howlwriter.provenance.manifest import render_manifest

    lines = [
        "Appendix: Generation Provenance",
        "",
        "This appendix documents how this document was produced. It is a record "
        "of workflow, not of evidence: the sources supporting the argument "
        "appear in the References list and nowhere here.",
        "",
        render_manifest(provenance),
        "",
        "This record contains the instructions HowlWriter sent to each model "
        "and the integrity hashes of each intermediate artifact. It does not "
        "contain any model's internal reasoning, which HowlWriter cannot "
        "observe.",
    ]
    return "\n".join(lines)
