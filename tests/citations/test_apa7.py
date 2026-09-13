from datetime import date

import pytest

from howlwriter.citations.apa7 import (
    CITATION_METADATA_MISSING,
    CITATION_TITLE_CASE,
    APA7Formatter,
)
from howlwriter.citations.styles import CitationStyle, get_formatter
from howlwriter.domain.source import Source

formatter = APA7Formatter()


def _source(**overrides) -> Source:
    defaults = dict(
        id="s1",
        title="A study of things",
        authors=["Jane A. Smith"],
        publisher="Example Press",
        publication_date=date(2024, 3, 1),
        url="https://example.com/study",
    )
    defaults.update(overrides)
    return Source(**defaults)


def test_reference_entry_with_complete_metadata_has_no_warnings():
    result = formatter.reference_entry(_source())
    assert result.warnings == []
    assert "Smith, J. A. (2024)." in result.text
    assert "A study of things." in result.text
    assert "https://example.com/study" in result.text


def test_reference_entry_missing_date_uses_nd_and_warns():
    source = _source(publication_date=None)
    result = formatter.reference_entry(source)
    assert "(n.d.)" in result.text
    codes = {w.code for w in result.warnings}
    fields = {w.field for w in result.warnings}
    assert CITATION_METADATA_MISSING in codes
    assert "publication_date" in fields
    warning = next(w for w in result.warnings if w.field == "publication_date")
    assert "Publication date could not be verified" in warning.message
    assert "undated-source format" in warning.message


def test_reference_entry_missing_author_moves_title_forward_and_warns():
    source = _source(authors=[])
    result = formatter.reference_entry(source)
    assert result.text.startswith("A study of things (2024).")
    assert any(w.field == "authors" for w in result.warnings)


def test_reference_entry_missing_locator_warns():
    source = _source(url=None, doi=None)
    result = formatter.reference_entry(source)
    assert any(w.field == "url" for w in result.warnings)


def test_one_two_and_three_plus_author_formatting():
    one = formatter.reference_entry(_source(authors=["Jane Smith"])).text
    two = formatter.reference_entry(_source(authors=["Jane Smith", "Bob Jones"])).text
    three = formatter.reference_entry(_source(authors=["Jane Smith", "Bob Jones", "Amy Lee"])).text
    assert "Smith, J. (2024)." in one
    assert "Smith, J., & Jones, B. (2024)." in two
    assert "Smith, J., Jones, B., & Lee, A. (2024)." in three


def test_in_text_parenthetical_forms():
    one = formatter.in_text_parenthetical(_source(authors=["Jane Smith"])).text
    two = formatter.in_text_parenthetical(_source(authors=["Jane Smith", "Bob Jones"])).text
    three = formatter.in_text_parenthetical(
        _source(authors=["Jane Smith", "Bob Jones", "Amy Lee"])
    ).text
    assert one == "(Smith, 2024)"
    assert two == "(Smith & Jones, 2024)"
    assert three == "(Smith et al., 2024)"


def test_narrative_forms():
    one = formatter.narrative(_source(authors=["Jane Smith"])).text
    two = formatter.narrative(_source(authors=["Jane Smith", "Bob Jones"])).text
    assert one == "Smith (2024)"
    assert two == "Smith and Jones (2024)"


def test_narrative_missing_author_uses_short_title():
    result = formatter.narrative(_source(authors=[]))
    assert result.text.startswith('"A study of things" (2024)')
    assert any(w.field == "authors" for w in result.warnings)


def test_organizational_author_is_not_inverted():
    source = _source(authors=["World Health Organization"])
    result = formatter.reference_entry(source)
    assert "World Health Organization (2024)." in result.text


def test_reference_page_alphabetizes_by_surname():
    sources = [
        _source(id="s1", title="Zebra Paper", authors=["Amy Zed"]),
        _source(id="s2", title="Apple Paper", authors=["Bob Adams"]),
    ]
    result = formatter.reference_page(sources)
    assert result.text.index("Adams") < result.text.index("Zed")


def test_reference_page_orders_same_author_works_by_year():
    sources = [
        _source(id="s1", authors=["The White House"], publication_date=date(2026, 1, 1)),
        _source(id="s2", authors=["The White House"], publication_date=date(2023, 1, 1)),
        _source(id="s3", authors=["The White House"], publication_date=date(2024, 1, 1)),
    ]
    result = formatter.reference_page(sources)
    assert result.text.index("(2023)") < result.text.index("(2024)")
    assert result.text.index("(2024)") < result.text.index("(2026)")


