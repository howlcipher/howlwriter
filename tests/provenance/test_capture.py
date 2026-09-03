"""Provenance capture: exact, honest about gaps, and safe to write down.

Three properties carry the whole feature, and each has a way of failing that
looks like success.

EXACT. A record whose prompts were re-rendered after the run is a plausible
fiction that drifts silently the moment a prompt builder changes. The tests
below compare captured text against the string the dispatch boundary received,
not against a re-render.

HONEST. HowlPlane returns `model` as optional and reports no token usage at
all. A record that omitted an unreported model would read as "no model"; one
that inferred it from the provider name would be a fabrication with an audit
trail.

SAFE. A full record contains every prompt, and prompts contain whatever was in
scope when they were built.
"""

from __future__ import annotations

from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    RoleBinding,
    RoleBindingRegistry,
    RoleDispatcher,
)

from howlwriter.domain.generation_provenance import (
    LEVEL_FULL,
    LEVEL_SUMMARY,
    MODEL_NOT_REPORTED,
    MODEL_REPORTED,
    GenerationProvenance,
    ModelCallRecord,
    redact,
    sha256_text,
)
from howlwriter.integration.model_role import WritingRole
from howlwriter.integration.provenance_capture import ProvenanceRecorder
from howlwriter.provenance.assemble import finalize
from howlwriter.provenance.manifest import render_manifest


def _bridge(agent_id: str = "fake", stdout: str = "ok", model: str | None = None):
    registry = RoleBindingRegistry()
    for role in ("writer", "humanizer", "final_reviewer"):
        registry.register_binding(
            RoleBinding(domain="writing", role=role, provider=agent_id)
        )
    metadata = {"model": model} if model else {}
    backend = FakeAgentBackend(
        agent_id=agent_id, default_stdout=stdout, default_metadata=metadata
    )
    bridge = HowlPlaneWritingBridge(
        dispatcher=RoleDispatcher(binding_registry=registry), registry=registry
    )
    set_howlplane_bridge(bridge)
    return bridge, backend


# --- exactness -----------------------------------------------------------

def test_the_captured_prompt_is_the_string_the_boundary_received():
    bridge, backend = _bridge()
    system = "SYSTEM: you expand outlines."
    prompt = "USER: write about moats.\nWith a second line."

    with ProvenanceRecorder(run_id="r") as recorder:
        bridge.execute_writing_role(
            role=WritingRole.WRITER,
            prompt=prompt,
            system_instruction=system,
            custom_backend=backend,
        )

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call.user_prompt == prompt
    assert call.system_instruction == system
    assert call.user_prompt_sha256 == sha256_text(prompt)
    assert call.system_instruction_sha256 == sha256_text(system)
    assert call.user_prompt_chars == len(prompt)


def test_every_call_is_captured_in_dispatch_order():
    bridge, backend = _bridge()
    with ProvenanceRecorder() as recorder:
        for role in (WritingRole.WRITER, WritingRole.HUMANIZER, WritingRole.FINAL_REVIEWER):
            bridge.execute_writing_role(
                role=role, prompt=f"prompt for {role.value}", custom_backend=backend
            )

    assert [c.role for c in recorder.calls] == ["writer", "humanizer", "final_reviewer"]
    assert [c.sequence for c in recorder.calls] == [1, 2, 3]


def test_nothing_is_captured_when_no_recorder_is_active():
    """Capture must be free when nobody asked for it."""
    bridge, backend = _bridge()
    bridge.execute_writing_role(
        role=WritingRole.WRITER, prompt="x", custom_backend=backend
    )
    recorder = ProvenanceRecorder()
    assert recorder.calls == []


def test_the_response_is_hashed_without_being_stored():
    bridge, backend = _bridge(stdout="the model said this")
    with ProvenanceRecorder() as recorder:
        bridge.execute_writing_role(
            role=WritingRole.WRITER, prompt="x", custom_backend=backend
        )
    call = recorder.calls[0]
    assert call.response_sha256 == sha256_text("the model said this")
    assert call.response_chars == len("the model said this")
    assert not hasattr(call, "response_text")


# --- honesty about what the provider did not say -------------------------

def test_an_unreported_model_is_recorded_as_such_and_never_inferred():
    bridge, backend = _bridge(agent_id="some_provider")
    with ProvenanceRecorder() as recorder:
        bridge.execute_writing_role(
            role=WritingRole.WRITER, prompt="x", custom_backend=backend
        )
    call = recorder.calls[0]
    assert call.model is None
    assert call.model_status == MODEL_NOT_REPORTED
    # The provider name is the tempting thing to fill in here. It must not be.
    assert call.provider == "some_provider"
    assert call.model != call.provider


