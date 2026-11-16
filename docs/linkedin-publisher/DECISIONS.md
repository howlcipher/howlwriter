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
| HowlProof coverage for link relevance, privacy scan of post text, duplicate detection | Resolved in M2 | Read and exercised. See D13 for what HowlProof covers and what it does not. |
| 3,000 character LinkedIn limit | M4 | Taken from the existing HowlWriter linter, not re-verified against LinkedIn. |
| Alt text length limit | M4 | The stored bound of 4,000 characters is a storage limit, not a LinkedIn rule. |

## D13. Which checks run in HowlProof and which in HowlWriter (M2)

What HowlProof 0.2.0b1 really offers for a post, found by reading its source and running
it:

| Need | HowlProof capability | Used |
| --- | --- | --- |
| Credentials in the post | `secrets.scan` over the text files of the target | Yes, and required |
| Factual claims | `research.claims` over a `howl.claim_bundle/v1` the author supplies. It never invents a check | Yes |
| Absolute wording ("always", "never") | `docs.claims` over files named in the contract | Yes |
| Fetching a link safely | `howlproof acquire --url` (public hosts only, every redirect re-checked, bounded) | Yes, opt in |
| Whether a source supports a claim | Structural only: fact value and author chosen subject terms present in acquired bytes | Yes, through `research.claims` |
| LinkedIn length and formatting, broken Unicode, link consistency | None | No |
| Duplicate posts | None | No |
| Internal hostnames, private paths, confidentiality markers | None (`secrets.scan` covers credential formats only) | No |
| Image container, size, alt text for a single post | `publication.package.integrity` exists but requires a campaign package (`MANIFEST.json`, `SUMMARY.md`, `POSTS/`) and a 1200 by 675 minimum | No |
| Extracting claims from prose | None, by design | No |
| Judging what an image shows | None | No |

| Option | For | Against |
| --- | --- | --- |
| A. HowlProof runs what it has; HowlWriter adds deterministic checks for the gaps and can only block or add limitations (chosen) | No fabricated verdict: the verdict field is HowlProof's word, copied. The gap checks are about LinkedIn and this queue, which HowlWriter owns. No change to a second repository. Works with the released HowlProof | Two kinds of result in one report. The HowlProof verdict does not reflect the gap checks, so the report needs a separate outcome |
| B. Add new evaluators to HowlProof for every gap | One verdict covers everything | LinkedIn rules and this queue's history do not belong in a general verifier. Needs HowlProof fixtures, contract tests, regenerated docs and a release before HowlWriter can use it |
| C. HowlWriter computes its own verdict | Simple | Forbidden: it would be a fabricated verdict |

Chosen: A. Recorded gap for a later decision by the owner: a generic `privacy.scan`
evaluator (internal hostnames, private addresses, local paths) would fit HowlProof's
security adversary and could replace `privacy.patterns` here. It is not built, because it
changes HowlProof's check catalog and that is the owner's call.

No model is used anywhere in verification. Every check is labelled with its method
(`deterministic` or `howlproof acquire`), so nothing is presented as judgment.

## D14. The acceptance contract belongs to the operator

HowlProof returns `INSUFFICIENT_EVIDENCE` when a target has no acceptance criteria, and
its own bridge documentation says a bridge never writes them. `howlwriter linkedin init`
therefore writes a starter `howlproof.post.yaml` once (like `howlproof init`), never
overwrites it, passes it with `--config`, and records its SHA-256 in each report.

Because the operator can edit the contract, HowlWriter enforces one floor of its own:
`secrets.scan` must have run and reached `VERIFIED`, or the post is blocked whatever the
verdict. A test proves a contract without the secret scan cannot make a post eligible.

## D15. What each verdict means for the queue

| HowlProof result | Effect |
| --- | --- |
| `PROVEN`, `CONDITIONALLY_PROVEN`, `REQUIRES_HUMAN` | Eligible for human approval. The rationale and every limitation are listed for the approver. Human approval is still required |
| `REJECT`, `INSUFFICIENT_EVIDENCE` | Blocked |
| Exit 2 (usage), 3 (internal), 4 (artifact changed), timeout, unreadable or inconsistent output, HowlProof missing | Blocked. The report verdict is null |
| Any HowlProof check with status `ERROR` | Blocked |
| Any deterministic check `FAILED` or `ERROR` | Blocked. The HowlProof verdict is still recorded unchanged |
| A check that did not run (for example links without `--allow-network`) | Recorded as `NOT_EXECUTED` and listed as a limitation |

| Option for unexecuted optional checks | For | Against |
| --- | --- | --- |
| A. List as a limitation the approver must see (chosen) | Posts can be verified offline; nothing is reported as done | The approver must read the list |
| B. Block until every check ran | Strictest | Forces a network fetch for every post, and a link HowlProof cannot fetch (a PDF) would block forever |

M3 must show the limitations to the approver and record which were accepted.

## D16. Binding the report to the post and to HowlProof's evidence

The post stores only a reference: report path, SHA-256 of the report bytes, and the content
fingerprint. When a reference is attached, and again at publish time, HowlWriter
recomputes everything it can:

1. The report bytes match the stored hash and the report is for this post and fingerprint.
2. The eligibility decision is derived again from the recorded checks; the stored
   `outcome` block is not trusted.
3. The sealed HowlProof bundle still matches its own integrity index, its manifest hash is
   the one recorded, and its verdict equals the report's.
4. The package is rebuilt from the post, media, claims and evidence on disk and its tree
   digest must equal the digest HowlProof recorded for its target. HowlWriter computes
   that digest independently; a contract test shows both programs agree.

Limit: nothing is signed. A writer to the repository can forge a consistent report and
bundle. HowlProof has `attest` and `verify-attestation` (SSH signatures); using them, or
re-running verification inside the trusted approval workflow, is an M3 decision.

## D17. Revalidation

A verification report older than `verification_max_age_days` (default 7, range 1 to 30)
blocks publication. `verify` may be run again on an approved or scheduled post:

| Result of the new run | Effect |
| --- | --- |
| Eligible and the verdict is not weaker than before | Report replaced, approval kept (same content fingerprint) |
| Blocked, or the verdict is weaker than before | Post returns to DRAFT and loses its approval |

Open for M3: an approval will name the verification report it relied on. Whether a
refreshed report with new limitations needs a new approval must be decided there.

## D18. Links are checked through `howlproof acquire`, not by HowlWriter

HowlWriter contains no HTTP client. Link contact is opt in (`verify --allow-network`) and
goes through `howlproof acquire`, which already defends against private, loopback, link
local and metadata addresses on every hop, pins the connection to the validated address,
and bounds redirects, time and size. Writing a second fetcher would duplicate that risk.

Consequences: only text content types are accepted, so a working PDF or image link is
reported `UNCONFIRMED`; a 404 or 410 is `BROKEN` and blocks; a redirect to another host
is a warning. A reachable link is never reported as support for the post.

## D19. Declared claims

Claims are authored, not extracted. The operator (or a drafting step whose output the
operator reviews) writes `claims/<post id>/claims.json` in `howl.claim_bundle/v1` with its
evidence files. The deterministic `claims.coverage` check blocks when the post text has a
figure with a unit, percent sign or currency that no declared claim mentions, and warns
on other bare numbers. It cannot see claims that carry no number.
