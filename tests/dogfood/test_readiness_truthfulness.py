from howlwriter.config.defaults import default_config
from howlwriter.pipeline.howl import run_howl_pipeline
from src.control_plane.agent_execution import FakeAgentBackend


def test_banned_words_remaining_gates_to_needs_review(tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text("Clean text without banned words.")

    # Simulated Humanizer that mistakenly introduces a banned word ('delve')
    fake_backend = FakeAgentBackend(
        agent_id="backend",
        default_stdout="""```yaml
resulting_text: |
  Let us delve into this topic.
changes_made:
  - "added delve"
```""",
    )

    res = run_howl_pipeline(draft, default_config(), custom_backend=fake_backend)

    assert res.report.banned_words > 0
    assert res.report.status == "NEEDS_REVIEW"


def test_pass_with_warnings_gates_to_needs_review(tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text("The service processed 100 requests in Q3.")

    fake_backend = FakeAgentBackend(
        agent_id="backend",
        default_stdout="""```yaml
resulting_text: |
  The service processed 100 requests in Q3.
verdict: "PASS_WITH_WARNINGS"
differences:
  - kind: "mild_tone_shift"
    description: "Slightly informal tone."
    severity: "warning"
rationale: "Acceptable but flagged."
```""",
    )

    res = run_howl_pipeline(draft, default_config(), custom_backend=fake_backend)

    assert res.report.semantic_meaning_status == "PASS_WITH_WARNINGS"
    assert res.report.status == "NEEDS_REVIEW"


def test_reviewer_crash_gates_to_needs_review(tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text("The service processed 100 requests in Q3.")

    # Humanizer succeeds, but reviewer crashes with code 1
    class CrashingReviewerBackend(FakeAgentBackend):
        def execute(self, task, cwd, role="implementation", **kwargs):
            if role == "writing:final_reviewer":
                return self._result(
                    success=False,
                    exit_code=1,
                    error_message="Reviewer process terminated abnormally (SIGSEGV)",
                )
            return super().execute(task, cwd, role, **kwargs)

    backend = CrashingReviewerBackend(
        agent_id="crashing_reviewer",
        default_stdout="""```yaml
resulting_text: |
  The service processed 100 requests in Q3.
```""",
    )

    res = run_howl_pipeline(draft, default_config(), custom_backend=backend)

    assert res.report.semantic_meaning_status == "FAIL"
    assert res.report.status == "NEEDS_REVIEW"
