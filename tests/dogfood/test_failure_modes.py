"""Tests for provider failures, structured output parsing, and independence verification."""

import pytest

from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.humanize.rewriter import ModelHumanizerRewriter
from howlwriter.review.meaning import RealModelMeaningReviewer
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    IndependenceStatus,
    RoleBinding,
    RoleBindingRegistry,
    RoleDispatcher,
)


def test_humanizer_fails_clearly_on_provider_crash():
    doc = Document.parse("Original text.")
    fake_crash = FakeAgentBackend(
        agent_id="crashing_agent",
        default_exit_code=1,
        default_stdout="",
        default_stderr="Process killed: Out of memory",
    )

    rewriter = ModelHumanizerRewriter()
    with pytest.raises(RuntimeError) as exc_info:
        rewriter.rewrite(doc, default_config(), custom_backend=fake_crash)

    assert "Out of memory" in str(exc_info.value) or "Exit code 1" in str(exc_info.value)


def test_humanizer_fails_on_empty_provider_response():
    doc = Document.parse("Original text.")
    fake_empty = FakeAgentBackend(
        agent_id="empty_agent",
        default_exit_code=0,
        default_stdout="   \n\n  ",
    )

    rewriter = ModelHumanizerRewriter()
    with pytest.raises(RuntimeError) as exc_info:
        rewriter.rewrite(doc, default_config(), custom_backend=fake_empty)

    assert "empty or unparseable" in str(exc_info.value).lower()


def test_reviewer_reports_fail_on_reviewer_provider_crash():
    orig = Document.parse("Original text.")
    rev = Document.parse("Revised text.")

    fake_crash = FakeAgentBackend(
        agent_id="crashing_reviewer",
        default_exit_code=1,
        default_stdout="",
        default_stderr="API rate limit reached (429)",
    )

    reviewer = RealModelMeaningReviewer()
    res = reviewer.compare(orig, rev, humanizer_provider="h_agent", custom_backend=fake_crash)

    desc = res.differences[0].description.lower()
    assert "rate limit" in desc or "exit code" in desc


def test_reviewer_independence_reporting():
    registry = RoleBindingRegistry()
    registry.register_binding(RoleBinding(domain="writing", role="final_reviewer", provider="claude_code"))

    dispatcher = RoleDispatcher(binding_registry=registry)

    # When avoid_provider is different -> INDEPENDENT
    prov, _, status = dispatcher.resolve_provider(
        domain="writing", role="final_reviewer", avoid_provider="codex"
    )
    assert status == IndependenceStatus.INDEPENDENT.value

    # When avoid_provider is None -> NOT_REVIEWED
    prov, _, status = dispatcher.resolve_provider(
        domain="writing", role="final_reviewer", avoid_provider=None
    )
    assert status == IndependenceStatus.NOT_REVIEWED.value
