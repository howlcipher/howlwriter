"""The diversity checker has to actually run, and has to stay honest when it does.

Two failures this guards against, and the first is the one that was real.

The checker was fully implemented, fully tested, and invoked from no live code
path: `build.py` recorded NOT_EVALUATED unconditionally because no generated
text exists at corpus-build time, and nothing else called it. A verdict engine
nothing calls cannot catch a regression. The benchmark path now calls it, and
these tests hold that call in place.

The second is the audit's original finding: a FAIL must not be presentable as a
pass, a WARNING must not silently become a PASS, and a NOT_EVALUATED must
survive as itself rather than being rounded up to a result the sample never
supported.
"""

from __future__ import annotations

import sys
from pathlib import Path

from howlwriter.voice.corpus.diversity import (
    FAIL,
    NOT_EVALUATED,
    PASS,
    WARNING,
    compare,
)
from howlwriter.voice.corpus.features import extract_features

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "dogfood"))

from tests.voice.corpus.conftest import synthetic_prose  # noqa: E402


def _corpus(count: int = 12):
    return [extract_features(synthetic_prose(i, paragraphs=6)) for i in range(count)]


def test_the_benchmark_metrics_module_actually_invokes_the_checker():
    """The regression that mattered: a verdict engine nothing called."""
    from metrics import analyze_batch

    corpus = _corpus()
    generated = [synthetic_prose(200 + i, paragraphs=6) for i in range(8)]

    result = analyze_batch(generated, corpus_features=corpus)

    assert "diversity" in result
    assert result["diversity"]["verdict"] in (PASS, WARNING, FAIL, NOT_EVALUATED)
    # The dimensions travel with the verdict so it can be re-checked rather
    # than taken on trust.
    assert result["diversity"]["dimensions"]
    assert all(
        {"name", "ratio", "converged"} <= set(d) for d in result["diversity"]["dimensions"]
    )


def test_a_batch_that_barely_varies_fails_rather_than_passing():
    corpus = _corpus()
    identical = ["The same sentence structure repeated exactly here."] * 10
    result = compare(corpus, identical)

    assert result.verdict in (FAIL, WARNING, NOT_EVALUATED)
    assert result.verdict != PASS


def test_a_large_length_mismatch_yields_not_evaluated_rather_than_a_pass():
    """Comparing 900-word papers against 30-word posts measures length."""
    corpus = [extract_features(synthetic_prose(i, paragraphs=14)) for i in range(12)]
    short = [
        f"A short post number {i}. It says one thing and stops there quickly."
        for i in range(10)
    ]
    result = compare(corpus, short)

    assert result.verdict != PASS
    if result.verdict == NOT_EVALUATED:
        assert any("length" in note.lower() for note in result.notes)


def test_a_verdict_is_never_upgraded_by_the_serializer():
    """The metrics layer reports the checker's verdict, not a friendlier one."""
    from metrics import diversity_verdict

    corpus = _corpus()
    identical = ["Exactly the same words, every single time, without variation."] * 10

    direct = compare(corpus, identical)
    serialized = diversity_verdict(corpus, identical)

    assert serialized["verdict"] == direct.verdict
    assert serialized["converged_dimensions"] == list(direct.converged_dimensions)


def test_notes_survive_serialization_so_a_weakened_verdict_explains_itself():
    corpus = [extract_features(synthetic_prose(i, paragraphs=14)) for i in range(12)]
    short = [f"Tiny post {i}." for i in range(10)]

    from metrics import diversity_verdict

    payload = diversity_verdict(corpus, short)
    assert payload["notes"], "a weakened or withheld verdict must say why"


def test_the_build_records_not_evaluated_because_no_generated_text_exists_yet():
    """Honest at build time, and it must stay honest rather than defaulting to PASS."""
    import inspect

    from howlwriter.voice.corpus import build

    source = inspect.getsource(build)
    assert "diversity=diversity_stage.NOT_EVALUATED" in source
    assert "diversity=diversity_stage.PASS" not in source
