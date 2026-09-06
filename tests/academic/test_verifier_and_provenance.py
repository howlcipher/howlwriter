from datetime import date

from howlwriter.academic.verifier import AcademicVerifier
from howlwriter.domain.document import Document
from howlwriter.domain.source import Source, SourceType


def test_provenance_and_supported_claim_mapping():
    s1 = Source(
        id="S001",
        title="Zero Trust Governance for Autonomous AI Agents",
        authors=["Oladimeji, Ganiyu"],
        publication_date=date(2025, 3, 15),
        publisher="Elsevier",
        doi="10.2139/ssrn.7194038",
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text=(
            "Recent studies demonstrate that dynamic delegated authorization "
            "reduces stale token privileges by 42% across multi-agent environments."
        ),
    )

    doc_text = """# Zero Trust Systems

Dynamic delegated authorization reduces stale token privileges by 42% (Oladimeji, 2025).
"""
    doc = Document.parse(doc_text)
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(doc, [s1])

    assert len(graph.sources) == 1
    assert "S001" in graph.sources
    assert summary.supported_claims >= 1
    assert summary.unsupported_claims == 0
    assert summary.status == "PASS"

    # Evidence links claim to source
    assert len(graph.evidence) >= 1
    ev = graph.evidence[0]
    assert ev.source_id == "S001"
    assert ev.supports is True


