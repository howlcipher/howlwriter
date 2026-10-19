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


#: Slide-style text: sentences wrapped over several lines, as slide extraction leaves them.
WRAPPED_SLIDE = """## slide2
Lab Report - Home Network Audit
For this lab, you will create a short audit of your home network.
Your audit MUST INCLUDE:
A DIAGRAM OF THE NETWORK and
A LIST OF DEVICES as the first item (router, laptop,
or phone), each with its owner.
NOTE
: You will need to follow the
audit checklist
 and record every finding.
In this course you will learn about networks.
"""


def test_wrapped_sentences_are_rejoined_into_whole_requirements():
    lines = extract_requirement_lines(WRAPPED_SLIDE)
    assert lines == [
        "For this lab, you will create a short audit of your home network.",
        "Your audit MUST INCLUDE: A DIAGRAM OF THE NETWORK and A LIST OF DEVICES as the first item "
        "(router, laptop, or phone), each with its owner.",
        "NOTE: You will need to follow the audit checklist and record every finding.",
    ]
    assert not any(line.startswith(":") for line in lines)


def test_a_lead_in_before_bullets_is_not_a_requirement_of_its_own():
    text = "You must include:\n- A diagram of the network\n- A list of the devices"
    assert extract_requirement_lines(text) == ["A diagram of the network", "A list of the devices"]


def test_headings_and_titles_are_not_joined_to_the_sentence_after_them():
    text = "## Lab Two\nHome Network Audit\nYou must submit one report per person."
    assert extract_requirement_lines(text) == ["You must submit one report per person."]


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
