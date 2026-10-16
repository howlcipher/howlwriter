"""Categories, authorship proposals, and the attestation workflow."""

from __future__ import annotations

import pytest
import yaml

from howlwriter.voice.corpus.cleanup import clean_document
from howlwriter.voice.corpus.features import extract_features
from howlwriter.voice.corpus import quality as quality_stage
from howlwriter.voice.identity import classify, review
from howlwriter.voice.identity.provenance import ProvenanceSignals, collect
from howlwriter.voice.identity.scanner import scan
from howlwriter.voice.identity.store import IdentityStore, parse_paragraph_ranges

from tests.voice.identity.conftest import attest_all, author_a


def _classify(
    text: str, context: str = "academic", filename: str = "doc.md"
) -> classify.Classification:
    cleaned = clean_document(text)
    features = extract_features(cleaned.text, headings=len(cleaned.headings))
    quality = quality_stage.classify_document(
        filename=filename, raw_text=text, cleanup=cleaned, features=features
    )
    return classify.classify_category(
        quality=quality,
        context=context,
        context_confidence=0.6,
        text=cleaned.text,
        words=features.words,
        first_person_rate=features.first_person_rate,
        list_rate=features.list_rate,
        heading_rate=features.heading_rate,
        filename=filename,
    )


LICENSE = (
    "## zlib v1.3\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy of this "
    "software and associated documentation files, to deal in the software without restriction. "
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. '
) * 6


def test_license_text_is_copied_reference_and_never_reviewed():
    result = _classify(LICENSE)
    assert result.category == classify.COPIED_REFERENCE
    proposal = classify.propose_authorship(
        classification=result,
        provenance=ProvenanceSignals(),
        filename="zlib.md",
    )
    assert proposal.authorship == classify.THIRD_PARTY
    assert proposal.needs_review is False


def test_lab_prose_with_undecided_context_still_reaches_review():
    text = (
        "I ran the capture in the virtual machine and the terminal output shows the alert. "
        "Figure 2 is a screenshot of the Wireshark command I ran, and the timing "
        "matched what the earlier capture had suggested about the retransmissions. "
    ) * 16
    result = _classify(text, context="unknown")
    assert result.category == classify.ACADEMIC_LAB
    assert result.context == "academic"


def test_proposals_never_confirm_and_name_their_reasons():
    classification = classify.Classification(category=classify.ACADEMIC_PAPER, context="academic")
    proposal = classify.propose_authorship(
        classification=classification,
        provenance=ProvenanceSignals(byline_identity=True, predates_llm_era=False),
        filename="paper.docx",
    )
    assert proposal.authorship == classify.UNKNOWN_AUTHORSHIP
    assert proposal.needs_review and proposal.affects_profile
    assert "AI-assisted drafting was possible" in proposal.reasons[0]


def test_pre_llm_bylined_document_is_proposed_human_but_still_needs_review():
    classification = classify.Classification(category=classify.ACADEMIC_PAPER, context="academic")
    signals = ProvenanceSignals(byline_identity=True, predates_llm_era=True)
    proposal = classify.propose_authorship(
        classification=classification, provenance=signals, filename="x"
    )
    assert proposal.authorship == classify.CONFIRMED_HUMAN_AUTHORED
    assert proposal.needs_review is True
    auto = classify.propose_authorship(
        classification=classification,
        provenance=signals,
        filename="x",
        auto_accept_pre_llm_bylined=True,
    )
    assert auto.needs_review is False


@pytest.mark.parametrize(
    "signals, expected",
    [
        (ProvenanceSignals(ownership="shared_with_me"), classify.THIRD_PARTY),
        (ProvenanceSignals(byline_other_person=True), classify.THIRD_PARTY),
        (ProvenanceSignals(generated_by_library=True), classify.UNKNOWN_AUTHORSHIP),
    ],
)
def test_provenance_signals_drive_proposals(signals, expected):
    classification = classify.Classification(category=classify.ACADEMIC_PAPER, context="academic")
    assert (
        classify.propose_authorship(
            classification=classification, provenance=signals, filename="x"
        ).authorship
        == expected
    )


def test_style_signals_raise_priority_but_never_decide():
    classification = classify.Classification(category=classify.ACADEMIC_PAPER, context="academic")
    plain = classify.propose_authorship(
        classification=classification, provenance=ProvenanceSignals(), filename="x"
    )
    styled = classify.propose_authorship(
        classification=classification,
        provenance=ProvenanceSignals(),
        filename="x",
        naturalness_values={"formulaic_density": 12.0},
    )
    assert styled.authorship == plain.authorship
    assert styled.review_priority > plain.review_priority
    assert "not evidence of authorship" in styled.style_signals[0]


