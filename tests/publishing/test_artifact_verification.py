"""Final-artifact verification: publish, read back, and refuse to claim what the destination did not confirm."""

from __future__ import annotations

import hashlib
import json

import pytest

from howlwriter.publishing.base import PublicationArtifact, PublishContext, PublishDestination
from howlwriter.publishing.google.publisher import GoogleDocsPublisher, _build_update_requests
from howlwriter.publishing.verification import (
    CITATION_LOST,
    DUPLICATED_CONTENT,
    FORMATTING_LITERAL,
    MISSING_PARAGRAPH,
    PRIOR_CONTENT_LOST,
    REFERENCE_LOST,
    REFERENCES_TRUNCATED,
    TEXT_TRUNCATED,
    UNSUPPORTED_ELEMENT,
    WORD_COUNT_CHANGED,
    WORD_COUNT_OUT_OF_RANGE,
    approved_record,
    extract_document_text,
    verify_readback,
    write_record,
)
from tests.fakes.google_docs import FakeGoogleDocsAdapter

TEXT = (
    "Backups belong inside the risk program because recovery is a business decision (Moreno, 2025).\n\n"
    "I would test restores against a stated downtime tolerance and assign an owner to each system.\n\n"
    "Vendors need the same scrutiny, so ask where copies live and who can delete them.\n\n"
    "**References**\n\n"
    "Moreno, D. (2025). *Backup resilience in ransomware response*. Example Press. https://doi.org/10.1234/example.1\n\n"
    "Nguyen, T. (2024). *Vendor recovery obligations*. Example Press. https://doi.org/10.1234/example.2\n"
)


def _codes(v):
    return {f.code for f in v.findings}


def _artifact(text=TEXT, sha=None):
    return PublicationArtifact(title="Backups", content=text, format="md", source_run_id="run-1",
                               authorized_sha256=sha or hashlib.sha256(text.encode()).hexdigest(),
                               metadata={"status": "READY"})


def _publish(fake, artifact=None, **dest):
    return GoogleDocsPublisher(adapter=fake).publish(
        artifact or _artifact(), PublishDestination(destination_type="google_docs", **dest),
        PublishContext(run_id="run-1"))


class TestVerifyReadback:
    def test_identical_text_is_verified(self):
        assert verify_readback(TEXT, TEXT).verified

    def test_destination_that_adds_the_title_line_is_still_verified(self):
        assert verify_readback(TEXT, "Backups\n\n" + TEXT, title="Backups").verified

    def test_destination_that_renders_markdown_is_verified(self):
        rendered = TEXT.replace("**References**", "References").replace("*", "")
        v = verify_readback(TEXT, rendered)
        assert v.verified and FORMATTING_LITERAL not in _codes(v)

    def test_missing_paragraph(self):
        v = verify_readback(TEXT, TEXT.replace("I would test restores against a stated downtime tolerance and assign "
                                               "an owner to each system.\n\n", ""))
        assert not v.verified and MISSING_PARAGRAPH in _codes(v)

    def test_altered_paragraph_counts_as_missing(self):
        v = verify_readback(TEXT, TEXT.replace("downtime tolerance", "uptime tolerance"))
        assert MISSING_PARAGRAPH in _codes(v)

    def test_duplicated_paragraph(self):
        para = "Vendors need the same scrutiny, so ask where copies live and who can delete them.\n\n"
        v = verify_readback(TEXT, TEXT.replace(para, para + para))
        assert not v.verified and DUPLICATED_CONTENT in _codes(v)

    def test_truncated_reference_list(self):
        v = verify_readback(TEXT, TEXT[:-45])
        assert not v.verified and {REFERENCES_TRUNCATED, TEXT_TRUNCATED} & _codes(v)

    def test_reference_entry_missing(self):
        v = verify_readback(TEXT, TEXT.split("Nguyen, T.")[0])
        assert not v.verified and REFERENCE_LOST in _codes(v)

    def test_citation_lost(self):
        v = verify_readback(TEXT, TEXT.replace(" (Moreno, 2025)", ""))
        assert not v.verified and CITATION_LOST in _codes(v)

    def test_word_count_is_recalculated_from_the_readback(self):
        v = verify_readback(TEXT, TEXT.replace("I would test", "I would then carefully test"))
        assert WORD_COUNT_CHANGED in _codes(v) and v.readback_words == v.approved_words + 2

    def test_required_range_is_enforced_on_what_was_read(self):
        v = verify_readback(TEXT, TEXT, min_words=200, max_words=300)
        assert not v.verified and WORD_COUNT_OUT_OF_RANGE in _codes(v)

    def test_unsupported_elements_are_reported_not_failed(self):
        table = TEXT + "\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        v = verify_readback(table, table)
        assert v.verified and UNSUPPORTED_ELEMENT in _codes(v)

    def test_prior_content_must_survive_an_append(self):
        v = verify_readback("New section words that are long enough to count here.",
                            "New section words that are long enough to count here.", prior_text="Earlier notes.")
        assert PRIOR_CONTENT_LOST in _codes(v)

    def test_extract_text_from_a_google_docs_body_structure(self):
        doc = {"body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "Hello "}},
                                                                {"textRun": {"content": "world\n"}}]}},
                                    {"sectionBreak": {}}]}}
        assert extract_document_text(doc) == "Hello world\n"


