# LinkedIn Publisher: Roadmap

Statuses: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `VERIFIED`, `COMPLETE`.
`VERIFIED` means the acceptance criteria were checked with the evidence listed and the
milestone is waiting for the owner at its gate. `COMPLETE` is set only after that.

Out of scope for all milestones: analytics, engagement optimization, multiple accounts,
AI auto approval, other social platforms.

Session start checklist for any agent: read this file and `JOURNAL.md`, inspect Git
state, identify the current milestone, re-run the evidence command of the last VERIFIED
milestone, and continue only the next authorized work.

| Milestone | Status |
| --- | --- |
| M0 Audit and architecture | COMPLETE |
| M1 Private post queue and scheduler | VERIFIED (at gate, awaiting owner review) |
| M2 HowlProof integration | NOT_STARTED |
| M3 Human approval | NOT_STARTED |
| M4 LinkedIn and GitHub Actions | NOT_STARTED |
| M5 Local management dashboard | NOT_STARTED |
| M6 Secure GitHub Pages | NOT_STARTED |

## M0. Audit and architecture

- Status: COMPLETE (2026-11-15)
- Scope: inspect HowlWriter and HowlProof as they are; record a baseline; design the
  component boundaries; write the five documents.
- Acceptance criteria:
  1. Git state checked before changes and a feature branch used. Met: branch
     `feat/linkedin-publisher` from main `83ad4eb`; only untracked `.task_runs/` present, untouched.
  2. Bounded baseline test run recorded. Met: ARCHITECTURE.md section 2.
  3. ARCHITECTURE, ROADMAP, THREAT_MODEL, DECISIONS, RUNBOOK exist and record observations.
     Met.
- Implementation tasks: done.
- Test requirements: baseline only.
- Security checks: threat model written; fail closed defaults chosen (DECISIONS D9).
- Dependencies: none.
- Evidence: `docs/linkedin-publisher/*.md`; baseline 1,935 passed, 11 skipped, 17 failed
  (all 17 in two files outside version control).
- Known limitations: HowlProof was audited at the level of commands, profiles and verdict
  semantics. Its evaluators were not exercised. HowlPlane was not inspected (not needed).

## M1. Private post queue and scheduler

- Status: VERIFIED (2026-11-15). Stopped at the gate as instructed.
- Scope: versioned post schema, external validated configuration, lifecycle, scheduling
  engine, persistence with compare and swap, daily ledger, publish protocol against mocked
  transports, CLI.
- Acceptance criteria and where each is proven (`tests/linkedin/`):

| Criterion | Evidence |
| --- | --- |
| Schema driven, versioned post with every required field | `test_models_and_config.py` (parser, JSON Schema agreement, round trip) |
| Explicit lifecycle; illegal transitions refused | `test_every_transition_outside_the_table_is_refused`, `test_lifecycle_safety_properties` |
| Verification and approval are separate referenced artifacts | `ArtifactRef`; `test_approval_requires_verification_for_the_same_content` |
| Config external, validated, defaults not hardcoded | `test_default_config_file_is_valid_and_safe`, `test_invalid_config_is_rejected`, `test_changing_the_default_time_moves_posts_without_an_override` |
| Unsupported times rejected | `test_past_dates_and_unsupported_times_are_refused`, `test_post_with_a_slot_no_longer_supported_is_blocked` |
| DST, month, year, leap year | `test_due_instant_is_correct_across_dst_and_calendar_edges`, `test_dst_days_publish_at_the_local_slot`, `test_bulk_reschedule_spans_dst_month_and_year_boundaries` |
| Missed and delayed runs | `test_missed_slot_is_recovered_by_the_next_slot_check_the_same_day`, `test_delayed_start_within_the_window_still_publishes` |
| Multiple approved posts, empty queue, past dates | `test_two_posts_due_the_same_day_yield_one_candidate`, `test_empty_queue_does_nothing`, `test_post_from_a_past_day_is_held_not_published` |
| Global pause, individual cancel, single and bulk reschedule, conflicts | `test_service.py` |
| Concurrent updates do not lose changes | `test_concurrent_writers_cannot_lose_an_update`, `test_concurrent_processes_cannot_both_claim_a_day` (real processes) |
| At most one publication per local day, persisted | `test_second_due_post_the_same_day_is_not_sent`, `test_a_fresh_coordinator_has_no_memory_and_still_respects_the_day`, `test_a_deleted_ledger_file_does_not_reopen_the_day`, seeded 45 day simulation |
| Intent persisted before sending; id persisted after success | `test_intent_is_persisted_before_the_transport_is_called`, `test_successful_publication_is_recorded_everywhere` |
| Unclear result is UNCERTAIN and never retried | `test_anything_unclear_becomes_uncertain_and_is_never_resent` |
| Crash recovery | `test_crash_during_the_send_becomes_uncertain_on_the_next_run`, `test_crash_between_ledger_claim_and_post_update_releases_the_day` |
| Overdue recovery without multiple posts in a day | held until `reschedule`; `test_reconcile_as_not_published_allows_an_explicit_retry` |
| Required commands | `test_cli.py` through the real parser |
| Archive never deletes from LinkedIn | `test_archiving_a_published_post_keeps_the_linkedin_record` |
| Mocked external services only | No network or LinkedIn code exists in `howlwriter/linkedin/` |

- Implementation tasks: done (see ARCHITECTURE.md section 4).
- Test requirements: met. 199 tests in `tests/linkedin/`, fake clock, fixed seeds, at most
  four worker processes in two tests.
- Security checks: fail closed defaults tested; path confinement tested; error messages
  that could carry tokens are never stored (`test_checkpoint_error_text_is_never_stored_or_reported`).
