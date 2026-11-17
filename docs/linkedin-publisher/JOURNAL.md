# LinkedIn Publisher: Progress Journal

Newest entry first. Read this and `ROADMAP.md` at the start of every session.

## 2026-11-15, session 1 (Claude Fable 5.2): M0 and M1

State at the end of the session

- Branch: `feat/linkedin-publisher`, created from main `83ad4eb`. Committed locally. Not pushed.
- Current milestone: M1 is VERIFIED and waiting at its gate for owner review. M2 is the
  next milestone and is not authorized yet.
- Nothing was pushed, merged, published, or created remotely. No LinkedIn or GitHub API
  was contacted. No private repository was created.

What was done

- M0: audited HowlWriter and HowlProof from the local checkouts; wrote ARCHITECTURE,
  DECISIONS, THREAT_MODEL, RUNBOOK and ROADMAP.
- M1: package `howlwriter.linkedin` (models, config, store, scheduler, checks, service,
  publisher), command group `howlwriter linkedin`, two JSON Schemas, 199 tests in
  `tests/linkedin/`.

Test evidence (final working tree, Python 3.14.4, one process, low priority)

| Run | Command | Result |
| --- | --- | --- |
| Baseline on main | `pytest -q -m "not contract" --ignore=tests/docs` | 1,935 passed, 11 skipped, 17 failed, 228 s |
| New tests | `pytest tests/linkedin -q` | 199 passed, 18 s |
| Final regression | `pytest -q -m "not contract" --ignore=tests/docs` | 2,134 passed, 11 skipped, 17 failed, 254 s |
| CI lint gate | `flake8 src/ --select=F821,F401` | clean |
| Full flake8 on new code | `flake8 src/howlwriter/linkedin src/howlwriter/cli/commands/linkedin.py` | clean |
| Python 3.11 | `python3.11 -m compileall` on new code and tests | compiles |

The 17 failures are identical before and after. They are in
`tests/publishing/test_campaign_final_release_qa.py` and
`tests/publishing/test_campaign_season_02_qa.py`, which are excluded from version control
on this machine and look for local release folders that do not exist. No tracked test fails.

Not run: browser tests (`tests/docs`), the HowlPlane contract job, and the test suite
under Python 3.11 to 3.13 (CI covers those after a push). The new tests were executed on
3.14 only.

Test impact assessment

- Behavior changed: a new command group and package. One existing file changed
  (`cli/main.py`, two lines to register the command).
- Existing tests touching it: `tests/cli/test_interop.py` enumerates every command from
  the live parser and still passes; a new test confirms the new commands appear there.
- `tests/publishing/test_linkedin_campaign_export.py` still asserts that `linkedin` is not
  a `publish --to` destination. That remains intended (DECISIONS D2).
- No obsolete or duplicate tests found. No tests removed.

Things a later session must know

1. `RefuseAllVerifier` and `RefuseAllGate` are the shipped defaults. M2 replaces the
   verification side, M3 the approval side. Do not add an approve command before M3.
2. Items in DECISIONS D12 are unverified claims. Verify them from official documentation
   at the start of M2 and M4.
3. The shared cross agent journal entry is
   `2026-11-15-howlwriter-linkedin-publisher-m0-m1` in `~/.ai-context/journal/`.
4. Untracked `.task_runs/` existed before this work and was left alone.

Next authorized step

None until the owner reviews M1. Recommended next: authorize M2, starting with a deep read
of HowlProof's evaluators and bundle format.

## 2026-11-16: M2 HowlProof integration (verified, at gate)

Authorization: the owner replied "Continue as recommended" to the M1 report. The M1 report
recommended starting M2 with a deep read of HowlProof. That was taken as authorization for
M2 only. It was not taken as authorization to push, so the branch is still local.

What was done

