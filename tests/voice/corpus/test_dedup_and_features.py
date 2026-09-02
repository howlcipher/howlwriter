"""Deduplication, revision grouping, and deterministic feature extraction."""

from __future__ import annotations

from pathlib import Path

from howlwriter.voice.corpus.dedup import (
    DedupCandidate,
    base_name,
    content_hash,
    deduplicate,
    jaccard,
    shingles,
)
from howlwriter.voice.corpus.features import extract_features
from tests.voice.corpus.conftest import synthetic_prose

BASE = (
    "The rollback took eleven minutes, which was longer than the incident that "
    "caused it. The runbook had not been touched since the migration.\n\n"
    "The dashboard reported success while the queue was still draining, because "
    "the metric measured the wrong boundary and had done for months.\n\n"
    "Fixing the metric took an afternoon. Finding the others took much longer."
)


def _candidate(key: str, text: str, suffix: str = ".md", words: int | None = None, mtime: float = 0.0):
    return DedupCandidate(
        key=key, path=Path(f"/corpus/{key}{suffix}"), text=text,
        words=words if words is not None else len(text.split()), mtime=mtime,
    )


# --- exact duplicates --------------------------------------------------

def test_exact_content_duplicates_collapse_to_one():
    result = deduplicate([
        _candidate("a", BASE),
        _candidate("b", BASE),
        _candidate("c", synthetic_prose(1)),
    ])
    assert result.exact_duplicates == 1
    assert len(result.representatives()) == 2


def test_whitespace_and_case_differences_still_count_as_exact():
    result = deduplicate([
        _candidate("a", BASE),
        _candidate("b", BASE.upper().replace("\n\n", "\n\n\n   ")),
    ])
    assert result.exact_duplicates == 1


def test_content_hash_is_stable_and_normalizing():
    assert content_hash(BASE) == content_hash(BASE.upper())
    assert content_hash(BASE) != content_hash(BASE + " One more sentence here.")


# --- cross-format ------------------------------------------------------

def test_cross_format_duplicate_prefers_the_richer_format():
    """A .docx and its .pdf export are one document; the .docx wins."""
    result = deduplicate([
        _candidate("paper", BASE, suffix=".pdf"),
        _candidate("paper2", BASE + " A trailing sentence from the export.", suffix=".docx"),
    ])
    assert result.cross_format_duplicates == 1
    representative = result.representatives()[0]
    assert result.members[representative].role == "representative"
    assert representative == "paper2"


def test_a_pdf_of_entirely_different_content_is_not_a_cross_format_duplicate():
    result = deduplicate([
        _candidate("one", BASE, suffix=".pdf"),
        _candidate("two", synthetic_prose(9), suffix=".docx"),
    ])
    assert result.cross_format_duplicates == 0
    assert len(result.representatives()) == 2


# --- revisions ---------------------------------------------------------

def test_near_duplicate_revision_is_grouped():
    revised = BASE.replace("eleven minutes", "twelve minutes") + "\n\nOne added paragraph."
    result = deduplicate([_candidate("v1", BASE), _candidate("v2", revised)])
    assert result.revision_duplicates == 1
    assert result.revision_groups == 1


def test_filename_revision_markers_are_recognized():
    assert base_name(Path("A5 (1).docx")) == base_name(Path("A5.docx"))
    assert base_name(Path("paper v2.docx")) == base_name(Path("paper.docx"))
    assert base_name(Path("report - Copy.docx")) == base_name(Path("report.docx"))
    assert base_name(Path("essay_final.docx")) == base_name(Path("essay.docx"))
    assert base_name(Path("Chapter Analysisv2.docx")) == base_name(Path("Chapter Analysis.docx"))


def test_same_base_name_with_unrelated_content_is_not_grouped():
    """A reused filename must not merge two genuinely different documents."""
    result = deduplicate([
        _candidate("A5", BASE),
        _candidate("A5 (1)", synthetic_prose(21, paragraphs=8)),
    ])
    assert len(result.representatives()) == 2


def test_revision_group_reports_one_family_not_many_observations():
    variants = [BASE]
    for index in range(4):
        variants.append(BASE.replace("eleven", f"{index + 12}"))
    result = deduplicate([_candidate(f"v{i}", text) for i, text in enumerate(variants)])
    assert len(result.representatives()) == 1
    assert result.revision_groups == 1


def test_grouping_is_deterministic_regardless_of_input_order():
    candidates = [
        _candidate("a", BASE),
        _candidate("b", BASE.replace("eleven", "twelve")),
        _candidate("c", synthetic_prose(3)),
        _candidate("d", synthetic_prose(4)),
    ]
    first = deduplicate(candidates)
    second = deduplicate(list(reversed(candidates)))
    assert sorted(first.representatives()) == sorted(second.representatives())


