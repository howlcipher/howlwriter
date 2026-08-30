from datetime import date

import pytest

from howlwriter.citations.apa7 import CITATION_METADATA_MISSING, APA7Formatter
from howlwriter.citations.styles import CitationStyle, get_formatter
from howlwriter.domain.source import Source

formatter = APA7Formatter()


def _source(**overrides) -> Source:
    defaults = dict(
        id="s1",
        title="A Study of Things",
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
    assert "A Study of Things." in result.text
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
    assert result.text.startswith("A Study of Things (2024).")
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
    assert result.text.startswith('"A Study of Things" (2024)')
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


def test_get_formatter_returns_apa7():
    assert isinstance(get_formatter(CitationStyle.APA7), APA7Formatter)


_UNIMPLEMENTED_STYLES = [CitationStyle.MLA, CitationStyle.CHICAGO, CitationStyle.IEEE, CitationStyle.HARVARD]


@pytest.mark.parametrize("style", _UNIMPLEMENTED_STYLES)
def test_get_formatter_raises_for_unimplemented_styles(style):
    with pytest.raises(NotImplementedError):
        get_formatter(style)
