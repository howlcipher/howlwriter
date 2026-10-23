"""Assignment-package readiness over synthetic deliverables."""

from __future__ import annotations

import json

import pytest

from howlwriter.assignment.package import PackageState, check_package, load_package_spec
from howlwriter.cli.main import main
from howlwriter.citations.verification import RecordFileProvider
from tests.replies.test_grounding import GOOD, POST

SOURCES = [
    {"id": "S1", "title": "Backup resilience in ransomware response", "authors": ["Moreno, D."],
     "publication_date": "2025-03-01", "doi": "10.1234/example.1", "publisher": "Example Press",
     "source_type": "journal_article", "retrieved_text": "Offline backups cut recovery time."},
]
RECORDS = {"records": [{"provider": "publisher-page", "authority": "publisher",
                        "title": "Backup resilience in ransomware response",
                        "authors": [{"family": "Moreno", "given": "Dana"}], "year": 2025,
                        "doi": "10.1234/example.1"}]}
REF = ("Moreno, D. (2025). *Backup resilience in ransomware response*. Example Press. "
       "https://doi.org/10.1234/example.1")

MAIN = ("Backups belong inside the risk program, not beside it, because recovery is a business decision. "
        "Offline copies cut recovery time (Moreno, 2025). I would test restores against a stated downtime "
        "tolerance and assign an owner to each system, since runbooks decay faster than the data does. "
        "Third-party storage vendors need the same scrutiny: ask where copies live and who can delete them.")
REPLY = GOOD + " Offline copies cut recovery time (Moreno, 2025)."


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")


def _package(tmp_path, *, main=MAIN, reply=REPLY, with_post=True, with_reply=True, lo=40, hi=300, extra=None):
    _write(tmp_path, "sources.json", json.dumps(SOURCES))
    _write(tmp_path, "records.json", json.dumps(RECORDS))
    _write(tmp_path, "main.md", main + "\n\n**References**\n\n" + REF + "\n")
    if with_reply:
        _write(tmp_path, "reply.md", reply + "\n\n**References**\n\n" + REF + "\n")
    if with_post:
        _write(tmp_path, "post.md", POST.text)
    spec = {
        "title": "Backups", "sources": "sources.json", "expected_deliverables": 2,
        "deliverables": [
            {"id": "main", "role": "discussion", "path": "main.md", "min_words": lo, "max_words": hi,
             "required_topics": [{"name": "third-party risk", "any_of": ["third-party", "vendor"]}]},
            {"id": "reply-1", "role": "peer_reply", "path": "reply.md", "min_words": lo, "max_words": hi,
             "source_post": {"author": "Casey Rowe", "path": "post.md"}},
        ],
    }
    if extra:
        spec.update(extra)
    import yaml
    _write(tmp_path, "package.yaml", yaml.safe_dump(spec))
    return load_package_spec(tmp_path / "package.yaml")


def _providers(tmp_path):
    return [RecordFileProvider(tmp_path / "records.json")]


def _codes(report):
    return {f.code for d in report.deliverables for f in d.findings} | {f.code for f in report.package_findings}


def test_complete_verified_package_is_ready_for_human_review(tmp_path):
    report = check_package(_package(tmp_path), providers=_providers(tmp_path))
    assert report.state is PackageState.READY_FOR_HUMAN_REVIEW, _codes(report)
    assert report.human_decisions  # a person still reads it


def test_missing_deliverable_is_incomplete(tmp_path):
    report = check_package(_package(tmp_path, with_reply=False), providers=_providers(tmp_path))
    assert report.state is PackageState.INCOMPLETE and "DELIVERABLE_MISSING" in _codes(report)


def test_missing_peer_post_is_incomplete_not_grounded(tmp_path):
    spec = _package(tmp_path, with_post=False)
    report = check_package(spec, providers=_providers(tmp_path))
    assert report.state is PackageState.INCOMPLETE and "PEER_POST_MISSING" in _codes(report)


def test_out_of_range_word_count_needs_revision(tmp_path):
    report = check_package(_package(tmp_path, lo=500, hi=600), providers=_providers(tmp_path))
    assert report.state is PackageState.NEEDS_REVISION and "WORD_COUNT" in _codes(report)


