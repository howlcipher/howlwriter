# LinkedIn Publisher: Architecture

Status: M0 audit complete, M1 implemented. Later milestones are designed here but not built.
Everything under "Observed" was read from the repositories on 2026-11-15, not assumed.

## 1. Goal

Publish at most one LinkedIn post per America/Detroit calendar day, from a private GitHub
repository, through LinkedIn's official API, with a human approval for exactly the content
that is sent, and with no AI model, paid service, or local machine needed at publish time.

## 2. Observed baseline (M0 audit)

### HowlWriter (`howlcipher/howlwriter`, main at `83ad4eb`, version 0.1.1)

| Area | What exists |
| --- | --- |
| Language and packaging | Python `>=3.11`, setuptools, `src/` layout. Core dependencies: PyYAML and `howl-provider-core`. Optional extras for web, docx, pdf, gdocs. |
| CLI | `howlwriter.cli.main`: argparse, one module per command in `cli/commands/`, each exposing `add_subparser` and a handler. Usage errors exit 1. Exit 2 is reserved for "no model chosen". `--json` is the convention for machine output. |
| Publishing | `howlwriter.publishing`: `ArtifactPublisher` protocol, `PublicationArtifact`, `PublishResult` (statuses `SUCCESS`, `UNCONFIRMED`, `CONFLICT`, `FAILED`), `RevisionConflictError`, and a registry with two destinations: `google_docs` and `plain_text`/`local`. `publish --to` has an `--allow-unverified` flag and no human approval record. |
| LinkedIn today | No LinkedIn transport. `linting/platforms.py` has `check_linkedin_conformance` (3,000 character limit, unrendered Markdown, hashtag count, control characters, hook length). `WritingMode.LINKEDIN` exists for drafting. `tests/publishing/test_linkedin_campaign_export.py` asserts that `linkedin` is an unsupported registry destination. |
| Facts and provenance | `facts/` (claim extraction, deterministic repository evidence), `provenance/` (manifest assembly), `publishing/verification.py` (read back comparison for published documents). |
| Configuration | `config/`: dataclass schema with layered YAML overrides; unknown keys are rejected. |
| Schemas | `howlwriter/schemas/*.json` shipped as package data; a test validates documents against them with `jsonschema` when it is installed. |
| Local web UI | FastAPI app (`web/app.py`) plus a React and Vite SPA in `frontend/`, built into `web/static/`. Owner only decisions use an explicit confirmation header (`web/owner.py`). CORS tests exist (`tests/web/test_cors_security.py`). |
| Tests | pytest, 1,963 collected in the core selection. Fakes in `tests/fakes/`. Browser tests are isolated in `tests/docs/` and in a separate CI job. |
| CI | `.github/workflows/ci.yml`: Python 3.11 to 3.13, `flake8 src/ --select=F821,F401`, `pytest -q -m "not contract" --ignore=tests/docs`. `permissions: contents: read`. Actions are pinned by major tag, not by commit. |
| Secrets conventions | `.gitignore` excludes Google token and client secret files. Credentials live outside the repository. |

### HowlProof (`howlcipher/howlproof`, main at `3b3e4ee`, version 0.2.0b1)

| Area | What exists |
| --- | --- |
| Purpose | Independent falsification. It judges and never repairs. The README calls it beta, for advisory evaluation of trusted local artifacts on Linux. |
| Verdicts and exit codes | `PROVEN` 0, `CONDITIONALLY_PROVEN` 10, `REQUIRES_HUMAN` 20, `REJECT` 30, `INSUFFICIENT_EVIDENCE` 40. Also 2 usage error, 3 internal fault, 4 artifact changed during evaluation. |
| Check statuses | `VERIFIED`, `FAILED`, `SKIPPED`, `UNAVAILABLE`, `NOT_APPLICABLE`, `ERROR`. Every check records a limitation. |
| CLI commands | `init`, `evaluate`, `acquire`, `calibration`, `validate`, `profiles`, `doctor`, `report`/`explain` style bundle readers, `findings`, `reproduce`, `verify`, `accept`, `compare`, `handoff`, `plane`, `attest`, `authenticate`, `interop`. |
| Contract | An evaluation needs a `howlproof.yaml` contract with acceptance criteria. A contract with no criteria cannot reach `PROVEN`. |
| Relevant profiles | `publication` (`publication.package.integrity`, `publication.manifest.consistency`: required files, safe paths, UTF-8, image signature and dimensions, alt text), `research` (`research.claims` over a `howl.claim_bundle/v1`), and a credential pattern scan (`secrets.scan`). |
| Evidence acquisition | `howlproof acquire --url` fetches one public http(s) URL with bounds, or registers a file the operator attests to. |
| Attestation | `attest` signs a bundle with an explicit SSH key; `authenticate` checks it against allowed signers. |

