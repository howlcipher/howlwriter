"""External, validated configuration for the LinkedIn publisher.

The configuration lives in ``publisher.yaml`` at the root of the private
publishing repository. Nothing here is hardcoded behavior: the values below
are only the defaults written by ``howlwriter linkedin init`` and used for
keys a file leaves out. Unknown keys and invalid values are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from howlwriter.linkedin.models import TIME_PATTERN, is_valid_timezone

CONFIG_SCHEMA = "howlwriter.linkedin_publisher_config/v1"
CONFIG_FILENAME = "publisher.yaml"

DEFAULTS: dict[str, Any] = {
    "timezone": "America/Detroit",
    "default_publish_time": "08:30",
    "allowed_publish_times": ["08:30", "09:00"],
    "max_posts_per_day": 1,
    "publishing_enabled": False,
    "dry_run": True,
    "max_lateness_minutes": 180,
    "verification_max_age_days": 7,
    "approval_max_age_days": 30,
}

#: The one post per calendar day rule is a hard product invariant. The value is
#: still read from configuration and enforced through the persisted ledger, but
#: this version refuses anything above the ceiling instead of silently allowing it.
MAX_POSTS_PER_DAY_CEILING = 1
MAX_LATENESS_CEILING_MINUTES = 720
MAX_ALLOWED_TIMES = 6
MAX_VERIFICATION_AGE_CEILING_DAYS = 30
MAX_APPROVAL_AGE_CEILING_DAYS = 90

_KEYS = frozenset(DEFAULTS) | {"schema"}


class ConfigError(ValueError):
    """The publisher configuration is invalid. ``problems`` lists every defect."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("invalid publisher configuration: " + "; ".join(self.problems))


@dataclass(frozen=True)
class PublisherConfig:
    timezone: str
    default_publish_time: str
    allowed_publish_times: tuple[str, ...]
    max_posts_per_day: int
    publishing_enabled: bool
    dry_run: bool
    max_lateness_minutes: int
    verification_max_age_days: int = 7
    approval_max_age_days: int = 30

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONFIG_SCHEMA,
            "timezone": self.timezone,
            "default_publish_time": self.default_publish_time,
            "allowed_publish_times": list(self.allowed_publish_times),
            "max_posts_per_day": self.max_posts_per_day,
            "publishing_enabled": self.publishing_enabled,
            "dry_run": self.dry_run,
            "max_lateness_minutes": self.max_lateness_minutes,
            "verification_max_age_days": self.verification_max_age_days,
            "approval_max_age_days": self.approval_max_age_days,
        }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _time_problem(name: str, value: Any) -> str | None:
    if isinstance(value, str) and TIME_PATTERN.match(value):
        return None
    hint = ""
    if _is_int(value):
        hint = ' (YAML read an unquoted time as a number; write it in quotes, for example "09:00")'
    return f"{name} must be a quoted 24 hour HH:MM time, got {value!r}{hint}"


