from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode


def test_parse_splits_paragraphs_on_blank_lines():
    text = "First paragraph.\n\nSecond paragraph."
    doc = Document.parse(text, title="t")
    assert len(doc.paragraphs) == 2
    assert doc.paragraphs[0].raw_text == "First paragraph."
    assert doc.paragraphs[1].raw_text == "Second paragraph."


def test_parse_splits_sentences_within_a_paragraph():
    text = "Sentence one. Sentence two! Sentence three?"
    doc = Document.parse(text, title="t")
    assert len(doc.paragraphs) == 1
    sentences = [s.text for s in doc.paragraphs[0].sentences]
    assert sentences == ["Sentence one.", "Sentence two!", "Sentence three?"]


def test_single_sentence_document():
    doc = Document.parse("Just one sentence.", title="t")
    assert len(doc.paragraphs) == 1
    assert len(doc.paragraphs[0].sentences) == 1


def test_trailing_whitespace_is_stripped():
    doc = Document.parse("  Padded sentence.  \n\n  ", title="t")
    assert len(doc.paragraphs) == 1
    assert doc.paragraphs[0].raw_text == "Padded sentence."


def test_document_sentence_accessor_and_all_sentences():
    doc = Document.parse("A. B.\n\nC.", title="t")
    assert doc.sentence(0, 1).text == "B."
    located = doc.all_sentences()
    assert (1, 0, doc.paragraphs[1].sentences[0]) in located


def test_document_default_mode_is_custom():
    doc = Document.parse("Text.", title="t")
    assert doc.mode == WritingMode.CUSTOM


def test_dotted_initialisms_and_abbreviations_do_not_end_sentences():
    """Regression: "U.S. Government" used to split into two sentences, producing
    fragment claims such as "Government Accountability Office, 2020)."."""
    text = (
        "Treasury did not track sector efforts (U.S. Government Accountability Office, 2020). "
        "The U.K. and D.C. examples remain intact. "
        "Some victims, e.g. Small utilities, serve larger firms; i.e. dependencies matter. "
        "Dr. Smith agreed. The rule took effect in Sept. 2021. It still applies."
    )
    doc = Document.parse(text, title="t")
    sentences = [s.text for s in doc.paragraphs[0].sentences]
    assert sentences == [
        "Treasury did not track sector efforts (U.S. Government Accountability Office, 2020).",
        "The U.K. and D.C. examples remain intact.",
        "Some victims, e.g. Small utilities, serve larger firms; i.e. dependencies matter.",
        "Dr. Smith agreed.",
        "The rule took effect in Sept. 2021.",
        "It still applies.",
    ]