Not yet verified (M2 work): how well the existing profiles cover link relevance, privacy
scanning of post text, and duplicate detection. Those are listed as M2 questions, not as
facts.

### Baseline tests

`pytest -q -m "not contract" --ignore=tests/docs`, one process, on main: 1,935 passed,
11 skipped, 17 failed, in 228 seconds. All 17 failures are in two files that are not in
version control (`tests/publishing/test_campaign_final_release_qa.py`,
`tests/publishing/test_campaign_season_02_qa.py`); they look for local release folders
that are absent. No tracked test failed.

## 3. Component boundaries

```
 HowlWriter (drafting)                HowlProof (independent)
   draft, import, edit, metadata        evidence, falsification, verdict
            |                                   |
            v                                   v
   posts/<id>.json  <----- reference -----  verification/<id>/...   (separate artifact)
            |
            v
   Approval service (M3)  human identity + exact content fingerprint -> approvals/<id>/...
            |
            v
   Publisher (M1 queue and scheduler, M4 transport and workflows)
     evaluate -> ledger claim -> intent -> send once -> outcome
            |
            v
   Dashboard (M5 local, M6 hosted if a safe design exists): reads and requests, never authorizes
```

| Component | Owns | Must never |
| --- | --- | --- |
| HowlWriter drafting | Text, links, media references, metadata, deterministic format checks | Mark anything verified or approved |
| HowlProof | Evidence, findings, verdict, limitations | Edit the post, authorize publication |
| Approval service | The record that a named human approved one exact fingerprint | Accept identity from post content or AI output |
| Publisher | Schedule, queue, ledger, transport, recovery | Send without every gate passing; retry an unclear send |
| Dashboard | Display and request operations | Hold publishing credentials; fake an approval |

Reusable logic lives in HowlWriter as the package `howlwriter.linkedin`. The private
repository holds data only.

## 4. Code layout (implemented in M1)

| Module | Responsibility |
| --- | --- |
| `howlwriter/linkedin/models.py` | `Post` record, strict parser, lifecycle table, canonical content fingerprint |
| `howlwriter/linkedin/config.py` | `publisher.yaml` validation and defaults |
| `howlwriter/linkedin/store.py` | Atomic file persistence, compare and swap, advisory lock, daily ledger |
| `howlwriter/linkedin/scheduler.py` | Pure scheduling evaluation (no clock, files or network) |
| `howlwriter/linkedin/checks.py` | Deterministic pre-review checks; reuses `check_linkedin_conformance` |
| `howlwriter/linkedin/service.py` | Queue operations with audit events |
| `howlwriter/linkedin/publisher.py` | The publish run: recovery, gates, intent, single send, outcome |
| `howlwriter/cli/commands/linkedin.py` | `howlwriter linkedin ...` |
| `howlwriter/schemas/howlwriter.linkedin_post.v1.schema.json` | Post schema for other tools |
| `howlwriter/schemas/howlwriter.linkedin_publisher_config.v1.schema.json` | Config schema |

Injected dependencies (protocols): `Clock`, `ArtifactVerifier`, `PublishGate`,
`PostTransport`, and a `checkpoint` callable. The defaults for `ArtifactVerifier` and
`PublishGate` refuse everything. Real implementations: `verification.ReportVerifier` and
`VerificationGate` (M2), `approval.ApprovalVerifier` and `ApprovalGate` (M3). No transport
exists until M4, so nothing can be sent.

## 5. Private repository layout

```
publisher.yaml                 configuration (human edited)
posts/<id>.json                one post per file
media/...                      local images referenced by posts
state/control.json             global pause switch with audit trail
ledger/<year>/<date>.json      one file per local calendar day
verification/...               HowlProof reports (M2)
approvals/<id>/...             approval and schedule authorization records (M3)
.github/workflows/...          scheduled and manual workflows (M3, M4)
```

`howlwriter linkedin init` creates the first five and a `.gitignore` for the lock file.
It does not create a GitHub repository.

## 6. Post record

Schema id `howlwriter.linkedin_post/v1`. Fields: `id`, `revision`, `title`, `text`, `urls`,
`media` (path, SHA-256, alt text), `created_at`, `updated_at`, `scheduled_date`,
`scheduled_time` (optional override), `timezone`, `state`, `content_fingerprint`,
`verification_ref`, `approval_ref`, `attempts`, `linkedin_post_id`, `history`.

