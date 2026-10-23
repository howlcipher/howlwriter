"""Citations are re-checked after editing: nothing silently disappears or drifts."""

from __future__ import annotations

from howlwriter.citations.revalidation import (
    CITATION_ADDED,
    CITATION_REMOVED,
    CITATION_STRIPPED_FROM_CLAIM,
    CITATION_YEAR_CHANGED,
    CLAIM_REMOVED,
    REFERENCE_CHANGED,
    REFERENCE_INCONSISTENT_WITH_CITATION,
    REFERENCE_MISSING,
    REFERENCE_ORPHANED,
    citation_delta,
    citation_key,
    parse_references,
)

REFS = (
    "\n\n**References**\n\n"
    "Boyens, J., Smith, A., & Fallon, M. (2022). *Cybersecurity supply chain risk management practices*. "
    "NIST. https://doi.org/10.6028/NIST.SP.800-161r1-upd1\n\n"
    "OWASP Gen AI Security Project. (2025). *OWASP top 10 for LLM applications 2025*. https://genai.owasp.org/llm-top-10/\n"
)
BODY = (
    "Supply chain risk stems from reduced visibility into how acquired technology is built (Boyens et al., 2022). "
    "Prompt injection can arrive through external content such as a file (OWASP Gen AI Security Project, 2025). "
    "I would require vendors to disclose model and subprocessor changes before they take effect."
)
DOC = BODY + REFS


def _codes(delta):
    return [c.code for c in delta.changes]


def test_an_untouched_document_has_no_citation_changes():
    delta = citation_delta(DOC, DOC)
    assert delta.clean and not delta.blocking


def test_a_revision_that_only_rewords_is_clean():
    revised = DOC.replace("I would require vendors", "I would have vendors").replace("before they take effect", "ahead of time")
    assert citation_delta(DOC, revised).clean


def test_humanizer_dropping_a_citation_is_an_error():
    revised = DOC.replace(" (Boyens et al., 2022)", "")
    delta = citation_delta(DOC, revised)
    assert CITATION_REMOVED in _codes(delta) and delta.blocking
    assert CITATION_STRIPPED_FROM_CLAIM in _codes(delta)
    assert REFERENCE_ORPHANED in _codes(delta)


def test_year_edited_in_text_but_not_in_the_reference_is_inconsistent():
    revised = DOC.replace("(Boyens et al., 2022)", "(Boyens et al., 2024)")
    codes = _codes(citation_delta(DOC, revised))
    assert CITATION_YEAR_CHANGED in codes and REFERENCE_INCONSISTENT_WITH_CITATION in codes


def test_a_correction_made_in_both_places_is_reported_but_not_blocking():
    revised = DOC.replace("(Boyens et al., 2022)", "(Boyens et al., 2024)").replace("Fallon, M. (2022)", "Fallon, M. (2024)")
    delta = citation_delta(DOC, revised)
    assert CITATION_YEAR_CHANGED in _codes(delta) and REFERENCE_CHANGED in _codes(delta)
    assert not delta.blocking  # a correction is allowed; it is visible, not silent


def test_a_reintroduced_error_is_caught_by_comparing_to_the_corrected_version():
    corrected = DOC.replace("2022", "2024")
    reverted = DOC  # a later pass puts the old year back
    assert CITATION_YEAR_CHANGED in _codes(citation_delta(corrected, reverted))


def test_reference_removed_while_citation_remains_is_an_error():
    revised = DOC.split("**References**")[0] + "**References**\n\n" + REFS.split("\n\n")[3] + "\n"
    delta = citation_delta(DOC, revised)
    assert REFERENCE_MISSING in _codes(delta) and delta.blocking


def test_new_citation_is_reported_for_review():
    revised = BODY + " Vendors rarely agree on this (Nguyen, 2023)." + REFS
    assert CITATION_ADDED in _codes(citation_delta(DOC, revised.replace(BODY, BODY)))


def test_deleting_a_cited_claim_is_reported_as_information():
    revised = BODY.replace(
        "Prompt injection can arrive through external content such as a file (OWASP Gen AI Security Project, 2025). ",
        "") + REFS
    delta = citation_delta(DOC, revised)
    assert CLAIM_REMOVED in _codes(delta)


def test_citation_key_ignores_et_al_and_coauthor_lists():
    assert citation_key("Autio et al.", "2024") == citation_key("Autio, Schwartz & Hall", "2024")


def test_parse_references_reads_year_doi_and_url():
    entries = parse_references(DOC)
    assert [e.lead for e in entries] == ["boyens", "owasp"]
    assert entries[0].doi == "10.6028/nist.sp.800-161r1-upd1" and entries[1].url.startswith("https://genai.owasp.org")