def test_a_reported_model_is_recorded_as_reported():
    call = ModelCallRecord(model="claude-sonnet-4-6", model_status=MODEL_REPORTED)
    provenance = GenerationProvenance(calls=[call])
    assert provenance.models_used() == ["claude-sonnet-4-6"]
    assert provenance.unknown_model_calls() == []


def test_token_usage_stays_none_rather_than_becoming_zero():
    """None means "not reported". Zero would mean "none used"."""
    bridge, backend = _bridge()
    with ProvenanceRecorder() as recorder:
        bridge.execute_writing_role(
            role=WritingRole.WRITER, prompt="x", custom_backend=backend
        )
    assert recorder.calls[0].token_usage is None
    assert recorder.calls[0].request_id is None


def test_the_manifest_says_a_model_was_not_reported_rather_than_leaving_a_blank():
    provenance = GenerationProvenance(
        run_id="r",
        workflow="howl",
        calls=[ModelCallRecord(sequence=1, role="writer", provider="agy", model=None)],
    )
    rendered = render_manifest(provenance)
    assert "not reported by provider" in rendered
    assert "model:    agy" not in rendered


def test_an_incomplete_record_says_so():
    provenance = GenerationProvenance(run_id="r", workflow="howl", complete=False)
    assert "INCOMPLETE" in render_manifest(provenance)
    assert "INCOMPLETE" not in render_manifest(
        GenerationProvenance(run_id="r", workflow="howl", complete=True)
    )


def test_a_run_with_no_model_calls_says_nothing_was_generated():
    provenance = GenerationProvenance(run_id="r", workflow="howl", complete=True)
    rendered = render_manifest(provenance)
    assert "No model-backed stage ran" in rendered


# --- retries and independence -------------------------------------------

def test_a_repeated_prompt_after_a_failure_is_marked_as_a_retry():
    """This is what the meaning reviewer's independence fallback does."""
    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(domain="writing", role="final_reviewer", provider="p")
    )
    failing = FakeAgentBackend(agent_id="p", default_exit_code=1, default_stdout="")
    ok = FakeAgentBackend(agent_id="p", default_stdout="fine")
    bridge = HowlPlaneWritingBridge(
        dispatcher=RoleDispatcher(binding_registry=registry), registry=registry
    )
    set_howlplane_bridge(bridge)

    with ProvenanceRecorder() as recorder:
        bridge.execute_writing_role(
            role=WritingRole.FINAL_REVIEWER, prompt="same prompt", custom_backend=failing
        )
        bridge.execute_writing_role(
            role=WritingRole.FINAL_REVIEWER, prompt="same prompt", custom_backend=ok
        )

    assert recorder.calls[0].success is False
    assert recorder.calls[1].retry_of == 1


def test_reviewer_independence_is_read_from_the_reviewer_call():
    provenance = GenerationProvenance(
        calls=[
            ModelCallRecord(sequence=1, role="humanizer", independence_status="INDEPENDENT"),
            ModelCallRecord(sequence=2, role="final_reviewer", independence_status="SAME_PROVIDER"),
        ]
    )
    assert provenance.reviewer_independence() == "SAME_PROVIDER"


def test_one_independent_stage_cannot_hide_a_same_provider_stage():
    provenance = GenerationProvenance(
        reviewer_independence_by_stage={
            "meaning_review": "INDEPENDENT_PROVIDER",
            "consistency_review": "SAME_PROVIDER",
        }
    )
    assert provenance.reviewer_independence() == "SAME_PROVIDER"


def test_every_provider_status_normalizes_to_the_four_value_contract():
    from howlwriter.domain.generation_provenance import (
        normalize_reviewer_independence,
    )

    assert normalize_reviewer_independence("INDEPENDENT") == "INDEPENDENT_PROVIDER"
    assert normalize_reviewer_independence("SAME_PROVIDER") == "SAME_PROVIDER"
    assert normalize_reviewer_independence("NOT_REVIEWED") == "NO_REVIEWER"
    assert normalize_reviewer_independence("UNAVAILABLE") == "UNKNOWN"


def test_the_avoided_provider_is_recorded_when_independence_was_requested():
    bridge, backend = _bridge()
    with ProvenanceRecorder() as recorder:
        bridge.execute_writing_role(
            role=WritingRole.FINAL_REVIEWER,
            prompt="review this",
            avoid_provider="fake",
            preferred_provider="fake",
            custom_backend=backend,
        )
    assert recorder.calls[0].avoid_provider == "fake"


# --- redaction and levels ------------------------------------------------

def test_credentials_are_removed_from_captured_text():
    dirty = (
        "Use sk-abcdefghijklmnopqrstuvwxyz123456 and ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n"
        "api_key: hunter2secretvalue\n"
        "AWS: AKIAIOSFODNN7EXAMPLE\n"
    )
    cleaned = redact(dirty)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in cleaned
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in cleaned
    assert "hunter2secretvalue" not in cleaned
    assert "AKIAIOSFODNN7EXAMPLE" not in cleaned
    assert "REDACTED" in cleaned