def test_unsupported_claim_demotes_readiness():
    s1 = Source(
        id="S001",
        title="General AI Security",
        authors=["Smith, Alice"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        retrieved_text="AI systems require basic credential isolation and token rotation.",
    )

    # Document asserts a fabricated statistical metric completely absent from the source
    doc_text = """# Security Claims

A benchmark across 950 Fortune 500 banks demonstrated an 89.4% reduction in data breaches during 2026.
"""
    doc = Document.parse(doc_text)
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(doc, [s1])

    assert summary.unsupported_claims >= 1
    assert summary.status == "NEEDS_REVIEW"


def test_quotation_integrity_checks():
    s1 = Source(
        id="S001",
        title="Foundations of Computer Security",
        authors=["Dijkstra, Edsger"],
        publication_date=date(1982, 5, 1),
        access_date=date.today(),
        retrieved_text=(
            "Simplicity is a great virtue but it requires hard work to achieve it "
            "and education to appreciate it."
        ),
    )

    # Case 1: Real verbatim quote from source
    quote1 = (
        'As Dijkstra noted, "Simplicity is a great virtue but it requires hard work '
        'to achieve it and education to appreciate it."'
    )
    doc1 = Document.parse(quote1)
    _, summary1 = AcademicVerifier().build_provenance_and_verify(doc1, [s1])
    assert len(summary1.quotation_warnings) == 0

    # Case 2: Fabricated quote not in source
    quote2 = (
        'Dijkstra stated, "Autonomous AI agents will inevitably destroy traditional network '
        'perimeters by 2026 without cryptographic zero trust."'
    )
    doc2 = Document.parse(quote2)
    _, summary2 = AcademicVerifier().build_provenance_and_verify(doc2, [s1])
    assert len(summary2.quotation_warnings) == 1
    assert "was not found verbatim in any retrieved source" in summary2.quotation_warnings[0]
    assert summary2.status == "NEEDS_REVIEW"


def test_identifier_warnings_populate_verification_summary():
    s1 = Source(
        id="S001",
        title="Cloud Threat Detection Overview",
        authors=["Rivera, Ana"],
        publication_date=date(2024, 6, 1),
        access_date=date.today(),
        retrieved_text=(
            "AWS GuardDuty and SIEM detections can flag anomalous credential use "
            "and unusual API activity tied to compromised access keys."
        ),
    )

    # The draft invents a suspiciously precise jitter figure not present in
    # any retrieved source or the assignment's own text.
    doc_text = """# Beaconing Behavior

The malware exhibited beacon traffic with 34.72% jitter to evade detection,
consistent with AWS GuardDuty telemetry for anomalous credential use.
"""
    doc = Document.parse(doc_text)
    verifier = AcademicVerifier()
    _, summary = verifier.build_provenance_and_verify(doc, [s1])

    assert len(summary.identifier_warnings) >= 1
    assert any("34.72" in w for w in summary.identifier_warnings)
    assert summary.status == "NEEDS_REVIEW"


def test_identifier_grounded_via_additional_grounding_texts_not_flagged():
    doc_text = "The lab specifically analyzes CVE-2024-31337 as a case study."
    doc = Document.parse(doc_text)
    verifier = AcademicVerifier()
    _, summary = verifier.build_provenance_and_verify(
        doc,
        sources=[],
        additional_grounding_texts=["Analyze CVE-2024-31337 as the primary case study."],
    )

    assert not any("CVE-2024-31337" in w for w in summary.identifier_warnings)


def _latency_source() -> Source:
    return Source(
        id="S001",
        title="Latency Study",
        authors=["Rose, Scott"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text=(
            "Our controlled deployment of mutual TLS across the service mesh "
            "reduced observed lateral movement incidents by 41 percent while "
            "adding 12 milliseconds of median request latency in Kubernetes "
            "clusters."
        ),
        evidence_depth="ABSTRACT",
        relevance="DIRECT",
    )


def test_statistic_absent_from_the_source_is_not_supported_by_it():
    """Topical overlap matched a source; the figure must come from it too."""
    doc = Document.parse(
        "# Paper\n\nMutual TLS reduced lateral movement incidents by 63 "
        "percent in Kubernetes clusters (Rose, 2024).\n"
    )

    _, summary = AcademicVerifier().build_provenance_and_verify(
        doc, [_latency_source()]
    )

    assert summary.supported_claims == 0
    assert summary.unsupported_claims == 1


def test_statistic_present_in_the_source_remains_supported():
    doc = Document.parse(
        "# Paper\n\nMutual TLS reduced lateral movement incidents by 41 "
        "percent in Kubernetes clusters (Rose, 2024).\n"
    )

    _, summary = AcademicVerifier().build_provenance_and_verify(
        doc, [_latency_source()]
    )

    assert summary.supported_claims == 1
    assert summary.unsupported_claims == 0


def test_claim_without_a_figure_is_unaffected_by_quantity_grounding():
    doc = Document.parse(
        "# Paper\n\nMutual TLS reduced observed lateral movement incidents "
        "across Kubernetes clusters (Rose, 2024).\n"
    )

    _, summary = AcademicVerifier().build_provenance_and_verify(
        doc, [_latency_source()]
    )

    assert summary.supported_claims == 1


def _study_source(text: str) -> Source:
    return Source(
        id="S001",
        title="Study",
        authors=["Rose, Scott"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text=text,
        evidence_depth="ABSTRACT",
        relevance="DIRECT",
    )


_SUBJECT = (
    "insider breaches across enterprise Kubernetes clusters under mutual TLS "
    "deployment"
)


def _supported(claim: str, source_text: str) -> bool:
    _, summary = AcademicVerifier().build_provenance_and_verify(
        Document.parse(f"# P\n\n{claim}\n"), [_study_source(source_text)]
    )
    return summary.supported_claims == 1


def test_rounded_claim_is_supported_by_a_more_precise_source():
    """A source reporting 41.2% supports a paper that rounds it to 41%."""
    assert _supported(
        f"Roughly 41% of {_SUBJECT} failed authentication (Rose, 2024).",
        f"In our trial, 41.2% of {_SUBJECT} failed authentication.",
    )


def test_decimal_rate_in_source_supports_a_percentage_claim():
    assert _supported(
        f"The model had a 5% false positive rate for {_SUBJECT} (Rose, 2024).",
        f"The false positive rate was 0.05 for {_SUBJECT}.",
    )


def test_thousands_separator_does_not_break_matching():
    assert _supported(
        f"Throughput for {_SUBJECT} scaled by 1200% (Rose, 2024).",
        f"Throughput for {_SUBJECT} scaled by 1,200%.",
    )


def test_reference_marker_does_not_ground_a_percentage():
    """"[41]" is a citation marker, not a measurement of 41 percent."""
    assert not _supported(
        f"Our analysis revealed a 41 percent drop in {_SUBJECT} (Rose, 2024).",
        f"Prior threat models for {_SUBJECT} assume perimeter defenses [41].",
    )


def test_section_number_does_not_ground_a_percentage():
    assert not _supported(
        f"Failure rates for {_SUBJECT} stabilized at 4.1 percent (Rose, 2024).",
        f"As detailed in Section 4.1, {_SUBJECT} were distributed evenly.",
    )


def test_same_number_in_a_different_unit_does_not_ground_a_percentage():
    assert not _supported(
        f"mTLS produced a 41 percent drop in latency for {_SUBJECT} (Rose, 2024).",
        f"Average ping time for {_SUBJECT} settled at 41 milliseconds.",
    )


def test_leading_decimal_percentage_is_still_checked():
    assert not _supported(
        f"False rejections for {_SUBJECT} dropped by .5% (Rose, 2024).",
        f"False rejections for {_SUBJECT} decreased slightly.",
    )


_TWO_TRENDS = (
    "Security enforcement increased deployment velocity across enterprise "
    "Kubernetes clusters by 15 percent. Separately, incident counts decreased "
    "by 40 percent."
)
_VELOCITY = (
    "deployment velocity across enterprise Kubernetes clusters under security "
    "enforcement"
)


def _supported_against(claim: str, source_text: str) -> bool:
    source = _study_source(source_text)
    source.authors = ["Alvarez, Nina"]
    _, summary = AcademicVerifier().build_provenance_and_verify(
        Document.parse(f"# P\n\n{claim}\n"), [source]
    )
    return summary.supported_claims == 1


def test_claim_reversing_its_source_is_not_supported():
    """The figure and the topic match; the claim says the opposite happened."""
    assert not _supported_against(
        f"Security enforcement decreased {_VELOCITY} by 15 percent "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )


def test_claim_agreeing_with_its_source_stays_supported():
    assert _supported_against(
        f"Security enforcement increased {_VELOCITY} by 15 percent "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )


def test_direction_is_bound_to_the_sentence_reporting_the_same_figure():
    """A different trend elsewhere in the abstract must not manufacture a
    disagreement, nor excuse a real one."""
    assert _supported_against(
        f"Incident counts decreased by 40 percent for {_VELOCITY} "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )
    assert not _supported_against(
        f"Incident counts increased by 40 percent for {_VELOCITY} "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )


def test_claim_without_a_direction_word_is_not_judged_on_direction():
    assert _supported_against(
        f"Security enforcement shifted {_VELOCITY} by 15 percent "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )


def test_author_surname_is_not_read_as_a_direction_word():
    """"(Rose, 2024)" must not make a claim read as "rose"."""
    source = _study_source(
        f"Security enforcement reduced {_VELOCITY} by 15 percent."
    )
    _, summary = AcademicVerifier().build_provenance_and_verify(
        Document.parse(
            f"# P\n\nSecurity enforcement reduced {_VELOCITY} by 15 percent "
            "(Rose, 2024).\n"
        ),
        [source],
    )
    assert summary.supported_claims == 1


def test_same_figure_for_two_metrics_supports_a_claim_about_either():
    """A source can report 15% for two metrics moving opposite ways.

    Rejecting on the first sentence that disagreed threw out correct claims.
    """
    source_text = (
        "Throughput rose by 15 percent across enterprise Kubernetes clusters. "
        "Latency fell by 15 percent across enterprise Kubernetes clusters."
    )
    assert _supported_against(
        "Latency fell by 15 percent across enterprise Kubernetes clusters "
        "(Alvarez, 2024).",
        source_text,
    )
    assert _supported_against(
        "Throughput rose by 15 percent across enterprise Kubernetes clusters "
        "(Alvarez, 2024).",
        source_text,
    )


def test_a_gain_claimed_against_a_reported_loss_is_not_supported():
    assert not _supported_against(
        "The fund recorded a 15 percent gain across enterprise Kubernetes "
        "clusters (Alvarez, 2024).",
        "The fund suffered a 15 percent loss across enterprise Kubernetes "
        "clusters.",
    )


def test_each_claim_cites_the_sentence_that_bears_on_it():
    """Evidence is the record of what a claim rests on.

    Handing every claim the opening of the abstract made the graph say the
    same thing about all of them, and for most the quoted text did not mention
    the claim's subject at all.
    """
    source = _study_source(
        "Mutual TLS deployment across the service mesh reduced lateral "
        "movement incidents by 41 percent in Kubernetes clusters. "
        "Separately, workload attestation via SPIFFE cut credential theft "
        "materially. "
        "Operators reported that policy-as-code adoption simplified audit "
        "preparation."
    )
    source.authors = ["Alvarez, Nina"]
    document = Document.parse(
        "# P\n\n"
        "Mutual TLS reduced lateral movement incidents by 41 percent "
        "(Alvarez, 2024).\n"
        "Workload attestation via SPIFFE cut credential theft (Alvarez, 2024).\n"
        "Policy-as-code adoption simplified audit preparation (Alvarez, 2024).\n"
    )

    graph, _ = AcademicVerifier().build_provenance_and_verify(document, [source])

    snippets = {
        claim_id: graph.evidence_for_claim(claim_id)[0].snippet
        for claim_id in graph.claims
        if graph.evidence_for_claim(claim_id)
    }
    assert len(set(snippets.values())) == 3, "every claim got the same evidence"
    for snippet, expected in zip(
        [snippets[c] for c in sorted(snippets)],
        ["Mutual TLS", "SPIFFE", "policy-as-code"],
    ):
        assert expected in snippet


_KUBE = "across enterprise Kubernetes clusters under security enforcement"


def test_negated_claim_does_not_agree_with_a_reported_increase():
    """"did not increase" is not a rise, and previously read as one."""
    assert not _supported_against(
        f"Deployment velocity did not increase by 15 percent {_KUBE} "
        "(Alvarez, 2024).",
        f"Deployment velocity increased by 15 percent {_KUBE}.",
    )


def test_negated_source_does_not_support_a_plain_increase_claim():
    assert not _supported_against(
        f"Deployment velocity increased by 15 percent {_KUBE} (Alvarez, 2024).",
        f"Deployment velocity did not increase by 15 percent {_KUBE}.",
    )


def test_two_metrics_swapped_between_claim_and_source_is_caught():
    """Direction is read per clause, so a sentence carrying both a rise and a
    fall no longer abandons the check."""
    assert not _supported_against(
        f"Latency fell by 10 percent and throughput grew by 20 percent {_KUBE} "
        "(Alvarez, 2024).",
        f"Latency grew by 10 percent and throughput fell by 20 percent {_KUBE}.",
    )


def test_two_metrics_in_agreement_stay_supported():
    assert _supported_against(
        f"Latency fell by 10 percent and throughput grew by 20 percent {_KUBE} "
        "(Alvarez, 2024).",
        f"Latency fell by 10 percent and throughput grew by 20 percent {_KUBE}.",
    )


def test_negation_after_the_direction_word_does_not_flip_it():
    """"increased ... without additional cost" is still an increase."""
    assert _supported_against(
        f"Throughput increased by 15 percent {_KUBE} without additional cost "
        "(Alvarez, 2024).",
        f"Throughput increased by 15 percent {_KUBE} without additional cost.",
    )


def test_unrelated_negation_in_another_clause_is_ignored():
    assert _supported_against(
        f"Latency fell by 15 percent {_KUBE}, though this was not unexpected "
        "(Alvarez, 2024).",
        f"Latency fell by 15 percent {_KUBE}.",
    )


def test_not_only_is_emphasis_not_negation():
    """"not only fell" reports a fall; reading "not" as negating the verb
    turned a correct claim into a contradiction."""
    assert _supported_against(
        f"Latency not only fell by 15 percent {_KUBE} but also stabilized "
        "(Alvarez, 2024).",
        f"Latency fell by 15 percent {_KUBE}.",
    )


def test_prevention_verbs_do_not_flip_a_direction():
    """Prevention framing is deliberately unhandled.

    Every rule broad enough to read "a 15% increase was prevented" as no rise
    also flipped these, which are ordinary prose, so the narrower rule is the
    honest one. "A 15% increase was prevented" is therefore still read as an
    increase; that limit is recorded rather than papered over.
    """
    assert _supported_against(
        "The study avoided selection bias and throughput rose by 15 percent "
        f"{_KUBE} (Alvarez, 2024).",
        "The study avoided selection bias and throughput rose by 15 percent "
        f"{_KUBE}.",
    )
    assert _supported_against(
        f"The protocol avoided deadlock by increasing timeouts by 15 percent "
        f"{_KUBE} (Alvarez, 2024).",
        f"Timeouts were increased by 15 percent {_KUBE}.",
    )
    assert _supported_against(
        f"Throughput increased by 15 percent {_KUBE} because bottlenecks were "
        "eliminated (Alvarez, 2024).",
        f"Throughput increased by 15 percent {_KUBE}.",
    )


def test_litotes_and_quantifiers_are_not_read_as_negating_the_verb():
    """"a not insignificant increase" and "with no overhead" are not denials.

    A three-token negation window turned both into contradictions, so only a
    verbal negator immediately before the direction word counts.
    """
    assert _supported_against(
        "The authors observed a not insignificant increase of 15 percent in "
        f"throughput {_KUBE} (Alvarez, 2024).",
        f"Throughput increased by 15 percent {_KUBE}.",
    )
    assert _supported_against(
        f"With no overhead latency fell by 15 percent {_KUBE} (Alvarez, 2024).",
        f"Latency fell by 15 percent {_KUBE}.",
    )
    assert _supported_against(
        f"The team observed no fewer than 15 percent increases in throughput "
        f"{_KUBE} (Alvarez, 2024).",
        f"Throughput increased by 15 percent {_KUBE}.",
    )


_TWO_METRICS_ONE_FIGURE = (
    "Latency fell by 15 percent while throughput grew by 15 percent "
    "across enterprise Kubernetes clusters."
)


def test_same_figure_on_two_metrics_binds_to_the_right_one():
    """A claim inverting either metric must be caught.

    With direction alone, "Latency grew by 15%" found the throughput clause,
    which also reports 15% and also rises, and was marked supported by it.
    """
    assert not _supported_against(
        f"Latency grew by 15 percent {_KUBE} (Alvarez, 2024).",
        _TWO_METRICS_ONE_FIGURE,
    )
    assert not _supported_against(
        f"Throughput fell by 15 percent {_KUBE} (Alvarez, 2024).",
        _TWO_METRICS_ONE_FIGURE,
    )


def test_same_figure_on_two_metrics_still_supports_agreeing_claims():
    assert _supported_against(
        f"Latency fell by 15 percent {_KUBE} (Alvarez, 2024).",
        _TWO_METRICS_ONE_FIGURE,
    )
    assert _supported_against(
        f"Throughput grew by 15 percent {_KUBE} (Alvarez, 2024).",
        _TWO_METRICS_ONE_FIGURE,
    )


def test_a_metric_the_source_never_discusses_is_not_contradicted():
    assert _supported_against(
        f"Memory use grew by 15 percent {_KUBE} (Alvarez, 2024).",
        _TWO_METRICS_ONE_FIGURE,
    )


def test_subject_binding_falls_back_when_a_clause_names_no_subject():
    """Passive framing puts the metric after the verb, leaving no subject.

    Losing the check there would be worse than comparing on the figure alone,
    so an unnamed subject falls back rather than abstaining.
    """
    assert _supported_against(
        f"Timeouts increased by 15 percent {_KUBE} (Alvarez, 2024).",
        f"There was an increase of 15 percent in timeouts {_KUBE}.",
    )


def test_differently_worded_subject_does_not_become_a_contradiction():
    assert _supported_against(
        f"Response latency fell by 15 percent {_KUBE} (Alvarez, 2024).",
        f"Latency fell by 15 percent {_KUBE}.",
    )


def test_passive_framing_cannot_evade_subject_binding():
    """"There was an increase of 15% in latency" names its metric after the
    verb. Reading only what precedes the verb left the clause subjectless,
    and a subjectless clause matches on the figure alone -- so a passive
    rewording of an inverted claim slipped through."""
    assert not _supported_against(
        f"There was an increase of 15 percent in latency {_KUBE} "
        "(Alvarez, 2024).",
        _TWO_METRICS_ONE_FIGURE,
    )
    assert _supported_against(
        f"There was a decrease of 15 percent in latency {_KUBE} "
        "(Alvarez, 2024).",
        _TWO_METRICS_ONE_FIGURE,
    )


def test_plural_metric_still_binds_to_its_singular():
    assert not _supported_against(
        f"Latencies grew by 15 percent {_KUBE} (Alvarez, 2024).",
        _TWO_METRICS_ONE_FIGURE,
    )


def test_a_shared_modifier_does_not_make_two_metrics_contradict():
    """"median request latency" and "median request throughput" share two
    words and are about different things."""
    assert _supported_against(
        f"Median request latency fell by 15 percent {_KUBE} (Alvarez, 2024).",
        f"Median request throughput grew by 15 percent {_KUBE}.",
    )


def test_a_postmodified_metric_still_binds():
    """"latency for requests" heads on "requests"; "request latency" heads on
    "latency". Either head naming the other clause keeps them together."""
    assert not _supported_against(
        f"Request latency grew by 15 percent {_KUBE} (Alvarez, 2024).",
        f"Latency for requests fell by 15 percent {_KUBE}.",
    )


def test_a_metric_named_after_a_movement_is_not_self_contradictory():
    """"Packet loss increased" is a rise in loss.

    Counting "loss" as a fall alongside "increased" as a rise made the clause
    read as carrying both directions, which switched the check off entirely
    and let the inversion through.
    """
    assert not _supported_against(
        f"Packet loss increased by 15 percent {_KUBE} (Alvarez, 2024).",
        f"Packet loss fell by 15 percent {_KUBE}.",
    )
    assert not _supported_against(
        f"Revenue growth fell by 15 percent {_KUBE} (Alvarez, 2024).",
        f"Revenue growth increased by 15 percent {_KUBE}.",
    )
