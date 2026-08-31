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

## Domain-Neutral Role Binding Architecture

The two gaps identified during initial development have been resolved cleanly
via HowlPlane's domain-neutral role execution framework:

1. **Domain-Neutral Role Dispatching (`src.control_plane.role_binding`)**:
   HowlPlane provides `RoleDescriptor`, `RoleBinding`, `RoleBindingRegistry`, and `RoleDispatcher`.
   Rather than hardcoding software-only reviewer roles, HowlPlane supports registering roles
   across any domain (e.g. `domain="writing"`, `role="humanizer"`, `role="final_reviewer"`).

2. **Explicit Role-to-Executor Binding**:
   Role bindings are configured declaratively in operator configuration (`~/.config/howlplane/config.toml`
   or `.env` / `settings.yaml`):
   ```toml
   [roles.writing]
   humanizer = "claude_code"
   final_reviewer = "codex"
   ```
   Or explicitly per role:
   ```toml
   [roles.writing.humanizer]
   provider = "claude_code"
   capability = "text_transform"
   timeout_seconds = 300
   ```

3. **HowlWriter / HowlPlane Bridge (`howlwriter.integration.howlplane_bridge`)**:
   `HowlPlaneWritingBridge` routes `WritingRole` requests from HowlWriter to HowlPlane's
   `RoleDispatcher`.
   - HowlWriter retains domain authority over prompt contracts, 10 humanizer priorities,
     deterministic linting, and semantic meaning-preservation validation.
   - HowlPlane retains execution authority over provider resolution, backend spawning,
     independent reviewer enforcement (`avoid_provider`), timeouts, and receipts.
   - When unconfigured, HowlWriter raises an explicit `ModelRoleNotConfiguredError` rather
     than quietly faking model output.
   - Independent review is verified and recorded with observable `IndependenceStatus`
     (`INDEPENDENT`, `SAME_PROVIDER`, `NOT_REVIEWED`, `UNAVAILABLE`).

## Summary

The separation of concerns is clean and domain-neutral:
HowlPlane owns model execution, provider pools, and control plane guarantees.
HowlWriter owns writing semantics, provenance graphs, linting, and verification contracts.
