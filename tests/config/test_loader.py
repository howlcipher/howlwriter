import pytest

from howlwriter.config.defaults import default_config
from howlwriter.config.loader import ConfigLoader, apply_overrides
from howlwriter.domain.modes import WritingMode


def test_defaults_survive_when_no_layers_set_a_field():
    config = ConfigLoader().load()
    assert config.citation_style == "apa7"
    assert any(bw.word == "delve" for bw in config.banned_words)


def test_mode_layer_overrides_defaults():
    config = ConfigLoader().load(mode=WritingMode.ACADEMIC)
    assert config.research_depth == "deep"
    assert config.fact_checking_strength == "high"


def test_project_override_does_not_clobber_mode_level_field():
    config = ConfigLoader().load(
        mode=WritingMode.ACADEMIC,
        request_overrides={"banned_words": ["jargon"]},
    )
    # citation_style came from the ACADEMIC mode layer and must survive
    # a later layer that only touches banned_words.
    assert config.citation_style == "apa7"
    assert [bw.word for bw in config.banned_words] == ["jargon"]


def test_request_overrides_win_over_all_prior_layers():
    config = ConfigLoader().load(
        mode=WritingMode.ACADEMIC,
        request_overrides={"citation_style": "mla"},
    )
    assert config.citation_style == "mla"


def test_banned_words_accepts_plain_strings_and_dicts_with_replacement():
    config = apply_overrides(
        default_config(),
        {"banned_words": ["delve", {"word": "utilize", "replacement": "use"}]},
    )
    words = {bw.word: bw.replacement for bw in config.banned_words}
    assert words == {"delve": None, "utilize": "use"}


def test_apply_overrides_rejects_unknown_field():
    with pytest.raises(ValueError):
        apply_overrides(default_config(), {"not_a_real_field": True})
