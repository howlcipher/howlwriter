from howlwriter.config.schema import BannedWord, HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting import rules
from howlwriter.linting.engine import LintEngine

engine = LintEngine()


def _codes(document_text: str, config: HowlWriterConfig) -> set[str]:
    document = Document.parse(document_text, title="t")
    return {match.rule_code for match in engine.run(document, config)}


def test_banned_word_is_detected_when_configured():
    config = HowlWriterConfig(banned_words=[BannedWord(word="delve")])
    codes = _codes("We need to delve into this topic.", config)
    assert rules.AI_STYLE_BANNED_WORD in codes


def test_banned_word_silent_when_not_configured():
    config = HowlWriterConfig(banned_words=[])
    codes = _codes("We need to delve into this topic.", config)
    assert rules.AI_STYLE_BANNED_WORD not in codes


def test_not_x_but_y_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["not_x_but_y"])
    codes = _codes("It's not just about speed, it's about accuracy.", config)
    assert rules.AI_STYLE_NOT_X_BUT_Y in codes


def test_not_x_but_y_silent_when_pattern_not_configured():
    config = HowlWriterConfig(banned_patterns=[])
    codes = _codes("It's not just about speed, it's about accuracy.", config)
    assert rules.AI_STYLE_NOT_X_BUT_Y not in codes


def test_empty_transition_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["empty_transition"])
    codes = _codes("At its core, this changes everything.", config)
    assert rules.AI_STYLE_EMPTY_TRANSITION in codes


def test_empty_transition_silent_when_pattern_not_configured():
    config = HowlWriterConfig(banned_patterns=[])
    codes = _codes("At its core, this changes everything.", config)
    assert rules.AI_STYLE_EMPTY_TRANSITION not in codes


def test_canned_conclusion_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["canned_conclusion"])
    codes = _codes("The reality is that this matters a great deal.", config)
    assert rules.AI_STYLE_CANNED_CONCLUSION in codes


def test_canned_conclusion_silent_when_pattern_not_configured():
    config = HowlWriterConfig(banned_patterns=[])
    codes = _codes("The reality is that this matters a great deal.", config)
    assert rules.AI_STYLE_CANNED_CONCLUSION not in codes


def test_repetitive_tricolon_detected_at_threshold():
    config = HowlWriterConfig(banned_patterns=["repetitive_tricolon"])
    text = (
        "We measured speed, accuracy, and reliability.\n\n"
        "We considered cost, time, and effort.\n\n"
        "We weighed risk, reward, and timing."
    )
    codes = _codes(text, config)
    assert rules.AI_STYLE_REPETITIVE_TRICOLON in codes


def test_repetitive_tricolon_silent_below_threshold():
    config = HowlWriterConfig(banned_patterns=["repetitive_tricolon"])
    text = "We measured speed, accuracy, and reliability."
    codes = _codes(text, config)
    assert rules.AI_STYLE_REPETITIVE_TRICOLON not in codes


def test_excessive_em_dash_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["excessive_em_dash"])
    text = "One—two—three—four—five."
    codes = _codes(text, config)
    assert rules.AI_STYLE_EXCESSIVE_EM_DASH in codes


def test_excessive_em_dash_silent_when_pattern_not_configured():
    config = HowlWriterConfig(banned_patterns=[])
    text = "One—two—three—four—five."
    codes = _codes(text, config)
    assert rules.AI_STYLE_EXCESSIVE_EM_DASH not in codes


def test_excessive_headings_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["excessive_headings"])
    text = "# Heading One\n\n# Heading Two\n\n# Heading Three\n\nSome body text."
    codes = _codes(text, config)
    assert rules.AI_STYLE_EXCESSIVE_HEADINGS in codes


def test_excessive_bold_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["excessive_bold"])
    text = " ".join(f"**bold{i}**" for i in range(5)) + "."
    codes = _codes(text, config)
    assert rules.AI_STYLE_EXCESSIVE_BOLD in codes


def test_repetitive_paragraph_structure_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["repetitive_paragraph_structure"])
    text = "This is one point.\n\nThis is another point.\n\nThis is a third point."
    codes = _codes(text, config)
    assert rules.AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE in codes


def test_excessive_rhetorical_questions_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["excessive_rhetorical_questions"])
    text = "Is this good? Why does it matter? Should we care? This is the answer."
    codes = _codes(text, config)
    assert rules.AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS in codes


def test_excessive_rhetorical_questions_silent_when_pattern_not_configured():
    config = HowlWriterConfig(banned_patterns=[])
    text = "Is this good? Why does it matter? Should we care? This is the answer."
    codes = _codes(text, config)
    assert rules.AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS not in codes
