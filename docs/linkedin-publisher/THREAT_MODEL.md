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
| Image bytes swapped under the same path | Media SHA-256 is part of the fingerprint and is rechecked by `validate` | M1 done; rechecked by the verification gate at publish time since M2 |
| A draft skips review | Lifecycle table allows `PUBLISHING` only from `SCHEDULED`, and `APPROVED` only from review | M1 done |
| Code path that approves without a human | `approve` works only inside the trusted workflow run; default verifier and gate refuse; empty gate list is refused | M1 done; M3 built |
| Edited verification report, or a blocked report relabelled as eligible | Report hash in the post; eligibility recomputed from recorded checks; sealed HowlProof bundle and package tree digest rechecked | M2 done (tamper evident, not authenticated) |
| Fully forged report plus matching forged bundle by someone with write access | Not prevented. The approval binds the report hash the owner was shown; the owner must read the post (decision D23) | Open; candidate for M4 |
| Forged approval file | HMAC-SHA256 with a key held only as an Actions secret; checked at approval and at publish time | M3 built, tested locally |
| Approval by an unauthorized GitHub actor | `GITHUB_ACTOR_ID` compared with the configured numeric ID; first attempt manual dispatch of the named workflow on main only | M3 built; never run on GitHub |
| Identity taken from post content or an AI report | Identity comes only from the run environment; no `--actor` on `approve` | M3 built |
| Approved post moved to another day | Approval records its schedule; a different slot needs an authenticated schedule record | M3 built |
| Genuine approval reused for another post, other content, or a weaker report | Record names post, fingerprint, media, report hash, verdict and accepted limitations; all rechecked | M3 built |
| Content swapped between review and approval | Approver passes the fingerprint and limitations digest they saw; the workflow recomputes both | M3 built |
| Very old approval used | `approval_max_age_days` (default 30) | M3 built |
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
| Credential inside post text, alt text or claims | HowlProof `secrets.scan`, required for every report | M2 done |
| Internal hostname, private address, local path or confidentiality marker in the post | Deterministic `privacy.patterns` check blocks | M2 done (patterns only) |
| Credential reprinted in a report | HowlProof masks matches; the report copies titles and locations, not evidence excerpts | M2 done |
| Link with embedded credentials | `URL_INVALID` check rejects user or password in a URL | M1 done |
| Drafts leak through a public Pages site | Separate public repository with static assets only; leak test on the build | M6 |
| Path traversal through post ids or media paths | Strict id pattern; media and artifact paths confined to the repository | M1 done |

### Network and content handling (later milestones)

| Threat | Control | Status |
| --- | --- | --- |
| Link checker used to reach private or local addresses | No fetch code in HowlWriter. `howlproof acquire` refuses non public addresses on every hop; contract tests confirm the refusals without connecting | M2 done |
| HTTP 200 treated as proof of a claim | Reachability is one check with a stated limit; support is decided only by `research.claims` | M2 done |
| Instructions hidden in fetched or imported text | Fetched bytes are stored by HowlProof and never interpreted; verification runs no model | M2 done |
| A weakened HowlProof contract makes everything pass | Contract hash recorded; `secrets.scan` required regardless of the contract | M2 done |
| HowlProof missing, failing or timing out read as a pass | Any such case yields a null verdict and a blocked report | M2 done |
| Evidence or media swapped after verification | Package rebuilt and its digest compared at attach and publish time | M2 done |
| Stale verification used weeks later | `verification_max_age_days` gate | M2 done |
| Files smuggled into the package through the claims directory | Symbolic links, reserved names and oversized files are refused and block | M2 done |
| Local dashboard reachable from the network or another site | Loopback bind, origin and CSRF checks, no credentials sent to the browser | M5 |

### Supply chain and workflow integrity

| Threat | Control | Status |
| --- | --- | --- |
| Compromised action or dependency reads the LinkedIn token | Pin actions by commit, minimal dependencies on the runner, minimal `GITHUB_TOKEN` permissions, secrets only in the publish job | M4 |
| Workflow file changed to drop a check | Branch protection is unavailable for private repositories on GitHub Free (observed 2026-11-17). Only the owner's own token may push to the private repository; review every workflow change | Open (platform limit) |
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

