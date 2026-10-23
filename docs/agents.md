# Using HowlWriter from an AI agent

HowlWriter is a command-line tool and a local web API. An AI agent (Claude
Code, Codex, Antigravity, or a script) can drive it the same way a person
does. This page covers what changes when nobody is at a terminal, and the
decisions an agent must leave to the owner.

## The short version

```bash
# Pick the model up front: an agent cannot answer the menu.
howlwriter --provider local --local-model qwen2.5:7b-instruct humanize draft.md
howlwriter --provider codex humanize draft.md

# Read-only and deterministic: no model, nothing leaves the machine.
howlwriter evaluate draft.md --identity william --mode academic --json
howlwriter lint draft.md
howlwriter project status <project> --json
howlwriter project validate <project> draft.md --json
howlwriter voice status --identity william --json
howlwriter voice review --identity william --json      # what awaits the owner's decision
```

```bash
# Reliability checks: read-only and deterministic. With --offline (citations verify,
# assignment check) nothing leaves the machine; paper --verify-sources always asks Crossref.
howlwriter citations verify sources.json --records records.json --offline --json
howlwriter reply check reply.md --post "Author=post.md" --json
howlwriter assignment check package.yaml --records records.json --offline --json
howlwriter lint draft.md --workflow-leakage --genre academic_discussion --json
```

Use `--json` wherever a command offers it (`evaluate`, `lint`, `project`,
`sources`, `benchmark`, `citations verify`, `reply check`, `assignment check`, and the `voice` identity commands) and read the exit
code, not the prose.

## Choosing the model

Without a terminal there is no menu. Pass `--provider claude|agy|codex|local`
before the subcommand (`--review-provider` for independent review steps), or
set `HOWLWRITER_PROVIDER` / `HOWLWRITER_REVIEW_PROVIDER`. If a step needs a
model and none was chosen, the command stops with exit code 2 and says so;
nothing is sent.

- `local` runs Ollama on this machine and needs `ollama serve`. Nothing
  leaves the machine. `--local-model` picks the Ollama model.
- `claude`, `agy`, and `codex` start that agent CLI in a new, empty
  temporary directory. An agent that calls `--provider claude` from inside
  Claude Code starts a second session and uses the same account's quota;
  `local` avoids that.

See [howlplane-integration.md](howlplane-integration.md#choosing-the-model-at-run-time).

## Decisions only the owner makes

These change what trains the owner's voice profile, or send their private
material off the machine. HowlWriter refuses them when nobody can be asked:

| Action | Command line | Web API |
| --- | --- | --- |
| Record who wrote a document | `voice review --set`, `--apply`, `--group --decide` | `POST /api/voice-intel/{id}/review/...`, `.../review-groups/...` |
| Count a Workshop answer as the owner's own writing | `voice workshop answer --self-written` / `--approve`, `approve`, `reclassify` | `POST .../workshop/samples` with `self_written` / `approve`, `.../actions/approve`, `.../context` |
| Permanently delete a Workshop answer | `voice workshop remove` | `POST .../actions/remove` |
| Send project evidence to a remote model | `project draft --allow-remote`, `project authorize-remote` | `allow_remote: true` on a draft, `POST .../authorize-remote` |

On the command line without a terminal these exit with code **4** and change
nothing. Through the web API, a request that does not come from HowlWriter's
own page (the browser marks those `Sec-Fetch-Site: same-origin`) gets HTTP
**403** `{"code": "owner_confirmation_required"}` and changes nothing.

When the owner has told you the exact decision in your conversation, relay
it:

- command line: add `--owner-confirmed`;
- web API: send `X-HowlWriter-Owner-Confirmed: 1`.

Authorship decisions made this way are recorded with source
`owner_relayed` rather than `user_attestation`, so the record shows they
were relayed. Two things cannot be relayed at all: `voice review
--interactive` and a `voice workshop` session refuse without a terminal,
because answers piped into their prompts would be nobody's decision.

Revoking (`authorize-remote --revoke`), excluding a Workshop answer, reading
the queue, and previewing a document never need the owner: they can only
keep material local or remove evidence.

Correcting a source's category (`project classify`, `POST
.../sources/{id}/category`) is yours to make, but the record says who made
it: `agent` by default without a terminal, `owner_relayed` with
`--owner-confirmed` (or the header) when the owner told you the category,
`user` only at a terminal or in HowlWriter's page.

Do correct a data file that a person or a model derived (ratings, a findings
ledger, a hand-written summary table) when you know it was derived, even if
it sits in `evidence/`: `project classify <project> <file> user_draft` (or
`supporting_reference`). Otherwise its rows count as the owner's direct
observations. Leave the file alone if you do not know how it was made.

### Rules for agents

- **Never pass `--owner-confirmed` or the owner header on your own
  judgement.** Pass it only for a decision the owner gave you, for the
  documents they named, in this conversation. If an answer is ambiguous
  (for example "assisted"), ask which code they mean.
- **Never write a Workshop answer for the owner.** Only text they wrote
  themselves may be saved as `--self-written`.
- **Ask before sending anything remote.** `--allow-remote`,
  `authorize-remote`, `--voice-examples on` with a remote model (it sends
  passages of the owner's writing), and `X-HowlWriter-Send-Confirmed: 1` all
  send private material to a provider. Say what will be sent and to whom,
  and wait for a yes.
- **Do not read or quote the private stores.** `~/.howlwriter/` holds the
  owner's documents, exports, and profiles. Use the commands, which report
  counts and reasons by default, and `voice review --preview` only when the
  owner asks to see a document.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | Error (bad argument or other usage error, including missing/conflicting/negative `runs prune` retention settings, unknown project or identity, or a model was chosen but HowlPlane, which runs it, cannot be imported); the message is on stderr. |
| 2 | A model step had no model chosen; `project`: refused by the remote-inference gate or browser policy; `voice scan`/`sync`: the drive is not mounted. Nothing was changed or sent. |
| 3 | Finished, but not ready: the `project validate` verdict is not `READY_FOR_HUMAN_REVIEW`, `citations verify` found a citation that is not `VERIFIED`, `reply check` found a reply that is not `GROUNDED`, `assignment check` is not `READY_FOR_HUMAN_REVIEW`, or a voice profile could not be built. A `project draft` reports its verdict in its output and provenance and exits 0, unless you pass `--fail-if-blocked`, which makes a not-ready draft exit 3 (the draft is still saved). `writer --fail-if-blocked` exits 3 when the draft cites a work, or names an exact identifier such as a CVE, that is not in `--sources` or the prompt; without the flag it warns on stderr and exits 0. |
| 4 | An owner-only decision was asked for without a terminal or `--owner-confirmed`. Nothing was changed. |
| 130 | `project`: cancelled. |

`howlwriter interop --json` prints this table, every command and flag, and the
documents `native request` and `native write` produce, as a `howl.interop/v1`
descriptor (the [Howl interop contract](https://github.com/howlcipher/howl/blob/main/docs/INTEROP.md)).
HowlPlane and `howl doctor` use it to check the commands they run.

## The web API

`howlwriter ui` serves the API on localhost. A model step answers HTTP 409
`model_choice_required` until the request carries `X-HowlWriter-Provider`
(`none` continues without a model where a rule-based path exists). The
owner-only actions above need the page or `X-HowlWriter-Owner-Confirmed: 1`.

## What these checks are, and are not

They stop an agent from making the owner's decisions by accident or on a
guess, and they make relayed decisions visible afterwards. They are not a
security boundary against a process that is determined to forge a flag or
a header on the owner's own machine.