The content fingerprint is SHA-256 over canonical JSON of the exact text, the ordered
links, and each media path, byte hash and alt text. The title and the schedule are
excluded. So a scheduling change keeps approval valid and any content change does not.
The scheduler always recomputes the fingerprint; it never trusts the stored value.

Verification and approval are references (`path`, `sha256`, `content_fingerprint`) to
separate files. They are not status flags.

## 7. Lifecycle

```
DRAFT -> READY_FOR_REVIEW -> APPROVED -> SCHEDULED -> PUBLISHING -> PUBLISHED -> ARCHIVED
                                                          |-> FAILED     (definitely not sent)
                                                          |-> UNCERTAIN  (cannot tell)
```

- Editing content from any editable state returns to `DRAFT` and discards both references.
- `SCHEDULED -> APPROVED` is an individual cancellation.
- `FAILED` re-enters the queue only through an explicit `reschedule`.
- `UNCERTAIN` leaves only through `reconcile`, a human statement after checking LinkedIn.
- `ARCHIVED` is terminal. Archiving a published record never touches LinkedIn.

## 8. Scheduling model

- Configuration lists `allowed_publish_times`. A post uses the default time or an override
  that must be in that list. Anything else is refused with a message that a schedule
  configuration change is needed.
- The hosted workflow will run once per supported time. A run does not know which slot it
  is: it evaluates the queue against its actual start time. That makes late and duplicate
  runs harmless.
- A post is due from its slot until `max_lateness_minutes` later, and only on its own
  local calendar day. After that it is `OVERDUE` and is held until a human reschedules it.
  Nothing is auto shifted, so a backlog can never post several items in a burst.
- Daylight saving: the slot is a wall clock time in the configured zone. A skipped wall
  time resolves after the gap; a repeated one resolves to its first occurrence.
- If several posts are due on one day (possible only through hand edits), the earliest
  slot wins, then the oldest post, then the lowest id. The others are reported.

## 9. Daily limit and publish protocol

1. Recover interrupted work: a post still `PUBLISHING` becomes `UNCERTAIN`.
2. Evaluate (pure function).
3. Claim the day: add an `INTENT` entry to `ledger/<year>/<date>.json`. New files use
   exclusive creation; existing files use compare and swap under the lock.
4. Save the post as `PUBLISHING` with a `PENDING` attempt.
5. Checkpoint (M4: commit and push). If it fails, nothing is sent and the attempt is `FAILED`.
6. Call the transport once.
7. Save `PUBLISHED` with the LinkedIn id, or `FAILED` (ledger entry `RELEASED`), or
   `UNCERTAIN` (ledger entry stays occupied).

The day is also cross checked against the posts' own attempt records, so deleting a ledger
file cannot reopen a day.

## 10. Concurrency

| Layer | Mechanism | Covers |
| --- | --- | --- |
| One machine | `flock` on `.publisher.lock` | Two local processes |
| Record | `revision` compare and swap on every write | Stale readers, lost updates |
| Creation | `O_EXCL` for posts and ledger days | Double creation |
| Hosted (M4) | One workflow concurrency group plus non fast forward push rejection | Two runners, runner versus a local push |

The lock is advisory and local. Across clones the guarantee comes from Git: two writers
that both create or change the same ledger file cannot both push.

## 11. What is real and what is mocked (M1)

| Real | Mocked or absent |
| --- | --- |
| Post schema, parser, fingerprint | LinkedIn transport (scripted fakes only) |
| Config validation | Verification verifier (test double; default refuses) |
| File store, lock, compare and swap, ledger | Approval verifier (test double; default refuses) |
| Scheduler and publish protocol | Git checkpoint (callable; default no operation) |
| CLI | GitHub Actions workflows (not written) |

A passing M1 suite says the queue logic is correct. It says nothing about the live
LinkedIn API.

## 12. Verification (implemented in M2)

Modules in `src/howlwriter/linkedin/`:

| Module | Role |
| --- | --- |
| `content_checks.py` | Deterministic checks for what HowlProof has no evaluator for: format, Unicode, link consistency, duplicates, privacy patterns, image container and alt text, coverage of figures by declared claims |
| `howlproof.py` | Adapter over the real `howlproof` program: `--version`, `evaluate`, `acquire`. Never produces a verdict |
| `verification.py` | Package builder, report, `VerificationService`, `ReportVerifier` (the M2 `ArtifactVerifier`), `VerificationGate` (a `PublishGate`) |

Flow of `howlwriter linkedin verify <id>`:

