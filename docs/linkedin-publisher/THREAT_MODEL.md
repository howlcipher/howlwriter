# LinkedIn Publisher: Threat Model

Scope: the system in ARCHITECTURE.md. Status column: "M1 done" means implemented and
tested now; a milestone number means planned; "limit" means a residual risk that the
design does not remove.

## Assets

| Asset | Why it matters |
| --- | --- |
| The owner's LinkedIn account and reputation | A wrong or unauthorized post is public and hard to retract |
| LinkedIn access token and client secret | Allow posting as the owner |
| GitHub account, token, and repository write access | Control posts, approvals, workflows and secrets |
| Unpublished drafts and evidence | Private until published |
| Approval records and the daily ledger | The proof of what was authorized and what was sent |

## Actors

| Actor | Trust |
| --- | --- |
| Owner (authenticated GitHub account) | Trusted to approve and operate |
| AI drafting agents (HowlWriter model steps, coding agents) | May propose text. Not trusted to verify, approve or publish |
| HowlProof | Trusted to report what it executed. Not an authorizer |
| GitHub Actions runner | Trusted to run pinned workflow code with scoped secrets |
| Linked web content, imported text, model output | Untrusted data |
| Anyone else on the internet | Untrusted |

## Threats and controls

### Unauthorized or altered publication

| Threat | Control | Status |
| --- | --- | --- |
| Text, link or image changed after approval | Approval is bound to a content fingerprint that the scheduler recomputes; an edit through the tool also resets the post to DRAFT | M1 done |
| Post file edited by hand or by a script | Stale approval and stale stored fingerprint both block; the post is reported, not sent | M1 done |
| Image bytes swapped under the same path | Media SHA-256 is part of the fingerprint and is rechecked by `validate` | M1 done (recheck at publish time: M4) |
| A draft skips review | Lifecycle table allows `PUBLISHING` only from `SCHEDULED`, and `APPROVED` only from review | M1 done |
| Code path that approves without a human | No approve command; default verifier and gate refuse; empty gate list is refused | M1 done |
| Forged approval or verification file | Tamper evident records checked by a trusted workflow | M3 |
| Approval by an unauthorized GitHub actor | Compare the workflow actor's numeric account id with a configured trusted id | M3 |
| Identity taken from post content or an AI report | Identity will come only from the GitHub workflow context | M3 |
| A second route to LinkedIn that skips the gates | LinkedIn is not in the generic `publish --to` registry (decision D2) | M1 done |
| Publishing switched on by accident | Two independent switches, both off by default, in a human edited file | M1 done |

### Duplicate or excess publication

| Threat | Control | Status |
| --- | --- | --- |
| Two posts on one day | Persistent per day ledger claimed before sending; scheduling commands refuse collisions | M1 done |
| Retry after a lost response posts twice | Unclear results become `UNCERTAIN`, never retried, human reconciliation only | M1 done |
| Workflow killed mid send, then rerun | Intent is saved first; the next run marks the post `UNCERTAIN` and does not send | M1 done |
| Two workflow runs at once | Local lock and compare and swap now; workflow concurrency group and push rejection later | M1 done locally, M4 hosted |
| Ledger file deleted to reopen a day | Cross check against attempt records in the posts | M1 done |
| Ledger or control file corrupted | Unreadable state stops the run | M1 done |
| Backlog published in a burst after an outage | Overdue posts are held until rescheduled | M1 done |

### Secrets and private data

| Threat | Control | Status |
| --- | --- | --- |
| Token stored in a post, config, log or record | No field holds a secret; transport and checkpoint exceptions are stored and reported by type only, never by message | M1 done for records; M4 for the transport and logs |
| Secret or internal detail inside post text | HowlProof privacy and secret checks | M2 |
| Link with embedded credentials | `URL_INVALID` check rejects user or password in a URL | M1 done |
| Drafts leak through a public Pages site | Separate public repository with static assets only; leak test on the build | M6 |
| Path traversal through post ids or media paths | Strict id pattern; media and artifact paths confined to the repository | M1 done |

### Network and content handling (later milestones)

| Threat | Control | Status |
| --- | --- | --- |
| Link checker used to reach private or local addresses | Deny private, loopback and link local ranges; re-check after each redirect | M2 |
| HTTP 200 treated as proof of a claim | Reachability and support are separate findings | M2 |
| Instructions hidden in fetched or imported text | Treat as data; publishing path runs no model | M2, and by design in M1 |
| Local dashboard reachable from the network or another site | Loopback bind, origin and CSRF checks, no credentials sent to the browser | M5 |

### Supply chain and workflow integrity

| Threat | Control | Status |
| --- | --- | --- |
| Compromised action or dependency reads the LinkedIn token | Pin actions by commit, minimal dependencies on the runner, minimal `GITHUB_TOKEN` permissions, secrets only in the publish job | M4 |
| Workflow file changed to drop a check | Protect the default branch and review workflow changes | M3, M4 |
| Push trigger loop burns Actions minutes | No push trigger on publishing workflows; path filters | M4 |

## Limits that will remain

1. Anyone or anything holding the owner's GitHub token with write access can change
   workflows, approvals and secrets. Actor checks do not protect against a stolen or
   shared owner token. Keep AI agents on tokens that cannot write to the private
   repository's default branch.
2. A local agent running as the owner's operating system user can read any local
   credential the owner can read. Publishing credentials therefore live only in GitHub
   encrypted secrets, not on the workstation after setup.
3. GitHub and LinkedIn are trusted platforms here. Their outages can delay a post;
   overdue posts are held.
4. With only `w_member_social` there may be no API way to confirm whether an unclear post
   exists. Reconciliation is then manual by design (to be confirmed in M4).
5. The file lock is advisory and local to one machine.
6. HowlProof 0.2.0b1 describes itself as beta and advisory. Its verdict informs the
   human; it never replaces the approval.
7. Git history keeps drafts and approvals. Deleting a file does not remove it from
   history.
8. In M1 the `actor` in audit entries is a label the caller supplies (`--actor`). It is a
   record of what was claimed, not an authenticated identity. Authenticated identity
   arrives with M3 and applies to approvals.

## M1 security review notes

- No network code, subprocess calls, dynamic evaluation, or deserialization of untrusted
  formats beyond `json` and `yaml.safe_load`.
- All file writes go through two functions (atomic replace, exclusive create).
- No new run time dependency.
