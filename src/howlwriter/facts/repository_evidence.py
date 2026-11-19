"""Deterministic validation of repository-backed implementation claims.

Verifies that repository-backed claims:
1. Reference the correct project and repository URL (preventing cross-project mismatch).
2. Point to resolvable git revisions or commits.
3. Reference source file paths that actually exist at the specified revision.
4. Prevent unverified or broken evidence references from silently receiving VERIFIED status.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KNOWN_PROJECTS = {
    "howlframe": ["howlframe", "howlcipher/howlframe"],
    "howlwriter": ["howlwriter", "howlcipher/howlwriter"],
    "howlproof": ["howlproof", "howlcipher/howlproof"],
    "howldream": ["howldream", "howlcipher/howldream"],
}


@dataclass
class EvidenceFinding:
    code: str
    message: str
    field: str
    severity: str = "ERROR"  # "ERROR", "WARNING"


@dataclass
class RepositoryEvidenceValidationResult:
    is_valid: bool
    status: str  # "VERIFIED", "UNRESOLVED", "CONTRADICTED", "NEEDS_REVIEW"
    findings: list[EvidenceFinding] = field(default_factory=list)
    resolved_paths: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "status": self.status,
            "findings": [{"code": f.code, "message": f.message, "field": f.field, "severity": f.severity} for f in self.findings],
            "resolved_paths": self.resolved_paths,
            "limitations": self.limitations,
        }


def _extract_project_name(text: str) -> str | None:
    lower = text.lower()
    for proj in KNOWN_PROJECTS:
        if proj in lower:
            return proj
    return None


_GIT_TIMEOUT_SECONDS = 30
_SHA = r"[0-9a-fA-F]{7,40}"
_COMMIT_URL_RE = re.compile(rf"/(?:commits?|blob|tree)/({_SHA})(?=[/?#\s)]|$)")
_COMMIT_NOTE_RE = re.compile(rf"\(\s*(?:git\s+)?(?:commit|rev(?:ision)?)\s+({_SHA})\s*\)", re.IGNORECASE)


def _find_repo_root(repo_name: str, candidate_roots: dict[str, Path] | None = None) -> Path | None:
    """Locate a repository from explicit configuration only.

    Order: ``candidate_roots[repo_name]``, then ``$HOWL_DEV_DIR/<repo_name>``. The result never
    depends on the working directory or on where the package is installed.
    """
    if candidate_roots and repo_name in candidate_roots:
        p = Path(candidate_roots[repo_name])
        if p.is_dir() and (p / ".git").exists():
            return p

    env_dev = os.environ.get("HOWL_DEV_DIR")
    if env_dev and env_dev.strip():
        candidate = Path(env_dev.strip()).expanduser() / repo_name
        if candidate.is_dir() and (candidate / ".git").exists():
            return candidate

    return None


def _extract_commit(source_url: str) -> str | None:
    """Take a commit only from a URL path segment or an explicit "(commit <sha>)" note."""
    match = _COMMIT_URL_RE.search(source_url) or _COMMIT_NOTE_RE.search(source_url)
    return match.group(1).lower() if match else None


def _path_is_inside(repo_path: Path, rel_file: str) -> bool:
    """True when rel_file is a relative path without '..' that resolves inside the repository."""
    if not rel_file or rel_file.startswith(("/", "\\")) or Path(rel_file).is_absolute():
        return False
    if ".." in Path(rel_file.replace("\\", "/")).parts:
        return False
    try:
        return (repo_path / rel_file).resolve().is_relative_to(repo_path.resolve())
    except (OSError, ValueError):
        return False


def _git_ok(repo_path: Path, *args: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo_path, capture_output=True, timeout=_GIT_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _extract_file_paths(location_str: str) -> list[str]:
    """Extract candidate relative file paths from an exact_location field."""
    # Split by common delimiters like &, comma, or semicolon
    raw_tokens = re.split(r"[,;&]|\sand\s", location_str)
    paths: list[str] = []
    for token in raw_tokens:
        clean = token.strip()
        # Look for tokens with slashes and file extensions
        match = re.search(r"[a-zA-Z0-9_\-\.\/]+\.[a-zA-Z0-9]+", clean)
        if match:
            candidate = match.group(0).strip()
            # Ignore markdown links or URLs
            if not candidate.startswith("http") and not candidate.startswith("www"):
                paths.append(candidate)
    return paths


def validate_repository_claim_evidence(
    claim_data: dict[str, Any],
    repo_roots: dict[str, Path] | None = None,
) -> RepositoryEvidenceValidationResult:
    """Validate a claim's evidence references against real repository contents."""
    findings: list[EvidenceFinding] = []
    limitations: list[str] = [
        "Deterministic check validates repository identity, commit resolution, and file existence only; "
        "it does not verify semantic entailment or arbitrary business logic correctness."
    ]

    claim_text = claim_data.get("exact_evaluated_claim") or claim_data.get("claim_text", "")
    source_doc = claim_data.get("source_document") or claim_data.get("source_reference", "")
    source_url = claim_data.get("source_url_or_revision", "")
    exact_loc = claim_data.get("exact_location", "")
    claimed_status = claim_data.get("current_status") or claim_data.get("verification_status", "UNRESOLVED")

    # 1. Check for required evidence fields
    if not source_doc or not source_url:
        findings.append(EvidenceFinding(
            code="MISSING_EVIDENCE_SOURCE",
            message="Claim lacks source_document or source_url_or_revision",
            field="source_document"
        ))
        return RepositoryEvidenceValidationResult(
            is_valid=False,
            status="UNRESOLVED",
            findings=findings,
            limitations=limitations,
        )

    # 2. Check for cross-project reference mismatches
    claimed_project = _extract_project_name(claim_text)
    cited_project_url = _extract_project_name(source_url)
    cited_project_doc = _extract_project_name(source_doc)

    if claimed_project:
        # If the claim is specifically about a known project (e.g. HowlFrame),
        # verify that the source URL does not cite an unrelated project (e.g. HowlWriter)
        if cited_project_url and cited_project_url != claimed_project:
            findings.append(EvidenceFinding(
                code="PROJECT_MISMATCH",
                message=f"Claim text asserts {claimed_project.title()} implementation, but source URL references {cited_project_url} repository",
                field="source_url_or_revision"
            ))

    # 3. Locate repository on disk if available
    target_project = cited_project_url or claimed_project or cited_project_doc
    repo_path = _find_repo_root(target_project, repo_roots) if target_project else None

    resolved_paths: list[str] = []
    if repo_path:
        # 4. Resolve revision/commit if present
        commit_found = _extract_commit(source_url)
        commit_ref = commit_found or "HEAD"

        if not _git_ok(repo_path, "cat-file", "-e", f"{commit_ref}^{{commit}}"):
            findings.append(EvidenceFinding(
                code="COMMIT_UNRESOLVED",
                message=f"Git commit '{commit_ref}' cannot be resolved in repository '{repo_path.name}'",
                field="source_url_or_revision"
            ))

        # 5. Verify referenced file paths exist in the repository
        referenced_files = _extract_file_paths(exact_loc)
        for rel_file in referenced_files:
            if not _path_is_inside(repo_path, rel_file):
                findings.append(EvidenceFinding(
                    code="PATH_OUTSIDE_REPOSITORY",
                    message=f"Referenced path '{rel_file}' is absolute, uses '..', or resolves outside "
                            f"repository '{repo_path.name}'",
                    field="exact_location"
                ))
                continue

            if commit_found:
                # A cited commit decides: the working tree must not stand in for it.
                file_exists = _git_ok(repo_path, "cat-file", "-e", f"{commit_ref}:{rel_file}")
            else:
                full_file = repo_path / rel_file
                file_exists = full_file.is_file() or _git_ok(
                    repo_path, "cat-file", "-e", f"{commit_ref}:{rel_file}"
                )

            if file_exists:
                resolved_paths.append(str(rel_file))
            else:
                findings.append(EvidenceFinding(
                    code="PATH_NOT_FOUND",
                    message=f"Referenced path '{rel_file}' does not exist in repository '{repo_path.name}' at revision '{commit_ref}'",
                    field="exact_location"
                ))
    elif target_project:
        findings.append(EvidenceFinding(
            code="REPOSITORY_NOT_LOCATED",
            message=f"Repository '{target_project}' was not found in repo_roots or HOWL_DEV_DIR; "
                    "commit and paths were not checked",
            field="source_url_or_revision",
            severity="WARNING",
        ))

    # Determine final status
    has_errors = any(f.severity == "ERROR" for f in findings)
    if has_errors:
        final_status = "UNRESOLVED"
        is_valid = False
    elif any(f.code == "REPOSITORY_NOT_LOCATED" for f in findings) and claimed_status == "VERIFIED":
        # Nothing was checked, so VERIFIED cannot stand.
        final_status = "NEEDS_REVIEW"
        is_valid = False
    else:
        final_status = claimed_status
        is_valid = (claimed_status == "VERIFIED")

    return RepositoryEvidenceValidationResult(
        is_valid=is_valid,
        status=final_status,
        findings=findings,
        resolved_paths=resolved_paths,
        limitations=limitations,
    )
