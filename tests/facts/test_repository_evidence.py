"""Regression tests for deterministic repository evidence validation.

Tests both:
1. Negative case: Known POST_30 evidence defect (HowlFrame claim citing HowlWriter with nonexistent path).
2. Positive control: Valid HowlFrame claim citing HowlFrame repository with real paths.
3. Missing evidence handling.
"""

import subprocess
from pathlib import Path

import pytest

from howlwriter.facts.repository_evidence import _find_repo_root, validate_repository_claim_evidence


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def _make_repo(base: Path, name: str, files: dict[str, str]) -> tuple[Path, str]:
    """Create a synthetic git repo with one commit; returns (path, commit sha)."""
    repo = base / name
    repo.mkdir(parents=True)
    for rel, text in files.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "ci@example.com")
    _git(repo, "config", "user.name", "CI")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo, _git(repo, "rev-parse", "HEAD")


def _claim(url: str, location: str, project: str = "HowlFrame") -> dict:
    return {
        "claim_id": "C1",
        "exact_evaluated_claim": f"In our {project} project, the VM is implemented in Go.",
        "source_document": f"{project} VM notes",
        "source_url_or_revision": url,
        "exact_location": location,
        "current_status": "VERIFIED",
    }

def test_rejects_post_30_evidence_mismatch(tmp_path: Path):
    """Reproduces the defect in Season 3 baseline where POST_30 cited HowlWriter for HowlFrame."""
    defective_claim = {
        "claim_id": "POST_30-C1",
        "exact_evaluated_claim": "In our HowlFrame project, we took an alternative architectural path: a minimal, stack-based bytecode virtual machine implemented in Go.",
        "classification": "VERIFIED_IMPLEMENTATION",
        "source_document": "HowlFrame Virtual Machine Dispatch Implementation & Unit Test Suite",
        "source_url_or_revision": "https://github.com/howlcipher/howlwriter (git rev 7d27e33)",
        "exact_location": "src/howlwriter/integration/howlplane_bridge.py & howlframe/vm/vm.go",
        "verification_method": "Unit test execution of instruction budget exhaustion test cases confirming deterministic termination with ErrBudgetExceeded",
        "limitations": "Instruction budgets meter pure VM opcode dispatch cycles",
        "current_status": "VERIFIED"
    }

    repo, _ = _make_repo(tmp_path, "howlwriter", {"README.md": "x\n"})
    result = validate_repository_claim_evidence(defective_claim, repo_roots={"howlwriter": repo})
    assert result.is_valid is False
    assert result.status == "UNRESOLVED"
    finding_codes = [f.code for f in result.findings]
    assert "PROJECT_MISMATCH" in finding_codes
    assert "PATH_NOT_FOUND" in finding_codes


def test_accepts_valid_howlframe_evidence_control(tmp_path: Path):
    """Positive control: Correctly bound HowlFrame claim citing real repository and paths."""
    hf_dir, rev = _make_repo(
        tmp_path,
        "howlframe",
        {"internal/vm/vm.go": "package vm\n", "internal/vm/error.go": "package vm\n"},
    )
    repo_roots = {"howlframe": hf_dir}
    url_rev = f"https://github.com/howlcipher/howlframe (commit {rev})"

    valid_claim = {
        "claim_id": "POST_30-C1",
        "exact_evaluated_claim": "In our HowlFrame project, we took an alternative architectural path: a minimal, stack-based bytecode virtual machine implemented in Go.",
        "classification": "VERIFIED_IMPLEMENTATION",
        "source_document": "HowlFrame Virtual Machine Engine and Execution Limits",
        "source_url_or_revision": url_rev,
        "exact_location": "internal/vm/vm.go & internal/vm/error.go",
        "verification_method": "Inspection of DefaultLimits.MaxInstructions (100,000 opcodes) and opcode dispatch loop",
        "limitations": "Instruction budgets govern VM bytecode execution cycles only; host I/O and external capability execution require host timeouts",
        "current_status": "VERIFIED"
    }

    result = validate_repository_claim_evidence(valid_claim, repo_roots=repo_roots)
    assert result.is_valid is True
    assert result.status == "VERIFIED"
    assert len(result.findings) == 0
    assert "internal/vm/vm.go" in result.resolved_paths


def test_rejects_missing_source_evidence():
    """Missing evidence must not silently retain VERIFIED status."""
    empty_claim = {
        "claim_id": "C-EMPTY",
        "exact_evaluated_claim": "Some claim without backing source documentation.",
        "source_document": "",
        "source_url_or_revision": "",
        "exact_location": "",
        "current_status": "VERIFIED"
    }

    result = validate_repository_claim_evidence(empty_claim)
    assert result.is_valid is False
    assert result.status == "UNRESOLVED"
    assert any(f.code == "MISSING_EVIDENCE_SOURCE" for f in result.findings)


def test_repo_discovery_is_explicit_only(tmp_path: Path, monkeypatch):
    repo, _ = _make_repo(tmp_path / "dev", "howlframe", {"a.go": "x\n"})
    monkeypatch.delenv("HOWL_DEV_DIR", raising=False)
    # A checkout next to the working directory must not be found implicitly.
    monkeypatch.chdir(tmp_path / "dev")
    assert _find_repo_root("howlframe") is None
    assert _find_repo_root("howlframe", {"howlframe": repo}) == repo
    assert _find_repo_root("howlframe", {"howlframe": tmp_path / "missing"}) is None
    monkeypatch.setenv("HOWL_DEV_DIR", str(tmp_path / "dev"))
    assert _find_repo_root("howlframe") == repo
    assert _find_repo_root("howlwriter") is None
    # Explicit root wins over the environment.
    other, _ = _make_repo(tmp_path / "other", "howlframe", {"b.go": "x\n"})
    assert _find_repo_root("howlframe", {"howlframe": other}) == other