def test_get_formatter_returns_apa7():
    assert isinstance(get_formatter(CitationStyle.APA7), APA7Formatter)


_UNIMPLEMENTED_STYLES = [CitationStyle.MLA, CitationStyle.CHICAGO, CitationStyle.IEEE, CitationStyle.HARVARD]


def test_title_is_rendered_in_sentence_case():
    result = formatter.reference_entry(
        _source(title="A Study of Things: A Longitudinal Analysis")
    )
    assert "A study of things: A longitudinal analysis." in result.text
    assert any(w.code == CITATION_TITLE_CASE for w in result.warnings)


def test_acronyms_are_preserved_in_sentence_case():
    result = formatter.reference_entry(_source(title="The NASA HTTP Protocol"))
    assert "The NASA HTTP protocol." in result.text


def test_proper_nouns_with_internal_caps_are_preserved():
    result = formatter.reference_entry(_source(title="Using iPhone in iOS Development"))
    assert "Using iPhone in iOS development." in result.text


@pytest.mark.parametrize("style", _UNIMPLEMENTED_STYLES)
def test_get_formatter_raises_for_unimplemented_styles(style):
    with pytest.raises(NotImplementedError):
        get_formatter(style)


@pytest.mark.parametrize(
    "author",
    [
        "Financial Stability Oversight Council",
        "Office of the Director of National Intelligence",
        "International Monetary Fund",
        "The White House",
        "U.S. Department of the Treasury",
        "Cyber Safety Review Board",
        "China Law Translate",
        "U.S.-China Economic and Security Review Commission",
    ],
)
def test_group_authors_without_org_suffix_are_kept_intact(author):
    """Group authors are cited by their full name, never inverted into initials.

    Regression: "Financial Stability Oversight Council" used to render as
    "Council, F. S. O. (2025)" and "(Council, 2025)" because only a short list
    of trailing words marked an author as organizational.
    """
    source = _source(authors=[author])
    assert f"{author} (2024)." in formatter.reference_entry(source).text
    assert formatter.in_text_parenthetical(source).text == f"({author}, 2024)"
    assert formatter.narrative(source).text == f"{author} (2024)"


@pytest.mark.parametrize(
    ("author", "surname", "reference_form"),
    [
        ("Hill, French", "Hill", "Hill, F."),
        ("Scott, Tim", "Scott", "Scott, T."),
        ("Jane A. Smith", "Smith", "Smith, J. A."),
        ("Del Rosso, Kristin", "Del Rosso", "Del Rosso, K."),
    ],
)
def test_person_names_are_still_inverted(author, surname, reference_form):
    source = _source(authors=[author])
    assert formatter.reference_entry(source).text.startswith(f"{reference_form} (2024).")
    assert formatter.in_text_parenthetical(source).text == f"({surname}, 2024)"


def test_title_cased_titles_are_converted_but_dotted_initialisms_survive():
    source = _source(title="Cyber Risk and the U.S. Financial System: A Pre-Mortem Analysis")
    result = formatter.reference_entry(source)
    assert "Cyber risk and the U.S. financial system: A pre-mortem analysis." in result.text
    assert any(w.code == CITATION_TITLE_CASE for w in result.warnings)


@pytest.mark.parametrize(
    "title",
    [
        "Sleight of hand: How China weaponizes software vulnerabilities",
        "Review of the summer 2023 Microsoft Exchange Online intrusion",
        "Letter to Secretary Yellen regarding the incident at the Department of the Treasury",
        "President Trump's cyber strategy for America",
        "Translation: Critical information infrastructure security protection regulations (effective Sept. 1, 2021)",
    ],
)
def test_titles_already_in_sentence_case_keep_their_proper_nouns(title):
    """Regression: "How China weaponizes" used to become "How china weaponizes"."""
    result = formatter.reference_entry(_source(title=title))
    assert f"{title}." in result.text
    assert not any(w.code == CITATION_TITLE_CASE for w in result.warnings)


def test_month_abbreviations_survive_sentence_case_conversion():
    result = formatter.reference_entry(
        _source(title="Critical Information Infrastructure Regulations (Effective Sept. 1, 2021)")
    )
    assert "Critical information infrastructure regulations (effective Sept. 1, 2021)." in result.text


def test_identical_organizational_author_and_publisher_is_not_repeated():
    source = _source(authors=["U.S. Government Accountability Office"])
    source.publisher = "U.S. Government Accountability Office"
    result = formatter.reference_entry(source)
    assert result.text.count("U.S. Government Accountability Office") == 1
