"""Drafting in parts that fit the model, and bringing each part closer to the person's voice."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from howlwriter.integration.howlplane_bridge import set_howlplane_bridge
from howlwriter.projects import voice_fidelity as vf
from howlwriter.projects import writing
from howlwriter.projects.scan import Extractors, scan_project
from howlwriter.projects.workspace import ProjectWorkspace
from howlwriter.projects.writing import build_brief, draft, plan_parts, render_prompt
from howlwriter.voice import exemplars

from tests.projects.conftest import FakeOcr, Off


@pytest.fixture
def project(lab_folder, private_dirs):
    pytest.importorskip("pypdf")
    workspace = ProjectWorkspace.create(lab_folder)
    extractors = Extractors(ocr=FakeOcr(), transcriber=Off())
    scan_project(workspace, extractors=extractors)
    extractors.close()
    return workspace


class ScriptedBridge:
    """A writer that answers each call from a script; records every prompt."""

    def __init__(self, provider: str, answers=None):
        self.registry = SimpleNamespace(get_binding=lambda domain, role: SimpleNamespace(provider=provider))
        self.calls: list[dict] = []
        self.answers = answers

    def is_available(self) -> bool:
        return True

    def execute_writing_role(self, role, prompt, system_instruction=None, **kwargs):
        self.calls.append({"prompt": prompt, "system": system_instruction, **kwargs})
        body = self.answers(prompt, system_instruction) if self.answers else "## Part\n\nText [MISSING: x]."
        return SimpleNamespace(success=True, raw_output=body, structured_output=None, provider="fake",
                               error_message="")


def _voice_config(tmp_path, private_dirs, bank_paragraphs=None):
    from howlwriter.config.defaults import default_config
    from howlwriter.voice.corpus.build import build_voice
    from howlwriter.voice.selection import apply_selection

    from tests.voice.corpus.conftest import synthetic_prose

    corpus = tmp_path / "voice-corpus"
    corpus.mkdir()
    for index in range(10):
        (corpus / f"d{index}.md").write_text(synthetic_prose(index), encoding="utf-8")
    build_voice("tester-academic", [corpus], store_root=private_dirs / "voices", deterministic_only=True)
    if bank_paragraphs is not None:
        bank = {"version": 1, "paragraphs": bank_paragraphs}
        (private_dirs / "voices" / "tester-academic" / exemplars.EXEMPLARS_FILE).write_text(json.dumps(bank))
    config = default_config()
    apply_selection(config, voice="tester-academic")
    return config


BANK = [{"doc": "d1", "weight": 1.0, "authorship": "CONFIRMED_HUMAN_AUTHORED", "words": 60, "text": None}]
PARAGRAPH = (
    "I ran the capture twice because the first one missed the handshake. The second run was cleaner, "
    "and it showed what I expected: the server certificate never crossed the wire in plain text. That "
    "matters for the IDS, since a rule that keys on the certificate has nothing to read."
)
BANK[0]["text"] = PARAGRAPH


# --- style example bank ---------------------------------------------------------------


def test_bank_keeps_prose_paragraphs_only_and_fully_attested_first():
    text = "\n\n".join(
        [
            "# Heading",
            "- a list item that is long enough to count as words but is a list item " * 3,
            "Short.",
            PARAGRAPH,
            "Visit http://example.com for " + "more words here " * 15 + ".",
        ]
    )
    bank = exemplars.build_bank([("a", text, 0.5, "HUMAN_AUTHORED_LIGHT_AI_EDITING"),
                                 ("b", PARAGRAPH, 1.0, "CONFIRMED_HUMAN_AUTHORED")])
    texts = [p["text"] for p in bank["paragraphs"]]
    assert texts == [PARAGRAPH, PARAGRAPH]
    assert bank["paragraphs"][0]["weight"] == 1.0  # fully attested first


def test_choose_takes_one_passage_per_document_within_the_budget():
    bank = [
        {"doc": "a", "weight": 1.0, "words": 60, "text": PARAGRAPH},
        {"doc": "a", "weight": 1.0, "words": 60, "text": PARAGRAPH + " Again."},
        {"doc": "b", "weight": 0.5, "words": 40, "text": "Certificates and handshakes differ. " * 4},
    ]
    chosen = exemplars.choose(bank, "certificate handshake capture", max_chars=10_000)
    assert len(chosen) == 2 and chosen[0] == PARAGRAPH
    assert exemplars.choose(bank, "x", max_chars=50) == []
    assert "Never copy their content" in exemplars.render(chosen)


def test_identity_profile_build_writes_a_private_bank_from_training_documents_only(tmp_path, monkeypatch):
    import stat

    from howlwriter.voice.corpus.store import VoiceStore
    from howlwriter.voice.identity.profiles import build_identity
    from howlwriter.voice.identity.scanner import scan

    from tests.voice.identity.conftest import attest_all, author_a

    monkeypatch.setenv("HOWLWRITER_IDENTITIES_DIR", str(tmp_path / "ids"))
    monkeypatch.setenv("HOWLWRITER_VOICES_DIR", str(tmp_path / "voices"))
    monkeypatch.setenv("HOWLWRITER_PREFERENCES_FILE", str(tmp_path / "prefs.yaml"))
    root = tmp_path / "drive" / "school"
    root.mkdir(parents=True)
    for index in range(16):
        (root / f"lab{index:02d}.md").write_text(author_a(index), encoding="utf-8")
    scan("william", sources=[str(tmp_path / "drive")])
    attest_all("william", "school/", "h", category="academic_lab")
    assert {r.profile: r for r in build_identity("william")}["academic"].status == "built"
    store = VoiceStore("william-academic")
    path = store.directory / exemplars.EXEMPLARS_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    bank = exemplars.load_bank(store.directory)
    assert bank, "attested prose should yield style examples"

    def doc_id(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    sources = store.load_sources()
    holdout = {doc_id(k) for k, r in sources.items() if r.split == "holdout"}
    train = {doc_id(k) for k, r in sources.items() if r.split == "train"}
    banked = {p["doc"] for p in bank}
    assert holdout and not holdout & banked and banked <= train


# --- measurement and revision guards -------------------------------------------------


def test_compact_voice_block_keeps_measurements_and_drops_long_rules(tmp_path, private_dirs):
    from howlwriter.domain.modes import parse_mode
    from howlwriter.humanize.rewriter import _load_voice_profile
    from howlwriter.voice.application import render_profile

    config = _voice_config(tmp_path, private_dirs)
    full = render_profile(_load_voice_profile(config.voice_profile), parse_mode("academic"))
    compact = vf.compact_voice_block(full)
    assert len(compact) < len(full)
    assert "GLOBAL TENDENCIES" in compact and "HOW TO USE THIS VOICE (short form)" in compact
    assert "HOW TO APPLY THIS VOICE" not in compact and "PRESENCE ACROSS PIECES" not in compact
    assert vf.compact_voice_block("legacy block") == "legacy block"


def test_a_revision_must_keep_every_marker_placeholder_heading_and_number():
    original = "## Results\n\nThe capture had 62 frames [ev-0123456789ab]. [MISSING: alert screenshot]"
    good = "## Results\n\nThere were 62 frames in the capture [ev-0123456789ab]. [MISSING: alert screenshot]"
    assert vf.revision_preserved(original, good) == (True, "")
    assert not vf.revision_preserved(original, good.replace("[ev-0123456789ab]", ""))[0]
    assert not vf.revision_preserved(original, good.replace(" [MISSING: alert screenshot]", ""))[0]
    assert not vf.revision_preserved(original, good.replace("## Results\n\n", ""))[0]
    more = good.replace("62 frames", "62 frames and 7 alerts")
    assert "numbers" in vf.revision_preserved(original, more)[1]
    assert not vf.revision_preserved(original, "  ")[0]


def test_style_feedback_turns_drift_findings_into_instructions(monkeypatch):
    def fake_evaluate(text, *, mode=None, voice=None, **kwargs):
        assert "[ev-" not in text and "## " not in text  # measured as prose
        return {"drift": {"findings": [
            {"severity": "minor", "message": "ignored", "suggestion": ""},
            {"severity": "notable", "message": "uses longer sentences (31 words).",
             "suggestion": "Split some."},
            {"severity": "strong", "message": "repeats sentence openings.", "suggestion": "Vary them."},
        ]}}

    monkeypatch.setattr("howlwriter.evaluation.personal.evaluate_text", fake_evaluate)
    text = "## A\n\n" + ("The draft says a thing [ev-0123456789ab]. " * 40)
    lines = vf.style_feedback(text, "tester-academic", "academic")
    assert lines == [
        "The draft repeats sentence openings. Vary them.",
        "The draft uses longer sentences (31 words). Split some.",
    ]
    assert vf.style_feedback("## A\n\nToo short.", "v", "academic") == []


# --- drafting in parts -------------------------------------------------------------------


def test_parts_fit_the_budget_and_an_oversized_section_keeps_its_best_evidence():
    evidence = [{"evidence_id": f"ev-{i:012x}", "citation": "c", "status": "directly_observed",
                 "category": "experimental_evidence", "excerpt": "x" * 400} for i in range(8)]
    brief = {"sections": [{"title": f"S{i}", "requirements": [], "missing": [], "evidence": list(evidence)}
                          for i in range(6)]}
    budget = 2_500
    parts = plan_parts(brief, budget)
    assert [i for part in parts for i in part] == list(range(6)) and len(parts) > 1
    for part in parts:
        assert len(render_prompt({"sections": [brief["sections"][i] for i in part]})) <= budget * 1.05
    assert all(s["evidence"][0]["evidence_id"] == "ev-000000000000" for s in brief["sections"])


def test_a_large_lab_is_drafted_in_parts_for_a_local_model(project, tmp_path, private_dirs, monkeypatch):
    config = _voice_config(tmp_path, private_dirs, bank_paragraphs=BANK)
    monkeypatch.setattr(writing, "LOCAL_PROMPT_CHARS", 9_000)
    bridge = ScriptedBridge("ollama", answers=lambda prompt, system: "## Section\n\nWritten part.")
    set_howlplane_bridge(bridge)
    result = draft(project, build_brief(project), config=config, revise=False)
    calls = bridge.calls
    assert len(calls) == result["provenance"]["parts"] > 1
    assert all(len(c["system"]) + len(c["prompt"]) <= 9_000 for c in calls)
    assert f"This is part 1 of {len(calls)}" in calls[0]["prompt"]
    assert "PREVIOUS PART ENDED WITH" in calls[1]["prompt"] and "Written part." in calls[1]["prompt"]
    assert "## STYLE EXAMPLES" in calls[0]["prompt"] and PARAGRAPH in calls[0]["prompt"]
    assert "HOW TO USE THIS VOICE (short form)" in calls[0]["prompt"]  # compact voice for local
    assert result["provenance"]["voice_examples"]["shown"] >= 1


def test_remote_models_get_no_style_examples_unless_asked(project, tmp_path, private_dirs):
    from howlwriter.projects.service import authorize_remote

    config = _voice_config(tmp_path, private_dirs, bank_paragraphs=BANK)
    authorize_remote(project, True)
    bridge = ScriptedBridge("claude")
    set_howlplane_bridge(bridge)
    draft(project, build_brief(project), config=config, revise=False)
    assert all(PARAGRAPH not in c["prompt"] for c in bridge.calls)
    assert "HOW TO APPLY THIS VOICE" in bridge.calls[0]["prompt"]  # full voice description for remote
    bridge.calls.clear()
    draft(project, build_brief(project), config=config, revise=False, voice_examples="on")
    assert any(PARAGRAPH in c["prompt"] for c in bridge.calls)


def test_a_part_is_revised_toward_the_voice_only_when_the_revision_keeps_the_evidence(
    project, tmp_path, private_dirs, monkeypatch
):
    config = _voice_config(tmp_path, private_dirs)
    original = "## Results\n\nThe capture had 62 frames [ev-0123456789ab]."

    def answers(prompt, system):
        if system == writing.REVISE_INSTRUCTION:
            return "## Results\n\nThere were 62 frames in the capture [ev-0123456789ab]."
        return original

    monkeypatch.setattr(vf, "style_feedback", lambda text, voice, mode: ["The draft uses longer sentences."])
    set_howlplane_bridge(ScriptedBridge("ollama", answers=answers))
    result = draft(project, build_brief(project), config=config)
    assert "There were 62 frames" in result["text"]
    assert all(r["applied"] for r in result["provenance"]["voice_revisions"])
    assert result["provenance"]["voice_revisions"][0]["differences"] == ["The draft uses longer sentences."]

    def bad_answers(prompt, system):
        if system == writing.REVISE_INSTRUCTION:
            return "## Results\n\nThere were 62 frames and 9 alerts."
        return original

    set_howlplane_bridge(ScriptedBridge("ollama", answers=bad_answers))
    result = draft(project, build_brief(project), config=config)
    assert "The capture had 62 frames [ev-0123456789ab]." in result["text"]
    assert not any(r["applied"] for r in result["provenance"]["voice_revisions"])
    assert "evidence markers" in result["provenance"]["voice_revisions"][0]["rejected_because"]


def test_draft_reports_scores_from_the_local_evaluator(project, tmp_path, private_dirs):
    config = _voice_config(tmp_path, private_dirs)
    set_howlplane_bridge(ScriptedBridge("ollama", answers=lambda p, s: "## A\n\n" + PARAGRAPH * 4))
    scores = draft(project, build_brief(project), config=config, revise=False)["provenance"]["scores"]
    assert "voice_match" in scores and "naturalness" in scores and "not who wrote it" in scores["note"]


# --- citation repair -------------------------------------------------------------------------

CLAIM = "## Findings\n\nSuricata raised alerts on the TLS 1.3 capture and the certificate was encrypted."


def _offered_marker(prompt: str) -> str:
    import re

    section = prompt.split("## EVIDENCE", 1)[1]
    return re.search(r"\[(ev-[0-9a-f]+)\]", section).group(1)


def test_uncited_claims_get_one_citation_repair_that_uses_only_offered_markers(
    project, tmp_path, private_dirs
):
    config = _voice_config(tmp_path, private_dirs)

    def answers(prompt, system):
        if system == writing.GROUNDING_INSTRUCTION:
            marker = _offered_marker(prompt)
            return f"```markdown\n[MISSING: alert screenshot] for the alerts. [{marker}]\n```"
        return CLAIM

    set_howlplane_bridge(ScriptedBridge("ollama", answers=answers))
    result = draft(project, build_brief(project), config=config, revise=False)
    repair = result["provenance"]["grounding_repairs"][0]
    assert repair["problems_before"] >= 1
    # The fenced repair removed the heading, so it is refused and the original kept.
    assert repair["applied"] is False and "headings" in repair["rejected_because"]

    def good(prompt, system):
        if system == writing.GROUNDING_INSTRUCTION:
            marker = _offered_marker(prompt)
            return f"```markdown\n## Findings\n\nThe capture is described in the evidence [{marker}]. " \
                   "[MISSING: screenshot of the Suricata alerts]\n```"
        return CLAIM

    set_howlplane_bridge(ScriptedBridge("ollama", answers=good))
    result = draft(project, build_brief(project), config=config, revise=False)
    repair = result["provenance"]["grounding_repairs"][0]
    assert repair["applied"] is True and repair["problems_after"] < repair["problems_before"]
    assert "[MISSING: screenshot of the Suricata alerts]" in result["text"] and "```" not in result["text"]


def test_a_repair_that_invents_a_marker_or_a_number_is_refused():
    allowed = {"ev-aaaaaaaaaaaa"}
    before = [{"type": "unsupported_claim", "sentence": "x"}]
    original = "## A\n\nThe capture was large."

    def check(repaired, after=()):
        return writing._repair_acceptable(original, repaired, allowed, before, list(after))

    assert "not offered" in check("## A\n\nIt was large [ev-bbbbbbbbbbbb].")[1]
    assert "numbers" in check("## A\n\nIt had 9000 packets [ev-aaaaaaaaaaaa].")[1]
    assert "did not reduce" in check("## A\n\nIt was large [ev-aaaaaaaaaaaa].", before)[1]
    assert check("## A\n\nIt was large [ev-aaaaaaaaaaaa].") == (True, "")


def test_a_revision_that_reads_further_from_the_voice_is_not_kept(
    project, tmp_path, private_dirs, monkeypatch
):
    config = _voice_config(tmp_path, private_dirs)
    original = "## Results\n\nThe capture is described elsewhere. [MISSING: alert screenshot]"
    revised = "## Results\n\nThe capture, as described elsewhere, is here. [MISSING: alert screenshot]"

    def answers(prompt, system):
        return revised if system == writing.REVISE_INSTRUCTION else original

    monkeypatch.setattr(vf, "style_feedback", lambda text, voice, mode: ["The draft uses longer sentences."])
    monkeypatch.setattr(
        vf, "style_distance", lambda text, voice, mode: 4.0 if "as described" in text else 3.0
    )
    set_howlplane_bridge(ScriptedBridge("ollama", answers=answers))
    result = draft(project, build_brief(project), config=config)
    (revision,) = result["provenance"]["voice_revisions"]
    assert revision["applied"] is False and "closer" in revision["rejected_because"]
    assert (revision["distance_before"], revision["distance_after"]) == (3.0, 4.0)
    assert original.split("\n\n")[1] in result["text"]


def test_every_model_draft_is_validated_and_the_verdict_saved(project, tmp_path, private_dirs):
    config = _voice_config(tmp_path, private_dirs)
    set_howlplane_bridge(ScriptedBridge("ollama", answers=lambda p, s: CLAIM))
    validation = draft(project, build_brief(project), config=config, revise=False)["provenance"]["validation"]
    assert validation["verdict"] in ("BLOCKED", "INCOMPLETE")
    assert validation["issue_counts"].get("unsupported_claim", 0) >= 1