def test_byline_detection_distinguishes_identity_from_others():
    mine = collect(
        suffix=".md",
        raw=b"",
        text="William Elias\nINFA 700\n\nBody.",
        mtime=1.7e9,
        aliases=["William Elias"],
    )
    theirs = collect(
        suffix=".md",
        raw=b"",
        text="Name: Jordan Smith\n\nBody.",
        mtime=1.7e9,
        aliases=["William Elias"],
    )
    assert mine.byline_identity and not mine.byline_other_person
    assert theirs.byline_other_person and not theirs.byline_identity
    assert (
        collect(suffix=".md", raw=b"", text="x", mtime=1.6e9, aliases=[]).predates_llm_era is True
    )


def test_paragraph_ranges():
    assert parse_paragraph_ranges("1-3,7") == {0, 1, 2, 6}
    with pytest.raises(ValueError):
        parse_paragraph_ranges("3-1")
    with pytest.raises(ValueError):
        parse_paragraph_ranges("0")


def test_attestation_is_recorded_logged_and_clears_the_queue(env, drive):
    scan("william", sources=[str(drive)])
    store = IdentityStore("william")
    before = len(review.queue(store))
    attested = attest_all("william", "school/")
    assert attested > 0
    assert len(review.queue(store)) < before or before == 0
    log = (store.directory / "decisions.log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == attested


def test_attest_validates_input(env, drive):
    scan("william", sources=[str(drive)])
    store = IdentityStore("william")
    doc_id = next(iter(store.load_inventory()["entries"]))
    with pytest.raises(ValueError):
        review.attest(store, doc_id, "PROBABLY_ME")
    with pytest.raises(ValueError):
        review.attest(store, doc_id, "h", include_paragraphs="1-2")
    with pytest.raises(ValueError):
        review.attest(store, doc_id, "m", include_paragraphs="900")
    with pytest.raises(ValueError):
        review.attest(store, "nope", "h")


def test_light_edit_carries_decision_forward_and_rewrite_reopens_it(env, drive):
    scan("william", sources=[str(drive)])
    attest_all("william", "school/lab05")
    path = drive / "school" / "lab05.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("Lab Report", "Lab Report (final)"), encoding="utf-8")
    report = scan("william").report
    assert report["decisions"]["carried_forward_this_scan"] == 1
    path.write_text(author_a(4242), encoding="utf-8")
    report = scan("william").report
    assert report["decisions"]["reopened_this_scan"] == 1
    store = IdentityStore("william")
    assert any(item.reopened for item in review.queue(store))


def test_worksheet_round_trip(env, drive):
    outcome = scan("william", sources=[str(drive)])
    store = IdentityStore("william")
    data = yaml.safe_load(outcome.review_queue_path.read_text(encoding="utf-8"))
    pending = data["pending"]
    if not pending:
        pytest.skip("fixture produced no reviewable documents")
    pending[0]["decision"] = "CONFIRMED_HUMAN_AUTHORED"
    pending[0]["category_override"] = "academic_lab"
    outcome.review_queue_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = review.apply_worksheet(store, outcome.review_queue_path)
    assert result["applied"] == 1 and result["errors"] == 0
    assert store.load_decisions()[pending[0]["doc_id"]].category == "academic_lab"


def test_preview_is_numbered_and_refuses_excluded_paths(env, drive):
    scan("william", sources=[str(drive)])
    store = IdentityStore("william")
    doc_id, entry = next(
        (k, v)
        for k, v in store.load_inventory()["entries"].items()
        if v["relative_path"] == "school/lab00.md"
    )
    lines = review.preview(store, doc_id)
    assert lines[0].startswith("[1] ")
    inventory = store.load_inventory()
    inventory["entries"][doc_id]["relative_path"] = "Gemini Gems/sneaky.md"
    store.save_inventory(inventory)
    with pytest.raises(ValueError):
        review.preview(store, doc_id)


def test_a_decision_pins_the_category_shown_so_reclassification_cannot_move_it(env, drive):
    from howlwriter.voice.identity.profiles import select_sources

    scan("william", sources=[str(drive)])
    store = IdentityStore("william")
    entries = store.load_inventory()["entries"]
    doc_id, entry = next((k, e) for k, e in entries.items() if e["relative_path"] == "school/lab01.md")
    shown = entry["classification"]["category"]
    assert classify.CATEGORY_CONTEXT.get(shown) == "academic"
    decision = review.attest(store, doc_id, "h")
    assert decision.category == shown

    inventory = store.load_inventory()
    inventory["entries"][doc_id]["classification"]["category"] = classify.UNKNOWN  # a later classifier
    store.save_inventory(inventory)
    config = store.load_config()
    chosen, _ = select_sources(
        config, store.load_inventory()["entries"], store.load_decisions(), config.profiles["academic"]
    )
    assert doc_id in {c.doc_id for c in chosen}
