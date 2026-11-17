"""Deterministic content checks: each rule fires on its defect and stays quiet on clean input."""

from __future__ import annotations

import struct
from dataclasses import replace

import pytest

from howlwriter.linkedin import content_checks as cc
from howlwriter.linkedin.models import LifecycleState, MediaRef, Post

CLEAN = "Shipping small changes every day keeps reviews short.\n\nWhat has worked for your team?"


def post(text: str = CLEAN, **changes) -> Post:
    base = Post(
        id="post-001",
        title="t",
        text=text,
        created_at="2026-11-16T12:00:00Z",
        updated_at="2026-11-16T12:00:00Z",
        timezone="America/Detroit",
    )
    return replace(base, **changes)


def codes(record: cc.CheckRecord) -> set[str]:
    return {finding.code for finding in record.findings}


def png(width: int, height: int) -> bytes:
    header = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + header


def jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 3


# Unicode


def test_clean_text_passes_every_text_check():
    for record in (cc.check_unicode(post()), cc.check_privacy(post()), cc.check_claim_coverage(post(), None)):
        assert record.status == cc.PASSED and not record.findings
        assert record.limitation and record.method == cc.DETERMINISTIC
    assert cc.check_links(post()).status == cc.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Broken \ufffd character", "UNICODE_REPLACEMENT"),
        ("It\u00e2\u20ac\u2122s wrongly decoded", "UNICODE_MOJIBAKE"),
        ("caf\u00c3\u00a9 culture", "UNICODE_MOJIBAKE"),
        ("safe \u202egnp.exe", "UNICODE_BIDI_CONTROL"),
    ],
)
def test_broken_or_deceptive_unicode_blocks(text, code):
    record = cc.check_unicode(post(text))
    assert record.status == cc.FAILED and code in codes(record)


def test_invisible_and_decomposed_characters_are_warnings_only():
    record = cc.check_unicode(post("zero\u200bwidth and cafe\u0301"))
    assert record.status == cc.PASSED
    assert codes(record) == {"UNICODE_INVISIBLE", "UNICODE_NOT_NFC"}


def test_emoji_and_accents_are_not_flagged():
    assert not cc.check_unicode(post("Café launch 🎉 naïve résumé — done")).findings


# Links


def test_link_in_text_must_be_declared_and_https():
    text = "See https://example.com/a and http://example.org/b."
    record = cc.check_links(post(text, urls=("https://example.com/other",)))
    assert record.status == cc.FAILED
    assert codes(record) == {"LINK_UNDECLARED", "LINK_NOT_HTTPS"}


def test_declared_link_with_trailing_punctuation_in_text_is_consistent():
    record = cc.check_links(post("Read https://example.com/a.", urls=("https://example.com/a",)))
    assert record.status == cc.PASSED and not record.findings


@pytest.mark.parametrize(
    ("url", "code", "status"),
    [
        ("https://bit.ly/abc", "LINK_SHORTENER", cc.PASSED),
        ("https://xn--pple-43d.com/", "LINK_PUNYCODE", cc.PASSED),
        ("https://192.168.1.10/admin", "LINK_HOST_NOT_PUBLIC_NAME", cc.FAILED),
        ("https://localhost/x", "LINK_HOST_NOT_PUBLIC_NAME", cc.FAILED),
    ],
)
def test_link_destination_rules(url, code, status):
    record = cc.check_links(post(f"Link {url}", urls=(url,)))
    assert record.status == status and code in codes(record)


# Duplicates


def test_exact_duplicate_of_a_queued_or_published_post_blocks():
    queued = post(id="post-002", state=LifecycleState.SCHEDULED)
    record = cc.check_duplicates(post(CLEAN.upper() + "  "), [queued])
    assert record.status == cc.FAILED and codes(record) == {"DUPLICATE_EXACT"}

    sent_then_archived = post(id="post-003", state=LifecycleState.ARCHIVED, linkedin_post_id="urn:li:share:1")
    assert cc.check_duplicates(post(), [sent_then_archived]).status == cc.FAILED


def test_archived_unsent_posts_and_the_post_itself_are_not_duplicates():
    abandoned = post(id="post-002", state=LifecycleState.ARCHIVED)
    record = cc.check_duplicates(post(), [post(), abandoned])
    assert record.status == cc.PASSED and not record.findings


def test_near_duplicate_is_a_warning():
    other = post(CLEAN + " Tell me below.", id="post-002")
    record = cc.check_duplicates(post(), [other])
    assert record.status == cc.PASSED and codes(record) == {"DUPLICATE_NEAR"}
    assert cc.similarity(CLEAN, "An unrelated note about gardening in spring and autumn") < 0.2


# Privacy


@pytest.mark.parametrize(
    ("text", "code", "status"),
    [
        ("Our box at 10.20.30.40 fell over", "PRIVACY_PRIVATE_ADDRESS", cc.FAILED),
        ("Router is 192.168.0.1", "PRIVACY_PRIVATE_ADDRESS", cc.FAILED),
        ("It ran on 10.1.2.3.", "PRIVACY_PRIVATE_ADDRESS", cc.FAILED),
        ("Deployed to build01.corp yesterday", "PRIVACY_INTERNAL_HOSTNAME", cc.FAILED),
        ("Try it on localhost first", "PRIVACY_INTERNAL_HOSTNAME", cc.FAILED),
        ("Logs are in /home/someone/project/logs", "PRIVACY_PRIVATE_PATH", cc.FAILED),
        ("Saved under C:\\Users\\someone\\Desktop", "PRIVACY_PRIVATE_PATH", cc.FAILED),
        ("From the CONFIDENTIAL roadmap deck", "PRIVACY_CONFIDENTIAL_MARKER", cc.FAILED),
        ("This is internal only for now", "PRIVACY_CONFIDENTIAL_MARKER", cc.FAILED),
        ("Write to person@example.com", "PRIVACY_EMAIL_ADDRESS", cc.PASSED),
        ("Call +1 555-010-9999 today", "PRIVACY_PHONE_NUMBER", cc.PASSED),
    ],
)
def test_privacy_patterns(text, code, status):
    record = cc.check_privacy(post(text))
    assert record.status == status and code in codes(record)