def test_home_paths_are_masked_only_when_asked():
    text = "reading /home/someone/private/corpus.md"
    assert "/home/someone" in redact(text)
    assert "/home/someone" not in redact(text, mask_paths=True)


def test_summary_level_keeps_hashes_but_drops_the_prompt_text():
    provenance = GenerationProvenance(
        calls=[
            ModelCallRecord(
                sequence=1,
                role="writer",
                system_instruction="secret system text",
                user_prompt="the user's own sentences",
                system_instruction_sha256=sha256_text("secret system text"),
                user_prompt_sha256=sha256_text("the user's own sentences"),
                user_prompt_chars=24,
            )
        ]
    )
    summary = finalize(provenance, level=LEVEL_SUMMARY)
    call = summary.calls[0]

    assert call.user_prompt == ""
    assert call.system_instruction == ""
    # Hashes survive, so a summary record is still checkable against a full one.
    assert call.user_prompt_sha256 == sha256_text("the user's own sentences")
    assert call.user_prompt_chars == 24


def test_full_level_keeps_the_prompt_but_still_redacts_secrets():
    provenance = GenerationProvenance(
        calls=[
            ModelCallRecord(
                sequence=1,
                role="writer",
                user_prompt="write this. api_key: supersecretvalue123",
            )
        ]
    )
    full = finalize(provenance, level=LEVEL_FULL)
    assert "write this" in full.calls[0].user_prompt
    assert "supersecretvalue123" not in full.calls[0].user_prompt


def test_finalizing_does_not_mutate_the_in_memory_record():
    provenance = GenerationProvenance(
        calls=[ModelCallRecord(sequence=1, role="writer", user_prompt="kept")]
    )
    finalize(provenance, level=LEVEL_SUMMARY)
    assert provenance.calls[0].user_prompt == "kept"


def test_a_provenance_record_round_trips():
    provenance = GenerationProvenance(
        run_id="hw-1",
        workflow="howl-outline",
        calls=[ModelCallRecord(sequence=1, role="writer", provider="p")],
    )
    restored = GenerationProvenance.from_dict(provenance.to_dict())
    assert isinstance(restored.calls[0], ModelCallRecord)
    assert restored.calls[0].role == "writer"
    assert restored.run_id == "hw-1"


# --- redaction covers the whole record, not only the prompts ---------------

def test_a_credential_in_preserved_text_is_scrubbed_from_every_sidecar(tmp_path):
    """Redacting only the prompt fields was not enough.

    A coverage finding echoes the user's preserved text back into the record
    verbatim, so a credential inside a preserved passage survived at
    `coverage.findings[].text` while the prompt carrying the same string was
    cleaned. The outline sidecar reproduced it a third time.
    """
    from howlwriter.config.defaults import default_config
    from howlwriter.domain.outline import load_outline
    from howlwriter.pipeline.howl import run_howl_pipeline
    from howlwriter.provenance.assemble import write_artifacts

    secret = "sk-abcdefghijklmnopqrstuvwxyz012345"
    body = f"Deploy uses api_key: {secret} for the pipeline."
    _bridge_with(body)

    outline = load_outline({"topic": "deploys", "nodes": [{"kind": "preserve", "text": body}]})
    result = run_howl_pipeline(
        None, default_config(), outline=outline,
        custom_backend=_BACKEND, provenance_level="full",
    )
    artifact = tmp_path / "post.md"
    artifact.write_text(result.final_document.text, encoding="utf-8")
    written = write_artifacts(result.provenance, artifact, level="full", outline=outline)

    for path in written.written():
        assert secret not in path.read_text(encoding="utf-8"), f"{path.name} leaked the credential"


def test_redaction_reaches_a_field_added_later(tmp_path):
    """The scrub walks the record rather than naming carriers one at a time."""
    from howlwriter.domain.generation_provenance import GenerationProvenance
    from howlwriter.provenance.assemble import finalize

    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    provenance = GenerationProvenance(
        run_id="r",
        gaps=[f"needs the token {secret}"],
        warnings=[f"saw {secret} in the draft"],
        coverage={"findings": [{"text": f"literal {secret} here", "status": "PRESENT"}]},
        added_claims=[{"claim": f"uses {secret}", "basis": "x"}],
    )
    cleaned = finalize(provenance, level="full").to_json()

    assert secret not in cleaned
    assert "REDACTED" in cleaned


_BACKEND = None


def _bridge_with(body: str):
    global _BACKEND
    stdout = (
        "```yaml\nbody_markdown: |\n  " + body + "\nadded_claims: []\ngaps: []\nwarnings: []\n```"
    )
    _, backend = _bridge(agent_id="fake", stdout=stdout)
    _BACKEND = backend
    return backend
