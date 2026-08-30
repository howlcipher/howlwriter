# HowlWriter

A writing, editing, humanization, research, citation, provenance, and
verification system built to work with [HowlPlane](https://github.com/howlcipher/howlplane).

## What this is

HowlWriter applies HowlPlane's control-plane philosophy to writing instead
of software engineering:

```
PROPOSE -> CHALLENGE -> EVALUATE -> VERIFY -> REVISE -> AUTHORIZE -> OUTPUT
```

Given a draft, HowlWriter can lint it against configurable style rules,
detect (and, only when explicitly configured, safely rewrite) common
LLM-writing habits, critique it without rewriting it, extract candidate
factual claims, track which sources support which claims, format APA 7
citations, learn an author's voice from a corpus of their own writing, and
check whether a rewrite preserved the original's meaning.

It is **not** another prompt-in-prose-out wrapper. AI models are meant to
be components inside a controlled process where drafts can be proposed,
criticized, researched, fact-checked, rewritten, and verified before being
called finished -- and this version already has a real, working
deterministic core that everything model-backed will plug into. See
[docs/vision.md](docs/vision.md) for the full ambition.

## Why it exists

Humanization here does **not** mean beating AI detectors -- they're
unreliable and are never treated as a measurement in this codebase (see
[docs/humanization.md](docs/humanization.md)). It means producing writing
that reads as authentically human and, when a voice profile exists, as
that specific author. Fact-checking and provenance are first-class, not an
afterthought: HowlWriter never invents a statistic, quotation, author,
date, or citation to fill a gap it can't verify (see
[docs/provenance.md](docs/provenance.md) and
[docs/citations.md](docs/citations.md)).

## Relationship to HowlPlane

HowlWriter defines writing-domain capability contracts and a real
deterministic core. HowlPlane -- or any other runtime a caller wires in --
supplies model execution, provider routing, retries, and orchestration.
HowlWriter never calls a model API itself: every capability that needs one
is a typed `Protocol` with an unconfigured default that fails loudly and
specifically (`ModelRoleNotConfiguredError`) instead of faking a result.
This repository is fully usable standalone for its deterministic
subsystems (linting, citations, provenance, voice statistics, meaning
preservation, red pen) and degrades honestly, never silently, for
model-backed ones. See [docs/architecture.md](docs/architecture.md) and
[docs/howlplane-integration.md](docs/howlplane-integration.md) for the
full boundary, including two integration gaps on HowlPlane's side that
this project surfaced but does not attempt to patch itself.

This repository is adopted by HowlPlane through the committed
[`.ai-project.toml`](.ai-project.toml) manifest, validated against
HowlPlane's own `ai project validate`.

## Architecture

```
src/howlwriter/
├── domain/       Document, Claim, Source/Evidence, ProvenanceGraph,
│                 VoiceProfile, WritingReport
├── config/       Layered config: defaults -> mode -> user -> project -> request
├── linting/      Deterministic, configurable style-rule engine
├── humanize/     Humanization detection + the one opt-in safe rewrite
├── editing/      Whitespace/heading normalization (real) + model-backed editing (stub)
├── redpen/       Criticism, not rewriting
├── facts/        Heuristic claim extraction + the verification stub
├── research/     The research stub
├── citations/    APA 7 formatter (MLA/Chicago/IEEE/Harvard reserved)
├── voice/        Deterministic corpus-stats voice learner
├── review/       Meaning-preservation review
├── integration/  The shared model-backed-role seam
├── pipeline/     The `howl` end-to-end pipeline
└── cli/          argparse CLI, one subcommand per capability
```

See [docs/architecture.md](docs/architecture.md) for the full walkthrough.

## MVP status

**Real, deterministic, and tested today:**

- The domain model, including a genuinely queryable `ProvenanceGraph`
- Layered configuration
- The style-lint engine, ten built-in rule families
- Humanization detection (reuses the lint engine) and the opt-in safe
  banned-word rewrite
- Whitespace/heading normalization (`PassthroughEditor`)
- Red Pen (deterministic critique, never auto-rewrites)
- Heuristic claim extraction (every claim starts `UNVERIFIABLE`, honestly)
- The APA 7 citation formatter, including missing-metadata warnings
- The voice corpus-stats learner
- Meaning-preservation review (number/attribution/hedge diffing)
- The full `howl` pipeline and every CLI subcommand

**Explicit typed interfaces, unconfigured by default (never faked):**

- Model-backed rewriting (`HumanizerRewriter`), prose-level editing
  (`Editor`'s model mode), claim verification (`ClaimVerifier`), research
  (`Researcher`), qualitative voice analysis (`VoiceAnalyzer`), and
  semantic meaning comparison (`ModelMeaningReviewer`)
- Drafting from nothing (`WRITER`) has no deterministic path at all

**Deferred entirely, named rather than half-built:** MLA/Chicago/IEEE/
Harvard citation styles, PDF/DOCX/HTML ingestion, a real "voice match %"
metric, citation *validation*, multi-file/directory-wide operations. See
[ROADMAP.md](ROADMAP.md).

## Using it

```bash
pip install -e ".[dev]"

# Deterministic style lint
howlwriter lint draft.md

# Humanization findings (and, only with --apply, the one safe rewrite)
howlwriter humanize draft.md [--apply]

# Criticism, not rewriting
howlwriter red-pen draft.md          # or: howlwriter critique draft.md

# Real, deterministic claim extraction (every claim starts UNVERIFIABLE)
howlwriter fact-check draft.md

# APA 7 citations from collected source metadata
howlwriter cite apa7 sources.json --form page
howlwriter references apa7 sources.json

# Was this source actually retrieved?
howlwriter sources sources.json

# Learn a voice profile from an author's own writing
howlwriter voice learn post1.txt post2.txt --author "Jane Doe"

# Compare meaning between two files (e.g. before/after a rewrite)
howlwriter finalize original.md revised.md

# The full pipeline: INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> FINAL REVIEW -> OUTPUT
howlwriter howl draft.md
```

`howlwriter writer <prompt>` and `howlwriter research <query>` are
model-backed with no implementation configured yet; both exit with a clear
`ModelRoleNotConfiguredError` message rather than doing nothing silently.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/
.venv/bin/flake8 src/
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the MVP scope checklist and the growth
path toward the full pipeline described in [docs/vision.md](docs/vision.md).
