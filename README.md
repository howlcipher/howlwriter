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
citations, learn an author's voice from a corpus of their own writing,
check whether a rewrite preserved the original's meaning, and run the
whole workflow through a local web interface.

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
├── humanize/     Humanization detection + model-backed Humanizer contract
├── editing/      Whitespace/heading normalization + model-backed editing seam
├── redpen/       Criticism, not rewriting
├── facts/        Heuristic claim extraction + verification
├── research/     Crossref / arXiv scholarly retrieval
├── citations/    APA 7 formatter (MLA/Chicago/IEEE/Harvard reserved)
├── voice/        Voice corpus profiling: build a private personal voice
│                 from a corpus of your own writing (voice/corpus/), plus
│                 the original deterministic corpus-stats learner
├── review/       Meaning-preservation review
├── integration/  The shared model-backed-role seam
├── pipeline/     The `howl` end-to-end pipeline
├── academic/     Researched academic paper pipeline
├── web/          FastAPI + React local web application
└── cli/          argparse CLI, one subcommand per capability
```

See [docs/architecture.md](docs/architecture.md) for the full walkthrough.

## MVP status

**Real, deterministic, and tested today:**

- The domain model, including a genuinely queryable `ProvenanceGraph`
- Layered configuration
- The style-lint engine, built-in rule families for AI-style patterns
- Humanization detection (reuses the lint engine) and the model-backed
  Humanizer with minimal-edit / zero-change contract
- Voice profile loading and prompt injection, for both hand-authored
  profiles and corpus-derived personal voices
- Writing-mode support (LinkedIn, academic, technical, casual, ...)
- Whitespace/heading normalization (`PassthroughEditor`)
- Red Pen (deterministic critique, never auto-rewrites)
- Heuristic claim extraction (every claim starts `UNVERIFIABLE`, honestly)
- The APA 7 citation formatter, including missing-metadata warnings
- The voice corpus-stats learner
- Voice Corpus Profiling: corpus discovery, safe DOCX/ODT/RTF/HTML/TXT/MD
  extraction (PDF via the optional `corpus` extra), academic-apparatus
  cleanup, corpus-quality and context classification, deduplication and
  revision grouping, ~35 deterministic style features, a stable
  train/holdout split, holdout validation, and the private local voice
  registry under `~/.howlwriter/voices/`
- Meaning-preservation review (number/attribution/hedge diffing)
- The full `howl` pipeline and every CLI subcommand
- Local web application (FastAPI + React) with source/claim/verification UI

**Explicit typed interfaces, unconfigured by default (never faked):**

- Model-backed rewriting (`HumanizerRewriter`), prose-level editing
  (`Editor`'s model mode), claim verification (`ClaimVerifier`), research
  (`Researcher`), qualitative voice analysis (`VoiceAnalyzer`), abstract
  corpus style analysis (`voice_analyst`), and semantic meaning
  comparison (`ModelMeaningReviewer`)
- Drafting from nothing (`WRITER`) has no deterministic path at all

**Deferred entirely, named rather than half-built:** MLA/Chicago/IEEE/
Harvard citation styles, a real "voice match %" metric, citation *validation*, multi-file/directory-wide operations. See
[ROADMAP.md](ROADMAP.md).

## Installation

```bash
# Core only
pip install -e ".[dev]"

# With local web application dependencies
pip install -e ".[dev,web]"
```

## Using the CLI

```bash
# Deterministic style lint
howlwriter lint draft.md

# Humanization findings (and, only with --apply, safe banned-word substitutions)
howlwriter humanize draft.md
howlwriter humanize post.md --mode linkedin
howlwriter humanize post.md --mode linkedin --voice-profile ~/.howlwriter/voice.json
howlwriter humanize post.md --mode linkedin --voice jane

# Run the full editorial pipeline
howlwriter howl draft.md --mode linkedin

# Criticism, not rewriting
howlwriter red-pen draft.md          # or: howlwriter critique draft.md

# Real, deterministic claim extraction (every claim starts UNVERIFIABLE)
howlwriter fact-check draft.md

# APA 7 citations from collected source metadata
howlwriter cite apa7 sources.json --form page
howlwriter references apa7 sources.json

# Was this source actually retrieved?
howlwriter sources sources.json

# Learn a voice profile from an author's own writing (plain text, no model)
howlwriter voice learn post1.txt post2.txt --author "Jane Doe"

# Build a private personal voice from a real corpus of your own documents.
# Stored in ~/.howlwriter/voices/, never committed, no passages retained.
howlwriter voice build --name jane --source ~/Documents/writing --recursive
howlwriter voice inspect jane
howlwriter voice rebuild jane
howlwriter voice list