- Dependencies: M0.
- Evidence command: `pytest tests/linkedin -q` and the core suite
  `pytest -q -m "not contract" --ignore=tests/docs`. Results are in `JOURNAL.md`.
- Known limitations:
  1. No post can be approved or sent through the product yet (by design until M2 to M4).
  2. Cross machine concurrency relies on Git push rejection, which arrives with the
     workflows in M4. M1 proves local locking and compare and swap only.
  3. A bulk reschedule writes one file per post. A crash mid way leaves a partial change;
     Git shows it and can restore it.
  4. Overdue posts need a human reschedule.
  5. `max_posts_per_day` accepts only 1.
  6. The 3,000 character limit comes from the existing HowlWriter linter and was not
     re-verified against LinkedIn.

## M2. HowlProof integration

- Status: NOT_STARTED
- Scope: adapter over the real HowlProof CLI or API; publishing verification profile
  (claims, links, images, privacy and security, content quality); machine readable report
  stored as a separate artifact; a real `ArtifactVerifier` for verification references.
- Acceptance criteria: only real HowlProof commands used; all five verdicts preserved;
  errors, missing evidence and incomplete runs block; report contains post fingerprint,
  evidence references and fingerprints, check identities, results, findings, limitations,
  timestamp, tool and version provenance, verdict; only executed checks reported as done;
  no fabricated `PROVEN`.
- Implementation tasks: read HowlProof evaluators and bundle format in depth; decide what
  belongs in HowlProof versus HowlWriter and record gaps; link checker with redirect and
  private network defenses; image format, size, dimension and alt text checks; secret and
  privacy scan of post text; duplicate detection against the queue and history;
  revalidation rule for time sensitive evidence.
- Test requirements: contract tests against the installed HowlProof; adapter tests for
  each verdict and for error exits 2, 3 and 4; link safety tests with a local fake server
  only; no live network in the default suite.
- Security checks: request forgery defenses; untrusted fetched text handled as data.
- Dependencies: M1. May need changes in the HowlProof repository.
- Evidence: none yet.
- Known limitations: to be recorded.

## M3. Human approval

- Status: NOT_STARTED
- Scope: approval through an authenticated GitHub `workflow_dispatch`; trusted account id
  check; tamper evident approval record; a real `ArtifactVerifier` for approvals and a
  real `PublishGate`.
- Acceptance criteria: approval references the exact content fingerprint, media
  fingerprints, verification artifact, verdict and accepted limitations, actor, workflow
  run identity and timestamp; any content change invalidates it; scheduling changes are
  separately audited; forged records and unauthorized actors are rejected in tests; limits
  documented.
- Implementation tasks: approval record schema; signing or authentication controlled by
  the trusted workflow; approve workflow; verifier; gate; documentation of token and
  branch protection requirements for AI agents.
- Test requirements: bypass and forgery attack tests; unauthorized actor tests.
- Security checks: identity only from the workflow context; AI agents cannot write to the
  approval path.
- Dependencies: M1, M2. Needs the private repository (owner authorization to create).
- Evidence: none yet.
- Known limitations: to be recorded.

## M4. LinkedIn and GitHub Actions

- Status: NOT_STARTED
- Scope: official LinkedIn Posts API transport for text and links; OAuth setup flow;
  token expiry metadata and monitoring; scheduled and manual workflows; Git checkpoint.
- Acceptance criteria: current LinkedIn API and permissions verified from official
  documentation before coding; no secrets in files, logs or artifacts; minimal token
  permissions; pinned actions; bounded jobs; no push loops; 401, 403, 429 with
  Retry-After, 5xx, timeouts and malformed responses handled without blind retries; no
  live post without explicit authorization.
- Implementation tasks: verify the provisional items in DECISIONS D12; transport;
  checkpoint (commit and push with conflict handling); workflows; slot coverage check
  between `allowed_publish_times` and the workflow; runbook completion including billing
  controls.
- Test requirements: transport contract tests against recorded response shapes; failure
  injection; workflow file static checks. Mock responses are not evidence of live behavior.
- Security checks: secret handling review; workflow permission review.
- Dependencies: M1, M2, M3. Owner actions: LinkedIn developer application, repository
  secrets, authorization for the first live post.
- Evidence: none yet.
- Known limitations: to be recorded.

## M5. Local management dashboard

- Status: NOT_STARTED
- Scope: Queue, Review, Editor, History and Settings pages in the existing HowlWriter
  FastAPI and React application.
- Acceptance criteria: functional against a real local repository; loopback only by
  default; CSRF, origin and input validation; no credentials in the browser; the approval
  action only reports success when the trusted approval operation succeeded.
- Implementation tasks: API routes over `QueueService`; pages; GitHub CLI status
  integration; rebuild of the committed SPA bundle.
- Test requirements: API tests; authorization boundary tests; browser tests limited to one
  worker.
- Security checks: as above.
- Dependencies: M1 to M3 (M4 for LinkedIn status).
- Evidence: none yet.
- Known limitations: to be recorded.

## M6. Secure GitHub Pages

- Status: NOT_STARTED
- Scope: evaluate a hosted static frontend in a separate public repository.
- Acceptance criteria: no private data in the Pages build (tested); a viable authenticated
  GitHub access design that is security tested, or a documented decision not to deploy
  hosted editing; zero cost.
- Implementation tasks: design review of authentication options; leak test for the build;
  decision record.
- Test requirements: public build leak tests.
- Security checks: no tokens in frontend code, storage or URLs.
- Dependencies: M5. Owner authorization to create a public repository.
- Evidence: none yet.
- Known limitations: to be recorded.
