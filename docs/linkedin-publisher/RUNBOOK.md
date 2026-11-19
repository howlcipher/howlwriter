# LinkedIn Publisher: Runbook

Sections marked "skeleton" describe milestones that are not built yet. Do not follow
them as instructions until the roadmap marks that milestone VERIFIED.

## What works today (M1 to M3, local only)

A local, deterministic post queue, verification through HowlProof, and the approval
boundary. Nothing here can contact LinkedIn. Approval needs the GitHub workflow below,
which has not been run yet (see ROADMAP M3).

### Set up a local publishing directory

```bash
howlwriter linkedin --repo ~/howlwriter-linkedin-private init
export HOWLWRITER_LINKEDIN_REPO=~/howlwriter-linkedin-private
```

This creates `publisher.yaml` (publishing off, dry run on), `howlproof.post.yaml` (the
HowlProof acceptance contract, yours to edit), `posts/`, `media/`, `claims/`,
`verification/`, `state/`, `ledger/` and a `.gitignore`. It does not create or contact any GitHub repository. Turn
the directory into a private Git repository yourself when you are ready.

### Daily commands

| Task | Command |
| --- | --- |
| Add a draft | `howlwriter linkedin add --title "Title" --text-file post.txt --date 2026-12-01` |
| Add with a link and image | add `--url https://...`, `--image media/chart.png --alt "Description"` |
| List posts | `howlwriter linkedin list` (optional `--state DRAFT`) |
| Inspect one post | `howlwriter linkedin show <id>` |
| Run the checks | `howlwriter linkedin validate <id>` (exit 3 on blocking findings) |
| Send to review | `howlwriter linkedin submit <id>` |
| Edit | `howlwriter linkedin edit <id> --text-file new.txt` (discards verification and approval) |
| Preview the queue | `howlwriter linkedin queue` |
| What would a run do | `howlwriter linkedin evaluate` or `evaluate --at 2026-12-01T13:30:00Z` |
| Reschedule one | `howlwriter linkedin reschedule <id> --date 2026-12-02 --time 09:00` |
| Follow the default time again | `howlwriter linkedin reschedule <id> --time default` |
| Shift all future posts | `howlwriter linkedin reschedule-all --shift-days 7` then repeat with `--apply` |
| Pause or resume everything | `howlwriter linkedin pause --reason "..."`, `howlwriter linkedin resume` |
| Take one post out of the queue | `howlwriter linkedin cancel <id>` |
| Archive | `howlwriter linkedin archive <id>` (never deletes from LinkedIn) |

Add `--actor NAME` to label the audit entry.

Add `--json` for machine output. Every command then prints one `howl.result/v1` envelope:
`{"schema", "component": "howlwriter", "command": ["linkedin", "<subcommand>"], "status", "data", "error"}`.
`data` holds the command's result object. `status` is `ok`, or `blocked` when the command
finished but the outcome is not ready, or, on an error, `denied` (a policy refusal) or `failed`;
then `data` is null and `error` is `{"code", "message"}`.

Exit codes: 0 success; 1 error (bad argument, refused, revision conflict, store problem; the
message is on stderr); 3 finished but not ready: `list` found invalid files, `validate` found
blocking findings, `verify` found the post not eligible, `review` found it not approvable, or
`reschedule-all` found conflicts (nothing was changed).

### Verify a post

Requires the `howlproof` program on `PATH` (or `--howlproof PATH`, or
`HOWLWRITER_HOWLPROOF`). Check it with `howlproof --version`.

```bash
howlwriter linkedin verify <id>                  # offline: no link is contacted
howlwriter linkedin verify <id> --allow-network  # also fetch each listed link through howlproof acquire
```

Exit 0 means the post is eligible for human approval and the report is attached. Exit 3
means it is blocked; the `BLOCKER` lines say why. Either way a report is written to
`verification/<id>/` and HowlProof's sealed evidence to `verification/howlproof/`. Commit
both. A report is never an approval.

| Output line | Meaning |
| --- | --- |
| `HowlProof verdict ...` | HowlProof's own verdict, unchanged. `none` means HowlProof gave no usable result |
| `BLOCKER` | Must be fixed. Edit the post, the claims or the contract, then verify again |
| `LIMIT` | Not established by this verification. You accept these when you approve |

### Declare factual claims

A figure with a percent sign, currency or unit blocks verification until a claim covers
it. Create `claims/<id>/claims.json` in the `howl.claim_bundle/v1` format and put each
evidence file beside it (for example `claims/<id>/evidence/e1.json`), then verify again.
The format, the check types (`fact_compare`, `text_presence`, `arithmetic`) and what each
can establish are in HowlProof's `docs/research_claims.md`. To let HowlProof confirm a
source, record it first with `howlproof acquire --store verification/acquisitions --url ...`
and reference the acquisition from the evidence entry.

Read the claim status in the report: `SUPPORTED` with `DETERMINISTIC_CHECK_ONLY` means the
arithmetic holds on numbers you supplied, not that the numbers were checked.

### Verification problems

| Situation | What to do |
| --- | --- |
| "HowlProof did not run" | Install HowlProof or pass `--howlproof`. Nothing is treated as passed without it |
| "HowlProof exited 2" | The contract is invalid. Run `howlproof validate howlproof.post.yaml` |
| "required HowlProof check secrets.scan is absent" | Restore `secrets.scan` in the contract's `profiles` |
| A previously verified post now reports changed evidence | Media, claims or evidence files changed. Verify again |
| "the verification is N day(s) old" | Verify again. A scheduled post keeps its approval if the result is not weaker |
| Verification of a scheduled post was blocked | The post returned to DRAFT and lost its approval. Fix it and go through review again |

