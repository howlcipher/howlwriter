from howlwriter.domain.source import (
    ORIGIN_ASSIGNMENT_MATERIALS,
    RELEVANCE_IRRELEVANT,
)
from howlwriter.materials import derive_requirements, extract_requirement_lines, materials_to_sources, scan_materials
from tests.materials.builders import build_package


def test_requirement_extraction_is_deterministic_and_bounded():
    text = "Intro paragraph.\n- Explain the thing in depth\n1. Discuss the other thing carefully\nYou must cite two sources."
    lines = extract_requirement_lines(text)
    assert lines == [
        "Explain the thing in depth",
        "Discuss the other thing carefully",
        "You must cite two sources.",
    ]
    assert extract_requirement_lines(text) == lines


def test_derived_requirements_skip_duplicates_and_are_ledgered(tmp_path):
    build_package(tmp_path / "p")
    scan = scan_materials(tmp_path / "p")
    new = derive_requirements(scan, existing=["explain microsegmentation and lateral movement"])
    assert "Explain microsegmentation and lateral movement" not in new
    assert "Discuss identity and device posture" in new
    ids = {d["material_id"] for d in scan.ledger.derived_requirements}
    by_id = {r.material_id: r for r in scan.ledger.records}
    assert all(by_id[i].may_be_requirements for i in ids)


def test_only_extracted_evidence_roles_become_sources(tmp_path):
    build_package(tmp_path / "p", with_pdf=False)
    scan = scan_materials(tmp_path / "p")
    sources = materials_to_sources(scan)
    titles = {s.material_id: s for s in sources}
    by_id = {r.material_id: r for r in scan.ledger.records}
    for mid in titles:
        assert by_id[mid].may_be_evidence
    names = {by_id[m].name for m in titles}
    assert names == {"lecture-notes.md", "reference-document.docx"}  # no instructions, rubric, pcap
    for s in sources:
        assert s.origin == ORIGIN_ASSIGNMENT_MATERIALS
        assert s.evidence_depth == "FULL_TEXT" and s.is_substantive_evidence
        assert s.content_sha256
        assert str(tmp_path) not in s.reliability_notes


def test_relevance_classifier_is_applied_and_can_reject(tmp_path):
    build_package(tmp_path / "p", with_pdf=False)
    scan = scan_materials(tmp_path / "p")
    sources = materials_to_sources(scan, classify_relevance=lambda s: RELEVANCE_IRRELEVANT)
    assert sources and all(not s.is_usable for s in sources)