# Compare meaning between two files (e.g. before/after a rewrite)
howlwriter finalize original.md revised.md

# Academic paper / assignment writing from a typed specification
howlwriter paper assignment.yaml --out paper.md
howlwriter paper assignment.yaml --out paper.md --deterministic

# Outline-guided authorship: write from your ideas, claims, structure and
# sentences. The more you supply, the less the model is free to invent.
howlwriter outline validate post.yaml     # check it, and see the freedom level
howlwriter outline show post.yaml
howlwriter howl --outline post.yaml --provenance
howlwriter paper --outline paper.yaml --provenance-level full
```

Outline mode reports, deterministically and without asking the model, whether
your verbatim passages survived, whether every required point is represented,
and whether your ordering held. `--provenance` writes a local, gitignored record
of every model call including the exact prompt HowlWriter sent. See
[docs/outline-authorship.md](docs/outline-authorship.md) and
[docs/provenance.md](docs/provenance.md).

`howlwriter writer <prompt>` drafts prose from notes using the configured Writer role, and `howlwriter research <query>` retrieves scholarly sources. When no model providers are wired in, model-only roles exit with a clear `ModelRoleNotConfiguredError` message rather than doing nothing silently. See [docs/academic-paper.md](docs/academic-paper.md) for details on academic workflows.

## Using the local web UI

```bash
howlwriter ui
```

This starts a FastAPI backend and serves the React frontend at
`http://127.0.0.1:8765`. The UI provides:

- A writing workspace with lint, Red Pen, Humanizer, and full Howl pipeline
- Writing-mode selection (LinkedIn, academic, technical, ...)
- Humanizer diff with change reasons, lint before/after, meaning review, and
  reviewer independence
- Intentional zero-change display when the input is already natural
- Academic assignment builder with source/claim/evidence inspector
- Source relevance display (DIRECT / SUPPORTING / TANGENTIAL / IRRELEVANT)
- Evidence-origin display (FULL_TEXT / ABSTRACT / METADATA_ONLY / OTHER)
- Provider / reviewer status panel
- Run history ledger

The web UI is localhost-only by default and does not phone home.

## Source relevance and evidence depth

Research sources are classified by relevance to the assignment:

- `DIRECT` -- directly addresses the topic
- `SUPPORTING` -- supports the topic without being central
- `TANGENTIAL` -- marginally related
- `IRRELEVANT` -- not related

Only `DIRECT` and `SUPPORTING` sources count toward the minimum source
requirement. Evidence is classified by what was actually retrieved:

- `FULL_TEXT` -- full paper body was retrieved and inspected
- `ABSTRACT` -- abstract only
- `METADATA_ONLY` -- no body or abstract text
- `OTHER` -- external reference or unknown

`METADATA_ONLY` evidence must not substantiate substantive technical or
statistical claims. The UI surfaces both classifications exactly as the
backend reports them.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,web]"
.venv/bin/playwright install chromium
.venv/bin/pytest tests/
.venv/bin/flake8 src/
cd frontend && npm install && npm run build
```

## Known limitations

- No comprehensive scholarly full-text retrieval; academic support is often
  based on abstracts and metadata.
- Relevance classification uses conservative heuristics.
- Upstream metadata can be malformed.
- APA proper-noun/title normalization may require manual inspection.
- Semantic reviewers vary by provider/model.
- Small local models may produce malformed structured Humanizer output.
- Author review remains necessary for final publication.
- Generated batches still converge structurally. The diversity checker runs
  against generated output and currently returns FAIL on a twenty-prompt
  benchmark for both the medium-only control and full HowlWriter: output varies
  less than the corpus on sentence length, paragraph size and lexical
  diversity. Parentheticals are no longer a recognizable signature; overall
  structural spread still is.
- Most runs cannot produce an APA reference entry for the tool, because the
  configured providers report no model name and APA's template requires a tool
  and a version. The disclosure statement is still generated; the reference is
  withheld with the reason stated rather than filled in with a guess.
- Reviewer independence is tracked only for the meaning reviewer against the
  humanizer. The consistency reviewer and the writer have none.
- HowlWriter records what it sent and what came back. It has no access to any
  model's internal reasoning and makes no claim about it.

See [docs/humanization.md](docs/humanization.md) and
[docs/academic-paper.md](docs/academic-paper.md) for detailed discussions.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the MVP scope checklist and the growth
path toward the full pipeline described in [docs/vision.md](docs/vision.md).
