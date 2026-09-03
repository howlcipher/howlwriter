"""The human-readable half of a provenance record.

Generated from the record, never written alongside it. That is the whole point
of this module existing rather than a formatted string being assembled at the
end of each pipeline: the previous milestone's report said parentheticals
appeared in 92% of outputs when the raw artifacts said 100%, and said the run
was production-ready while the diversity checker said FAIL. Both numbers had a
correct value sitting in a data structure at the time. The failure was a human
transcribing them.

So every figure below is read out of `GenerationProvenance`. If a stage did not
run, its line is absent rather than reassuring. If a provider did not report its
model, the manifest says so in those words rather than leaving a blank that
reads as "none".
"""

from __future__ import annotations

from howlwriter.domain.generation_provenance import (
    MODEL_NOT_REPORTED,
    GenerationProvenance,
)


def _model_label(model: str | None, status: str) -> str:
    if status == MODEL_NOT_REPORTED or not model:
        return "not reported by provider"
    return model


def render_manifest(provenance: GenerationProvenance) -> str:
    """A plain-text manifest of one run, derived entirely from the record."""
    lines: list[str] = []
    add = lines.append

    add("HowlWriter Generation Manifest")
    add("=" * 30)
    add(f"Run ID:            {provenance.run_id or 'unknown'}")
    add(f"Workflow:          {provenance.workflow or 'unknown'}")
    if provenance.writing_mode:
        add(f"Writing Mode:      {provenance.writing_mode}")
    if provenance.generation_freedom:
        add(f"Generation Freedom: {provenance.generation_freedom}")
    add(f"Started:           {provenance.started_at}")
    if provenance.completed_at:
        add(f"Completed:         {provenance.completed_at}")
    if not provenance.complete:
        add("Record status:     INCOMPLETE -- this run did not finish every stage")
    add("")

    # --- what the user supplied ---
    contribution = provenance.contribution
    if provenance.outline_present:
        add("User contribution")
        add("-" * 17)
        add(f"  thesis/claims supplied:     {contribution.claims_supplied}")
        add(f"  required points supplied:   {contribution.required_points_supplied}")
        add(f"  preserved sentences:        {contribution.preserved_supplied}")
        add(f"  examples/experiences:       {contribution.examples_supplied}")
        add(f"  voice seeds:                {contribution.voice_seeds_supplied}")
        add(f"  words of user prose:        {contribution.user_words_supplied}")
        add("")

        add("Coverage")
        add("-" * 8)
        add(
            f"  required points represented: "
            f"{contribution.required_points_represented}/"
            f"{contribution.required_points_supplied}"
        )
        add(
            f"  preserved sentences retained: "
            f"{contribution.preserved_retained}/{contribution.preserved_supplied}"
        )
        if contribution.examples_supplied:
            add(
                f"  examples represented:        "
                f"{contribution.examples_represented}/{contribution.examples_supplied}"
            )
        status = provenance.coverage.get("status")
        if status:
            add(f"  coverage verdict:            {status}")
        if provenance.coverage.get("order_enforced") is not None:
            satisfied = provenance.coverage.get("order_satisfied")
            add(f"  ordering satisfied:          {satisfied}")
        add("")

    # --- what the model added ---
    add("Model-assisted")
    add("-" * 14)
    if contribution.artifact_words:
        add(f"  artifact words:              {contribution.artifact_words}")
    add(f"  factual claims added:        {contribution.model_added_claims}")
    if contribution.research_grounded_additions:
        add(f"  research-grounded additions: {contribution.research_grounded_additions}")
    if contribution.unsupported_additions:
        add(f"  unsupported additions:       {contribution.unsupported_additions}")
    if contribution.gaps_reported:
        add(f"  gaps reported by the writer: {contribution.gaps_reported}")
    add("")
    add(
        "  Counts only. This system cannot establish what share of the finished\n"
        "  text is human-authored, and does not estimate one."
    )
    add("")

    # --- research ---
    if provenance.research:
        add("Research")
        add("-" * 8)
        for key in ("queries", "sources_retrieved", "accepted", "rejected"):
            if key in provenance.research:
                add(f"  {key.replace('_', ' '):27s} {provenance.research[key]}")
        add("")

    # --- verification ---
    if provenance.review:
        add("Verification")
        add("-" * 12)
        for key, value in provenance.review.items():
            if key == "freshness_findings" and isinstance(value, list):
                continue
            add(f"  {key.replace('_', ' '):27s} {value}")
        add("")

    # --- models ---
    add("Models")
    add("-" * 6)
    if not provenance.calls:
        add("  No model-backed stage ran. Nothing was generated or rewritten by a model.")
    else:
        for call in provenance.calls:
            marker = "" if call.success else "  [FAILED]"
            retry = f"  (retry of call {call.retry_of})" if call.retry_of else ""
            add(f"  {call.sequence}. {call.role}{marker}{retry}")
            add(f"       provider: {call.provider or 'unknown'}")
            add(f"       model:    {_model_label(call.model, call.model_status)}")
            if call.duration_seconds is not None:
                add(f"       duration: {call.duration_seconds:.2f}s")
            if call.independence_status:
                add(f"       independence: {call.independence_status}")
            if call.token_usage is None:
                add("       token usage: not reported by provider")
            else:
                add(f"       token usage: {call.token_usage}")
        unknown = provenance.unknown_model_calls()
        if unknown:
            add("")
            add(
                f"  {len(unknown)} of {len(provenance.calls)} call(s) ran on a provider "
                "that did not report a model name. The name is omitted rather than "
                "inferred."
            )
    independence = provenance.reviewer_independence()
    if independence:
        add("")
        add(f"  Reviewer independence: {independence}")
    add("")

    # --- integrity ---
    add("Artifact integrity")
    add("-" * 18)
    for label, value in (
        ("outline", provenance.outline_sha256),
        ("input", provenance.input_sha256),
        ("draft", provenance.draft_sha256),
        ("humanized", provenance.humanized_sha256),
        ("reviewed", provenance.reviewed_sha256),
        ("final artifact", provenance.artifact_sha256),
    ):
        if value:
            add(f"  {label:15s} sha256:{value}")
    add("")
    add(
        "  These hashes establish that the recorded artifact is the one this\n"
        "  record describes and that it has not changed since. They are NOT\n"
        "  evidence of human authorship and must not be presented as such."
    )

    if provenance.warnings:
        add("")
        add("Warnings")
        add("-" * 8)
        for warning in provenance.warnings:
            add(f"  - {warning}")

    return "\n".join(lines)
