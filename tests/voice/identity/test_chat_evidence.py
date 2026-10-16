"""ChatGPT export ingestion: user text only, supporting evidence only."""

from __future__ import annotations

import json

import pytest

from howlwriter.voice.identity import chat
from howlwriter.voice.application import render_profile
from howlwriter.domain.voice import VoiceProfile


def _message(
    role: str, text: str, t: float, content_type: str = "text", hidden: bool = False
) -> dict:
    return {
        "message": {
            "author": {"role": role},
            "content": {"content_type": content_type, "parts": [text]},
            "create_time": t,
            "metadata": {"is_visually_hidden_from_conversation": hidden},
        }
    }


def _conversation(messages: list[dict]) -> dict:
    return {"title": "synthetic", "mapping": {str(i): m for i, m in enumerate(messages)}}


ASSISTANT_REPLY = (
    "Here is a detailed explanation of the configuration steps you should follow when setting up "
    "the monitoring pipeline across every environment in your organisation today"
)


def _export() -> list[dict]:
    conversations = []
    for i in range(30):
        conversations.append(
            _conversation(
                [
                    _message("system", "You are a helpful assistant.", 1),
                    _message(
                        "user",
                        f"how do I check port {8000 + i} on the vm? need exact command for /etc/hosts too",
                        2,
                    ),
                    _message("assistant", ASSISTANT_REPLY, 3),
                    _message("user", "also make sure it works without sudo", 4),
                    _message("tool", "tool output", 5),
                    _message(
                        "user", "custom instructions", 6, content_type="user_editable_context"
                    ),
                ]
            )
        )
    conversations.append(
        _conversation(
            [
                _message(
                    "user",
                    "# ROLE\n\nYou are a senior engineer.\n\n## TASK\n\n"
                    + "word " * 400
                    + "\n\n## OUTPUT\n\nx",
                    1,
                ),
                _message("assistant", ASSISTANT_REPLY, 1.5),
                _message("user", "Copying this back: " + ASSISTANT_REPLY, 2),
                _message(
                    "user",
                    "```python\nprint('x')\n```\n> quoted line from a paper\n"
                    "[ERROR] trace here\nok what about the logs?",
                    3,
                ),
            ]
        )
    )
    return conversations


def test_only_user_prose_is_kept():
    messages, excluded = chat.extract_user_messages(_export())
    texts = [m["text"] for m in messages]
    assert all("helpful assistant" not in t and "tool output" not in t for t in texts)
    assert all("custom instructions" not in t for t in texts)
    assert (
        excluded["role_assistant"] == 31
        and excluded["role_system"] == 30
        and excluded["role_tool"] == 30
    )
    assert excluded["likely_pasted_prompt"] == 1
    assert excluded["pasted_assistant_text"] == 1
    assert "ok what about the logs?" in texts
    assert all("print(" not in t and "quoted line" not in t and "[ERROR]" not in t for t in texts)


def test_repeated_requests_are_deduplicated():
    messages, excluded = chat.extract_user_messages(_export())
    assert excluded["duplicate"] >= 29  # "also make sure it works without sudo" x30
    assert sum(1 for m in messages if m["text"] == "also make sure it works without sudo") == 1


def test_import_stores_statistics_not_text(tmp_path):
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(_export()), encoding="utf-8")
    evidence = chat.import_export(path)
    blob = json.dumps(evidence)
    assert "without sudo" not in blob and "/etc/hosts" not in blob
    assert evidence["affects_scores"] is False and evidence["affects_confidence"] is False
    assert evidence["statistics"]["messages"] > 0


def test_tendencies_need_enough_messages():
    assert chat.tendencies_from({"messages": 5}) == []


def test_missing_export_is_an_error_not_a_fabrication(tmp_path):
    with pytest.raises(FileNotFoundError):
        chat.import_export(tmp_path / "nothing.json")


def test_provisional_evidence_is_labelled():
    evidence = chat.provisional_evidence()
    assert evidence["status"] == "provisional_unvalidated"
    assert evidence["source"] == "user_supplied_observations"


def test_academic_profiles_get_only_formal_safe_tendencies():
    evidence = chat.provisional_evidence()
    academic = chat.supporting_evidence_for(evidence, "academic")
    professional = chat.supporting_evidence_for(evidence, "professional")
    assert len(academic["tendencies"]) < len(professional["tendencies"])
    assert not any("follow-ups" in t or "concise" in t for t in academic["tendencies"])


def test_supporting_evidence_renders_below_mode_rules():
    profile = VoiceProfile(
        author_name="", generated_from="corpus_build", version=2, profile_name="x"
    )
    profile.supporting_evidence = chat.supporting_evidence_for(
        chat.provisional_evidence(), "professional"
    )
    rendered = render_profile(profile, "professional")
    assert "SUPPORTING EVIDENCE" in rendered
    assert "never override the mode's rules" in rendered