1. Read HowlProof 0.2.0b1 in depth: command line, exit codes, configuration model, verdict
   derivation, evidence bundle format, `secrets.scan`, `research.claims`, `docs.claims`,
   `publication.*`, `acquire`. Ran the real program on a scratch post package to see its
   actual output before writing any adapter code.
2. Decided the split of work between HowlProof and HowlWriter (DECISIONS D13 to D19).
3. Implemented `content_checks.py`, `howlproof.py`, `verification.py`, the `verify`
   command, the report schema, the `verification_max_age_days` setting, and the starter
   contract written by `init`.
4. `attach_verification` now also refreshes a report on an approved or scheduled post;
   new `withdraw_verification` records a blocked result and fails closed.
5. No change to the HowlProof repository.

Test evidence (final working tree, Python 3.14.4, one process, low priority, HowlProof
0.2.0b1 on PATH)

| Run | Command | Result |
| --- | --- | --- |
| LinkedIn tests | `pytest tests/linkedin -q` | 330 passed, 30 s (199 from M1, 131 new) |
| Of which real HowlProof | `pytest tests/linkedin/test_howlproof_contract.py -q` | 20 passed |
| Final regression | `pytest -q -m "not contract" --ignore=tests/docs` | 2,265 passed, 11 skipped, 17 failed, 278 s |
| CI lint gate | `flake8 src/ --select=F821,F401` | clean |
| Full flake8 on M2 files | new modules, the command module and the new test files | clean |
| Python 3.11 | `python3.11 -m compileall` on the package and tests | compiles |
| Live link check | `verify --allow-network` on a scratch post linking `https://example.com/` | REACHABLE, run once by hand |

The 17 failures are the same untracked local release tests as in the M1 baseline. No
tracked test fails.

Not run: browser tests, the HowlPlane contract job, Python 3.11 to 3.13 test runs. The
real HowlProof tests are skipped wherever HowlProof is not installed, which includes
HowlWriter's CI.

Test impact assessment

- Behavior changed: new `verify` command; `init` creates three more entries
  (`howlproof.post.yaml`, `claims/`, `verification/`); `attach_verification` accepts
  approved, scheduled and failed posts; one new configuration key with a default.
- Existing tests: all 199 M1 tests pass unchanged. None was edited or removed.
- New coverage: happy path, each verdict, every error exit, forgery and staleness of
  reports, lifecycle effects, the publish gate, and each deterministic rule with a
  defective and a clean input.
- Gap: exit 3, exit 4, timeouts and redirect handling are exercised with a scripted
  stand-in only.

Mistakes made and caught during this session

- A one off script used to wrap long lines turned one parenthesized condition into a
  tuple (always true) and one subscript into a tuple key. The tests failed immediately and
  both were fixed by hand; the files were then scanned for the same pattern.
- The private address pattern missed an address followed by a full stop. Found by a test,
  fixed, and a regression case added.
- The local path pattern matched paths inside public web addresses. Found by a test, fixed.

Things a later session must know

1. The report is tamper evident, not signed. Do not let M3 treat "the report verifies" as
   trust. Options are in DECISIONS D16.
2. M3 must show `outcome.limitations` to the approver and record what was accepted, and
   must decide what a refreshed report means for an existing approval (D17).
3. `VerificationGate` exists but nothing installs it. `RefuseAllGate` is still the default
   and there is still no approve or publish command.
4. Scratch repositories used for manual checks were under the session scratch directory
   and are not part of the repository.

Next authorized step

None. Stop at the M2 gate. Recommended next: owner review of M2, a decision on pushing the
branch, then M3 (human approval), which needs the private repository to exist.

## 2026-11-16: M3 human approval (built locally, live run blocked)

Authorization: the owner replied "continue" to the M2 report. That report named M3 as the
next milestone and listed pushing the branch and creating the private repository as
separate decisions. "continue" was taken as authorization for M3 work that stays local.
Nothing was pushed and no repository was created.

What was done