def test_every_member_carries_a_reason():
    result = deduplicate([_candidate("a", BASE), _candidate("b", BASE)])
    duplicate = [m for m in result.members.values() if m.role == "duplicate"][0]
    assert duplicate.relation == "exact"
    assert duplicate.reason


def test_shingle_overlap_behaves():
    assert jaccard(shingles(BASE), shingles(BASE)) == 1.0
    assert jaccard(shingles(BASE), shingles(synthetic_prose(5))) < 0.05


def test_empty_input_is_handled():
    result = deduplicate([])
    assert result.groups == []
    assert result.representatives() == []


# --- deterministic features -------------------------------------------

def test_features_are_deterministic():
    text = synthetic_prose(11, paragraphs=5)
    assert extract_features(text).to_dict() == extract_features(text).to_dict()


def test_sentence_statistics():
    text = "One two three four five. " + "Six seven eight nine ten eleven twelve. " * 3
    features = extract_features(text)
    assert features.sentences == 4
    assert features.sentence_length_mean > 0
    assert features.sentence_length_min == 5
    assert features.sentence_length_max == 7
    assert features.sentence_length_p90 >= features.sentence_length_median


def test_sentence_variation_is_captured_not_flattened():
    varied = "Short. " + ("A considerably longer sentence that runs on with several "
                          "clauses and keeps going for a while yet. ") * 3 + "Tiny."
    uniform = "Exactly six words in this sentence. " * 5
    assert extract_features(varied).sentence_length_stdev > \
        extract_features(uniform).sentence_length_stdev


def test_paragraph_distribution():
    text = "One sentence here.\n\nTwo sentences here. And another one.\n\nThree. Four. Five."
    features = extract_features(text)
    assert features.paragraphs == 3
    assert features.paragraph_sentences_mean == 2.0
    assert features.paragraph_sentences_stdev > 0


def test_contraction_feature():
    with_contractions = "I don't think it's working. We won't know until it's live. I'd wait."
    without = "I do not think it is working. We will not know until it is live. I would wait."
    assert extract_features(with_contractions).contraction_rate > \
        extract_features(without).contraction_rate
    assert extract_features(without).contraction_rate == 0.0


def test_pronoun_features():
    first = "I looked at my notes. We agreed our approach was wrong. I rewrote it."
    second = "You should check your notes. You will find your approach was wrong."
    assert extract_features(first).first_person_rate > 0
    assert extract_features(first).second_person_rate == 0
    assert extract_features(second).second_person_rate > 0
    assert extract_features(second).first_person_rate == 0


def test_punctuation_features():
    text = (
        "One clause, then another; then a third: and finally — an aside (a short one). "
        "Is that too much? Yes! It certainly is."
    )
    features = extract_features(text)
    assert features.comma_rate > 0
    assert features.semicolon_rate > 0
    assert features.colon_rate > 0
    assert features.em_dash_rate > 0
    assert features.parenthetical_rate > 0
    assert features.question_rate > 0
    assert features.exclamation_rate > 0


def test_lexical_diversity_distinguishes_repetitive_from_varied():
    repetitive = "The same word again. " * 20
    varied = synthetic_prose(13, paragraphs=4)
    assert extract_features(repetitive).lexical_diversity < \
        extract_features(varied).lexical_diversity


def test_transition_and_conjunction_features():
    signposted = (
        "However, the result held. Furthermore, it held twice. "
        "Therefore we shipped it. Moreover, nothing broke."
    )
    plain = "The result held. It held twice. We shipped it. Nothing broke."
    assert extract_features(signposted).transition_rate > extract_features(plain).transition_rate

    conjunctions = "And then it broke. But nobody noticed. So we waited. Or we thought we did."
    assert extract_features(conjunctions).sentence_initial_conjunction_rate > 0.9


def test_headings_are_counted_but_excluded_from_sentence_statistics():
    with_headings = "# A Heading\n\nOne real sentence here that is long enough to count.\n"
    without = "One real sentence here that is long enough to count.\n"
    a = extract_features(with_headings)
    b = extract_features(without)
    assert a.heading_rate > 0
    assert b.heading_rate == 0
    assert a.sentence_length_mean == b.sentence_length_mean


def test_repetition_rate_detects_repeated_openings():
    repeated = "The system failed. The system recovered. The system failed again. The system held."
    varied = "Deployment failed. Recovery took minutes. Nobody escalated. Monday came anyway."
    assert extract_features(repeated).repetition_rate > extract_features(varied).repetition_rate


def test_empty_and_whitespace_input_returns_zeroed_features():
    for text in ("", "   \n\n  "):
        features = extract_features(text)
        assert features.words == 0
        assert features.sentences == 0
        assert features.sentence_length_mean == 0.0
