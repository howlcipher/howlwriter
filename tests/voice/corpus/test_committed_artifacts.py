"""What may and may not be committed.

The failure this guards against is quiet: a private profile, a corpus
fragment, or a Drive path landing in the repository because a build was run
with the wrong working directory. These assertions run in CI on every change.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
PROFILES = REPO / "profiles"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout


def _tracked() -> list[str]:
    return [line for line in _git("ls-files").splitlines() if line.strip()]


# --- the synthetic examples are committed ------------------------------

def test_the_synthetic_examples_exist_and_are_tracked():
    for name in ("voice_profile.example.yaml", "shared_style.example.yaml"):
        path = PROFILES / name
        assert path.is_file(), f"{name} is missing"
        assert f"profiles/{name}" in _tracked(), f"{name} must stay tracked"


def test_the_examples_are_valid_yaml_matching_the_documented_shape():
    personal = yaml.safe_load((PROFILES / "voice_profile.example.yaml").read_text())
    assert personal["version"] == 1
    assert personal["type"] == "personal_voice"
    assert personal["identity"]["profile_name"] == "example"
    assert "global" in personal and "contexts" in personal
    assert "academic" in personal["contexts"]
    assert personal["overrides"] == {"preserve": [], "avoid": [], "traits": {}, "notes": ""}

    shared = yaml.safe_load((PROFILES / "shared_style.example.yaml").read_text())
    assert shared["version"] == 1
    assert shared["type"] == "shared_style"


def test_personal_voice_and_shared_style_are_distinct_types():
    personal = yaml.safe_load((PROFILES / "voice_profile.example.yaml").read_text())
    shared = yaml.safe_load((PROFILES / "shared_style.example.yaml").read_text())
    assert personal["type"] != shared["type"]
    # A shared style describes a way of writing, so it carries no corpus
    # evidence: there is no individual for it to have observed.
    assert "corpus_summary" not in shared
    assert "validation" not in shared
    assert "corpus_summary" in personal


def test_the_examples_require_no_real_identity():
    for name in ("voice_profile.example.yaml", "shared_style.example.yaml"):
        text = (PROFILES / name).read_text().lower()
        assert "@" not in text.replace("e.g.", ""), f"{name} should carry no email"


def test_the_examples_declare_themselves_synthetic():
    for name in ("voice_profile.example.yaml", "shared_style.example.yaml"):
        header = (PROFILES / name).read_text()[:900].lower()
        assert "synthetic" in header
        assert "not derived" in header or "not committed" in header or "authored" in header


def test_the_shared_style_example_holds_no_phrase_bank():
    shared = yaml.safe_load((PROFILES / "shared_style.example.yaml").read_text())
    for key in ("preferred_phrases", "favorite_openings", "favorite_phrases",
                "reusable_stems", "representative_examples", "open_with"):
        assert key not in shared, key


def test_the_personal_example_holds_no_phrase_bank_or_passages():
    personal = yaml.safe_load((PROFILES / "voice_profile.example.yaml").read_text())
    for key in ("preferred_phrases", "representative_examples", "favorite_openings",
                "favorite_phrases", "reusable_stems"):
        assert key not in personal, key

    # Every leaf value is a short label or a number, never a sentence.
    def leaves(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from leaves(value)
        elif isinstance(node, list):
            for value in node:
                yield from leaves(value)
        else:
            yield node

    for value in leaves(personal):
        if isinstance(value, str) and value:
            assert len(value.split()) <= 4, value


# --- nothing private is committed --------------------------------------

def test_no_generated_voice_profile_is_tracked():
    tracked = _tracked()
    offenders = [
        path for path in tracked
        if Path(path).name in ("profile.json", "sources.json", "features.json", "build.json")
        or path.startswith("voices/")
        or path.startswith(".voice/")
        or ".voice.local." in path
    ]
    assert offenders == [], f"private voice artifacts are tracked: {offenders}"


#: This file is the one place these patterns legitimately appear, so it is
#: excluded from its own searches. Everything else in the tree is fair game.
_SELF = "tests/voice/corpus/test_committed_artifacts.py"

#: Assembled from fragments so the guard file does not itself contain the
#: literal strings it is searching for.
_MOUNT_MARKERS = ("Expan" + "Drive", "Google" + " Drive")
_PRIVATE_NAME_MARKERS = ("proton_" + "2FA", "William_" + "credentials")


def _grep_files(*patterns: str) -> list[str]:
    args = ["grep", "-l", "-i"]
    for pattern in patterns:
        args += ["-e", pattern]
    hits = _git(*args, "--", ".")
    return [
        line for line in hits.splitlines()
        if line.strip() and line != _SELF and not line.startswith("docs/")
    ]


def test_no_drive_path_or_home_corpus_path_is_committed():
    """A source path from the dogfood machine must never reach the repo."""
    offenders = _grep_files(*_MOUNT_MARKERS)
    assert offenders == [], f"drive paths committed in: {offenders}"


@pytest.mark.parametrize("marker", _PRIVATE_NAME_MARKERS)
def test_no_private_source_filename_is_committed(marker):
    offenders = _grep_files(marker)
    assert offenders == [], f"'{marker}' appears in: {offenders}"


def test_the_gitignore_covers_local_voice_artifacts_without_hiding_the_schema():
    rules = (REPO / ".gitignore").read_text()
    for pattern in (".voice/", "voices/", "voice_corpus/", "profiles/private/"):
        assert pattern in rules, pattern

    def ignored(path: str) -> bool:
        result = subprocess.run(
            ["git", "check-ignore", "-q", path], cwd=REPO, capture_output=True, check=False
        )
        return result.returncode == 0

    # The committed examples, schema, and tests must stay visible.
    assert not ignored("profiles/voice_profile.example.yaml")
    assert not ignored("profiles/shared_style.example.yaml")
    assert not ignored("src/howlwriter/domain/voice.py")
    assert not ignored("tests/voice/corpus/test_store_and_build.py")


# --- generation provenance artifacts ------------------------------------

def test_no_generation_provenance_artifact_is_tracked():
    """A provenance record is private user data, like a voice profile.

    At full level it contains every prompt HowlWriter built, and those prompts
    contain the user's own sentences. The sidecars are written beside whatever
    artifact the user chose to produce, which means they can land inside a
    repository, which means this has to be a gate rather than a convention.
    """
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    offenders = [
        path for path in tracked
        if path.endswith((".provenance.json", ".manifest.txt"))
    ]
    assert not offenders, (
        "generation provenance artifacts must stay local: " + ", ".join(offenders)
    )


def test_the_gitignore_covers_the_provenance_sidecars():
    body = (REPO / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.provenance.json", "*.manifest.txt", "*.outline.yaml"):
        assert pattern in body, f"{pattern} must be ignored"


def test_provenance_redaction_removes_credentials_before_anything_is_written():
    """The one guard that runs on content rather than on filenames."""
    from howlwriter.domain.generation_provenance import redact

    for secret in (
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        "AKIAIOSFODNN7EXAMPLE",
    ):
        assert secret not in redact(f"prompt containing {secret} inline")
