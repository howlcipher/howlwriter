"""The academic pipeline must hand its structural realization to the humanizer.

The pipeline derives a realization, records it in provenance, and passes it to
the writer. If it then calls the humanizer without it, the humanizer renders
corpus-wide averages and pulls the writer's varied draft back toward the mean --
while provenance still claims the realization applied. Nothing else in the
pipeline would surface that, so it is asserted directly.

`tests/voice/test_realization_wiring.py` proves the keyword is spelled at every
call site; this proves a real realization actually arrives at this one.
"""

from datetime import date

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.config.defaults import default_config
from howlwriter.domain.source import Source, SourceType
from howlwriter.domain.voice import StructuralVector, VoiceContext, VoiceProfile
from howlwriter.humanize.rewriter import ModelHumanizerRewriter
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

BACKEND_STDOUT = """```yaml
body_markdown: |
  # Zero Trust and Autonomous AI Agents

  ## Introduction
  Autonomous AI agents represent an emerging paradigm in distributed computing (Oladimeji, 2025).

  ## Conclusion
  Cryptographic zero-trust policies ensure verifiable posture.
claims_made: []
verdict: "PASS"
differences: []
rationale: "Rigorous factual alignment."
warnings: []
```"""


def _academic_profile() -> VoiceProfile:
    """A profile whose academic anchors are length-compatible with the spec.

    The vectors have to sit inside the engine's 0.5x-2x length window around the
    50-word target, otherwise selection falls through to the no-guidance path and
    the test would pass on a realization that carries nothing.
    """
    vectors = [
        StructuralVector(
            context="academic",
            words=60,
            paragraphs=3,
            paragraph_words_mean=20.0,
            paragraph_sentences_mean=2.0,
            sentence_length_mean=19.0,
            sentence_length_stdev=6.0,
            short_sentence_rate=0.10,
            long_sentence_rate=0.20,
            transition_rate=0.04,
            opening_class="background",
            closing_class="forward_looking",
        ),
        StructuralVector(
            context="academic",
            words=90,
            paragraphs=4,
            paragraph_words_mean=22.5,
            paragraph_sentences_mean=2.5,
            sentence_length_mean=21.0,
            sentence_length_stdev=7.0,
            short_sentence_rate=0.05,
            long_sentence_rate=0.25,
            transition_rate=0.03,
            opening_class="background",
            closing_class="forward_looking",
        ),
    ]
    return VoiceProfile(
        author_name="wiring_test",
        version=3,
        profile_name="wiring_test",
        generated_from="corpus_build",
        contexts={
            "academic": VoiceContext(
                name="academic",
                document_count=2,
                word_count=150,
                confidence=0.8,
                structural_vectors=list(vectors),
            )
        },
        structural_vectors=vectors,
    )


def test_academic_pipeline_forwards_realization_to_humanizer(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    # The humanizer stage is skipped entirely unless the role is bound, which
    # would make the assertion below vacuous.
    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(domain="writing", role="humanizer", provider="fake")
    )
    set_howlplane_bridge(
        HowlPlaneWritingBridge(
            dispatcher=RoleDispatcher(binding_registry=registry), registry=registry
        )
    )

    monkeypatch.setattr(
        "howlwriter.humanize.rewriter._load_voice_profile",
        lambda _path: _academic_profile(),
    )

    captured: dict = {}
    original_rewrite = ModelHumanizerRewriter.rewrite

    def capturing_rewrite(self, document, config, **kwargs):
        captured.update(kwargs)
        return original_rewrite(self, document, config, **kwargs)

    monkeypatch.setattr(ModelHumanizerRewriter, "rewrite", capturing_rewrite)

    source = Source(
        id="S001",
        title="Zero Trust Governance for Autonomous AI Agents",
        authors=["Oladimeji, Ganiyu"],
        publication_date=date(2025, 3, 1),
        publisher="Elsevier BV",
        doi="10.2139/ssrn.7194038",
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text=(
            "Autonomous AI agents represent an emerging paradigm in distributed computing."
        ),
    )
    spec = AssignmentSpec(
        title="Zero Trust and Autonomous AI Agents",
        topic="Examine how autonomous AI agents complicate identity and access control.",
        target_words=50,
        word_tolerance_percent=30.0,
        outline=["Introduction", "Conclusion"],
        source_requirements=dict(minimum_sources=1),
    )

    cfg = default_config()
    cfg.voice_profile = str(tmp_path / "profile.json")

    run_academic_pipeline(
        spec,
        cfg,
        existing_sources=[source],
        custom_backend=FakeAgentBackend(
            agent_id="fake_academic_backend",
            default_stdout=BACKEND_STDOUT,
        ),
    )

    assert "realization" in captured, (
        "the academic pipeline called the humanizer without realization=; "
        "the humanizer would render corpus-wide averages instead"
    )
    realization = captured["realization"]
    assert realization is not None
    assert realization.selection_method == "EMPIRICAL_JOINT_ANCHOR_VECTOR"
