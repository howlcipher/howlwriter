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
   The default role registry reads explicit environment bindings when it is
   first initialized. Select an available provider before starting HowlWriter:
   ```bash
   export HOWLPLANE_ROLE_WRITING_WRITER=claude_code
   export HOWLPLANE_ROLE_WRITING_HUMANIZER=claude_code
   export HOWLPLANE_ROLE_WRITING_FINAL_REVIEWER=codex
   ```
   These examples require the named providers to be installed and authenticated.
   Choose bindings appropriate to your environment and reviewer independence
   requirements. Setting a binding enables that role when it is requested;
   discovery itself does not execute a provider.

   Install HowlPlane in the same Python environment as HowlWriter, or point at
   an explicit source checkout:
   ```bash
   export HOWLPLANE_ROOT=/path/to/howlplane
   ```
   The bridge supports the current `src/howlplane/control_plane` layout and
   the legacy `src/control_plane` layout. An installed `howlplane` package
   works without `HOWLPLANE_ROOT`.

   The default registry does not automatically read `config.toml`, `.env`, or
   `settings.yaml`. Export environment bindings yourself, or register bindings
   through HowlPlane's programmatic registry. Restart the process after changing
   bindings because the default registry is initialized once per process.

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

## Choosing the model at run time

Role bindings are optional. When a step needs a model and its role is not
bound, HowlWriter asks which model to use before anything is sent:

- **CLI, on a terminal:** a menu offers Claude Code, Antigravity (`agy`),
  Codex, and a local model (Ollama), marks any that cannot run now and why,
  and offers "continue without a model" where a rule-based path exists.
  Choosing a model that is not local shows what will be sent and needs a `y`.
  The choice lasts for that command only; the next command asks again.
- **CLI, non-interactive:** pass `--provider claude|agy|codex|local` (and
  `--review-provider` for independent review steps) before the subcommand,
  e.g. `howlwriter --provider codex humanize draft.md`, or set
  `HOWLWRITER_PROVIDER` / `HOWLWRITER_REVIEW_PROVIDER`. Without a choice the
  command refuses and nothing is sent. `--local-model <ollama model>` (or
  `HOWLWRITER_LOCAL_MODEL`) chooses which Ollama model "local" runs;
  HowlPlane's default is `qwen2.5-coder:7b-instruct`.
- **Web UI:** a model step answers HTTP 409 `model_choice_required` and the
  page shows a picker; the request is retried once with the choice in the
  `X-HowlWriter-Provider` header (`none` = continue without a model). A model
  that is not local needs the "I agree to send it" box ticked
  (`X-HowlWriter-Send-Confirmed: 1`). Nothing is remembered between runs.

A review step that must be independent of the writer (`avoid_provider`) asks
separately. It never switches to a model the person did not pick: with no
reviewer chosen, the same model reviews and the result says `SAME_PROVIDER`.

Project drafts keep their own gate for sending project evidence: an
interactive or web confirmation authorizes that one run; `--provider` alone
does not, so `--allow-remote` or `project authorize-remote` is still needed.
For an AI agent driving HowlWriter, see [agents.md](agents.md): those two,
and authorship decisions, need the owner's word (`--owner-confirmed`).

Every model call runs in a new, empty, owner-only temporary directory that is
deleted afterwards. The backends are agent CLIs (agy and Codex may edit their
working directory in writing roles), and writing roles get their whole input
in the prompt, so no model is ever started in the user's folder.

## Summary

The separation of concerns is clean and domain-neutral:
HowlPlane owns model execution, provider pools, and control plane guarantees.
HowlWriter owns writing semantics, provenance graphs, linting, and verification contracts.