class TestApprovedRecord:
    def test_record_captures_hash_words_citations_and_references(self, tmp_path):
        rec = approved_record(TEXT, title="Backups", run_id="run-1")
        assert rec.sha256 == hashlib.sha256(TEXT.encode()).hexdigest()
        assert rec.reference_entries == 2 and rec.citations == ["moreno 2025"] and rec.words > 30
        path = write_record(rec, tmp_path / "out")
        assert json.loads(path.read_text())["sha256"] == rec.sha256


class TestPublishWithReadback:
    def test_confirmed_publication_is_success_and_records_the_readback(self, tmp_path):
        fake = FakeGoogleDocsAdapter()
        art = _artifact()
        res = GoogleDocsPublisher(adapter=fake).publish(
            art, PublishDestination(destination_type="google_docs"),
            PublishContext(run_id="run-1", extra={"record_dir": str(tmp_path)}))
        assert res.status == "SUCCESS" and res.revision_metadata["readback"]["status"] == "VERIFIED"
        assert (tmp_path / f"approved-artifact-{art.content_hash[:12]}.json").is_file()

    def test_truncated_write_is_unconfirmed_not_success(self):
        fake = FakeGoogleDocsAdapter()
        fake.truncate_tail_chars = 60
        res = _publish(fake)
        assert res.status == "UNCONFIRMED" and not res.is_success
        assert any("TRUNCATED" in d or "REFERENCE" in d for d in res.diagnostics)

    def test_duplicated_write_is_unconfirmed(self):
        fake = FakeGoogleDocsAdapter()
        fake.duplicate_writes = True
        res = _publish(fake)
        assert res.status == "UNCONFIRMED" and any(DUPLICATED_CONTENT in d for d in res.diagnostics)

    def test_unreadable_destination_is_unconfirmed(self):
        fake = FakeGoogleDocsAdapter()
        real_get = fake.get_document
        calls = {"n": 0}

        def flaky(doc_id):
            calls["n"] += 1
            if calls["n"] >= 1:
                raise ConnectionError("timed out")
            return real_get(doc_id)

        fake.get_document = flaky
        res = _publish(fake)
        assert res.status == "UNCONFIRMED" and "could not be read back" in res.diagnostics[0]

    def test_content_changed_after_approval_is_refused(self):
        fake = FakeGoogleDocsAdapter()
        art = _artifact(sha=hashlib.sha256(b"what was approved").hexdigest())
        res = _publish(fake, art)
        assert res.status == "FAILED" and "ARTIFACT_CHANGED_AFTER_APPROVAL" in res.diagnostics[0]
        assert fake.documents == {}  # nothing was created


