"""Post schema, lifecycle rules, fingerprint, and configuration validation."""

import copy
import json
import random
from importlib import resources

import pytest
import yaml

from howlwriter.linkedin.config import CONFIG_SCHEMA, DEFAULTS, ConfigError, parse_config, render_default_config
from howlwriter.linkedin.models import (
    ALLOWED_TRANSITIONS,
    IllegalTransitionError,
    LifecycleState,
    MediaRef,
    Post,
    PostValidationError,
    content_fingerprint,
    require_transition,
)
from tests.linkedin.helpers import SHA, approved_post

S = LifecycleState
FP = "sha256:" + "b" * 64


def valid_document(service) -> dict:
    existing = service.store.load_snapshot().posts
    if existing:
        return existing[0].to_dict()
    return approved_post(service, "Schema subject", "2026-11-20").to_dict()


def _schema(name: str) -> dict:
    return json.loads(resources.files("howlwriter.schemas").joinpath(name).read_text(encoding="utf-8"))


# Mutations that both the JSON Schema and the run time parser must reject.
STRUCTURAL_DEFECTS = {
    "unknown key": lambda d: d.update(extra=1),
    "missing key": lambda d: d.pop("history"),
    "wrong schema": lambda d: d.update(schema="howlwriter.linkedin_post/v2"),
    "uppercase id": lambda d: d.update(id="Bad_ID"),
    "negative revision": lambda d: d.update(revision=-1),
    "boolean revision": lambda d: d.update(revision=True),
    "blank title": lambda d: d.update(title="   "),
    "multi line title": lambda d: d.update(title="a\nb"),
    "numeric text": lambda d: d.update(text=5),
    "oversized text": lambda d: d.update(text="x" * 20001),
    "http url": lambda d: d.update(urls=["http://example.com/a"]),
    "duplicate urls": lambda d: d.update(urls=["https://example.com/a", "https://example.com/a"]),
    "url with whitespace": lambda d: d.update(urls=["https://example.com/a b"]),
    "media traversal": lambda d: d.update(media=[{"path": "media/../x.png", "sha256": SHA, "alt_text": "x"}]),
    "media outside media dir": lambda d: d.update(media=[{"path": "posts/x.png", "sha256": SHA, "alt_text": "x"}]),
    "media without alt text": lambda d: d.update(media=[{"path": "media/x.png", "sha256": SHA, "alt_text": " "}]),
    "two media": lambda d: d.update(media=[{"path": f"media/{n}.png", "sha256": SHA, "alt_text": "x"} for n in "ab"]),
    "timestamp with offset": lambda d: d.update(created_at="2026-11-16T07:00:00-05:00"),
    "bad date shape": lambda d: d.update(scheduled_date="20261120"),
    "bad time": lambda d: d.update(scheduled_time="24:00"),
    "unknown state": lambda d: d.update(state="LIVE"),
    "short fingerprint": lambda d: d.update(content_fingerprint="sha256:abc"),
    "approval ref extra key": lambda d: d["approval_ref"].update(by="someone"),
    "approval ref absolute path": lambda d: d["approval_ref"].update(path="/etc/passwd"),
    "attempt bad outcome": lambda d: d.update(
        attempts=[{"attempt_id": "attempt-001", "started_at": d["created_at"], "content_fingerprint": FP,
                   "outcome": "MAYBE", "finished_at": None, "detail": ""}]
    ),
    "history not a list": lambda d: d.update(history={}),
    "history missing actor": lambda d: d.update(history=[{"at": d["created_at"], "action": "x", "detail": ""}]),
    "not an object": None,
}

# Defects only the run time parser catches (it is stricter than the schema by design).
SEMANTIC_DEFECTS = {
    "impossible date": lambda d: d.update(scheduled_date="2026-02-30"),
    "unknown timezone": lambda d: d.update(timezone="Mars/Olympus"),
    "approved without approval": lambda d: d.update(approval_ref=None),
    "scheduled without date": lambda d: d.update(state="SCHEDULED", scheduled_date=None),
    "published without id": lambda d: d.update(state="PUBLISHED"),
    "linkedin id on a draft": lambda d: d.update(state="DRAFT", linkedin_post_id="urn:li:share:9"),
    "publishing without intent": lambda d: d.update(state="PUBLISHING"),
    "updated before created": lambda d: d.update(updated_at="2020-01-01T00:00:00Z"),
    "pending attempt on approved post": lambda d: d.update(
        attempts=[{"attempt_id": "attempt-001", "started_at": d["created_at"], "content_fingerprint": FP,
                   "outcome": "PENDING", "finished_at": None, "detail": ""}]
    ),
}