def test_privacy_scan_covers_alt_text_and_ignores_public_details():
    media = MediaRef("media/a.png", "a" * 64, "Screenshot of /Users/someone/secret.txt")
    assert "PRIVACY_PRIVATE_PATH" in codes(cc.check_privacy(post(media=(media,))))
    public = "Python 3.10.12 on example.com, version 10.15.7, see https://docs.example.org/home/page"
    assert not cc.check_privacy(post(public)).findings


# Images


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [("a.png", png(1200, 627), ("png", 1200, 627)), ("a.jpg", jpeg(800, 600), ("jpeg", 800, 600)),
     ("a.gif", gif(640, 480), ("gif", 640, 480))],
)
def test_image_header_is_read_for_each_supported_format(store, name, data, expected):
    assert cc.image_info(data) == expected
    (store.root / "media" / name).write_bytes(data)
    media = MediaRef(f"media/{name}", "a" * 64, "A bar chart of weekly build time")
    record, facts = cc.check_images(post(media=(media,)), store)
    assert record.status == cc.PASSED
    assert codes(record) == {"IMAGE_CONTENT_UNVERIFIED"}, "image content is never reported as verified"
    assert facts[0]["width"] == expected[1] and facts[0]["format"] == expected[0]
    assert "No visual verification" in record.limitation


def _image_codes(store, name: str, data: bytes, alt: str = "A bar chart of weekly build time"):
    (store.root / "media" / name).write_bytes(data)
    record, _ = cc.check_images(post(media=(MediaRef(f"media/{name}", "a" * 64, alt),)), store)
    return record.status, codes(record)


def test_image_defects_block(store):
    assert _image_codes(store, "a.png", b"not an image at all")[1] == {"MEDIA_FORMAT_UNSUPPORTED"}
    assert "MEDIA_EXTENSION_MISMATCH" in _image_codes(store, "b.png", jpeg(800, 600))[1]
    assert "MEDIA_DIMENSIONS_INVALID" in _image_codes(store, "c.png", png(0, 10))[1]
    assert "MEDIA_DIMENSIONS_INVALID" in _image_codes(store, "d.png", png(60000, 60000))[1]
    assert "ALT_TEXT_MISSING" in _image_codes(store, "e.png", png(800, 600), alt="  ")[1]
    record, _ = cc.check_images(post(media=(MediaRef("media/missing.png", "a" * 64, "x"),)), store)
    assert record.status == cc.FAILED and "MEDIA_UNREADABLE" in codes(record)


def test_small_image_and_empty_alt_text_description_are_warnings(store):
    status, found = _image_codes(store, "a.png", png(120, 90), alt="screenshot")
    assert status == cc.PASSED and {"MEDIA_SMALL", "ALT_TEXT_UNINFORMATIVE"} <= found


def test_truncated_and_hostile_image_headers_do_not_crash():
    for data in (
        b"",
        b"\xff\xd8",
        b"\xff\xd8\xff\xe0\x00\x00",
        b"\x89PNG\r\n\x1a\n",
        b"GIF89a",
        jpeg(1, 1)[:12],
    ):
        assert cc.image_info(data) is None
    assert cc.check_images(post(), None)[0].status == cc.NOT_APPLICABLE


# Quantitative statements


def test_measured_figure_without_a_declared_claim_blocks():
    record = cc.check_claim_coverage(post("We cut build time by 40% and saved $1,200 a month."), None)
    assert record.status == cc.FAILED
    assert [f.code for f in record.findings] == ["CLAIM_UNDECLARED_METRIC", "CLAIM_UNDECLARED_METRIC"]


def test_declared_claims_cover_their_numbers_only():
    text = "We cut build time by 40% and saved $1,200 a month."
    covered = cc.check_claim_coverage(post(text), ["Build time fell 40%", "Monthly saving was $1200"])
    assert covered.status == cc.PASSED and not covered.findings
    assert "not that the claim is supported" in covered.limitation
    partial = cc.check_claim_coverage(post(text), ["Build time fell 40%"])
    assert partial.status == cc.FAILED and "$1,200" in partial.findings[0].message


def test_bare_numbers_warn_and_list_markers_urls_and_identifiers_are_ignored():
    text = "1. First point\n2. Second point\nSee https://example.com/2026/11 and #100DaysOfCode with v2 API."
    assert not cc.check_claim_coverage(post(text), None).findings
    record = cc.check_claim_coverage(post("I interviewed 14 engineers."), None)
    assert record.status == cc.PASSED and codes(record) == {"CLAIM_UNDECLARED_NUMBER"}


# Faults


def test_a_check_that_raises_is_an_error_never_a_pass():
    def boom() -> cc.CheckRecord:
        raise RuntimeError("secret detail that must not be recorded")

    record = cc.run_guarded("content.format", boom)
    assert record.status == cc.CHECK_ERROR and record.reason == "RuntimeError"
    assert "secret detail" not in str(record.to_dict())
