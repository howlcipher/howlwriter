from howlwriter.domain.claim import Claim, DocumentSpan, VerificationStatus
from howlwriter.domain.document import Document
from howlwriter.redpen.critic import RedPenEngine

engine = RedPenEngine()


def test_filler_sentence_is_flagged_for_deletion():
    document = Document.parse("We tried hard. The reality is that nothing changed.", title="t")
    findings = engine.critique(document)

    filler = [f for f in findings if "reality is" in f.reason]
    assert len(filler) == 1
    assert filler[0].recommendation == "delete"
    assert filler[0].paragraph_index == 0
    assert filler[0].id == "RED_PEN_001"


def test_sentence_length_outlier_is_flagged_for_revision():
    long_sentence = "This sentence keeps going and going with many extra words to pad it out considerably."
    text = f"Short one. Short two. Short three. Short four. {long_sentence}"
    document = Document.parse(text, title="t")
    findings = engine.critique(document)

    outliers = [f for f in findings if f.recommendation == "revise"]
    assert len(outliers) == 1
    assert outliers[0].quoted_text == long_sentence


def test_unhedged_unverifiable_claim_is_flagged():
    document = Document.parse("Ninety percent of users prefer this feature.", title="t")
    claim = Claim(
        id="c1",
        text="Ninety percent of users prefer this feature.",
        verification_status=VerificationStatus.UNVERIFIABLE,
        document_span=DocumentSpan(paragraph_index=0, sentence_index=0),
    )
    findings = engine.critique(document, claims=[claim])

    flagged = [f for f in findings if f.recommendation == "flag"]
    assert len(flagged) == 1
    assert flagged[0].paragraph_index == 0
    assert flagged[0].sentence_index == 0


def test_hedged_unverifiable_claim_is_not_flagged():
    document = Document.parse("This feature likely appeals to most users.", title="t")
    claim = Claim(
        id="c1",
        text="This feature likely appeals to most users.",
        verification_status=VerificationStatus.UNVERIFIABLE,
        document_span=DocumentSpan(paragraph_index=0, sentence_index=0),
    )
    findings = engine.critique(document, claims=[claim])
    assert not any(f.recommendation == "flag" for f in findings)


def test_supported_claim_is_never_flagged():
    document = Document.parse("This is well established.", title="t")
    claim = Claim(
        id="c1",
        text="This is well established.",
        verification_status=VerificationStatus.SUPPORTED,
        document_span=DocumentSpan(paragraph_index=0, sentence_index=0),
    )
    findings = engine.critique(document, claims=[claim])
    assert not any(f.recommendation == "flag" for f in findings)


def test_ids_are_assigned_sequentially():
    document = Document.parse("The reality is nothing. At its core, it fails.", title="t")
    findings = engine.critique(document)
    assert [f.id for f in findings] == [f"RED_PEN_{i:03d}" for i in range(1, len(findings) + 1)]