class TestRevisionAwareUpdates:
    def _existing(self, fake, text="Notes from the owner that must not be lost by an update.\n"):
        doc = fake.create_document("Doc")
        fake.batch_update(doc["documentId"], [{"insertText": {"text": text}}])
        return doc["documentId"]

    def test_edit_between_read_and_write_is_a_conflict_and_nothing_is_overwritten(self):
        fake = FakeGoogleDocsAdapter()
        doc_id = self._existing(fake)
        fake.after_read = lambda doc: None
        edits = {"done": False}

        def edit_once(doc):
            if not edits["done"]:
                edits["done"] = True
                fake.concurrent_edit(doc_id, "A collaborator's new paragraph written in the meantime.\n")

        fake.after_read = edit_once
        res = _publish(fake, update_doc_id=doc_id, update_mode="replace")
        assert res.status == "CONFLICT" and not res.is_success
        assert "collaborator's new paragraph" in fake.documents[doc_id]["body"]
        assert "recovery is a business decision" not in fake.documents[doc_id]["body"]

    def test_edit_in_the_last_instant_is_caught_by_the_destination_guard(self):
        fake = FakeGoogleDocsAdapter()
        doc_id = self._existing(fake)
        fake.before_write = lambda doc: fake.concurrent_edit(doc_id, "Late edit by someone else.\n") \
            if "Late edit" not in doc["body"] else None
        res = _publish(fake, update_doc_id=doc_id, update_mode="replace")
        assert res.status == "CONFLICT" and "Late edit" in fake.documents[doc_id]["body"]

    def test_clean_replace_succeeds_with_the_read_revision_recorded(self):
        fake = FakeGoogleDocsAdapter()
        doc_id = self._existing(fake)
        res = _publish(fake, update_doc_id=doc_id, update_mode="replace")
        assert res.status == "SUCCESS" and res.revision_metadata["read_revision"]

    def test_append_keeps_prior_content_and_verifies_it(self):
        fake = FakeGoogleDocsAdapter()
        doc_id = self._existing(fake)
        res = _publish(fake, update_doc_id=doc_id, update_mode="append")
        assert res.status == "SUCCESS" and "Notes from the owner" in fake.documents[doc_id]["body"]

    def test_adapter_without_revision_guard_is_refused_for_updates(self):
        class Legacy(FakeGoogleDocsAdapter):
            def batch_update(self, doc_id, requests):  # no required_revision_id
                return super().batch_update(doc_id, requests)

        fake = Legacy()
        doc_id = self._existing(fake)
        res = _publish(fake, update_doc_id=doc_id, update_mode="replace")
        assert res.status == "FAILED" and "revision" in res.diagnostics[0].lower()

    def test_ambiguous_update_mode_is_still_refused(self):
        fake = FakeGoogleDocsAdapter()
        doc_id = self._existing(fake)
        assert _publish(fake, update_doc_id=doc_id, update_mode="").status == "FAILED"


def test_replace_never_asks_to_delete_the_final_newline():
    # The Docs API rejects a delete range that includes the body's last newline.
    requests = _build_update_requests("New text.", title="T", mode="replace", existing_body_length=51)
    assert requests[0]["deleteContentRange"]["range"] == {"startIndex": 1, "endIndex": 50}


class TestApprovalHashFailsClosed:
    @pytest.mark.parametrize("asserted", [
        "sha256:" + "ab" * 32,          # right shape, wrong content
        "AB" * 32,                       # upper case, wrong content
        "sha-101",                       # not a hash
        "sha256:" + "ab" * 35,           # wrong length
    ])
    def test_a_present_but_wrong_or_malformed_hash_is_refused(self, asserted):
        fake = FakeGoogleDocsAdapter()
        res = _publish(fake, _artifact(sha=asserted))
        assert res.status == "FAILED" and "ARTIFACT_CHANGED_AFTER_APPROVAL" in res.diagnostics[0]
        assert fake.documents == {}

    def test_the_right_hash_in_any_common_spelling_is_accepted(self):
        digest = hashlib.sha256(TEXT.encode()).hexdigest()
        for spelling in (digest, digest.upper(), "sha256:" + digest):
            assert _publish(FakeGoogleDocsAdapter(), _artifact(sha=spelling)).status == "SUCCESS"

    def test_no_assertion_means_no_check_and_the_record_says_so(self, tmp_path):
        art = _artifact()
        art.authorized_sha256 = ""
        fake = FakeGoogleDocsAdapter()
        res = GoogleDocsPublisher(adapter=fake).publish(
            art, PublishDestination(destination_type="google_docs"),
            PublishContext(run_id="run-1", extra={"record_dir": str(tmp_path)}))
        assert res.status == "SUCCESS"
        record = json.loads(next(tmp_path.glob("approved-artifact-*.json")).read_text())
        assert record["authorized_sha256"] == ""


