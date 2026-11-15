# LinkedIn Publisher: Runbook

Sections marked "skeleton" describe milestones that are not built yet. Do not follow
them as instructions until the roadmap marks that milestone VERIFIED.

## What works today (M1)

A local, deterministic post queue. Nothing in M1 can contact LinkedIn or approve a post.

### Set up a local publishing directory

```bash
howlwriter linkedin --repo ~/howlwriter-linkedin-private init
export HOWLWRITER_LINKEDIN_REPO=~/howlwriter-linkedin-private
```

This creates `publisher.yaml` (publishing off, dry run on), `posts/`, `media/`, `state/`,
`ledger/` and a `.gitignore`. It does not create or contact any GitHub repository. Turn
the directory into a private Git repository yourself when you are ready.

### Daily commands

| Task | Command |
| --- | --- |
| Add a draft | `howlwriter linkedin add --title "Title" --text-file post.txt --date 2026-12-01` |
| Add with a link and image | add `--url https://...`, `--image media/chart.png --alt "Description"` |
| List posts | `howlwriter linkedin list` (optional `--state DRAFT`) |
| Inspect one post | `howlwriter linkedin show <id>` |
| Run the checks | `howlwriter linkedin validate <id>` (exit 1 on blocking findings) |
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

Add `--json` to any command for machine output and `--actor NAME` to label the audit entry.

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
| A post is `UNCERTAIN` | Look at your LinkedIn profile. If the post is there: `howlwriter linkedin reconcile <id> --published <post id or URL>`. If it is not: `howlwriter linkedin reconcile <id> --not-published`, then `reschedule` to retry. Never guess. |
| A post is `FAILED` | Read the attempt detail with `show <id> --json`. Fix the cause, then `reschedule` it. |
| "changed (revision ...)" error | Someone else changed the record first. Run the command again. |
| Ledger or control file reported unreadable | Restore the file from Git history. Do not delete a ledger file to "unblock" a day. |

## Hosted publishing (skeleton, M3 and M4)

To be written and verified in M3 and M4:

1. Create the private repository (owner action; needs explicit authorization).
2. Configure the trusted GitHub account id for approvals.
3. Approve a post through the manual workflow.
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
