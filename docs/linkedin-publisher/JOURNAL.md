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
