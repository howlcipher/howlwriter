"""Tests for semantic source authority classification and topic-sensitive priority."""

from howlwriter.domain.source import Source, SourceAuthority, SourceType, source_from_dict
from howlwriter.research.authority import (
    classify_source_authority,
    detect_topic_preferred_authorities,
)


def test_classify_primary_law():
    s_gdpr = Source(
        id="S1",
        title="Regulation (EU) 2016/679 (General Data Protection Regulation)",
        authors=["European Parliament and Council"],
        url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
    )
    assert classify_source_authority(s_gdpr) == SourceAuthority.PRIMARY_LAW

    s_uscode = Source(
        id="S2",
        title="18 U.S. Code § 1030 - Fraud and related activity in connection with computers",
        authors=["US Congress"],
        url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title18-section1030",
    )
    assert classify_source_authority(s_uscode) == SourceAuthority.PRIMARY_LAW


def test_classify_government():
    s_cisa = Source(
        id="S3",
        title="CISA Cybersecurity Advisory: StopRansomware",
        authors=["Cybersecurity and Infrastructure Security Agency"],
        url="https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-341a",
    )
    assert classify_source_authority(s_cisa) == SourceAuthority.GOVERNMENT

    s_ftc = Source(
        id="S4",
        title="FTC Enforcement Action Concerning Health Privacy",
        authors=["Federal Trade Commission"],
        url="https://www.ftc.gov/news-events/news/press-releases/2023/11/ftc-action",
    )
    assert classify_source_authority(s_ftc) == SourceAuthority.GOVERNMENT


def test_classify_standards():
    s_nist = Source(
        id="S5",
        title="Security and Privacy Controls for Information Systems and Organizations",
        authors=["NIST"],
        url="https://csrc.nist.gov/publications/detail/sp/800-53/rev-5/final",
    )
    assert classify_source_authority(s_nist) == SourceAuthority.STANDARD

    s_rfc = Source(
        id="S6",
        title="HTTP Semantics (RFC 9110)",
        authors=["Fielding, R."],
        url="https://www.rfc-editor.org/rfc/rfc9110.html",
    )
    assert classify_source_authority(s_rfc) == SourceAuthority.STANDARD


def test_classify_scholarly():
    s_journal = Source(
        id="S7",
        title="Adversarial Robustness in Deep Neural Networks",
        authors=["Goodfellow, I."],
        doi="10.1145/3372297.3417281",
        source_type=SourceType.JOURNAL_ARTICLE,
    )
    assert classify_source_authority(s_journal) == SourceAuthority.SCHOLARLY

    s_arxiv = Source(
        id="S8",
        title="Attention Is All You Need",
        authors=["Vaswani, A."],
        url="https://arxiv.org/abs/1706.03762",
    )
    assert classify_source_authority(s_arxiv) == SourceAuthority.SCHOLARLY


def test_detect_topic_preferred_authorities():
    topic_law = "EU GDPR compliance requirements and cross-border data transfer mandates"
    auths_law = detect_topic_preferred_authorities(topic_law)
    assert SourceAuthority.PRIMARY_LAW in auths_law
    assert SourceAuthority.GOVERNMENT in auths_law

    topic_nist = "Implementing the NIST CSF 2.0 and Zero Trust Architecture across enterprise systems"
    auths_nist = detect_topic_preferred_authorities(topic_nist)
    assert SourceAuthority.STANDARD in auths_nist
    assert SourceAuthority.SCHOLARLY in auths_nist


def test_source_authority_serialization_and_property():
    s = Source(
        id="S9",
        title="Primary Legal Act",
        authors=["Court of Justice"],
        authority=SourceAuthority.PRIMARY_LAW,
    )
    assert s.is_primary_authority is True

    # Serialization check
    s_dict = s.to_dict()
    assert s_dict["authority"] == "PRIMARY_LAW"

    restored = source_from_dict(s_dict)
    assert restored.authority == SourceAuthority.PRIMARY_LAW
    assert restored.is_primary_authority is True

    # Non-primary authority check
    s_news = Source(
        id="S10",
        title="News Article",
        authors=["Reporter, R."],
        authority=SourceAuthority.NEWS,
    )
    assert s_news.is_primary_authority is False