class TestReadbackComparesTheWholeSequence:
    """Each case was a false VERIFIED found by an independent audit."""

    SHORT = TEXT.replace("Backups belong", "Short claim here.\n\nBackups belong", 1)

    def test_a_short_paragraph_removed_or_altered(self):
        assert MISSING_PARAGRAPH in _codes(verify_readback(self.SHORT, self.SHORT.replace("Short claim here.\n\n", "")))
        assert MISSING_PARAGRAPH in _codes(verify_readback(self.SHORT, self.SHORT.replace("Short claim here.", "Short claim gone.")))

    def test_paragraphs_in_a_different_order(self):
        paras = TEXT.split("\n\n")
        swapped = "\n\n".join([paras[1], paras[0], *paras[2:]])
        assert "READBACK_REORDERED_CONTENT" in _codes(verify_readback(TEXT, swapped))

    def test_spam_appended_after_the_references(self):
        v = verify_readback(TEXT, TEXT + "\nBuy cheap watches now at a very good price today only.\n")
        assert not v.verified and "READBACK_EXTRA_CONTENT" in _codes(v)

    def test_a_paragraph_inserted_in_the_middle(self):
        v = verify_readback(TEXT, TEXT.replace("I would test", "Visit this unrelated site for a discount today.\n\nI would test", 1))
        assert "READBACK_EXTRA_CONTENT" in _codes(v)

    def test_paragraphs_merged_into_one(self):
        v = verify_readback(TEXT, TEXT.replace("(Moreno, 2025).\n\n", "(Moreno, 2025). ", 1))
        assert not v.verified and MISSING_PARAGRAPH in _codes(v)

    def test_nothing_approved_is_never_verified(self):
        v = verify_readback("", "anything at all in the destination")
        assert not v.verified and "READBACK_NOTHING_APPROVED" in _codes(v)

    def test_appended_text_must_still_appear_in_order(self):
        approved = "First approved paragraph.\n\nSecond approved paragraph."
        ok = verify_readback(approved, "Earlier notes.\n\nFirst approved paragraph.\n\nSecond approved paragraph.\n",
                             prior_text="Earlier notes.")
        assert ok.verified
        bad = verify_readback(approved, "Earlier notes.\n\nSecond approved paragraph.\n\nFirst approved paragraph.\n",
                              prior_text="Earlier notes.")
        assert "READBACK_REORDERED_CONTENT" in _codes(bad)

    def test_oversized_texts_are_refused_not_scanned(self):
        v = verify_readback("a " * 1_100_000, "a")
        assert "READBACK_TEXT_TOO_LARGE" in _codes(v)


class TestFolderMoveAfterWrite:
    def test_a_failed_folder_move_does_not_say_nothing_was_published(self):
        fake = FakeGoogleDocsAdapter()
        fake.simulate_folder_not_found = True
        res = _publish(fake, target="Research", folder="Research")
        assert res.status == "UNCONFIRMED" and res.artifact_id and res.url
        assert "could not be moved" in res.diagnostics[0]
        assert fake.documents  # the document exists


def test_a_concurrent_edit_on_a_fresh_document_is_detected():
    # The fake's first edit used to reuse the creation revision, hiding exactly this case.
    fake = FakeGoogleDocsAdapter()
    doc_id = fake.create_document("Doc")["documentId"]
    before = fake.documents[doc_id]["revisionId"]
    fake.concurrent_edit(doc_id, "A collaborator wrote this.\n")
    assert fake.documents[doc_id]["revisionId"] != before