def _mutated(service, mutate):
    if mutate is None:
        return ["not", "an", "object"]
    document = copy.deepcopy(valid_document(service))
    mutate(document)
    return document


@pytest.mark.parametrize("name", sorted(STRUCTURAL_DEFECTS))
def test_parser_rejects_structural_defects(service, name):
    with pytest.raises(PostValidationError):
        Post.from_dict(_mutated(service, STRUCTURAL_DEFECTS[name]))


@pytest.mark.parametrize("name", sorted(SEMANTIC_DEFECTS))
def test_parser_rejects_lifecycle_and_semantic_defects(service, name):
    with pytest.raises(PostValidationError):
        Post.from_dict(_mutated(service, SEMANTIC_DEFECTS[name]))


def test_parser_reports_every_problem_at_once(service):
    document = valid_document(service)
    document.update(id="BAD", title="", state="LIVE")
    with pytest.raises(PostValidationError) as caught:
        Post.from_dict(document)
    assert len(caught.value.problems) == 3


def test_json_schema_and_parser_agree(service):
    """Contract: the schema accepts what the parser accepts and rejects every structural defect."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema("howlwriter.linkedin_post.v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    valid = valid_document(service)
    assert Post.from_dict(valid).to_dict() == valid
    assert validator.is_valid(valid)
    for name, mutate in STRUCTURAL_DEFECTS.items():
        assert not validator.is_valid(_mutated(service, mutate)), name


def test_config_schema_matches_defaults_and_rejects_bad_values():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema("howlwriter.linkedin_publisher_config.v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    assert validator.is_valid({"schema": CONFIG_SCHEMA, **DEFAULTS})
    assert {key: spec["default"] for key, spec in schema["properties"].items() if "default" in spec} == DEFAULTS
    assert not validator.is_valid({"schema": CONFIG_SCHEMA, "max_posts_per_day": 2})
    assert not validator.is_valid({"schema": CONFIG_SCHEMA, "surprise": True})


def test_round_trip_is_lossless(service):
    post = approved_post(service, "Round trip", "2026-11-20", "09:00")
    assert Post.from_dict(json.loads(post.to_json())) == post


# Fingerprint


def test_fingerprint_changes_with_text_links_and_media():
    media = (MediaRef("media/a.png", SHA, "A chart"),)
    base = content_fingerprint("Hello", ("https://example.com/a",), media)
    assert base == content_fingerprint("Hello", ("https://example.com/a",), media)
    changed = [
        content_fingerprint("Hello.", ("https://example.com/a",), media),
        content_fingerprint("Hello ", ("https://example.com/a",), media),
        content_fingerprint("Hello", ("https://example.com/b",), media),
        content_fingerprint("Hello", (), media),
        content_fingerprint("Hello", ("https://example.com/a",), ()),
        content_fingerprint("Hello", ("https://example.com/a",), (MediaRef("media/a.png", "c" * 64, "A chart"),)),
        content_fingerprint("Hello", ("https://example.com/a",), (MediaRef("media/a.png", SHA, "Another"),)),
    ]
    assert base not in changed and len(set(changed)) == len(changed)


def test_fingerprint_ignores_schedule_and_title(service):
    post = approved_post(service, "Stable", "2026-11-20")
    moved = service.reschedule(
        post.id, actor="tester", new_date="2026-11-25", new_time="09:00", authorized=True
    )
    retitled = service.update_content(post.id, actor="tester", title="A new internal title")
    assert post.computed_fingerprint() == moved.computed_fingerprint() == retitled.computed_fingerprint()
    assert retitled.approval_is_current and retitled.state is S.APPROVED


def test_fingerprint_is_stable_across_unicode_and_key_order():
    text = "Café \U0001f680 naïve"
    assert content_fingerprint(text, (), ()) == content_fingerprint(text, [], [])
    assert content_fingerprint(text, (), ()) != content_fingerprint("Café \U0001f680 naïve", (), ())


# Lifecycle


def test_every_transition_outside_the_table_is_refused():
    for current in S:
        for target in S:
            if target in ALLOWED_TRANSITIONS[current]:
                require_transition(current, target)
            else:
                with pytest.raises(IllegalTransitionError):
                    require_transition(current, target)


def test_lifecycle_safety_properties():
    assert ALLOWED_TRANSITIONS[S.ARCHIVED] == frozenset()
    assert ALLOWED_TRANSITIONS[S.UNCERTAIN] == {S.PUBLISHED, S.FAILED}
    assert ALLOWED_TRANSITIONS[S.PUBLISHED] == {S.ARCHIVED}
    # Only PUBLISHING can lead to PUBLISHED, apart from human reconciliation of UNCERTAIN.
    assert {s for s in S if S.PUBLISHED in ALLOWED_TRANSITIONS[s]} == {S.PUBLISHING, S.UNCERTAIN}
    assert {s for s in S if S.PUBLISHING in ALLOWED_TRANSITIONS[s]} == {S.SCHEDULED}
    assert {s for s in S if S.APPROVED in ALLOWED_TRANSITIONS[s]} == {S.READY_FOR_REVIEW, S.SCHEDULED}


def test_random_walks_never_reach_published_without_publishing():
    rng = random.Random(20261116)
    for _ in range(300):
        state, path = S.DRAFT, [S.DRAFT]
        for _ in range(25):
            options = sorted(ALLOWED_TRANSITIONS[state], key=lambda s: s.value)
            if not options:
                break
            state = rng.choice(options)
            path.append(state)
        for index, visited in enumerate(path):
            if visited is S.PUBLISHED:
                assert path[index - 1] in (S.PUBLISHING, S.UNCERTAIN)
                assert S.PUBLISHING in path[:index]


# Configuration


def test_default_config_file_is_valid_and_safe():
    config = parse_config(yaml.safe_load(render_default_config()))
    assert config.to_dict() == {"schema": CONFIG_SCHEMA, **DEFAULTS}
    assert config.publishing_enabled is False and config.dry_run is True
    assert config.timezone == "America/Detroit" and config.default_publish_time == "08:30"


def test_missing_keys_take_defaults():
    assert parse_config({"schema": CONFIG_SCHEMA}).allowed_publish_times == ("08:30", "09:00")


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"default_publish_time": "10:15"}, "not one of the supported slots"),
        ({"allowed_publish_times": []}, "allowed_publish_times"),
        ({"allowed_publish_times": ["08:30", "08:30"]}, "unique"),
        ({"allowed_publish_times": ["8:30"]}, "HH:MM"),
        ({"timezone": "Detroit"}, "timezone"),
        ({"max_posts_per_day": 2}, "max_posts_per_day"),
        ({"max_posts_per_day": 0}, "max_posts_per_day"),
        ({"max_posts_per_day": True}, "max_posts_per_day"),
        ({"publishing_enabled": "yes"}, "publishing_enabled"),
        ({"dry_run": 0}, "dry_run"),
        ({"max_lateness_minutes": 100000}, "max_lateness_minutes"),
        ({"surprise": 1}, "unknown key"),
        ({"schema": "other/v1"}, "schema"),
    ],
)
def test_invalid_config_is_rejected(override, fragment):
    with pytest.raises(ConfigError) as caught:
        parse_config({"schema": CONFIG_SCHEMA, **override})
    assert fragment in str(caught.value)


def test_unquoted_yaml_time_is_rejected_with_a_hint():
    """YAML 1.1 reads an unquoted 9:00 as the number 540. That must never become a schedule."""
    data = yaml.safe_load(f"schema: {CONFIG_SCHEMA}\ndefault_publish_time: 9:00\nallowed_publish_times: [9:00]\n")
    assert data["default_publish_time"] == 540
    with pytest.raises(ConfigError) as caught:
        parse_config(data)
    assert "quotes" in str(caught.value)


def test_config_must_be_a_mapping():
    with pytest.raises(ConfigError):
        parse_config(["timezone"])
