"""Tests for HowlWriter diagnostic run records and continuous dogfood telemetry."""

import pytest

from howlwriter.cli.main import main
from howlwriter.config.defaults import default_config
from howlwriter.diagnostic.run_record import (
    RunRecord,
    classify_failure,
    compute_sha256,
    generate_run_id,
)
from howlwriter.pipeline.howl import run_howl_pipeline
from src.control_plane.agent_execution import FakeAgentBackend


def test_generate_run_id_format():
    rid = generate_run_id()
    assert rid.startswith("hw-")
    parts = rid.split("-")
    assert len(parts) == 4
    assert len(parts[1]) == 8  # YYYYMMDD
    assert len(parts[2]) == 6  # HHMMSS


def test_compute_sha256_preserves_privacy():
    text = "Top secret human draft that should never be stored."
    hashed = compute_sha256(text)
    assert len(hashed) == 64
    assert text not in hashed


def test_classify_failure():
    assert classify_failure(TimeoutError("Process timed out")) == "PROVIDER_TIMEOUT"
    assert classify_failure(RuntimeError("Process exited with code 1")) == "PROVIDER_NONZERO_EXIT"
    assert classify_failure(RuntimeError("returned an empty response")) == "PROVIDER_EMPTY_RESPONSE"
    assert classify_failure(ValueError("exceeds safe single-pass limit")) == "DOCUMENT_SIZE_EXCEEDED"
    assert classify_failure(FileNotFoundError("input.md not found")) == "USER_ERROR"


def test_successful_howl_execution_saves_run_record(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    draft = tmp_path / "draft.md"
    draft.write_text("# Project Draft\n\nInitial draft text with 10 items.")

    fake_backend = FakeAgentBackend(
        agent_id="fake_humanizer",
        default_stdout="""```yaml
resulting_text: |
  # Project Draft

  Rewritten clean draft text with 10 items.
changes_made:
  - "polished cadence"
verdict: "PASS"
differences: []
rationale: "Clean preservation."
```""",
    )

    res = run_howl_pipeline(draft, default_config(), custom_backend=fake_backend)
    assert res.report.status == "READY"
    assert res.report.run_id is not None

    record = RunRecord.load(res.report.run_id)
    assert record is not None
    assert record.run_id == res.report.run_id
    assert record.command == "howl"
    assert record.success is True
    assert record.status == "READY"
    assert record.input_chars == len("# Project Draft\n\nInitial draft text with 10 items.")
    assert record.input_sha256 == compute_sha256(draft.read_text())
    assert record.output_chars == len(res.final_document.text)
    assert record.output_sha256 == compute_sha256(res.final_document.text)

    # Privacy Guarantee: Full prose is NOT in the JSON file
    record_file = (tmp_path / "runs" / f"{res.report.run_id}.json").read_text()
    assert "Top secret" not in record_file
    assert "Rewritten clean draft" not in record_file
    assert "Initial draft text" not in record_file


def test_failed_execution_saves_failure_record(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    draft = tmp_path / "draft.md"
    draft.write_text("# Failing Draft\n\nSome text.")
    from src.control_plane.agent_execution import AgentExecutionResult

    class FailingBackend(FakeAgentBackend):
        def execute(self, task, cwd, role="implementation", **kwargs):
            return AgentExecutionResult(
                agent_id=self.agent_id,
                role=role,
                command="failing",
                exit_code=1,
                stdout="",
                stderr="process failed",
                duration_seconds=0.1,
                success=False,
                error_message="Process terminated with exit code 1",
            )

    backend = FailingBackend("failing_provider")

    with pytest.raises(RuntimeError):
        run_howl_pipeline(draft, default_config(), custom_backend=backend)

    records = RunRecord.list_records()
    assert len(records) == 1
    rec = records[0]
    assert rec.success is False
    assert rec.status == "BLOCKED"
    assert rec.failure_category == "PROVIDER_NONZERO_EXIT"
    assert "exit code 1" in (rec.error_message or "").lower()


def test_diagnostic_failure_does_not_destroy_output_document(tmp_path, monkeypatch):
    # Make save fail by pointing to an unwritable directory or monkeypatching atomic_write_text
    def fail_save(self, runs_dir=None):
        raise OSError("Simulated disk error during diagnostic save")

    monkeypatch.setattr(RunRecord, "save", fail_save)

    draft = tmp_path / "draft.md"
    draft.write_text("# Protected Doc\n\nClean text with 42.")

    fake_backend = FakeAgentBackend(
        agent_id="backend",
        default_stdout="""```yaml
resulting_text: |
  # Protected Doc

  Clean text with 42.
```""",
    )

    # Pipeline must still complete successfully even if run record save fails
    res = run_howl_pipeline(draft, default_config(), custom_backend=fake_backend)
    assert res.final_document.text == "# Protected Doc\n\nClean text with 42."


def test_runs_cli_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    # Create dummy record
    rec = RunRecord(
        run_id="hw-20260831-120000-abcdef",
        command="humanize",
        success=True,
        status="READY",
        humanizer_provider="agy",
        meaning_reviewer_provider="devin",
        total_duration_seconds=12.4,
    )
    rec.save()

    # Test runs list
    exit_code = main(["runs", "list"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "hw-20260831-120000-abcdef" in captured.out
    assert "agy" in captured.out

    # Test runs show
    exit_code_show = main(["runs", "show", "hw-20260831-120000-abcdef"])
    captured_show = capsys.readouterr()
    assert exit_code_show == 0
    assert "RUN RECORD: hw-20260831-120000-abcdef" in captured_show.out
    assert "Duration:            12.4s" in captured_show.out