def test_uncovered_topic_needs_revision(tmp_path):
    main = "Backups belong inside the risk program because recovery is a business decision. " * 6
    report = check_package(_package(tmp_path, main=main), providers=_providers(tmp_path))
    assert "TOPIC_NOT_COVERED" in _codes(report)


def test_leaked_workflow_text_needs_revision(tmp_path):
    report = check_package(_package(tmp_path, main=MAIN + " This is my recommendation, not a cited result."),
                           providers=_providers(tmp_path))
    assert report.state is PackageState.NEEDS_REVISION and "LEAK_PROVENANCE_NOTE" in _codes(report)


def test_wrong_year_in_citation_is_blocked_by_metadata(tmp_path):
    # The text and the source data agree with each other on 2021, so only the authoritative
    # record (2025) can reveal the error. A resolving DOI does not.
    bad = [dict(SOURCES[0], publication_date="2021-03-01")]
    spec = _package(tmp_path)
    _write(tmp_path, "sources.json", json.dumps(bad))
    for name in ("main.md", "reply.md"):
        _write(tmp_path, name, (tmp_path / name).read_text().replace("2025", "2021"))
    report = check_package(spec, providers=_providers(tmp_path))
    assert report.state is PackageState.BLOCKED and any(c.startswith("CITATION_MISMATCH") for c in _codes(report))


def test_unresolved_in_text_citation_is_blocked(tmp_path):
    report = check_package(_package(tmp_path, main=MAIN + " Vendors rarely agree (Nguyen, 2024)."),
                           providers=_providers(tmp_path))
    assert report.state is PackageState.BLOCKED and "CITATION_UNRESOLVED" in _codes(report)


def test_distorted_reply_is_blocked(tmp_path):
    reply = "You argue that zero trust segmentation removes the need for any backup program. " + REPLY
    report = check_package(_package(tmp_path, reply=reply), providers=_providers(tmp_path))
    assert report.state is PackageState.BLOCKED and "REPLY_ATTRIBUTION_UNSUPPORTED" in _codes(report)


def test_no_provider_means_verification_unavailable_not_a_pass(tmp_path):
    report = check_package(_package(tmp_path), providers=[])
    assert report.state is PackageState.VERIFICATION_UNAVAILABLE
    assert any("citation metadata" in u for u in report.unavailable_checks)


def test_unreachable_provider_is_unavailable_not_mismatch(tmp_path):
    from howlwriter.citations.verification import ProviderUnavailable

    class Down:
        name = "crossref"

        def fetch(self, source):
            raise ProviderUnavailable("timeout")

    report = check_package(_package(tmp_path), providers=[Down()])
    assert report.state is PackageState.VERIFICATION_UNAVAILABLE


def test_wrong_deliverable_count_is_incomplete(tmp_path):
    report = check_package(_package(tmp_path, extra={"expected_deliverables": 3}), providers=_providers(tmp_path))
    assert report.state is PackageState.INCOMPLETE and "DELIVERABLE_COUNT" in _codes(report)


def test_reference_list_that_disagrees_with_the_metadata_needs_revision(tmp_path):
    spec = _package(tmp_path)
    text = (tmp_path / "main.md").read_text().replace("Moreno, D. (2025)", "Moreno, D. (2024)")
    _write(tmp_path, "main.md", text)
    report = check_package(spec, providers=_providers(tmp_path))
    assert "REFERENCE_MISSING_OR_DIFFERENT" in _codes(report)


def test_cli_exit_codes(tmp_path, capsys):
    _package(tmp_path)
    ok = main(["assignment", "check", str(tmp_path / "package.yaml"), "--offline",
               "--records", str(tmp_path / "records.json"), "--json"])
    assert ok == 0 and json.loads(capsys.readouterr().out)["state"] == "READY_FOR_HUMAN_REVIEW"
    (tmp_path / "reply.md").unlink()
    assert main(["assignment", "check", str(tmp_path / "package.yaml"), "--offline",
                 "--records", str(tmp_path / "records.json")]) == 3