9. Verification reports and HowlProof bundles are tamper evident, not authenticated.
   Anyone who can write to the repository can produce a consistent forged pair. The
   approval boundary (M3) must not treat a report as trusted merely because it verifies.
10. The deterministic checks are patterns. They do not find reworded duplicates, claims
    without a number, confidential material without a marker, or anything inside an image.
11. `claims.coverage` trusts the author to declare a claim honestly. A declared claim that
    HowlProof finds inconclusive does not block; it is listed for the approver.
12. A HowlProof `PROVEN` can rest on arithmetic over numbers the author supplied. The
    report states this for each such claim (`DETERMINISTIC_CHECK_ONLY`).

13. The approval key is a repository Actions secret. A workflow that someone with write
    access pushes can ask for it, on any branch, unless GitHub settings prevent that. So
    the approval boundary holds only against parties who cannot push workflows to the
    private repository and cannot use the owner's token. Give AI drafting agents no push
    access to that repository; let them hand over drafts another way (a pull request from
    a fork, or files the owner commits).
14. The approval job installs HowlWriter and its dependencies before the step that
    receives the key. A compromised dependency in that job could read the key. Pin the
    HowlWriter commit and keep the job's dependencies minimal.
15. A valid approval stays valid for its content and day until it expires, even after the
    owner withdraws it in the queue, if someone restores the files by hand. Rotate the key
    to revoke for certain.
16. The local `approve` command can be run by anyone with made up `GITHUB_*` variables and
    their own key. The local post file then says APPROVED. Every holder of the real key
    rejects that record, so it cannot publish; do not read the state field as proof.
17. The publishing job holds the same key and could create approvals. It is trusted code;
    M4 must keep it free of any path that writes approval records.
18. Only the newest authenticated schedule authorization counts, so an older slot cannot
    be replayed. Someone with write access can still delete the newest schedule record,
    which brings back the one before it (or the approval's own slot). Git history shows
    the deletion; key rotation voids every record.

## M3 security review notes

- No new dependency, no network code, no subprocess. `hmac`, `hashlib` and `json` only.
- The authentication code is compared with `hmac.compare_digest`. A domain prefix keeps
  the code from being valid for any other purpose.
- The key is read from the environment, kept out of `repr`, never written to a record,
  a log line or an error message. A malformed key is reported without echoing it.
- Record paths are confined to `approvals/<post id>/`; schedule records cannot be used as
  approvals; links (checked on the path as written, component by component) and oversized
  files are refused.
- Pre-merge review of PR #43 (2026-11-17) found and closed: a local `reschedule` that kept
  the approval but left the post blocked at publish time (now refused for approved posts);
  replay of a superseded schedule (now newest wins, limit 18); a link check that ran on
  the resolved path and never fired; a dry run that skipped the gates; a ledger entry
  left at INTENT when a run stopped between the post and ledger writes; and `verify`
  deciding from a post snapshot taken before HowlProof ran (now refused if the post
  changed).
- When the authentication code fails, no other field of the record is reported on.
- Workflow template: dispatch trigger only, `contents: write` only, inputs passed through
  environment variables, the key given to one step, re-runs and other branches skipped.

## M2 security review notes

- One new subprocess call site (`howlproof.subprocess_runner`): fixed argument list, no
  shell, bounded timeout, standard input closed.
- No HTTP client was added to HowlWriter. Network contact happens only inside
  `howlproof acquire`, only with `--allow-network`.
- The package is built in a private temporary directory and removed afterwards.
- HowlProof is called with paths relative to the repository so its sealed bundle holds
  no home directory path. The bundle does record the temporary package path.
- Report and bundle paths are confined to `verification/`; a reference outside the post's
  own report directory is refused.

## M1 security review notes

- No network code, subprocess calls, dynamic evaluation, or deserialization of untrusted
  formats beyond `json` and `yaml.safe_load`.
- All file writes go through two functions (atomic replace, exclusive create).
- No new run time dependency.
