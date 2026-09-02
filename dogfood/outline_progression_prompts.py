"""One idea, supplied five ways, to test whether authorship buys control.

The same argument runs through every level: AI collapses implementation cost,
so code stops being a moat and the defensible ground moves to data,
distribution and trust. Holding the idea fixed is what makes the levels
comparable -- any difference in how much the model invented is attributable to
how much the author supplied, not to the topic changing underneath.

Level E is deliberately a real draft rather than a long outline. A
near-complete draft is the case where the correct behaviour is to do almost
nothing, and it is the case a system eager to help gets wrong.
"""

from __future__ import annotations

_TOPIC = "AI, implementation cost, and where the moat actually is"

_VERBATIM_OPENER = (
    "If every company has access to the same models, using AI isn't really a moat."
)

LEVELS = [
    {
        "id": "A_sparse",
        "expected_freedom": "HIGH",
        "outline": {
            "schema": "outline/v1",
            "topic": _TOPIC,
            "mode": "linkedin",
            "target_words": 220,
            "nodes": [
                {"kind": "idea", "text": "AI reduces implementation cost."},
                {"kind": "idea", "text": "The same AI is available to competitors."},
                {"kind": "idea", "text": "Code becomes less of a moat."},
            ],
        },
    },
    {
        "id": "B_minimal",
        "expected_freedom": "MEDIUM",
        "outline": {
            "schema": "outline/v1",
            "topic": _TOPIC,
            "mode": "linkedin",
            "target_words": 220,
            "nodes": [
                {"kind": "idea", "text": "AI lowers implementation cost."},
                {"kind": "required_point", "text": "everyone gets access to similar models"},
                {"kind": "required_point", "text": "feature replication gets easier"},
                {"kind": "required_point", "text": "the durable moat shifts elsewhere"},
                {"kind": "ending", "text": "close on data, distribution and trust"},
            ],
        },
    },
    {
        "id": "C_structured",
        "expected_freedom": "MEDIUM",
        "outline": {
            "schema": "outline/v1",
            "topic": _TOPIC,
            "mode": "linkedin",
            "target_words": 220,
            "enforce_order": True,
            "nodes": [
                {
                    "kind": "thesis",
                    "text": (
                        "If AI makes developers replaceable, it probably makes SaaS "
                        "more replaceable too."
                    ),
                },
                {"kind": "claim", "text": "Implementation used to require significant effort."},
                {"kind": "claim", "text": "That effort created friction."},
                {"kind": "claim", "text": "AI reduces the friction."},
                {"kind": "required_point", "text": "competitors gain the same capability"},
                {"kind": "required_point", "text": "code becomes less defensible"},
                {
                    "kind": "ending",
                    "text": "Stop on proprietary data, distribution and integration.",
                },
            ],
        },
    },
    {
        "id": "D_authorship_rich",
        "expected_freedom": "LOW",
        "outline": {
            "schema": "outline/v1",
            "topic": _TOPIC,
            "mode": "linkedin",
            "target_words": 220,
            "enforce_order": True,
            "nodes": [
                {"kind": "preserve", "text": _VERBATIM_OPENER},
                {
                    "kind": "claim",
                    "text": "Implementation cost historically creates competitive friction.",
                },
                {"kind": "expand", "text": "Explain how AI changes that friction."},
                {
                    "kind": "example",
                    "text": (
                        "A workflow that previously required six months of engineering "
                        "now takes a fraction of that."
                    ),
                },
                {"kind": "transition", "text": "Move to proprietary data and distribution."},
                {
                    "kind": "required_point",
                    "text": "proprietary data, distribution and integration remain defensible",
                },
                {"kind": "ending", "text": "No motivational ending."},
                {
                    "kind": "voice_seed",
                    "text": (
                        "I keep seeing this framed as an advantage when it is really "
                        "just a new baseline."
                    ),
                },
            ],
        },
    },
    {
        "id": "E_near_complete",
        "expected_freedom": "MINIMAL",
        "outline": {
            "schema": "outline/v1",
            "topic": _TOPIC,
            "mode": "linkedin",
            "target_words": 130,
            "nodes": [
                {
                    "kind": "preserve",
                    "text": (
                        f"{_VERBATIM_OPENER} Implementation cost is what used to protect "
                        "incumbents. Building the thing took months, and those months were "
                        "the barrier, not the idea.\n\n"
                        "That barrier is coming down for everyone at the same time. If a "
                        "competitor can now replicate a feature in a week, the feature was "
                        "never the advantage. The advantage was the cost of copying it.\n\n"
                        "What survives is less exciting and harder to acquire: proprietary "
                        "data nobody else has, distribution you already own, and the trust "
                        "that took years to earn. None of those get cheaper because the "
                        "model got better.\n\n"
                        "The moat moved. It did not disappear."
                    ),
                },
                {"kind": "style_note", "text": "Minimum necessary editing only."},
            ],
        },
    },
]