### Change the schedule

- Default time: edit `default_publish_time` in `publisher.yaml`. It must be one of
  `allowed_publish_times`. Posts without an override follow it.
- New time slot: add it to `allowed_publish_times` and (from M4) add a matching scheduled
  check to the workflow. A time that is not listed is refused.
- Always quote times: `"09:00"`. An unquoted `9:00` is read by YAML as a number and is
  rejected.

### Reading queue statuses

| Status | Meaning | Action |
| --- | --- | --- |
| `FUTURE`, `NOT_YET_DUE` | Waiting | None |
| `DUE` | Would publish on a run now | None |
| `OVERDUE` | Its day or lateness window passed | `reschedule` |
| `BLOCKED` | Stale approval, edited file, unsupported slot or timezone | Read the reason; fix and re-approve if content changed |
| `DAILY_LIMIT_CONFLICT` | Another post is due first that day | `reschedule` one of them |

### Recovery

| Situation | What to do |
| --- | --- |
| `evaluate` says `QUEUE_INVALID` | `howlwriter linkedin list` names the bad file and its problems. Fix or restore it with Git. Nothing publishes until it is fixed. |
| `evaluate` says `IN_FLIGHT` | A run was interrupted. The next real run marks the post `UNCERTAIN`. Then reconcile. |
| A post is `UNCERTAIN` | Look at your LinkedIn profile. If the post is there: `howlwriter linkedin reconcile <id> --published <post id or URL>`. If it is not: `howlwriter linkedin reconcile <id> --not-published`, then re-queue it with `authorize-schedule`. Never guess. |
| A post is `FAILED` | Read the attempt detail with `show <id> --json`. Fix the cause, then re-queue it with the approval workflow's `authorize-schedule` action. |
| "changed (revision ...)" error | Someone else changed the record first. Run the command again. |
| Ledger or control file reported unreadable | Restore the file from Git history. Do not delete a ledger file to "unblock" a day. |

### Approving a post (M3: built, not yet run on GitHub)

One time setup in the private repository, by the owner:

1. Copy `docs/linkedin-publisher/workflows/linkedin-approve.yml` to
   `.github/workflows/linkedin-approve.yml` on `main`. The two actions are pinned to
   release commits; check them again when you update the pins.
2. Create the key and store it as the Actions secret `LINKEDIN_APPROVAL_KEY`:
   `openssl rand -hex 32`. Do not save it anywhere else.
3. Set the Actions variable `LINKEDIN_APPROVER_ID` to your numeric GitHub account ID
   (shown by `gh api user --jq .id`), and `HOWLWRITER_COMMIT` to the HowlWriter commit to
   install.
4. Do not give AI agents, or any token other than your own, push access to this
   repository. Branch protection is not available here: GitHub answered "Upgrade to
   GitHub Pro or make this repository public" for this private repository on 2026-11-17.

For each post:

1. `howlwriter linkedin verify <id>`, then `howlwriter linkedin submit <id>`. Commit and push.
2. `howlwriter linkedin review <id>`. Read the text, links, image details and every
   limitation. The command prints `fingerprint` and `limitations_digest`.
3. On GitHub, open Actions, "LinkedIn approve", "Run workflow" on `main`, action
   `approve`, and paste the post ID and the two values. Do this yourself.
4. Pull. The post is APPROVED; `howlwriter linkedin schedule <id>` queues it.

To move an approved post, or to put a FAILED approved post back in the queue on a new
day: run the same workflow with action `authorize-schedule` and the new date or time.
Local `reschedule` and `reschedule-all` move only posts that are not approved yet. Only
the most recent authorization counts: moving a post back to an earlier slot needs a new
authorization too.

A dry run now evaluates the verification and approval gates as well, so it reports
BLOCKED with the reasons when a real run would block.

| Message | Meaning |
| --- | --- |
| "not authorized: ..." | The run is not your own first attempt dispatch of the approval workflow on `main`, or the key or approver ID is not configured |
| "the fingerprint you confirmed is not the post's current content" | The post changed after you reviewed it. Review again |
| "the record was made with a different approval key" | The key was rotated, or the record was made elsewhere. Approve again |
| "the schedule ... was not authorized" | Someone moved the post file by hand. Run `authorize-schedule` for the slot you want |
| "the approval is N day(s) old" | Approve again (`approval_max_age_days`) |

To revoke every outstanding approval, replace the `LINKEDIN_APPROVAL_KEY` secret.

## Hosted publishing (skeleton, M4)

To be written and verified in M4:

1. Create the private repository (owner action; needs explicit authorization).
2. Run the approval workflow once and record what GitHub actually reports (closes M3).
3. Install `approval.publish_gates` in the publishing job.
4. LinkedIn developer application, OAuth setup flow, and storing the token as a GitHub
   encrypted secret.
5. Token expiry monitoring and re-authorization before expiry.
6. Scheduled workflow, manual dispatch, concurrency group.
7. Turning on `publishing_enabled` and turning off `dry_run` for the first live post
   (requires explicit authorization).
8. Handling 401, 403, 429 and timeouts.

## Cost controls (skeleton, verify in M4)

Intended setup, to be confirmed against current GitHub documentation before use:

- Keep the publishing repository private and its workflows short: a few scheduled checks
  per day, each bounded by `timeout-minutes`.
- In GitHub billing settings, set the Actions budget or spending limit so that usage
  beyond the included allowance is blocked rather than charged, and enable usage alerts.
- Do not add a payment method for this project.
- Keep artifact retention minimal.

The exact menu names and the current free allowance are not recorded here because they
were not verified in this session.

## Dashboard (skeleton, M5 and M6)

Not built.
