"""End to end: research -> draft -> verify -> edit -> reverify -> render -> publish -> read back -> final validation.

One controlled assignment: a main discussion and two peer replies, three shared
authoritative sources, word limits, known citation errors and a required revision
pass. Everything runs offline: a scripted writer backend, recorded canonical
records and an in-memory destination. The destination is never a real document.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest
import yaml

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.assignment.package import PackageState, check_package, load_package_spec
from howlwriter.citations.verification import RecordFileProvider
from howlwriter.config.defaults import default_config
from howlwriter.domain.source import Source, SourceType
from howlwriter.publishing.base import PublicationArtifact, PublishContext, PublishDestination
from howlwriter.publishing.google.publisher import GoogleDocsPublisher
from howlwriter.review.change_report import build_change_report
from src.control_plane.agent_execution import FakeAgentBackend
from tests.fakes.google_docs import FakeGoogleDocsAdapter

RECORDS = Path(__file__).parents[1] / "fixtures" / "citations" / "canonical_records.json"
BOYENS = ["Boyens, Jon", "Smith, Angela", "Bartol, Nadya", "Winkler, Kris", "Holbrook, Alex", "Fallon, Matthew"]
AUTIO = ["Autio, Chloe", "Schwartz, Reva", "Dunietz, Jesse", "Jain, Shomik", "Stanley, Martin",
         "Tabassi, Elham", "Hall, Patrick", "Roberts, Kamie"]


def _sources(*, sp161_year):
    def make(id_, title, authors, year, doi, text, identifier):
        s = Source(id=id_, title=title, authors=authors, publication_date=date(year, 1, 1), doi=doi,
                   publisher="National Institute of Standards and Technology", access_date=date.today(),
                   source_type=SourceType.REPORT, retrieved_text=text)
        s.freshness.document_identifier = identifier
        return s

    return [
        make("S001", "Artificial intelligence risk management framework (AI RMF 1.0)", ["Tabassi, Elham"], 2023,
             "10.6028/NIST.AI.100-1",
             "GOVERN is a cross-cutting function that is infused throughout AI risk management. The framework is "
             "intended to be integrated into existing organizational risk management processes.", "NIST AI 100-1"),
        make("S002", "Artificial intelligence risk management framework: Generative artificial intelligence profile",
             AUTIO, 2024, "10.6028/NIST.AI.600-1",
             "GAI value chains involve many third-party components such as procured datasets, pre-trained models, "
             "and software libraries. It may be difficult to attribute issues to any one of these sources.",
             "NIST AI 600-1"),
        make("S003", "Cybersecurity supply chain risk management practices for systems and organizations",
             BOYENS, sp161_year, "10.6028/NIST.SP.800-161r1-upd1",
             "Supply chain risks stem from reduced visibility into how acquired technology is developed and "
             "deployed.", "NIST SP 800-161r1-upd1"),
    ]


MAIN = (
    "AI belongs inside the security program's existing risk management, not beside it (Tabassi, 2023). I would "
    "inventory AI systems, assign an owner to each, and keep analysts, not the tools, making consequential "
    "decisions. Third-party risk changes shape too. Generative AI value chains involve pre-trained models and "
    "software libraries that may not be properly vetted (Autio et al., 2024), and supply chain risk stems from "
    "reduced visibility into how acquired technology is developed and deployed (Boyens et al., {Y}). I would ask "
    "vendors how they handle our data and which models and APIs they rely on, and reassess when those change."
)
POST_1 = ("Backups are the last line of defense against ransomware. Organizations should test restores quarterly "
          "because an untested backup is only a guess. Vendors that host copies should be reviewed at contract time.")
POST_2 = ("Agentic assistants can triage vendor questionnaires faster than analysts. Missing evidence should stay "
          "visible as uncertainty instead of becoming a pass. Humans should keep control of final decisions.")
REPLY_1 = (
    "You say untested backups are only a guess, and the restore-testing cadence is the right control. I would add "
    "that a hosting vendor's model or subprocessor can change after the contract is signed, so the same restore "
    "test should be repeated when those change (Autio et al., 2024). The framework reaches a vendor only through "
    "contract terms, which is why the review you mention at contract time needs a notice clause behind it "
    "(Tabassi, 2023). A short check for minor changes and a full review for material ones keeps the effort "
    "proportionate."
)
REPLY_2 = (
    "You note that missing evidence should stay visible as uncertainty, and that humans keep final decisions. I "
    "would extend that: a questionnaire triage tool reads documents from the vendor being assessed, so those "
    "documents are untrusted input and can carry instructions aimed at the tool (Autio et al., 2024). Supply "
    "chain visibility is already limited (Boyens et al., {Y}), and a tool that can also write the final rating "
    "removes the human gate in practice. Enforce the gate with permissions, not with process alone."
)
REF = {
    "S001": "Tabassi, E. (2023). *Artificial intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1). "
            "National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.100-1",
}


def _yaml_reply(body):
    claims = [("S001", "GOVERN is a cross-cutting function"), ("S002", "third-party components"),
              ("S003", "reduced visibility")]
    return "```yaml\nbody_markdown: |\n" + "\n".join("  " + ln for ln in body.split("\n")) + "\nclaims_made:\n" + "".join(
        f'  - claim: "{c}"\n    source_id: "{sid}"\n' for sid, c in claims) + 'verdict: "PASS"\ndifferences: []\nrationale: "ok"\nwarnings: []\n```'


def _draft(tmp_path, monkeypatch, name, genre, body, sources, peer=None, target=60):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))
    spec = AssignmentSpec(
        title=name, topic="AI and risk management in security programs", genre=genre, target_words=target,
        word_tolerance_percent=60.0, source_requirements=dict(minimum_sources=1),
        peer_posts=[{"author": peer[0], "text": peer[1]}] if peer else [])
    backend = FakeAgentBackend(agent_id=f"fake_{name}", default_stdout=_yaml_reply(body))
    return run_academic_pipeline(spec, default_config(), existing_sources=sources, custom_backend=backend)


def _write_package(out: Path, sources, docs):
    (out / "sources.json").write_text(json.dumps([_dump(s) for s in sources]), encoding="utf-8")
    for name, text in docs.items():
        (out / f"{name}.md").write_text(text, encoding="utf-8")
    (out / "post-1.md").write_text(POST_1, encoding="utf-8")
    (out / "post-2.md").write_text(POST_2, encoding="utf-8")
    spec = {
        "title": "AI and Risk Management", "sources": "sources.json", "expected_deliverables": 3,
        "deliverables": [
            {"id": "main", "role": "discussion", "path": "main.md", "min_words": 60, "max_words": 300,
             "required_topics": [{"name": "third-party risk", "any_of": ["third-party", "vendor"]},
                                 {"name": "security program", "any_of": ["security program"]}]},
            {"id": "reply-1", "role": "peer_reply", "path": "reply-1.md", "min_words": 60, "max_words": 300,
             "source_post": {"author": "Casey Rowe", "path": "post-1.md"}},
            {"id": "reply-2", "role": "peer_reply", "path": "reply-2.md", "min_words": 60, "max_words": 300,
             "source_post": {"author": "Dana Moss", "path": "post-2.md"}},
        ],
    }
    (out / "package.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return load_package_spec(out / "package.yaml")


def _dump(source):
    d = source.to_dict()
    for key in ("publication_date", "access_date"):
        if d.get(key) is not None:
            d[key] = str(d[key])
    return d


def _codes(report):
    return {f.code for d in report.deliverables for f in d.findings} | {f.code for f in report.package_findings}


def _draft_all(tmp_path, monkeypatch, sources):
    """The scripted writer cites each source with the year its source data carries."""
    year = next(str(s.publication_date.year) for s in sources if s.id == "S003")
    texts = {}
    texts["main"] = _draft(tmp_path, monkeypatch, "main", "academic_discussion", MAIN.replace("{Y}", year),
                           sources).final_document.text
    texts["reply-1"] = _draft(tmp_path, monkeypatch, "reply-1", "academic_peer_reply", REPLY_1.replace("{Y}", year),
                              sources, peer=("Casey Rowe", POST_1)).final_document.text
    texts["reply-2"] = _draft(tmp_path, monkeypatch, "reply-2", "academic_peer_reply", REPLY_2.replace("{Y}", year),
                              sources, peer=("Dana Moss", POST_2)).final_document.text
    return texts


def test_full_workflow_catches_known_errors_then_verifies_the_final_artifacts(tmp_path, monkeypatch):
    out = tmp_path / "bundle"
    out.mkdir()
    providers = [RecordFileProvider(RECORDS)]

    # Draft with a known citation error: the source year says 2024 but the publisher's cite-as year is 2022.
    bad_sources = _sources(sp161_year=2024)
    drafts = _draft_all(tmp_path, monkeypatch, bad_sources)
    spec = _write_package(out, bad_sources, drafts)

    # The pipeline itself accepts these documents (it has no authoritative record), so only the
    # package check can see the error.
    first = check_package(spec, providers=providers)
    assert first.state is PackageState.BLOCKED
    assert any(c.startswith("CITATION_MISMATCH") or c.startswith("CITATION_NEEDS_REVIEW") for c in _codes(first))

    # Edit pass 1: correct the source metadata and regenerate. The corrected year must reach every document.
    good_sources = _sources(sp161_year=2022)
    corrected = _draft_all(tmp_path, monkeypatch, good_sources)
    assert "Boyens et al., 2022" in corrected["main"] and "Fallon, M. (2024)" not in "".join(corrected.values())
    spec = _write_package(out, good_sources, corrected)

    # Edit pass 2: a careless editor drops a citation from a reply. The change report and the package check both see it.
    edited = corrected["reply-2"].replace(" (Boyens et al., 2022)", "")
    change = build_change_report(corrected["reply-2"], edited)
    assert change.changes[0].citation_effect == "citation removed"
    assert any(c.code == "CITATION_REMOVED" for c in change.citation_changes)
    (out / "reply-2.md").write_text(edited, encoding="utf-8")
    assert check_package(load_package_spec(out / "package.yaml"), providers=providers).state is not \
        PackageState.READY_FOR_HUMAN_REVIEW
    (out / "reply-2.md").write_text(corrected["reply-2"], encoding="utf-8")  # restored

    # Reverify the bundle: ready for a human, with evidence, and not "submitted".
    final = check_package(load_package_spec(out / "package.yaml"), providers=providers)
    assert final.state is PackageState.READY_FOR_HUMAN_REVIEW, [(f.code, f.message) for d in final.deliverables for f in d.findings] + [(f.code, f.message) for f in final.package_findings]
    assert final.human_decisions and {r.status for r in final.verification_records if r.check.startswith("citation metadata: ")} == {"PASS"}

    # Render (markdown) and publish each document to a test destination, then read it back.
    fake = FakeGoogleDocsAdapter()
    publisher = GoogleDocsPublisher(adapter=fake)
    readback = {}
    for name, text in corrected.items():
        art = PublicationArtifact(title=name, content=text, format="md", source_run_id="e2e",
                                  authorized_sha256=__import__("hashlib").sha256(text.encode()).hexdigest(),
                                  metadata={"status": "READY"})
        result = publisher.publish(art, PublishDestination(destination_type="google_docs"),
                                   PublishContext(run_id="e2e", extra={"record_dir": str(out / "approved"),
                                                                       "min_words": 60, "max_words": 300}))
        assert result.status == "SUCCESS", result.diagnostics
        assert result.revision_metadata["readback"]["status"] == "VERIFIED"
        readback[name] = fake.get_document(result.artifact_id)["body"].split("\n", 2)[2]  # strip the title line
    assert len(list((out / "approved").glob("approved-artifact-*.json"))) == 3

    # Final validation: the package checked again on the text the destination actually holds.
    for name, text in readback.items():
        (out / f"{name}.md").write_text(text, encoding="utf-8")
    read_report = check_package(load_package_spec(out / "package.yaml"), providers=providers)
    assert read_report.state is PackageState.READY_FOR_HUMAN_REVIEW, _codes(read_report)


def test_a_faulty_destination_is_never_reported_as_a_successful_publication(tmp_path, monkeypatch):
    drafts = _draft_all(tmp_path, monkeypatch, _sources(sp161_year=2022))
    statuses = {}
    for fault in ("truncate_tail_chars", "duplicate_writes"):
        fake = FakeGoogleDocsAdapter()
        setattr(fake, fault, 80 if fault == "truncate_tail_chars" else True)
        art = PublicationArtifact(title="main", content=drafts["main"], format="md", source_run_id="e2e",
                                  authorized_sha256="n/a", metadata={"status": "READY"})
        statuses[fault] = GoogleDocsPublisher(adapter=fake).publish(
            art, PublishDestination(destination_type="google_docs"), PublishContext(run_id="e2e")).status
    assert statuses == {"truncate_tail_chars": "UNCONFIRMED", "duplicate_writes": "UNCONFIRMED"}


def test_a_correction_in_one_document_but_not_the_others_is_found(tmp_path, monkeypatch):
    out = tmp_path / "bundle"
    out.mkdir()
    sources = _sources(sp161_year=2022)
    drafts = _draft_all(tmp_path, monkeypatch, sources)
    drafts["reply-2"] = drafts["reply-2"].replace("Boyens et al., 2022", "Boyens et al., 2024").replace(
        "Fallon, M. (2022)", "Fallon, M. (2024)")
    spec = _write_package(out, sources, drafts)
    report = check_package(spec, providers=[RecordFileProvider(RECORDS)])
    assert "CROSS_DOCUMENT_YEAR_CONFLICT" in _codes(report)
    assert report.state is not PackageState.READY_FOR_HUMAN_REVIEW
