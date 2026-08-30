# Humanization

## What this is not

AI-detector evasion is **not** the objective. AI detectors are unreliable
and are not treated as an objective measurement anywhere in this codebase.
There is no code in this project that tries to beat, fool, or score against
a detector, and none should be added.

## What this is

Humanization means making writing more closely resemble authentic human
writing and, when a Voice Profile exists (see
[docs/voice.md](voice.md)), the writing of that particular author.
Authentic writing often contains fragments, uneven sentence lengths,
unusual transitions, slight repetition, and personal expressions.
HowlWriter does not remove these simply because a model would normally
smooth them away.

## The pattern families

`humanize/detector.py` detects the humanization-relevant subset of
`linting/engine.py`'s findings (see [docs/architecture.md](architecture.md)
for why the two aren't a separate pattern list):

| Rule code | What it flags |
| --- | --- |
| `AI_STYLE_BANNED_WORD` | A configured banned word (`delve`, `tapestry`, `crucial` by default) |
| `AI_STYLE_NOT_X_BUT_Y` | "It's not X, it's Y" / "It's not just X, it's Y" contrast constructions |
| `AI_STYLE_EMPTY_TRANSITION` | "At its core," "In today's rapidly evolving...," "Whether you're X or Y..." |
| `AI_STYLE_CANNED_CONCLUSION` | "This highlights the importance of...," "The reality is..." |
| `AI_STYLE_REPETITIVE_TRICOLON` | Three or more parallel three-item lists in one document |
| `AI_STYLE_EXCESSIVE_EM_DASH` | Four or more em dashes in one document |
| `AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE` | Three or more paragraphs opening with the same word |
| `AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS` | Question sentences making up a quarter or more of the document |

Excessive headings and excessive bold are detected too
(`AI_STYLE_EXCESSIVE_HEADINGS`, `AI_STYLE_EXCESSIVE_BOLD`), but
`humanize/detector.py` leaves them out of its subset -- they read as
formatting/structure concerns rather than "this sentence sounds like an
AI wrote it." They still surface through `howlwriter lint`.

Every rule is config-gated: absent from `config.banned_words` /
`config.banned_patterns`, a rule finds nothing. Nothing here is hard-coded
as universally wrong -- see [docs/architecture.md](architecture.md) for how
the gating works.

## Findings over rewrites

The default behavior for every pattern above is **findings-only**. The one
exception is `humanize/rewriter.py`'s `SafeRewriter`: a literal
substitution of a banned word for its configured replacement --
`banned_words: [{word: delve, replacement: "look into"}]` -- and only when
`config.apply_safe_rewrites` is explicitly set. No pattern-based rewriting
(rewriting a "not X but Y" sentence, restructuring a paragraph, cutting a
rhetorical question) happens automatically anywhere in this codebase.

Prose-level rewriting that genuinely "makes this sound less AI" needs
judgment a regex can't provide. That's `humanize/rewriter.py`'s
`HumanizerRewriter` Protocol -- model-backed, unconfigured by default
(`NotConfiguredHumanizer`), and not invoked by the `howl` pipeline unless a
caller wires an implementation in.
