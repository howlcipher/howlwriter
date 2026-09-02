# Outline-Guided Authorship

## The problem

`howlwriter howl <file>` transforms prose that already exists. That is the
right shape for a draft, and the wrong shape for the thing people actually want
help with: turning ideas, claims, a structure and a few sentences they care
about into a finished piece, without the system quietly taking over.

The product claim is that **supplying more authorship buys more control**. An
outline is how you supply it.

## Five levels, one schema

The same idea can be handed over five ways. Generation freedom is *derived*
from what you supplied, not declared, so the claim is checkable:

| You supply | Freedom | What the model does |
|---|---|---|
| A few ideas | `HIGH` | Writes almost all of it |
| Points and an ending | `MEDIUM` | Writes the prose; your structure holds |
| Thesis, claims, order | `MEDIUM` | Writes prose inside your argument |
| Verbatim passages, examples | `LOW` | Joins and develops your material |
| A finished draft | `MINIMAL` | Minimum necessary editing |

Check yours before spending a run:

    howlwriter outline validate post.yaml
    howlwriter outline show post.yaml

## Node kinds are not interchangeable

    nodes:
      - kind: preserve        # reproduced character for character
        text: "If every company has access to the same models, using AI isn't really a moat."
      - kind: claim           # your assertion; may be rephrased, never contradicted
        text: Implementation cost historically creates competitive friction.
      - kind: expand          # an instruction, not prose
        text: Explain how AI changes that friction.
      - kind: example         # yours; never embellished
        text: A workflow that previously required six months of engineering.
      - kind: required_point  # must appear in the output
        text: proprietary data and distribution remain defensible
      - kind: ending
        text: No motivational ending.
      - kind: voice_seed      # register evidence for THIS piece
        text: I keep seeing this framed as an advantage when it is just a new baseline.

Collapsing these into one "content" type is how a rough note becomes an
authoritative-sounding claim. `preserve` may not be rewritten. `claim` may be
rephrased but not contradicted. `idea` invites expansion. A `voice_seed` shapes
register and is deliberately *not* required to appear.

Full kind list: `topic, thesis, claim, idea, preserve, expand, example,
experience, required_point, optional_point, transition, heading, source,
research, ending, style_note, voice_seed`.

## Authority order

When two inputs disagree, the higher one wins, and a lower one never silently
rewrites a higher one:

1. Evidence and grounded fact
2. Assignment constraints (length, prohibitions, required sections)
3. Your verbatim sentences
4. Your claims
5. Your conclusions
6. Your structure and ordering
7. Your examples and experiences
8. Voice seeds from this outline
9. The writing mode's rules
10. The context-specific voice profile
11. The global voice profile
12. The model's connective prose
13. The model's general stylistic preferences

The practical consequence: a voice profile built mostly from academic writing
does not get to strip the first person out of your personal anecdote, and
structural variance does not get to reorder an argument you fixed.

## What is checked, and how

Nothing asks the model whether it complied. It will say yes.

- **Verbatim retention** is exact. A passage either appears character for
  character or it does not. A smoothed sentence is reported as `ALTERED` with
  the closest text found, because "almost verbatim" is the failure that looks
  like success.
- **Required points** use a documented lexical-overlap threshold, biased toward
  reporting `MISSING` when uncertain. A false alarm costs a glance; a false
  clear costs the guarantee.
- **Ordering** is checked when `enforce_order` is true.

    howlwriter howl --outline post.yaml --provenance

prints the coverage verdict and writes a local provenance record.

## What the model may not invent

Personal voice is not licence to invent a life. The writer is instructed, and
the prompt is recorded so you can verify it was, that it may not invent jobs,
employers, coworkers, clients, outages, incidents, meetings, interviews,
conversations, family events, education, timelines or metrics, and may not
invent opinions and attribute them to you.

Where developing a point would need a personal specific you did not supply, the
writer reports a gap instead of filling it. Those gaps appear in the manifest.
A convincing fabricated anecdote is the worst possible output: indistinguishable
from the real thing, and not something you can stand behind.

## Academic outlines

An outline is translated into the `AssignmentSpec` the academic pipeline
already takes, so source relevance and sufficiency, evidence depth, identifier
grounding, claim verification, APA formatting, requirement classification, the
soft target against the hard ceiling, redundancy, consistency and quotation
validation all still run:

    howlwriter paper --outline paper.yaml --provenance

Claims carry the sources and research requests you assigned:

    nodes:
      - kind: claim
        id: claim_1
        text: Valid credentials complicate detection.
        sources: [source_04]
    research:
      - question: Find evidence about detection difficulty with valid credentials.
        required: true
        supports_claims: [claim_2]

Assignment constraints outrank the outline: an outline may tighten a hard
ceiling the assignment set, never raise it.
