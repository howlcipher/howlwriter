#!/usr/bin/env python3
"""Mixed-context dogfood set for Contextual Structural Variance.

The structural-variance benchmark is twenty polished technical mini-essays,
which is a narrow slice of what anyone actually writes. A voice model can look
healthy on that slice purely because every prompt invites the same shape.

This set deliberately varies register and natural length -- personal
observation, career reflection, short opinion, longer analytical opinion,
casual comment, technical explanation, a contrarian view -- and includes
prompts written in the first person, to test whether personal framing survives
the voice layer rather than being flattened into impersonal exposition.

These are evaluation inputs only. Nothing here is a fixture, and nothing about
any particular author is encoded in product behaviour or tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.humanize.rewriter import ModelHumanizerRewriter
from howlwriter.voice.corpus.store import VoiceStore

DOGFOOD_DIR = Path(__file__).resolve().parent
RESULTS_DIR = DOGFOOD_DIR / "mixed_context_experiment_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PROMPTS = [
    {
        "id": "mixed_01",
        "register": "personal observation (first person)",
        "expect": "first-person framing preserved",
        "sparse_text": (
            "I like working across development, QA, databases, networking, and operations. "
            "Narrow engineering roles sometimes feel strange because a lot of my value comes "
            "from understanding how all the pieces connect. Make this a LinkedIn post."
        ),
    },
    {
        "id": "mixed_02",
        "register": "personal observation (first person)",
        "expect": "first-person framing preserved",
        "sparse_text": (
            "I've noticed I learn tools faster when I can actually press all the buttons and "
            "break things instead of reading documentation for three days. Turn this into a "
            "short LinkedIn post."
        ),
    },
    {
        "id": "mixed_03",
        "register": "career reflection (first person)",
        "expect": "first-person framing preserved",
        "sparse_text": (
            "Going back to school while working full time has made me much more selective "
            "about what technology I spend time learning. Make this into a reflective "
            "LinkedIn post."
        ),
    },
    {
        "id": "mixed_04",
        "register": "short opinion",
        "expect": "naturally 60-90 words",
        "sparse_text": (
            "Standups should be shorter than the time people spend preparing for them. "
            "Make this a very short LinkedIn post."
        ),
    },
    {
        "id": "mixed_05",
        "register": "longer analytical opinion",
        "expect": "naturally 150-250 words",
        "sparse_text": (
            "Hiring for 'culture fit' quietly became a way to hire people who interview "
            "comfortably, which is not the same as people who do the work well. Walk through "
            "why the two get confused, what it costs teams over several years, and what to "
            "measure instead. Make this a longer, analytical LinkedIn post."
        ),
    },
    {
        "id": "mixed_06",
        "register": "casual professional comment",
        "expect": "conversational register",
        "sparse_text": (
            "Everyone says documentation matters and then nobody budgets a single hour for "
            "it. Make this a casual, offhand LinkedIn comment."
        ),
    },
    {
        "id": "mixed_07",
        "register": "technical explanation",
        "expect": "explanatory, not persuasive",
        "sparse_text": (
            "Explain what a write-ahead log actually does and why databases use one, for an "
            "engineer who has never implemented storage. Make this a LinkedIn post."
        ),
    },
    {
        "id": "mixed_08",
        "register": "disagreement / contrarian",
        "expect": "argues against a consensus",
        "sparse_text": (
            "Unpopular view: most teams do not need Kubernetes, and adopting it early costs "
            "them more velocity than it ever returns. Make this a LinkedIn post."
        ),
    },
    {
        "id": "mixed_09",
        "register": "personal observation (first person)",
        "expect": "first-person framing preserved",
        "sparse_text": (
            "The best code review I ever got was three sentences long and completely changed "
            "how I think about error handling. Make this a short LinkedIn post."
        ),
    },
    {
        "id": "mixed_10",
        "register": "short opinion",
        "expect": "naturally 60-90 words",
        "sparse_text": (
            "If your test suite takes forty minutes, you do not have a test suite, you have a "
            "nightly job. Make this a sharp, short post."
        ),
    },
]


def generate(prompt_text: str, voice_profile_path: str | None) -> str:
    cfg = default_config()
    cfg.voice_profile = voice_profile_path
    doc = Document.parse(prompt_text, title="sparse_prompt", mode=WritingMode.LINKEDIN)
    return ModelHumanizerRewriter().rewrite(doc, cfg).document.text.strip()


def main() -> None:
    store = VoiceStore("william")
    if not store.exists():
        raise RuntimeError("Local voice 'william' not found. Build it first.")
    profile_path = str(store.directory / "profile.json")

    os.environ["HOWLPLANE_ROLE_WRITING_HUMANIZER"] = "agy"
    os.environ["HOWLPLANE_ROLE_WRITING_FINAL_REVIEWER"] = "codex"

    medium: list[dict[str, Any]] = []
    full: list[dict[str, Any]] = []
    t0 = time.time()

    for index, item in enumerate(PROMPTS, 1):
        print(f"[{index:02d}/{len(PROMPTS):02d}] {item['id']}: {item['register']}...")
        for label, bucket, path in (
            ("medium_only", medium, None),
            ("full_howlwriter", full, profile_path),
        ):
            started = time.time()
            try:
                output = generate(item["sparse_text"], path)
            except Exception as error:  # noqa: BLE001 - recorded, not swallowed
                print(f"  [ERROR] {label} failed: {error}")
                output = ""
            bucket.append({
                "id": item["id"],
                "register": item["register"],
                "expect": item["expect"],
                "prompt": item["sparse_text"],
                "output": output,
                "duration": round(time.time() - started, 2),
            })

    payload = {
        "experiment": "Mixed-context structural variance dogfood",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_prompts": len(PROMPTS),
        "total_duration_seconds": round(time.time() - t0, 2),
        "generations": {"medium_only": medium, "full_howlwriter": full},
    }
    report = RESULTS_DIR / "mixed_context_dogfood_report.json"
    report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved to {report}")


if __name__ == "__main__":
    main()
