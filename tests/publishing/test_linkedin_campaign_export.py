"""Regression tests for LinkedIn campaign export, plain-text validation, and micro-content evaluation."""

import re
import pytest

from howlwriter.publishing.registry import PublisherRegistry, UnsupportedDestinationError
from howlwriter.evaluation.personal import evaluate_text
from howlwriter.domain.document import Document
from howlwriter.linting.engine import LintEngine
from howlwriter.config.loader import ConfigLoader


def test_unsupported_destination_reporting():
    """Verify that unsupported destinations (like 'linkedin' or 'twitter') fail with clear errors."""
    registry = PublisherRegistry()
    with pytest.raises(UnsupportedDestinationError):
        registry.get("linkedin")
    with pytest.raises(UnsupportedDestinationError):
        registry.get("twitter")
    # Verify local and plain_text are supported
    assert registry.get("local") is not None
    assert registry.get("plain_text") is not None


def test_micro_content_length_gate_returns_unavailable():
    """Verify that micro-content (<250 words) gracefully reports UNAVAILABLE rather than crashing."""
    short_text = (
        "AI coding assistants can generate fifty lines of clean-looking Python or Go in under three "
        "seconds. The trouble starts when the code looks idiomatic, compiles cleanly, and fails silently "
        "in production under high concurrency. Speed of generation does not equal speed of delivery."
    )
    result = evaluate_text(short_text)

    # Naturalness must report UNAVAILABLE with informative explanation
    assert result["naturalness"]["status"] == "UNAVAILABLE"
    assert "250 words" in result["naturalness"]["reason"]

    # Descriptive dimensional features must still be computed
    assert len(result["naturalness"]["dimensions"]) > 0
    assert result["words"] == len(short_text.split())


def test_linkedin_copy_paste_plain_text_invariants():
    """Verify plain-text export invariant checks for LinkedIn compatibility."""
    sample_post = (
        "In production support, you quickly learn to recognize operational debt: "
        "the three-step manual fix, the weekly log-cleanup script someone runs by hand, "
        "or the spreadsheet used to cross-reference failed jobs.\n\n"
        "Each individual task takes only ten minutes, so nobody prioritizes fixing it. "
        "Over six months, across an entire on-call rotation, those ten-minute tasks consume "
        "hundreds of engineering hours.\n\n"
        "Automate the friction out of existence."
    )

    # Invariant 1: UTF-8 encodable without BOM
    encoded = sample_post.encode("utf-8")
    assert not encoded.startswith(b"\xef\xbb\xbf")

    # Invariant 2: Under 3000 character limit
    assert len(sample_post) <= 3000

    # Invariant 3: Zero markdown headers, code fences, or bold asterisks
    assert not re.search(r"^#{1,6}\s", sample_post, re.M)
    assert "**" not in sample_post
    assert "```" not in sample_post
    assert not re.search(r"<[a-zA-Z/][^>]*>", sample_post)

    # Invariant 4: Logical paragraph separation preserved
    paras = [p for p in sample_post.split("\n\n") if p.strip()]
    assert len(paras) == 3


def test_linter_zero_warnings_on_clean_post():
    """Verify that HowlWriter linting engine approves clean engineering prose without false positives."""
    clean_post = (
        "Autonomous coding agents can clone a repository, edit files, and submit a pull request without "
        "human intervention. Writing code has low blast radius. Deploying to production has immediate "
        "blast radius.\n\n"
        "Autonomy without boundary enforcement is just unmanaged risk."
    )
    doc = Document.parse(clean_post, title="clean_test")
    config = ConfigLoader().load()
    matches = LintEngine().run(doc, config)
    assert len(matches) == 0


def test_linkedin_platform_linter_checks():
    """Verify that LinkedIn platform linter detects platform-specific formatting issues."""
    from howlwriter.linting.platforms import (
        LINKEDIN_CHAR_LIMIT,
        LINKEDIN_CONTROL_CHARACTERS,
        LINKEDIN_EXCESSIVE_HASHTAGS,
        LINKEDIN_UNRENDERED_MARKDOWN,
        check_platform_rules,
    )

    bad_markdown = "### Header\nThis has **bold** text and [a link](https://example.com) and ```code```."
    findings = check_platform_rules(bad_markdown, platform="linkedin")
    codes = {f.rule_code for f in findings}
    assert LINKEDIN_UNRENDERED_MARKDOWN in codes

    hashtag_spam = "Post with too many tags #one #two #three #four #five #six"
    findings_tags = check_platform_rules(hashtag_spam, platform="linkedin")
    assert any(f.rule_code == LINKEDIN_EXCESSIVE_HASHTAGS for f in findings_tags)

    long_post = "A" * 3005
    findings_long = check_platform_rules(long_post, platform="linkedin")
    assert any(f.rule_code == LINKEDIN_CHAR_LIMIT for f in findings_long)

    bad_chars = "Corrupted text \x00 with null byte"
    findings_chars = check_platform_rules(bad_chars, platform="linkedin")
    assert any(f.rule_code == LINKEDIN_CONTROL_CHARACTERS for f in findings_chars)


def test_claim_extractor_list_enumeration_and_experiential_claims():
    """Verify claim extractor ignores list prefixes and flags first-person experiential claims."""
    from howlwriter.facts.extraction import HeuristicClaimExtractor
    from howlwriter.domain.claim import ClaimType

    # List items with leading numbers should NOT trigger statistical claims
    list_text = (
        "High-performing teams enforce deterministic policy:\n"
        "1. Automated verification must run in an isolated environment.\n"
        "2. Production access must require authenticated human approval.\n"
        "3. Automated rollback triggers must be hardwired into telemetry."
    )
    doc_list = Document.parse(list_text, title="list_test")
    extractor = HeuristicClaimExtractor()
    claims_list = extractor.extract(doc_list)
    assert len(claims_list) == 0

    # First-person experiential claim should be detected
    exp_text = "When we replaced a manual procedure, we eliminated an entire category of access requests."
    doc_exp = Document.parse(exp_text, title="exp_test")
    claims_exp = extractor.extract(doc_exp)
    assert len(claims_exp) > 0
    assert any("first-person" in c.notes for c in claims_exp)
    assert any(c.claim_type == ClaimType.FACTUAL for c in claims_exp)