1. Decided how approvals are authenticated and where identity comes from (DECISIONS D20
   to D25), closing the questions D16 and D17 left open.
2. Added `approval.py`: trust settings and run identity from the environment, approval
   and schedule records with HMAC-SHA256, `ApprovalVerifier`, `ApprovalGate`,
   `publish_gates`, `ApprovalService` (`review`, `approve`, `authorize_schedule`).
3. Added commands `review`, `approve`, `authorize-schedule`; setting
   `approval_max_age_days`; two record schemas; `approvals/` in `init`.
4. `verify` on an approved post now also withdraws it when the new report lists a
   limitation the approval did not accept.
5. Added a workflow template under `docs/linkedin-publisher/workflows/`.
6. Updated four older tests whose wording said approval did not exist yet. The behavior
   they protect (refusal without a trusted verifier or gate) is unchanged.

Mistake caught by the tests: a command line test assumed the real clock was far from the
test clock. It was the same day, so the command approved instead of refusing. The test now
uses the real clock throughout.

Not done, and why

- The workflow has not run on GitHub: no private repository exists. M3 stays IN_PROGRESS.
- GitHub variable semantics and secret exposure rules were not re-verified (D12).

Next: owner decisions listed in ROADMAP M3 and the session report.

## 2026-11-17: pull request, private repository

Authorization: the owner replied "Do all recommendations" to the M3 report. Those were:
open a pull request, create the private repository with only the approval workflow and
an empty queue (the owner adds the key and account ID), and hold M4 until a real
approval run has been observed.

What was done

1. Scanned the branch diff for personal data and secrets (none), pushed
   `feat/linkedin-publisher`, opened pull request #43.
2. Pinned `actions/checkout` (v7.0.1) and `actions/setup-python` (v7.1.0) by commit in the
   template, with a test that keeps every action pinned.
3. Created `howlcipher/howlwriter-linkedin-private` as private (confirmed through the API),
   pushed the `init` layout, the workflow and a README, and set the non-secret variable
   `HOWLWRITER_COMMIT`. GitHub lists the workflow as active.
4. Observed that branch protection is unavailable for this private repository on the free
   plan (HTTP 403) and corrected the runbook, which had asked for it.

Not done: the approval key and approver ID are for the owner to set; no workflow run was
started; M4 not started.

## 2026-11-17: pre-merge review fixes

Authorization: the owner said "Merge and continue". The shipping rules require an
independent review before a merge, so one was run on PR #43 (medium depth). It reported
nine findings; all were checked against the code and seven were defects:

1. Local `reschedule` and `reschedule-all` moved approved posts and kept the approval,
   but the approval gate then blocked them. They now refuse; approved posts move only
   through `authorize-schedule` (`authorized=True` internally).
2. The approval's own slot and every older schedule authorization stayed valid, so a
   superseded slot could be replayed. Now only the newest authenticated authorization
   counts (ordered by `authorized_at`, then the same second collision suffix). More than
   200 records blocks instead of silently ignoring the rest. Deleting the newest record
   is a documented limit (THREAT_MODEL 18).
3. The link check on approval records ran on the resolved path and never fired. It now
   checks each component of the path as written.
4. A dry run returned DRY_RUN before the gates ran. It now reports BLOCKED with reasons.
5. A stop between saving the closed post and updating the ledger left an INTENT entry
   that kept the day used. Recovery now copies the post's closed outcome to the ledger.
6. `verify` decided from a snapshot taken before HowlProof ran without the lock. It now
   refuses to attach or withdraw when the post's revision changed; the report is kept.
7. Shared helpers: `_VERDICT_RANK` and `_dump` are imported instead of duplicated.

The double slot check on FAILED reschedule was removed as part of fix 1. Tests: eight new
regression tests; ten older tests that moved approved posts locally were changed to use
unapproved dated drafts, `authorized=True` (standing in for the workflow) or a direct
file edit (the untrusted move the gate must catch).