```
post + media + claims/<id>/         (private repository)
        |
        v
package in a temporary directory:  post.txt, post.json, media/..., claims.json, evidence/...
        |                                   tree digest computed by HowlWriter
        +--> deterministic checks (content_checks)
        +--> howlproof acquire --url ...     (only with --allow-network)
        +--> howlproof evaluate <package> --config howlproof.post.yaml
        |        --evidence-root verification/howlproof --json
        v
verification/<id>/<time>-<fingerprint>.json   report (schema howlwriter.linkedin_verification/v1)
verification/howlproof/<run id>/              HowlProof's sealed bundle
        |
        v
eligible: post.verification_ref = {path, sha256, content_fingerprint}
blocked:  reference removed; an approved or scheduled post returns to DRAFT
```

Additions to the private repository layout: `howlproof.post.yaml`, `claims/<post id>/`,
`verification/<post id>/`, `verification/howlproof/`, `verification/acquisitions/`.

The report carries the post fingerprint, media facts, the package file list with hashes,
evidence references with hashes, every check with its identity, method, status, findings
and stated limitation, HowlProof's version and implementation hash, the contract hash,
the time, HowlProof's verdict, and a derived outcome (`ELIGIBLE_FOR_HUMAN_APPROVAL` or
`BLOCKED`) with blockers and limitations. Decisions D13 to D19 explain the choices.

### What is real and what is mocked (M2)

| Area | Evidence |
| --- | --- |
| HowlProof `evaluate` for all five verdicts, exit 2, `secrets.scan`, `research.claims`, `docs.claims`, bundle integrity, tree digest agreement | Real program, `tests/linkedin/test_howlproof_contract.py` (skipped where HowlProof is not installed) |
| `howlproof acquire` refusing private, loopback, metadata, credential, non default port and non http addresses | Real program, same file. No connection is made |
| `howlproof acquire` fetching a public page | Run once by hand against `https://example.com/` on 2026-11-16 (result REACHABLE). Not in the automated suite, which uses no network |
| HowlProof exit 3 and 4, timeouts, malformed output, inconsistent exit codes | Scripted stand-in only (`tests/linkedin/proof_fakes.py`) |
| Redirects to another host, 404, unsupported content type | Scripted stand-in only |
| LinkedIn | Not contacted. No LinkedIn code exists |

## 13. Human approval (implemented in M3, not yet run on GitHub)

`src/howlwriter/linkedin/approval.py`. Decisions D20 to D25.

```
owner, locally          howlwriter linkedin review <id>
                        prints text, links, media, verdict, limitations,
                        content fingerprint, limitations digest
owner, on GitHub        Actions > LinkedIn approve > Run workflow (main)
                        inputs: post id, fingerprint, limitations digest
trusted workflow run    howlwriter linkedin approve ...
                        1. run identity: manual dispatch, first attempt, main,
                           named workflow, GITHUB_ACTOR_ID == trusted ID
                        2. post is READY_FOR_REVIEW, report genuine and recent
                        3. fingerprint and digest equal what is in the repository now
                        4. write approvals/<id>/<time>-<fp8>.json with an HMAC
                        5. post becomes APPROVED; workflow commits and pushes
publishing run (M4)     approval.publish_gates: VerificationGate + ApprovalGate
```

An approval record (`howlwriter.linkedin_approval/v1`) holds the post ID, content
fingerprint, media paths and hashes, the verification report (path, hash, time, verdict,
status, HowlProof run and manifest hash), the accepted limitations and their digest, the
approved schedule, the actor (numeric ID and login), the workflow run (repository and its
ID, run ID and attempt, workflow ref, event, ref, commit), the time, and the
authentication code. A schedule authorization
(`howlwriter.linkedin_schedule_authorization/v1`) names the approval by hash, the previous
and the new slot, and carries the same identity and authentication.

`ApprovalGate` accepts a post only when the record's hash matches the reference, its
structure is exact, its authentication code verifies with the key, the actor is the
trusted ID, the run identity is the trusted workflow, the post ID, fingerprint and media
match the post now, the approval is not too old, the attached report is the approved one
or a refresh that is no worse, and the post's slot is the approved one or an authorized
one.

### What is real and what is mocked (M3)

| Area | Evidence |
| --- | --- |
| Record creation, authentication, every refusal and forgery case | Real code, `tests/linkedin/test_approval.py` |
| GitHub run identity | A dictionary shaped like the variables GitHub sets. GitHub was not contacted and the workflow has never run |
| HowlProof inside these tests | Scripted stand-in (`proof_fakes.py`) |
| Publishing through both gates | Scripted transport. Says nothing about LinkedIn |
| Workflow file | Template, parsed and checked statically only |
