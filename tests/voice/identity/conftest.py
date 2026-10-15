"""Fixtures for the Personal Voice Intelligence tests.

Everything is synthetic. The two "authors" below are seeded generators with
deliberately different habits, written for these tests and derived from no
one's real writing. Author A writes long, hedged, semicolon-heavy lab prose in
the first person; author B writes short imperative onboarding copy.
"""

from __future__ import annotations

from pathlib import Path
import random

import pytest

_A_SUBJECTS = [
    "the capture",
    "this control",
    "the alert rule",
    "the sensor feed",
    "the audit trail",
    "the packet sample",
    "the host baseline",
    "the firewall policy",
    "the log pipeline",
    "the timeline",
    "the segment map",
    "the dashboard query",
    "the signature set",
]
_A_VERBS = [
    "suggests",
    "indicates",
    "may show",
    "appears to confirm",
    "could reflect",
    "likely points to",
]
_A_OBJECTS = [
    "a gap in monitoring coverage",
    "that the rule fired late",
    "configuration drift on two hosts",
    "weak segmentation between subnets",
    "an unpatched service on the edge",
    "a noisy baseline",
    "retransmissions during the transfer",
    "an expired certificate",
    "a missing index pattern",
    "duplicate events in the queue",
    "a mismatch between the two clocks",
]
_A_TAILS = [
    "; however, the sample is small",
    ", although the evidence is limited",
    ", which is consistent with the earlier capture",
    "; this deserves a closer look",
    ", so I repeated the test",
    " (Rivera, 2021)",
    " (Okafor et al., 2019)",
    "",
    "",
]

_B_LINES = [
    "Click the blue button.",
    "Open the console now.",
    "Save your work often!",
    "You will see a green light.",
    "Check the box first.",
    "Your manager approves it.",
    "Read the policy today.",
    "Ask questions anytime.",
    "Log in with your badge.",
    "Close every window.",
    "Print the summary.",
    "Wait for the beep.",
]


def author_a(seed: int, paragraphs: int | None = None, byline: bool = True) -> str:
    rng = random.Random(seed)
    out = []
    for _ in range(paragraphs or rng.randint(6, 9)):
        sentences = []
        for _ in range(rng.randint(3, 6)):
            subject = rng.choice(_A_SUBJECTS).capitalize()
            sentence = (
                f"{subject} {rng.choice(_A_VERBS)} {rng.choice(_A_OBJECTS)}{rng.choice(_A_TAILS)}."
            )
            if rng.random() < 0.3:
                sentence = "In my review, " + sentence[0].lower() + sentence[1:]
            sentences.append(sentence)
        out.append(" ".join(sentences))
    head = "William Elias\n\nLab Report\n\n" if byline else ""
    return head + "\n\n".join(out)


def author_b(seed: int, paragraphs: int | None = None) -> str:
    rng = random.Random(seed)
    out = [
        " ".join(rng.choice(_B_LINES) for _ in range(rng.randint(6, 10)))
        for _ in range(paragraphs or rng.randint(8, 11))
    ]
    return "Name: Jordan Smith\n\nOnboarding Guide\n\n" + "\n\n".join(out)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Private stores redirected into the test's temporary directory."""
    ids = tmp_path / "identities"
    voices = tmp_path / "voices"
    monkeypatch.setenv("HOWLWRITER_IDENTITIES_DIR", str(ids))
    monkeypatch.setenv("HOWLWRITER_VOICES_DIR", str(voices))
    monkeypatch.setenv("HOWLWRITER_PREFERENCES_FILE", str(tmp_path / "preferences.yaml"))
    return {"identities": ids, "voices": voices, "tmp": tmp_path}


@pytest.fixture
def drive(tmp_path) -> Path:
    """A synthetic drive: author A's labs, author B's shared guides, and noise."""
    root = tmp_path / "drive"
    (root / "school").mkdir(parents=True)
    (root / "Shared with Me").mkdir(parents=True)
    for index in range(16):
        (root / "school" / f"lab{index:02d}.md").write_text(author_a(index), encoding="utf-8")
    for index in range(8):
        (root / "Shared with Me" / f"guide{index}.md").write_text(
            author_b(100 + index), encoding="utf-8"
        )
    return root


def attest_all(identity: str, prefix: str, authorship: str = "h", **kwargs) -> int:
    from howlwriter.voice.identity import review
    from howlwriter.voice.identity.store import IdentityStore

    store = IdentityStore(identity)
    count = 0
    for doc_id, entry in store.load_inventory()["entries"].items():
        if (
            entry["relative_path"].startswith(prefix)
            and entry.get("status") == "extracted"
            and entry.get("duplicate_role") != "duplicate"
        ):
            review.attest(store, doc_id, authorship, **kwargs)
            count += 1
    return count
