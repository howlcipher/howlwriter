import math

import pytest

from howlwriter.voice.learner import CorpusStatsLearner

learner = CorpusStatsLearner()


def test_learn_raises_on_empty_corpus():
    with pytest.raises(ValueError):
        learner.learn([])


def test_learn_computes_known_statistics_on_a_hand_crafted_corpus():
    corpus = ["I can't believe it works. This is amazing! Really?"]
    profile = learner.learn(corpus, author_name="Test Author")

    assert profile.author_name == "Test Author"
    assert profile.generated_from == "corpus_stats"

    # sentence word counts (split on whitespace, punctuation attached): 5, 3, 1
    assert profile.sentence_length_mean == pytest.approx(3.0)
    assert profile.sentence_length_stdev == pytest.approx(math.sqrt(8 / 3))

    # one paragraph containing all three sentences
    assert profile.paragraph_length_mean == pytest.approx(3.0)

    # 1 contraction ("can't") across 9 total words
    assert profile.contraction_rate == pytest.approx(1 / 9)

    # 1 question ("Really?") out of 3 sentences
    assert profile.rhetorical_question_rate == pytest.approx(1 / 3)

    # "This is amazing!" and "Really?" are both under the 4-word floor
    assert profile.fragment_rate == pytest.approx(2 / 3)


def test_representative_examples_are_drawn_verbatim_from_the_corpus():
    corpus = ["I can't believe it works. This is amazing! Really?"]
    profile = learner.learn(corpus)
    original_sentences = {"I can't believe it works.", "This is amazing!", "Really?"}
    assert profile.representative_examples
    for example in profile.representative_examples:
        assert example.text in original_sentences


def test_learn_handles_multi_document_corpus():
    corpus = ["First document. It has two sentences.", "Second document here."]
    profile = learner.learn(corpus)
    assert profile.sentence_length_mean > 0
