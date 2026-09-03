"""Adversarial checks for deterministic rhetorical classification."""

from howlwriter.voice.corpus.diversity import (
    classify_closing,
    classify_opening,
    classify_reasoning_moves,
    classify_reasoning_shape,
)


def test_a_later_question_does_not_turn_a_declarative_opening_into_a_question():
    text = (
        "Bounded queues protect latency under overload. Why do teams still "
        "configure them without limits?"
    )
    assert classify_opening(text) == "direct_thesis"


def test_a_colon_inside_a_claim_is_not_mistaken_for_a_labelled_opening():
    text = "Reliability improves when queues are bounded: overload stays local."
    assert classify_opening(text) == "direct_thesis"


def test_a_real_short_labelled_opening_is_distinguished_from_a_thesis():
    text = "Connection pooling: more connections can reduce throughput."
    assert classify_opening(text) == "labelled_claim"


def test_contextual_and_conditional_setups_are_distinct():
    assert (
        classify_opening("For small services, a bounded pool is enough.")
        == "contextual_statement"
    )
    assert (
        classify_opening("If the queue is unbounded, tail latency wins.")
        == "conditional_setup"
    )


def test_headings_and_hashtag_trailers_do_not_control_the_classes():
    text = (
        "# Queueing\n\n"
        "Why let overload spread across every dependency?\n\n"
        "Cap the queue before it caps your availability.\n\n"
        "#Reliability #SRE"
    )
    assert classify_opening(text) == "question"
    assert classify_closing(text) == "recommendation"


def test_tradeoff_lexicon_alone_does_not_create_an_implication_close():
    assert (
        classify_closing("The design remains a deliberate trade-off.")
        == "declarative_stop"
    )


def test_recommendation_and_qualified_closes_are_meaningfully_separate():
    assert classify_closing("Teams should cap the queue.") == "recommendation"
    assert (
        classify_closing("If workload changes, that choice may need revision.")
        == "qualified_conclusion"
    )


def test_explanatory_block_count_does_not_masquerade_as_reasoning_diversity():
    three_blocks = (
        "Bounded queues protect a service.\n\n"
        "The queue absorbs short bursts.\n\n"
        "Capacity stays measurable.\n\n"
        "That is the operational takeaway."
    )
    four_blocks = (
        "Bounded queues protect a service.\n\n"
        "The queue absorbs short bursts.\n\n"
        "Capacity stays measurable.\n\n"
        "Overload remains local.\n\n"
        "That is the operational takeaway."
    )
    assert classify_reasoning_shape(three_blocks) == classify_reasoning_shape(
        four_blocks
    )
    assert classify_reasoning_moves(three_blocks).count("explanation") == 2
    assert classify_reasoning_moves(four_blocks).count("explanation") == 3


def test_problem_explanation_recommendation_is_not_a_thesis_mechanism_takeaway():
    problem_shape = classify_reasoning_shape(
        "The problem is an unbounded queue.\n\n"
        "Traffic accumulates faster than workers drain it.\n\n"
        "Teams should reject excess work early."
    )
    causal_shape = classify_reasoning_shape(
        "Bounded queues protect latency.\n\n"
        "They work because excess traffic is rejected early.\n\n"
        "The service remains predictable."
    )
    assert problem_shape == "problem>explanation>recommendation"
    assert causal_shape == "thesis>mechanism>takeaway"
    assert problem_shape != causal_shape
