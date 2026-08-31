from pathlib import Path
import pytest

from howlwriter.config.defaults import default_config
from howlwriter.domain.io import atomic_write_text
from howlwriter.pipeline.howl import run_howl_pipeline
from src.control_plane.agent_execution import FakeAgentBackend


def test_atomic_write_creates_parent_directories(tmp_path):
    nested_target = tmp_path / "deep" / "nested" / "dir" / "output.md"
    atomic_write_text(nested_target, "# Hello World")

    assert nested_target.exists()
    assert nested_target.read_text(encoding="utf-8") == "# Hello World"


def test_atomic_write_replaces_existing_file_safely(tmp_path):
    target = tmp_path / "doc.md"
    target.write_text("Version 1", encoding="utf-8")

    atomic_write_text(target, "Version 2")

    assert target.read_text(encoding="utf-8") == "Version 2"
    # Ensure no leftover temporary files
    leftovers = [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
    assert len(leftovers) == 0


def test_atomic_write_cleans_up_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "doc.md"

    def fail_replace(self, dst):
        raise OSError("Disk simulated write error")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError):
        atomic_write_text(target, "Failing write")

    leftovers = [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
    assert len(leftovers) == 0


def test_pipeline_does_not_mutate_original_file(tmp_path):
    orig_file = tmp_path / "input.md"
    original_content = "# The Title\n\nFurthermore, this is text with numbers 12 and 45."
    orig_file.write_text(original_content, encoding="utf-8")

    fake_backend = FakeAgentBackend(
        agent_id="backend",
        default_stdout="""```yaml
resulting_text: |
  # The Title

  This is rewritten text with numbers 12 and 45.
changes_made:
  - "removed furthermore"
```""",
    )

    res = run_howl_pipeline(orig_file, default_config(), custom_backend=fake_backend)

    # Original file must remain untouched
    assert orig_file.read_text(encoding="utf-8") == original_content
    # Pipeline returned transformed document
    assert res.final_document.text != original_content
