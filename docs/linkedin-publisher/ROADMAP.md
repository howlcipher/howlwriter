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
| M1 Private post queue and scheduler | COMPLETE |
| M2 HowlProof integration | COMPLETE |
| M3 Human approval | IN_PROGRESS (built and tested locally; live workflow run blocked on the private repository) |
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

- Status: COMPLETE. Verified 2026-11-15; the owner authorized continuing on 2026-11-16.
  Still open from M1: the branch is not pushed, so CI has not run it on Python 3.11 to 3.13.
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

- Status: COMPLETE. Verified 2026-11-16; the owner replied "continue" to the M2 report.
- Scope: adapter over the real HowlProof program; publishing verification (claims, links,
  images, privacy and security, content quality); machine readable report stored as a
  separate artifact; a real `ArtifactVerifier` for verification references; a publish
  gate for verification.
- Acceptance criteria and where each is proven (`tests/linkedin/`):

| Criterion | Evidence |
| --- | --- |
| Only real HowlProof commands and flags are used | `test_the_commands_and_flags_the_adapter_uses_exist` (reads `howlproof interop`), `test_only_real_howlproof_subcommands_and_flags_are_used` |
| All five verdicts preserved, never rewritten | Real program: clean post CONDITIONALLY_PROVEN, credential REJECT, arithmetic claim PROVEN, unevaluable criterion INSUFFICIENT_EVIDENCE, expired exclusion REQUIRES_HUMAN (`test_howlproof_contract.py`). Scripted: `test_howlproof_verdict_is_preserved_and_decides_eligibility` |
| No fabricated PROVEN | `test_missing_howlproof_blocks_with_no_verdict`, `test_howlproof_error_exits_block_with_no_verdict`, `test_exit_code_that_disagrees_with_the_printed_verdict_is_rejected`, `test_unreadable_or_incomplete_output_is_never_a_verdict`, `test_verdict_upgraded_inside_the_report_is_caught_by_the_sealed_bundle` |
| Errors, missing evidence and incomplete runs block | `test_timeout_blocks`, `test_errored_howlproof_check_blocks_even_under_an_approvable_verdict`, `test_check_fault_blocks`, `test_missing_contract_blocks`, `test_malformed_claim_bundle_errors_and_blocks` |
| Report holds fingerprint, evidence references and hashes, check identities, results, findings, limitations, time, tool and version provenance, verdict | `test_clean_post_gets_a_report_and_a_reference`, `test_report_matches_the_published_schema` |
| Only executed checks are reported as done | `test_links_are_not_contacted_without_opt_in_and_are_reported_as_not_executed`, `test_missing_howlproof_blocks_with_no_verdict` |
| Claims: supported, refuted, unverifiable kept apart; invented metrics caught | `test_supported_arithmetic_claim_reaches_real_proven_with_its_limit_stated`, `test_refuted_claim_is_rejected_by_the_real_claim_evaluator`, `test_unverifiable_empirical_claim_stays_unresolved`, `test_measured_figure_without_a_declared_claim_blocks` |
| Links: syntax, https, redirects, response, destination, relevance; 200 is not proof | `test_link_in_text_must_be_declared_and_https`, `test_link_destination_rules`, `test_link_results_come_from_howlproof_acquire` |
| Unsafe redirects and private networks | `test_real_acquire_refuses_unsafe_destinations_before_connecting` (real program) |
| Images: format, size, dimensions, alt text, fingerprint; no claim of visual verification | `test_image_header_is_read_for_each_supported_format`, `test_image_defects_block` |
| Privacy and security | `test_credential_in_the_post_is_rejected_by_the_real_secret_scan`, `test_privacy_patterns` |
| Content quality: formatting, length, duplicates, Unicode, link consistency | `test_content_checks.py` |
| Human approval still required after PROVEN | `test_proven_still_requires_human_approval_and_cannot_be_approved_here` |
| Revalidation before publication | `test_gate_requires_revalidation_after_the_configured_age`, `test_revalidation_of_a_scheduled_post_keeps_its_approval`, `test_failed_or_weaker_revalidation_withdraws_a_scheduled_post` |
| Forged, edited or stale reports refused | `test_blocked_report_cannot_be_attached_by_editing_its_outcome`, `test_tampered_or_missing_howlproof_bundle_is_rejected`, `test_claims_or_media_changed_after_verification_invalidate_it`, `test_reference_outside_the_posts_own_report_directory_is_rejected` |

- Implementation tasks: done (ARCHITECTURE.md section 12, DECISIONS D13 to D19).
- Test requirements: met. 131 new tests. 20 of them run the real HowlProof program and are
  skipped where it is not installed, which includes HowlWriter's CI today. No test uses
  the network.
- Security checks: THREAT_MODEL.md, "M2 security review notes".
- Dependencies: M1. No change was made to the HowlProof repository.
- Evidence command: `pytest tests/linkedin -q` with `howlproof` on `PATH`, and the core
  suite `pytest -q -m "not contract" --ignore=tests/docs`. Results are in `JOURNAL.md`.
- Known limitations:
  1. Reports and bundles are tamper evident, not signed (DECISIONS D16). M3 must add trust.
  2. Claims are declared by the author. Statements without a number are not detected, and
     no model reads the post.
  3. Image checks cover the container and alt text only. Image source and provenance are
     not recorded, and nothing looks at what an image shows.
  4. Link relevance is structural and only for links that are the recorded source of a
     declared claim. Link contact is opt in.
  5. HowlProof exit 3 and 4, timeouts, redirects to another host, 404 and unsupported
     content types are covered with a scripted stand-in only.
  6. The real HowlProof tests ran against 0.2.0b1 on this machine. CI does not install
     HowlProof, so CI cannot detect a future incompatible HowlProof release.
  7. HowlProof gaps recorded, not built: a generic privacy evaluator, and an image
     evaluator for single posts (DECISIONS D13).
  8. The verification gate exists but no command installs it; the publish run still
     refuses everything until M3 and M4.
  9. The private repository does not exist yet, so nothing was verified against real posts.

