"""Informal communication evidence from a ChatGPT data export.

The person's chat messages show how they communicate when nobody is grading
them: how directly they ask, how they add constraints, how much filler they
tolerate. That is useful supporting evidence about cross-context tendencies.
It is not academic or professional writing, and it is handled so it cannot
pass for either:

* Only user-authored message text is read. Assistant, system, developer,
  and tool messages are skipped by role; hidden context (custom instructions)
  by content type.
* Inside a user message, code blocks, log-like lines, and quoted lines are
  removed, and a message that repeats a long run of an assistant reply is
  treated as pasted AI text and excluded. A long, heading-structured message
  that reads like a system prompt is excluded as a likely pasted prompt.
* Repeated and minimally changed requests are deduplicated.
* What is stored is aggregate statistics and a short list of tendencies.
  No message text, no conversation titles.
* The evidence never contributes to a numeric baseline and never raises a
  profile's confidence. It is attached to profiles as a separately
  attributed, low-weight note, and the academic profile receives only the
  tendencies that are safe for formal writing.

When no export exists, nothing is fabricated. The observations the person
supplied are recorded as provisional and unvalidated, and labelled so.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import statistics
from typing import Any, Iterable

from howlwriter.voice.corpus.dedup import hamming, normalize, shingles, simhash

EVIDENCE_VERSION = "chat-evidence/v1"
MIN_MESSAGES_FOR_TENDENCIES = 40
PASTED_AI_RUN = 12
PASTED_PROMPT_WORDS = 350

#: The person's own provisional observations of their informal style, used
#: only when no export is available and always labelled unvalidated.
PROVISIONAL_OBSERVATIONS = (
    "direct and concise; usually opens with the substantive question",
    "short iterative follow-ups that add constraints or clarifications",
    "prefers concrete technical detail: exact paths, tools, versions, outputs",
    "challenges assumptions and asks for comparisons",
    "low tolerance for generic, polished, corporate-sounding language",
    "expresses preferences and qualifications explicitly",
    "natural variation in sentence length and organization",
)

#: Tendencies safe for formal writing. Everything else is professional-only.
_ACADEMIC_SAFE = ("concrete technical detail", "generic, polished", "qualifications explicitly")

_FENCE = re.compile(r"```.*?(?:```|$)", re.DOTALL)
_LOGLIKE = re.compile(
    r"^\s*(?:\$ |# |>>> |PS [A-Z]:\\|C:\\|at [\w.$]+\(|File \".+\", line \d+|Traceback|"
    r"\[\s*(?:INFO|WARN|WARNING|ERROR|DEBUG)\s*\]|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}|"
    r"(?:ERROR|WARNING|INFO|DEBUG)[: ]|\{|\}|</?\w+[^>]*>$|[\w.-]+=\S+$)",
)
_QUOTED_LINE = re.compile(r"^\s*>")
_HEADING = re.compile(r"^\s*#{1,6}\s+\S", re.MULTILINE)
_SYSTEM_PROMPT = re.compile(r"^\s*(?:you are (?:a|an)\b|act as\b|#+\s*role\b|role:)", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_DIRECT_OPENING = re.compile(
    r"^\s*(?:can you|could you|how|what|why|which|where|when|is|are|does|do|should|"
    r"make|write|build|fix|give|show|add|create|explain|compare|check|run|use|list|"
    r"update|implement|find|help)\b",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening)|greetings)\b", re.IGNORECASE
)
_CONSTRAINT = re.compile(
    r"\b(?:also|make sure|don't|do not|only|must|without|instead|but|except|keep|avoid)\b",
    re.IGNORECASE,
)
_TECHNICAL = re.compile(
    r"(?:[\w.-]*/[\w./-]+|\b[A-Z]{2,}[A-Za-z0-9]*\b|\b\w+\.\w{1,4}\b|\bv?\d+\.\d+(?:\.\d+)?\b|`[^`]+`)"
)
_FILLER = re.compile(
    r"\b(?:leverage|synergy|cutting-edge|game[- ]changer|robust solution|seamless(?:ly)?|"
    r"best-in-class|world-class|unlock|empower|holistic)\b",
    re.IGNORECASE,
)


def _shares_run(candidate: str, source_grams: set[tuple[str, ...]], length: int) -> bool:
    """True when `candidate` repeats any `length`-word run from the source.

    The corpus leakage helper caps its search at ten words by design, which is
    shorter than the run used here, so this is a direct n-gram membership test.
    """
    words = [w.lower() for w in _WORD.findall(candidate)]
    return any(tuple(words[i:i + length]) in source_grams for i in range(len(words) - length + 1))


def _grams(text: str, length: int) -> set[tuple[str, ...]]:
    words = [w.lower() for w in _WORD.findall(text)]
    return {tuple(words[i:i + length]) for i in range(len(words) - length + 1)}


def _iter_conversations(data: Any) -> Iterable[dict]:
    if isinstance(data, list):
        yield from (c for c in data if isinstance(c, dict))
    elif isinstance(data, dict) and isinstance(data.get("conversations"), list):
        yield from (c for c in data["conversations"] if isinstance(c, dict))


def _messages(conversation: dict) -> list[dict]:
    mapping = conversation.get("mapping") or {}
    messages = []
    for node in mapping.values():
        message = (node or {}).get("message") or {}
        if not message:
            continue
        author = (message.get("author") or {}).get("role", "")
        content = message.get("content") or {}
        content_type = content.get("content_type", "")
        metadata = message.get("metadata") or {}
        parts = [p for p in content.get("parts", []) or [] if isinstance(p, str)]
        messages.append(
            {
                "role": author,
                "content_type": content_type,
                "hidden": bool(metadata.get("is_visually_hidden_from_conversation")),
                "text": "\n".join(parts),
                "time": message.get("create_time") or 0,
            }
        )
    messages.sort(key=lambda m: m["time"] or 0)
    return messages


def clean_user_message(text: str) -> str:
    """Strip code, logs, and quoted lines from one user message."""
    text = _FENCE.sub(" ", text)
    kept = []
    for line in text.splitlines():
        if _QUOTED_LINE.match(line) or _LOGLIKE.match(line):
            continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def extract_user_messages(data: Any) -> tuple[list[dict], dict[str, int]]:
    """User-authored prose messages, and counts of everything excluded."""
    excluded: dict[str, int] = {}
    kept: list[dict] = []

    def skip(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    conversations = 0
    for conversation in _iter_conversations(data):
        conversations += 1
        messages = _messages(conversation)
        assistant_grams = _grams(
            " ".join(m["text"] for m in messages if m["role"] == "assistant"), PASTED_AI_RUN
        )
        position = 0
        for message in messages:
            if message["role"] != "user":
                skip(f"role_{message['role'] or 'unknown'}")
                continue
            if message["hidden"] or message["content_type"] not in ("text", "multimodal_text"):
                skip("hidden_or_context")
                continue
            raw = message["text"]
            if not raw.strip():
                skip("empty")
                continue
            words = len(_WORD.findall(raw))
            if words >= PASTED_PROMPT_WORDS and (
                len(_HEADING.findall(raw)) >= 3 or _SYSTEM_PROMPT.match(raw)
            ):
                skip("likely_pasted_prompt")
                continue
            if assistant_grams and _shares_run(raw, assistant_grams, PASTED_AI_RUN):
                skip("pasted_assistant_text")
                continue
            cleaned = clean_user_message(raw)
            if len(_WORD.findall(cleaned)) < 2:
                skip("no_prose_after_cleaning")
                continue
            kept.append({"text": cleaned, "follow_up": position > 0})
            position += 1

    # Deduplicate repeated and minimally changed requests.
    unique: list[dict] = []
    seen_exact: set[str] = set()
    hashes: list[int] = []
    for message in kept:
        key = normalize(message["text"])
        if key in seen_exact:
            skip("duplicate")
            continue
        seen_exact.add(key)
        if len(key.split()) >= 8:
            value = simhash(shingles(message["text"]))
            if any(hamming(value, other) <= 3 for other in hashes):
                skip("near_duplicate")
                continue
            hashes.append(value)
        unique.append(message)
    excluded["conversations"] = conversations
    return unique, excluded


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if _WORD.search(s)]


def summarize(messages: list[dict]) -> dict[str, Any]:
    """Descriptive statistics over user messages. Numbers only."""
    if not messages:
        return {"messages": 0}
    lengths = [len(_WORD.findall(m["text"])) for m in messages]
    sentence_lengths = [len(_WORD.findall(s)) for m in messages for s in _sentences(m["text"])]
    words = sum(lengths) or 1
    joined = "\n".join(m["text"] for m in messages)
    follow_ups = [m for m in messages if m["follow_up"]]
    mean_sentence = statistics.mean(sentence_lengths) if sentence_lengths else 0.0
    return {
        "messages": len(messages),
        "words": words,
        "median_words_per_message": statistics.median(lengths),
        "short_message_share": sum(1 for n in lengths if n < 15) / len(lengths),
        "direct_opening_share": sum(1 for m in messages if _DIRECT_OPENING.match(m["text"]))
        / len(messages),
        "greeting_opening_share": sum(1 for m in messages if _GREETING.match(m["text"]))
        / len(messages),
        "question_share": sum(1 for m in messages if "?" in m["text"]) / len(messages),
        "constraint_follow_up_share": (
            sum(1 for m in follow_ups if _CONSTRAINT.search(m["text"])) / len(follow_ups)
            if follow_ups
            else 0.0
        ),
        "technical_tokens_per_100_words": len(_TECHNICAL.findall(joined)) * 100.0 / words,
        "generic_filler_per_1000_words": len(_FILLER.findall(joined)) * 1000.0 / words,
        "sentence_length_mean": mean_sentence,
        "sentence_length_cv": (
            statistics.pstdev(sentence_lengths) / mean_sentence
            if len(sentence_lengths) > 1 and mean_sentence
            else 0.0
        ),
    }


def tendencies_from(stats: dict[str, Any]) -> list[str]:
    """Plain-language tendencies, each tied to a stated measurement.

    Thresholds are heuristic and documented as such; they describe the
    messages, not the person.
    """
    found: list[str] = []
    if stats.get("messages", 0) < MIN_MESSAGES_FOR_TENDENCIES:
        return found
    if stats["direct_opening_share"] >= 0.4 and stats["greeting_opening_share"] < 0.1:
        found.append(
            f"direct and concise; usually opens with the substantive question "
            f"({stats['direct_opening_share']:.0%} of messages open directly)"
        )
    if stats["constraint_follow_up_share"] >= 0.3:
        found.append(
            "short iterative follow-ups that add constraints or clarifications "
            f"({stats['constraint_follow_up_share']:.0%} of follow-ups add one)"
        )
    if stats["technical_tokens_per_100_words"] >= 3.0:
        found.append(
            "prefers concrete technical detail: exact paths, tools, versions, outputs "
            f"({stats['technical_tokens_per_100_words']:.1f} technical tokens per 100 words)"
        )
    if stats["generic_filler_per_1000_words"] < 0.5:
        found.append("low tolerance for generic, polished, corporate-sounding language")
    if stats["sentence_length_cv"] >= 0.6:
        found.append("natural variation in sentence length and organization")
    return found


def import_export(path: Path) -> dict[str, Any]:
    """Build the evidence record from a ChatGPT export (conversations.json)."""
    path = Path(path).expanduser()
    if path.is_dir():
        path = path / "conversations.json"
    if not path.is_file():
        raise FileNotFoundError(f"no ChatGPT export found at {path}")
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("export is larger than 512 MB; refusing to load it into memory")
    data = json.loads(path.read_text(encoding="utf-8"))
    messages, excluded = extract_user_messages(data)
    stats = summarize(messages)
    tendencies = tendencies_from(stats)
    return {
        "version": EVIDENCE_VERSION,
        "status": "measured" if tendencies else "measured_insufficient",
        "source": "chatgpt_export",
        "statistics": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in stats.items()},
        "excluded": excluded,
        "tendencies": tendencies,
        "affects_scores": False,
        "affects_confidence": False,
        "note": (
            "Derived from user-authored chat messages only. Supporting evidence about "
            "informal communication; never a writing baseline."
        ),
    }


def provisional_evidence() -> dict[str, Any]:
    """The record used when no export exists. Labelled, never measured."""
    return {
        "version": EVIDENCE_VERSION,
        "status": "provisional_unvalidated",
        "source": "user_supplied_observations",
        "statistics": {},
        "excluded": {},
        "tendencies": list(PROVISIONAL_OBSERVATIONS),
        "affects_scores": False,
        "affects_confidence": False,
        "note": (
            "No ChatGPT export was available. These are the author's own qualitative "
            "observations of their informal style, recorded as hypotheses."
        ),
    }


def supporting_evidence_for(evidence: dict[str, Any], context: str) -> dict[str, Any]:
    """The context-safe subset attached to one profile."""
    tendencies = list(evidence.get("tendencies", []))
    if context == "academic":
        tendencies = [t for t in tendencies if any(key in t for key in _ACADEMIC_SAFE)]
    return {
        "version": evidence.get("version", EVIDENCE_VERSION),
        "status": evidence.get("status", "provisional_unvalidated"),
        "source": evidence.get("source", ""),
        "context": context,
        "tendencies": tendencies,
        "affects_scores": False,
        "affects_confidence": False,
    }