def test_unlocated_repository_cannot_be_verified(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HOWL_DEV_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    result = validate_repository_claim_evidence(
        _claim("https://github.com/howlcipher/howlframe/blob/main/x.go", "x.go")
    )
    assert result.is_valid is False
    assert result.status == "NEEDS_REVIEW"
    assert any(f.code == "REPOSITORY_NOT_LOCATED" for f in result.findings)


@pytest.mark.parametrize("location", ["../x.py", "/etc/hosts.allow", "internal/../../x.py"])
def test_paths_outside_the_repository_are_rejected(tmp_path: Path, location: str):
    repo, _ = _make_repo(tmp_path / "dev", "howlframe", {"a.go": "x\n"})
    (tmp_path / "dev" / "x.py").write_text("print()\n", encoding="utf-8")
    result = validate_repository_claim_evidence(
        _claim("https://github.com/howlcipher/howlframe", location), repo_roots={"howlframe": repo}
    )
    assert result.is_valid is False
    assert result.status == "UNRESOLVED"
    assert any(f.code == "PATH_OUTSIDE_REPOSITORY" for f in result.findings)
    assert result.resolved_paths == []


def test_symlink_escaping_the_repository_is_rejected(tmp_path: Path):
    repo, _ = _make_repo(tmp_path / "dev", "howlframe", {"a.go": "x\n"})
    outside = tmp_path / "outside.py"
    outside.write_text("x\n", encoding="utf-8")
    (repo / "link.py").symlink_to(outside)
    result = validate_repository_claim_evidence(
        _claim("https://github.com/howlcipher/howlframe", "link.py"), repo_roots={"howlframe": repo}
    )
    assert any(f.code == "PATH_OUTSIDE_REPOSITORY" for f in result.findings)


def test_file_added_after_cited_commit_is_not_present_at_revision(tmp_path: Path):
    repo, rev = _make_repo(tmp_path / "dev", "howlframe", {"old.go": "x\n"})
    (repo / "new.go").write_text("y\n", encoding="utf-8")  # in the working tree only
    _git(repo, "add", "new.go")
    _git(repo, "commit", "-q", "-m", "second")
    url = f"https://github.com/howlcipher/howlframe/blob/{rev}/old.go"

    ok = validate_repository_claim_evidence(_claim(url, "old.go"), repo_roots={"howlframe": repo})
    assert ok.is_valid is True and ok.resolved_paths == ["old.go"]

    late = validate_repository_claim_evidence(_claim(url, "new.go"), repo_roots={"howlframe": repo})
    assert late.is_valid is False
    assert any(f.code == "PATH_NOT_FOUND" for f in late.findings)

    # Without a cited commit, HEAD (and the working tree) is checked.
    head = validate_repository_claim_evidence(
        _claim("https://github.com/howlcipher/howlframe", "new.go"), repo_roots={"howlframe": repo}
    )
    assert head.is_valid is True


def test_untracked_working_tree_file_does_not_count_at_a_cited_commit(tmp_path: Path):
    repo, rev = _make_repo(tmp_path / "dev", "howlframe", {"old.go": "x\n"})
    (repo / "untracked.go").write_text("y\n", encoding="utf-8")
    result = validate_repository_claim_evidence(
        _claim(f"https://github.com/howlcipher/howlframe/commit/{rev}", "untracked.go"),
        repo_roots={"howlframe": repo},
    )
    assert any(f.code == "PATH_NOT_FOUND" for f in result.findings)


def test_hex_run_elsewhere_in_url_is_not_a_commit(tmp_path: Path):
    repo, _ = _make_repo(tmp_path / "dev", "howlframe", {"old.go": "x\n"})
    url = "https://github.com/howlcipher/howlframe?q=deadbeefcafe&ref=abcdef1234"
    result = validate_repository_claim_evidence(_claim(url, "old.go"), repo_roots={"howlframe": repo})
    assert result.is_valid is True  # treated as HEAD, no COMMIT_UNRESOLVED


def test_git_calls_have_a_timeout(tmp_path: Path, monkeypatch):
    from howlwriter.facts import repository_evidence as mod

    repo, _ = _make_repo(tmp_path / "dev", "howlframe", {"old.go": "x\n"})
    seen = []
    real_run = subprocess.run

    def spy(*a, **kw):
        seen.append(kw.get("timeout"))
        return real_run(*a, **kw)

    monkeypatch.setattr(mod.subprocess, "run", spy)
    validate_repository_claim_evidence(
        _claim("https://github.com/howlcipher/howlframe", "old.go"), repo_roots={"howlframe": repo}
    )
    assert seen and all(t == 30 for t in seen)

    def hang(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="git", timeout=30)

    monkeypatch.setattr(mod.subprocess, "run", hang)
    result = validate_repository_claim_evidence(
        _claim("https://github.com/howlcipher/howlframe", "nothere.go"), repo_roots={"howlframe": repo}
    )
    assert result.is_valid is False
