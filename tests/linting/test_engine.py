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


def test_canned_opening_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["canned_opening"])
    text = "In today's rapidly evolving technological landscape, organizations are leveraging AI."
    codes = _codes(text, config)
    assert rules.AI_STYLE_CANNED_OPENING in codes


def test_canned_opening_silent_when_pattern_not_configured():
    config = HowlWriterConfig(banned_patterns=[])
    text = "In today's rapidly evolving technological landscape, organizations are leveraging AI."
    codes = _codes(text, config)
    assert rules.AI_STYLE_CANNED_OPENING not in codes


def test_formulaic_contrast_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["formulaic_contrast"])
    codes = _codes("This is not about speed; it is about accuracy.", config)
    assert rules.AI_STYLE_FORMULAIC_CONTRAST in codes


def test_generic_transition_detected_when_repeated():
    config = HowlWriterConfig(banned_patterns=["generic_transition"])
    text = (
        "Furthermore, we did A. Moreover, we did B. Additionally, we did C. "
        "Consequently, we shipped."
    )
    codes = _codes(text, config)
    assert rules.AI_STYLE_GENERIC_TRANSITION in codes


def test_generic_transition_silent_when_rare():
    config = HowlWriterConfig(banned_patterns=["generic_transition"])
    text = "Furthermore, we did A. Then we went home."
    codes = _codes(text, config)
    assert rules.AI_STYLE_GENERIC_TRANSITION not in codes


def test_corporate_filler_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["corporate_filler"])
    text = "We must leverage synergy to unlock value and empower users."
    codes = _codes(text, config)
    assert rules.AI_STYLE_CORPORATE_FILLER in codes


def test_generic_intensifier_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["generic_intensifier"])
    text = "This is a pivotal, transformative, and crucial decision."
    codes = _codes(text, config)
    assert rules.AI_STYLE_GENERIC_INTENSIFIER in codes


def test_repetitive_mini_conclusion_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["repetitive_mini_conclusion"])
    text = (
        "A happened. In summary, good.\n\n"
        "B happened. In summary, fine.\n\n"
        "C happened. In summary, ok."
    )
    codes = _codes(text, config)
    assert rules.AI_STYLE_REPETITIVE_MINI_CONCLUSION in codes


def test_paragraph_length_symmetry_detected_when_configured():
    config = HowlWriterConfig(banned_patterns=["paragraph_length_symmetry"])
    text = "A b c. D e f.\n\nG h i. J k l.\n\nM n o. P q r.\n\nS t u. V w x."
    codes = _codes(text, config)
    assert rules.AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY in codes


# --- paragraph word-count hyper-symmetry ------------------------------

_SYMMETRY = HowlWriterConfig(banned_patterns=["paragraph_length_symmetry"])


def _metronomic_body(words: int, blocks: int) -> str:
    """Blocks of identical length, which is the tell being detected."""
    return "\n\n".join(
        f"Block {index} " + "filler word " * (words - 3) + "ends here."
        for index in range(blocks)
    )


def test_hyper_uniform_paragraph_word_counts_are_flagged():
    codes = _codes(_metronomic_body(30, 4), _SYMMETRY)
    assert rules.AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY in codes


def test_a_trailing_hashtag_line_does_not_hide_hyper_symmetry():
    """The tell has to survive the publishing convention wrapped around it.

    A trailing tag line was being counted as a paragraph, which put a
    three-word block into every short-form post and dragged the minimum
    paragraph length under the floor the check requires -- so the rule could
    never fire on exactly the content it was written for.
    """
    codes = _codes(
        _metronomic_body(30, 4) + "\n\n#Engineering #Systems #Reliability",
        _SYMMETRY,
    )
    assert rules.AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY in codes


def test_ordinary_varied_paragraphs_are_not_flagged():
    body = (
        "A short opening line.\n\n"
        + "This paragraph runs considerably longer than the one above it and "
        "develops the point across several clauses before it finally stops. "
        "It keeps going for a while yet.\n\n"
        + "Medium length paragraph sitting between the two extremes here.\n\n"
        + "Then a much longer closing block that returns to the length of the "
        "second paragraph and adds a further sentence to make the spread "
        "unmistakable across the piece as a whole."
    )
    codes = _codes(body, _SYMMETRY)
    assert rules.AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY not in codes


def test_short_form_single_sentence_paragraphs_are_not_a_false_positive():
    """Four one-line paragraphs in a short post are cadence, not a template."""
    body = (
        "Latency is a feature.\n\n"
        "Nobody files a ticket about it.\n\n"
        "They just leave.\n\n"
        "Measure it before you argue about it."
    )
    codes = _codes(body, _SYMMETRY)
    assert rules.AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY not in codes


def test_symmetry_is_silent_when_the_pattern_is_not_configured():
    codes = _codes(_metronomic_body(30, 4), HowlWriterConfig(banned_patterns=[]))
    assert rules.AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY not in codes