def parse_config(data: Any) -> PublisherConfig:
    """Validate a configuration mapping and return an immutable config."""
    if not isinstance(data, dict):
        raise ConfigError(["configuration must be a mapping"])
    problems: list[str] = []
    unknown = sorted(str(key) for key in set(data) - _KEYS)
    if unknown:
        problems.append(f"unknown key(s): {', '.join(unknown)}")
    if data.get("schema") != CONFIG_SCHEMA:
        problems.append(f"schema must be {CONFIG_SCHEMA!r}, got {data.get('schema')!r}")
    merged = {**DEFAULTS, **{key: value for key, value in data.items() if key in DEFAULTS}}

    if not is_valid_timezone(merged["timezone"]):
        problems.append(f"timezone is not a known IANA zone: {merged['timezone']!r}")

    allowed = merged["allowed_publish_times"]
    allowed_ok = isinstance(allowed, list) and 1 <= len(allowed) <= MAX_ALLOWED_TIMES
    if not allowed_ok:
        problems.append(f"allowed_publish_times must be a list of 1 to {MAX_ALLOWED_TIMES} times")
    else:
        for item in allowed:
            problem = _time_problem("allowed_publish_times entry", item)
            if problem:
                problems.append(problem)
                allowed_ok = False
        if allowed_ok and len(set(allowed)) != len(allowed):
            problems.append("allowed_publish_times entries must be unique")
            allowed_ok = False

    default_problem = _time_problem("default_publish_time", merged["default_publish_time"])
    if default_problem:
        problems.append(default_problem)
    elif allowed_ok and merged["default_publish_time"] not in allowed:
        problems.append(
            f"default_publish_time {merged['default_publish_time']!r} is not one of the supported slots "
            f"{allowed}; add the slot to allowed_publish_times (and to the scheduled workflow) first"
        )

    limit = merged["max_posts_per_day"]
    if not _is_int(limit) or not 1 <= limit <= MAX_POSTS_PER_DAY_CEILING:
        problems.append(
            f"max_posts_per_day must be an integer from 1 to {MAX_POSTS_PER_DAY_CEILING} "
            "(one post per calendar day is a hard limit in this version)"
        )
    for key in ("publishing_enabled", "dry_run"):
        if not isinstance(merged[key], bool):
            problems.append(f"{key} must be true or false")
    lateness = merged["max_lateness_minutes"]
    if not _is_int(lateness) or not 0 <= lateness <= MAX_LATENESS_CEILING_MINUTES:
        problems.append(f"max_lateness_minutes must be an integer from 0 to {MAX_LATENESS_CEILING_MINUTES}")
    age = merged["verification_max_age_days"]
    if not _is_int(age) or not 1 <= age <= MAX_VERIFICATION_AGE_CEILING_DAYS:
        problems.append(
            f"verification_max_age_days must be an integer from 1 to {MAX_VERIFICATION_AGE_CEILING_DAYS}"
        )
    approval_age = merged["approval_max_age_days"]
    if not _is_int(approval_age) or not 1 <= approval_age <= MAX_APPROVAL_AGE_CEILING_DAYS:
        problems.append(
            f"approval_max_age_days must be an integer from 1 to {MAX_APPROVAL_AGE_CEILING_DAYS}"
        )

    if problems:
        raise ConfigError(problems)
    return PublisherConfig(
        timezone=merged["timezone"],
        default_publish_time=merged["default_publish_time"],
        allowed_publish_times=tuple(sorted(allowed)),
        max_posts_per_day=limit,
        publishing_enabled=merged["publishing_enabled"],
        dry_run=merged["dry_run"],
        max_lateness_minutes=lateness,
        verification_max_age_days=age,
        approval_max_age_days=approval_age,
    )


def load_config(path: Path) -> PublisherConfig:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            [f"{path} does not exist; run 'howlwriter linkedin init' in the publishing repository"]
        )
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError([f"{path.name} is not valid YAML: {error}"])
    return parse_config(data)


def render_default_config() -> str:
    """The starter ``publisher.yaml``: publishing off and dry run on."""
    return (
        "# LinkedIn publisher configuration. Validated on every command; unknown keys are rejected.\n"
        f"schema: {CONFIG_SCHEMA}\n"
        "timezone: America/Detroit\n"
        "# Times must be quoted. Every time listed here needs a matching scheduled workflow check.\n"
        'default_publish_time: "08:30"\n'
        "allowed_publish_times:\n"
        '  - "08:30"\n'
        '  - "09:00"\n'
        "max_posts_per_day: 1\n"
        "# Both switches must be flipped by a human before anything is sent.\n"
        "publishing_enabled: false\n"
        "dry_run: true\n"
        "# A due post is still published this many minutes after its slot (same calendar day only).\n"
        "max_lateness_minutes: 180\n"
        "# A verification report older than this blocks publication until the post is verified again.\n"
        "verification_max_age_days: 7\n"
        "# An approval older than this no longer permits publication; the post must be approved again.\n"
        "approval_max_age_days: 30\n"
    )
