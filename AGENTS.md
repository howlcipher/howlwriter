# HowlWriter: notes for AI agents

This file is for any AI agent (Claude Code, Codex, Antigravity, Gemini CLI,
or another) that uses HowlWriter or works on this repository. `CLAUDE.md`
and `GEMINI.md` only import it; edit this file, never those.

## Using HowlWriter

Read [docs/agents.md](docs/agents.md) first. In short:

- Choose the model up front with `--provider claude|agy|codex|local`; there
  is no menu without a terminal, and a model step without a choice exits 2.
- Prefer `--json` output and exit codes over parsing prose.
- **Owner-only decisions stay with the owner.** Recording who wrote a
  document, counting a Workshop answer as the owner's writing, and sending
  private evidence to a remote model (`--allow-remote`,
  `project authorize-remote`) refuse without a terminal (exit 4, or HTTP 403
  `owner_confirmation_required`). Pass `--owner-confirmed` (or
  `X-HowlWriter-Owner-Confirmed: 1`) only to relay a decision the owner
  gave you, for the documents they named. If the owner's answer is
  ambiguous, ask.
- Never send the owner's private material (`~/.howlwriter/`, a mounted
  drive, project evidence, voice passages) to a remote model without their
  yes, and never write a Workshop answer for them.

## Working on this repository

- Lint gate (CI): `flake8 src/ --select=F821,F401`; `setup.cfg` sets the
  line length to 110. Code must also compile on Python 3.11.
- Tests: `pytest tests/` (see `.ai-project.toml`). Run the affected tests
  while working and the full suite before a pull request; report results
  from the final tree.
- Tests and fixtures are synthetic. Never commit private corpus data,
  document titles, credentials, lab materials, or anything from
  `~/.howlwriter/`.
