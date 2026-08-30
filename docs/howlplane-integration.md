# HowlWriter / HowlPlane integration

HowlWriter is deliberate dogfooding: it exists partly to prove HowlPlane's
control-plane concepts generalize beyond software engineering. This
document draws the boundary between the two, and lists what's missing on
HowlPlane's side to fully support HowlWriter -- as backlog observations,
not requests to change frozen code. HowlPlane's control plane is in an
explicit Architectural Freeze (`documentation/CONTROL_PLANE.md` in the
`howlcipher/howlplane` repository); nothing in this project modifies it,
and nothing below asks for that.

## The split

**HowlPlane supplies:** orchestration, task lifecycle, independent-reviewer
coordination and role selection, deterministic verification execution,
the durable evidence ledger, and human authority gating. All of that is
engineering-shaped today, and HowlWriter does not reimplement any of it.

**HowlWriter supplies:** local truth about itself as a project, through
exactly one committed artifact -- `.ai-project.toml` at this repository's
root. HowlPlane's `ai` CLI discovers that file by walking upward from the
working directory and builds its own `ProjectContext` from it
(`src/control_plane/project_adapter.py` in the howlplane repository).
HowlWriter has no code mirroring `ProjectContext` and shouldn't grow any --
the manifest is the entire interface.

Concretely, this repository's manifest declares:

- `test = ["pytest", "tests/"]`, `lint = ["flake8", "src/"]` -- real,
  currently-passing commands, not aspirational ones
- `capabilities = ["filesystem:repository", "process:project_commands"]`
  -- no network, git, database, or secrets grants, because the MVP CLI
  never needs them (`writer` and `research` raise
  `ModelRoleNotConfiguredError` rather than reaching the network)
- `[routing] implementation = [...]`, `review = [...]` -- HowlPlane's
  standard engineering task-type keys, describing which coding agent
  should implement or review changes made **to this codebase**. This is
  unrelated to HowlWriter's own internal `WritingRole` vocabulary (see
  below) -- an early draft of this document conflated the two; they are
  different layers and the manifest's `[routing]` only ever meant the
  former.

## Where HowlWriter needs a model, and where that leaves off

Every capability that needs a model call --
`humanize.rewriter.HumanizerRewriter`, the model-backed mode of
`editing.editor.Editor`, `facts.verification.ClaimVerifier`,
`research.researcher.Researcher`, `voice.model_hook.VoiceAnalyzer`,
`review.meaning.ModelMeaningReviewer` -- is defined in
`integration/model_role.py` as a typed `Protocol` against the
`WritingRole` enum (WRITER, EDITOR, HUMANIZER, VOICE_REVIEWER,
FACT_CHECKER, RESEARCHER, RED_PEN, CITATION_VALIDATOR, FINAL_REVIEWER),
with a `NotConfiguredRole` default that raises `ModelRoleNotConfiguredError`
rather than executing anything. HowlWriter never calls a model API on its
own behalf, anywhere in this codebase -- "provider routing/execution is a
HowlPlane concern" is enforced by this being the *only* seam, not by
convention.

This is where two real gaps show up:

### 1. HowlPlane's reviewer-role vocabulary is engineering-shaped

`CONTROL_PLANE.md` §3.4 enumerates `correctness-reviewer,
regression-reviewer, security-reviewer, test-falsifier,
architecture-reviewer, simplicity-reviewer`. None of those map cleanly onto
HowlWriter's writing-domain roles (`HUMANIZER`, `VOICE_REVIEWER`,
`RED_PEN`, `CITATION_VALIDATOR`, ...). If HowlPlane's independent-review
coordination is ever asked to route a HowlWriter task, it currently has no
vocabulary for what kind of reviewer that is. **Observation, not a change
request:** an extensible or project-declared reviewer-role vocabulary
would let a non-engineering project register its own role set instead of
being forced into engineering-shaped ones. Whether this is worth doing is
a question for whoever owns that roadmap, evaluated against the Freeze's
own bar (does it block real work, repeatedly, across real tasks).

### 2. There is no committed artifact binding a `WritingRole` to an executor

`.ai-project.toml`'s `[routing]` field routes *engineering* tasks
performed on a repository (see above) -- it was never meant to, and
doesn't, say anything about how HowlWriter's own internal `WritingRole`
Protocols get a real implementation at runtime. The
`PROJECT_MANIFEST_SPEC.md` is explicit that "provider execution" and
"routing resolution logic" are non-goals of the manifest format by design
(§7). So even when HowlPlane is present and available, there is currently
no artifact analogous to `.ai-project.toml` that says "here is the
`HumanizerRewriter` implementation for this project" or "route
`FACT_CHECKER` verification calls to provider X."

This is not a defect in what's frozen -- it's a layer above the manifest
that neither project currently owns. The temptation this creates is for
HowlWriter to build its own lightweight provider-calling shim to fill the
gap. **That has been deliberately not done here.** `NotConfiguredRole`
raising a clear, named error is the correct MVP behavior: it makes the gap
visible instead of quietly working around it. Filling this gap properly
belongs to whoever designs HowlPlane's (or another runtime's) execution
boundary, not to ad hoc code inside HowlWriter.

## Summary

Two gaps, both genuine, both explicitly left open rather than patched
inside this codebase: an engineering-shaped reviewer vocabulary that
doesn't fit writing roles, and no execution-binding artifact for
`WritingRole` at all. Everything else HowlWriter needs from HowlPlane --
project discovery, command execution, capability grants -- already works
through the existing `.ai-project.toml` boundary, validated in this
repository against HowlPlane's own `ai project validate`.