## M3. Human approval

- Status: IN_PROGRESS (2026-11-16). Implemented and tested locally. One acceptance
  criterion is BLOCKED: the approval workflow has never run on GitHub, because the private
  repository does not exist and creating it needs the owner's authorization. M3 is not
  VERIFIED until that run has been observed.
- Scope: approval through an authenticated GitHub `workflow_dispatch`; trusted account ID
  check; authenticated approval record; a real `ArtifactVerifier` for approvals and a
  real `PublishGate`; separately authorized schedule changes.
- Acceptance criteria and where each is proven (`tests/linkedin/test_approval.py`):

| Criterion | Evidence |
| --- | --- |
| Approval references content fingerprint, media fingerprints, verification artifact, verdict, accepted limitations, actor, workflow run and time | `test_owner_dispatch_records_an_approval_that_names_everything_it_covers`, `test_records_match_the_published_schemas` |
| Actor checked against a configured numeric account ID | `test_anything_but_the_owners_own_dispatch_is_refused` (18 cases) |
| Identity never taken from a post, a login name or a command line argument | `test_a_name_in_the_post_or_the_login_never_authorizes`, `test_review_and_approve_commands` |
| Approver confirms the exact content and limitations | `test_the_approver_must_confirm_the_exact_content_and_limitations`, `test_content_changed_between_review_and_approval_is_refused` |
| Only a verified, recent, submitted post can be approved | `test_unverified_blocked_stale_or_unsubmitted_posts_cannot_be_approved` |
| Forged or altered records are rejected | `test_record_signed_with_another_key_is_rejected_everywhere`, `test_any_edit_to_a_genuine_record_breaks_its_authentication` (8 cases), `test_post_file_edited_to_say_approved_does_not_publish`, `test_genuine_approval_cannot_be_moved_to_another_post_or_path`, `test_schedule_record_cannot_stand_in_for_an_approval`, `test_service_refuses_to_attach_an_approval_the_verifier_rejects` |
| Nothing is reported as authenticated without the key | `test_without_the_key_nothing_is_reported_as_authenticated` |
| Any text or link change invalidates the approval | `test_editing_through_the_product_discards_the_approval`, `test_content_changed_by_hand_after_approval_is_blocked`; media bytes: M2 `test_claims_or_media_changed_after_verification_invalidate_it` |
| Scheduling change keeps verification and approval, and is separately authorized and audited | `test_schedule_change_keeps_approval_but_needs_its_own_authorization`, `test_schedule_authorization_needs_the_trusted_run_and_a_valid_approval`, `test_forged_or_borrowed_schedule_authorizations_are_ignored`, `test_post_approved_without_a_date_needs_the_date_authorized` |
| Evidence made stale or weaker after approval needs a new approval | `test_refreshed_report_with_a_new_limitation_needs_a_new_approval`, `test_weaker_verdict_reattached_by_hand_needs_a_new_approval`, `test_refreshed_report_with_nothing_new_keeps_the_approval`, `test_old_approval_expires` |
| Human approval required even for PROVEN | `test_proven_post_is_not_approved_until_the_human_approves` |
| Publishing run needs both gates | `test_valid_approval_lets_the_run_reach_the_transport_once`, `test_run_without_the_key_or_with_an_unauthorized_day_sends_nothing` (scripted transport) |
| The key is never stored or shown | `test_the_key_is_never_shown_or_stored` |
| Approval workflow is dispatch only, single key holder, no input reaches the shell unquoted | `test_approval_workflow_template_is_narrow` (static check of the template) |
| The approval workflow works on GitHub for the owner and refuses others | NOT EXECUTED. Needs the private repository |

- Evidence: `.venv/bin/python -m pytest tests/linkedin -q` gives 388 passed (58 new in
  `test_approval.py`). GitHub was not contacted.
- Known limitations:
  1. Never run on GitHub. The meaning of `GITHUB_ACTOR_ID`, `GITHUB_TRIGGERING_ACTOR`,
     `GITHUB_RUN_ATTEMPT` and `GITHUB_WORKFLOW_REF` is taken from memory of GitHub's
     documentation and was not re-read or observed in this session (DECISIONS D12).
  2. The key authenticates the workflow, not the person. Whoever can dispatch the workflow
     with the owner's token, or change a workflow that receives the secret, can approve
     (THREAT_MODEL limits 1 and 13).
  3. Withdrawing an approval is repository state. Someone with write access can restore
     the exact approved content, report and record; only key rotation revokes for certain
     (`test_restoring_withdrawn_approved_content_by_hand_is_a_known_limit`).
  4. Verification reports are still unsigned. The approver approves the content shown and
     the report as presented; the approval workflow rechecks the report but does not
     re-run HowlProof (DECISIONS D23).
  5. A change to `default_publish_time` moves posts that have no time override without a
     schedule authorization. Bulk rescheduling needs one authorization per post.
  6. The workflow template uses action tags, not commit pins, and installs HowlWriter
     from GitHub; the owner must pin both before first use.
  7. No publish command exists. `publish_gates` is ready for M4 to install.

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
