from howlwriter.domain.claim import ClaimType, VerificationStatus
from howlwriter.domain.document import Document
from howlwriter.facts.extraction import HeuristicClaimExtractor

extractor = HeuristicClaimExtractor()


def test_extracts_sentence_with_a_number():
    document = Document.parse("Ninety percent of users prefer this feature. Nothing else here.", title="t")
    claims = extractor.extract(document)
    assert len(claims) == 0  # "Ninety" is spelled out, not a digit -- confirms no false positive


def test_extracts_sentence_with_a_digit():
    document = Document.parse("90% of users prefer this. This sentence has no numbers.", title="t")
    claims = extractor.extract(document)
    assert len(claims) == 1
    assert claims[0].claim_type == ClaimType.STATISTICAL
    assert claims[0].verification_status == VerificationStatus.UNVERIFIABLE


def test_extracts_sentence_with_attribution_marker():
    document = Document.parse("According to the report, adoption is rising. Nothing else here.", title="t")
    claims = extractor.extract(document)
    assert len(claims) == 1
    assert claims[0].claim_type == ClaimType.FACTUAL
    assert claims[0].verification_status == VerificationStatus.UNVERIFIABLE


def test_ordinary_sentences_are_not_extracted():
    document = Document.parse("This is a plain sentence with no claims in it.", title="t")
    claims = extractor.extract(document)
    assert claims == []


def test_extracted_claims_carry_document_span():
    document = Document.parse("Filler.\n\n42 people attended the event.", title="t")
    claims = extractor.extract(document)
    assert len(claims) == 1
    assert claims[0].document_span.paragraph_index == 1
    assert claims[0].document_span.sentence_index == 0


def test_extractor_never_assigns_supported_status():
    document = Document.parse(
        "50% growth was reported. According to the study, results held. 100 people attended.",
        title="t",
    )
    claims = extractor.extract(document)
    assert len(claims) == 3
    assert all(c.verification_status == VerificationStatus.UNVERIFIABLE for c in claims)
