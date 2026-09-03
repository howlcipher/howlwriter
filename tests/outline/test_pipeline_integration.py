"""Outline mode through the real pipeline, with the fake provider seam.

What these cover that the unit tests cannot: that the outline's guarantees are
checked against the FINAL artifact rather than the writer's draft. A guarantee
that survives the writer and dies in the humanizer is not a guarantee, and the
humanizer is the stage most likely to smooth a verbatim sentence.
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

from howlwriter.config.defaults import default_config
from howlwriter.domain.generation_provenance import MODEL_NOT_REPORTED
from howlwriter.domain.outline import load_outline
from howlwriter.pipeline.howl import run_howl_pipeline

_VERBATIM = "If every company has access to the same models, using AI isn't really a moat."

_OUTLINE = {
    "topic": "AI moats",
    "mode": "linkedin",
    "target_words": 200,
    "nodes": [
        {"kind": "preserve", "text": _VERBATIM},
        {"kind": "claim", "text": "Implementation cost creates competitive friction."},
        {"kind": "required_point", "text": "proprietary data and distribution"},
    ],
}

_BODY = (
    f"{_VERBATIM}\n\n"
    "Implementation cost creates competitive friction between firms.\n\n"
    "What survives is proprietary data and distribution."
)


def _writer_yaml(body: str, added: str = "") -> str:
    claims = (
        f'added_claims:\n  - claim: "{added}"\n    basis: "general knowledge"\n'
        if added
        else "added_claims: []\n"
    )
    indented = "\n".join(f"  {line}" for line in body.splitlines())
    return f"```yaml\nbody_markdown: |\n{indented}\n{claims}gaps: []\nwarnings: []\n```"


def _configure(stdout: str):
    registry = RoleBindingRegistry()
    for role in ("writer", "humanizer", "final_reviewer"):
        registry.register_binding(
            RoleBinding(domain="writing", role=role, provider="fake_provider")
        )
    backend = FakeAgentBackend(agent_id="fake_provider", default_stdout=stdout)
    set_howlplane_bridge(
        HowlPlaneWritingBridge(
            dispatcher=RoleDispatcher(binding_registry=registry), registry=registry
        )
    )
    return backend


def test_an_outline_produces_an_artifact_with_no_input_file():
    backend = _configure(_writer_yaml(_BODY))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )

    assert result.final_document.text.strip()
    assert result.coverage is not None
    assert result.coverage.status == "PASS"
    assert result.provenance is not None
    assert result.provenance.workflow == "howl-outline"
    assert result.provenance.complete is True


def test_coverage_is_checked_against_the_final_artifact_not_the_draft():
    """The humanizer runs after the writer, and can undo what the writer honoured."""
    backend = _configure(_writer_yaml(_BODY))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )
    from howlwriter.domain.generation_provenance import sha256_text

    assert result.provenance.artifact_sha256 == sha256_text(result.final_document.text)
    stages = [s.name for s in result.provenance.stages]
    assert stages.index("outline_writer") < stages.index("outline_coverage")


def test_a_writer_that_drops_a_required_point_is_caught():
    dropped = _BODY.replace(
        "What survives is proprietary data and distribution.", "Something else entirely."
    )
    backend = _configure(_writer_yaml(dropped))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )

    assert result.coverage.status == "FAIL"
    assert result.report.status == "NEEDS_REVIEW"
    assert any(f.node_id == "required_point_1" for f in result.coverage.missing)


def test_a_writer_that_paraphrases_verbatim_text_is_caught():
    smoothed = _BODY.replace("isn't really a moat", "is not truly a moat")
    backend = _configure(_writer_yaml(smoothed))
    import pytest

    with pytest.raises(RuntimeError, match="verbatim-preserve contract"):
        run_howl_pipeline(
            None,
            default_config(),
            outline=load_outline(_OUTLINE),
            custom_backend=backend,
        )


def test_every_model_call_in_the_run_lands_in_the_provenance():
    backend = _configure(_writer_yaml(_BODY))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )

    roles = [c.role for c in result.provenance.calls]
    assert "writer" in roles
    assert "humanizer" in roles
    assert all(c.user_prompt_sha256 for c in result.provenance.calls)
    assert all(
        c.model_status == MODEL_NOT_REPORTED for c in result.provenance.calls
    ), "the fake provider reports no model, and that must be recorded as such"


def test_the_writer_prompt_carries_the_authority_order_and_the_fabrication_ban():
    backend = _configure(_writer_yaml(_BODY))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )
    writer_call = next(c for c in result.provenance.calls if c.role == "writer")

    assert "AUTHORITY ORDER" in writer_call.user_prompt
    assert "DO NOT INVENT THE AUTHOR'S LIFE" in writer_call.user_prompt
    assert "reproduce EXACTLY" in writer_call.user_prompt
    assert _VERBATIM in writer_call.user_prompt


def test_model_added_claims_are_recorded_rather_than_dropped():
    backend = _configure(_writer_yaml(_BODY, added="Friction protected incumbents"))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )

    assert result.provenance.contribution.model_added_claims == 1
    assert result.provenance.added_claims[0]["claim"] == "Friction protected incumbents"


def test_the_contribution_summary_reports_counts_and_never_a_percentage():
    backend = _configure(_writer_yaml(_BODY))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )
    contribution = result.provenance.contribution

    assert contribution.preserved_supplied == 1
    assert contribution.preserved_retained == 1
    assert contribution.claims_supplied == 1
    assert contribution.user_words_supplied > 0
    payload = contribution.to_dict()
    assert not any("percent" in key or "share" in key for key in payload)
    assert all(isinstance(v, int) for v in payload.values())


def test_a_file_run_still_works_and_records_no_outline():
    backend = _configure(_writer_yaml(_BODY))
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "draft.md"
        target.write_text("A human wrote this paragraph already.\n", encoding="utf-8")
        result = run_howl_pipeline(target, default_config(), custom_backend=backend)

    assert result.coverage is None
    assert result.provenance.outline_present is False
    assert result.provenance.workflow == "howl"


def test_a_run_needs_either_a_path_or_an_outline():
    import pytest

    with pytest.raises(ValueError, match="either a path or an outline"):
        run_howl_pipeline(None, default_config())


def test_sidecars_are_written_beside_the_artifact_and_nowhere_else(tmp_path):
    from howlwriter.provenance.assemble import write_artifacts

    backend = _configure(_writer_yaml(_BODY))
    outline = load_outline(_OUTLINE)
    result = run_howl_pipeline(
        None, default_config(), outline=outline, custom_backend=backend
    )

    artifact = tmp_path / "post.md"
    artifact.write_text(result.final_document.text, encoding="utf-8")
    written = write_artifacts(result.provenance, artifact, outline=outline)

    for path in written.written():
        assert path.parent == tmp_path
    assert written.provenance_json.name == "post.provenance.json"
    assert written.manifest_text.name == "post.manifest.txt"
    assert written.outline_yaml.name == "post.outline.yaml"


def test_a_summary_sidecar_does_not_contain_the_prompts(tmp_path):
    from howlwriter.provenance.assemble import write_artifacts

    backend = _configure(_writer_yaml(_BODY))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )
    artifact = tmp_path / "post.md"
    artifact.write_text("x", encoding="utf-8")
    written = write_artifacts(result.provenance, artifact, level="summary")

    body = written.provenance_json.read_text(encoding="utf-8")
    assert "AUTHORITY ORDER" not in body
    assert "user_prompt_sha256" in body


def test_a_full_sidecar_contains_the_exact_prompts(tmp_path):
    from howlwriter.provenance.assemble import write_artifacts

    backend = _configure(_writer_yaml(_BODY))
    result = run_howl_pipeline(
        None, default_config(), outline=load_outline(_OUTLINE), custom_backend=backend
    )
    artifact = tmp_path / "post.md"
    artifact.write_text("x", encoding="utf-8")
    written = write_artifacts(result.provenance, artifact, level="full")

    body = written.provenance_json.read_text(encoding="utf-8")
    assert "AUTHORITY ORDER" in body


def test_outline_and_deterministic_are_refused_with_a_reason(tmp_path):
    """An outline is not prose yet, so there is nothing to transform.

    Without the guard this surfaced as a bare "writer is not configured",
    which is true but does not tell the user the two flags cannot go together.
    """
    import pytest
    import yaml

    from howlwriter.cli.commands.howl import run

    outline_path = tmp_path / "o.yaml"
    outline_path.write_text(yaml.safe_dump(_OUTLINE), encoding="utf-8")

    class Args:
        path = None
        outline = str(outline_path)
        deterministic = True
        mode = None
        voice = None
        voice_profile = None
        project_config_path = None
        out = None
        target_words = None
        max_words = None
        provenance = False
        provenance_level = "summary"
        mask_paths = False

    with pytest.raises(ValueError, match="cannot be combined with --deterministic"):
        run(Args())


def test_a_path_and_an_outline_together_are_refused(tmp_path):
    import pytest
    import yaml

    from howlwriter.cli.commands.howl import run

    outline_path = tmp_path / "o.yaml"
    outline_path.write_text(yaml.safe_dump(_OUTLINE), encoding="utf-8")
    draft = tmp_path / "draft.md"
    draft.write_text("Already written.\n", encoding="utf-8")

    class Args:
        path = str(draft)
        outline = str(outline_path)
        deterministic = False
        mode = None
        voice = None
        voice_profile = None
        project_config_path = None
        out = None
        target_words = None
        max_words = None
        provenance = False
        provenance_level = "summary"
        mask_paths = False

    with pytest.raises(ValueError, match="not both"):
        run(Args())
