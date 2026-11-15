# LinkedIn Publisher: Decision Log

Each entry lists the options considered with their trade offs. Decisions marked
"provisional" must be confirmed in the milestone named.

## D1. Where the publishing logic lives

| Option | For | Against |
| --- | --- | --- |
| A. New package `howlwriter.linkedin` inside HowlWriter (chosen) | Reuses the CLI, config style, schemas folder, platform linter, test setup and CI. One install for local use and for the hosted runner. | HowlWriter grows; its heavy optional extras must stay optional for the runner. |
| B. Separate repository and package | Small install surface | Duplicates CLI, packaging and CI; a second release process |
| C. Code inside the private data repository | Self contained | Mixes code with private data; code review and tests would be private and unshared |

Chosen: A. The private repository holds data and workflows only.

## D2. Do not register LinkedIn in the generic `publish --to` registry

The existing `publish` command accepts `--allow-unverified` and has no approval record or
daily ledger. Registering a LinkedIn destination there would create a second path to
LinkedIn that skips the approval boundary. The LinkedIn transport (M4) will be reachable
only through `PublishCoordinator`. The existing test that `linkedin` is an unsupported
registry destination stays as a guard.

## D3. Post storage format

| Option | For | Against |
| --- | --- | --- |
| A. One JSON file per post (chosen) | Standard library only, exact canonical form, JSON Schema, small Git diffs, per file conflicts | Multi line text is awkward to hand edit |
| B. Markdown with YAML front matter | Pleasant to hand edit | Ambiguous whitespace and YAML typing make an exact fingerprint fragile |
| C. One queue file | Simple listing | Every change conflicts with every other change |
| D. SQLite in the repository | Transactions | Binary diffs, merge conflicts, no review in GitHub |

Chosen: A. Editing is done through commands and later the dashboard.

## D4. Validation: hand written parser plus JSON Schema

| Option | For | Against |
| --- | --- | --- |
| A. Strict Python parser at run time, JSON Schema as the published contract, tests hold them together (chosen) | No new run time dependency; cross field lifecycle rules are expressible; all problems reported at once | Two descriptions to keep aligned (a contract test does this) |
| B. `jsonschema` at run time | One description | New run time dependency on the hosted runner; cannot express lifecycle rules |
| C. pydantic | Rich models | Only present in the `web` extra today; heavier runner install |

Chosen: A. `jsonschema` was added to the `dev` extra so the contract test runs in CI.

## D5. Content fingerprint scope

Covers text, ordered links, media path, media bytes hash, and alt text. Excludes title
and schedule. Reason: the requirement that any text, media or link change invalidates
approval while a scheduling change does not. The title is an internal label and is not
sent to LinkedIn. If M4 ever sends the title (for example as a link preview title), the
fingerprint schema version must change and include it.

No Unicode normalization is applied: visually identical but differently encoded text is
different content. That is the conservative choice for an approval boundary.

## D6. Daily limit enforcement

| Option | For | Against |
| --- | --- | --- |
| A. One ledger file per local day, claimed before sending (chosen) | Persistent, readable, exclusive creation, natural Git conflict on the same path | A stale `INTENT` needs recovery logic (implemented) |
| B. Count `PUBLISHED` posts by date | No extra files | An unclear send would not count; relies on every post file being intact |
| C. In memory or cache | Simple | Forbidden by the requirements; lost on restart |

Chosen: A, plus B as a cross check that can only block.

`max_posts_per_day` is read from configuration but must be exactly 1 in this version.
Raising it is a code change on purpose, because one per day is a stated hard limit.

## D7. Overdue posts are held, not auto shifted

| Option | For | Against |
| --- | --- | --- |
| A. Hold and require an explicit reschedule (chosen) | Predictable; no surprise bursts; every date change is audited | A missed day needs a human action |
| B. Publish the oldest overdue post on the next free day | Self healing | Silently displaces later posts and changes dates nobody approved |

Chosen: A. Mitigation for missed runs: several slot checks per day and a lateness window
(`max_lateness_minutes`, default 180) inside the same local day.

## D8. Slot agnostic runs

A run decides from its real start time, not from the slot that triggered it. This covers
delayed starts, missed runs recovered by a later check, manual dispatch, and duplicates.

## D9. Fail closed defaults

`publishing_enabled: false`, `dry_run: true`, `RefuseAllVerifier`, `RefuseAllGate`, and an
empty gate list is replaced by the refusing gate. There is no `approve` command and no
command that calls a transport. An invalid post file blocks the whole run rather than
being skipped.

## D10. Ambiguity handling

Any transport exception, a success without a usable id, or an unrecognized result is
`UNCERTAIN`. A process that dies after the intent is saved is recovered as `UNCERTAIN`.
`UNCERTAIN` is never retried and leaves only through `reconcile`. A definite failure
releases the day but still needs an explicit reschedule to retry.

## D11. Audit trail location

Per post `history` list written in the same atomic write as the change, and a history
list in `state/control.json` for pause and resume. A single global log file was rejected
because every operation would then conflict in Git.

## D12. Provisional items to verify before relying on them

| Item | Milestone | Why provisional |
| --- | --- | --- |
| GitHub Actions `schedule` with a timezone | M4 | Stated in the brief; not checked against GitHub documentation in this session. The design does not depend on it: two UTC cron entries per slot also work because runs are slot agnostic. |
| LinkedIn Posts API version, `w_member_social`, token lifetime, image upload flow | M4 | Not checked in this session. No LinkedIn code exists yet. |
| GitHub Free minutes for private repositories and how to block overage | M4 | Runbook section is a skeleton until verified. |
| HowlProof coverage for link relevance, privacy scan of post text, duplicate detection | M2 | Only the command surface and profiles were read. |
| 3,000 character LinkedIn limit | M4 | Taken from the existing HowlWriter linter, not re-verified against LinkedIn. |
| Alt text length limit | M4 | The stored bound of 4,000 characters is a storage limit, not a LinkedIn rule. |
