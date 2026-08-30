from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.humanize.detector import detect
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD, AI_STYLE_EXCESSIVE_HEADINGS


def test_detector_matches_lint_engine_output_for_the_humanization_subset():
    config = default_config()
    document = Document.parse("We need to delve into this topic.", title="t")

    lint_matches = LintEngine().run(document, config)
    humanize_matches = detect(document, config)

    assert any(m.rule_code == AI_STYLE_BANNED_WORD for m in humanize_matches)
    assert {m.rule_code for m in humanize_matches} <= {m.rule_code for m in lint_matches}


def test_detector_excludes_excessive_headings_from_the_humanization_subset():
    config = default_config()
    text = "# Heading One\n\n# Heading Two\n\n# Heading Three\n\nBody text."
    document = Document.parse(text, title="t")

    humanize_matches = detect(document, config)
    assert not any(m.rule_code == AI_STYLE_EXCESSIVE_HEADINGS for m in humanize_matches)
