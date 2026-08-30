import pytest

from howlwriter.config.schema import BannedWord, HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.humanize.rewriter import NotConfiguredHumanizer, SafeRewriter
from howlwriter.integration.model_role import ModelRoleNotConfiguredError

rewriter = SafeRewriter()


def test_safe_rewriter_substitutes_only_when_replacement_and_opt_in_are_both_set():
    config = HowlWriterConfig(
        banned_words=[BannedWord(word="delve", replacement="look into")],
        apply_safe_rewrites=True,
    )
    document = Document.parse("Let's delve into this.", title="t")
    result = rewriter.rewrite(document, config)

    assert "look into" in result.document.text
    assert "delve" not in result.document.text.lower()
    assert len(result.changes) == 1


def test_safe_rewriter_leaves_text_untouched_without_apply_safe_rewrites():
    config = HowlWriterConfig(
        banned_words=[BannedWord(word="delve", replacement="look into")],
        apply_safe_rewrites=False,
    )
    document = Document.parse("Let's delve into this.", title="t")
    result = rewriter.rewrite(document, config)

    assert result.document.text == document.text
    assert result.changes == []


def test_safe_rewriter_leaves_text_untouched_when_no_replacement_configured():
    config = HowlWriterConfig(banned_words=[BannedWord(word="delve")], apply_safe_rewrites=True)
    document = Document.parse("Let's delve into this.", title="t")
    result = rewriter.rewrite(document, config)

    assert result.document.text == document.text
    assert result.changes == []


def test_not_configured_humanizer_raises():
    config = HowlWriterConfig()
    document = Document.parse("Text.", title="t")
    with pytest.raises(ModelRoleNotConfiguredError):
        NotConfiguredHumanizer().rewrite(document, config)
