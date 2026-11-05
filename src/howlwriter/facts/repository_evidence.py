"""Deterministic validation of repository-backed implementation claims.

Verifies that repository-backed claims:
1. Reference the correct project and repository URL (preventing cross-project mismatch).
2. Point to resolvable git revisions or commits.
3. Reference source file paths that actually exist at the specified revision.
4. Prevent unverified or broken evidence references from silently receiving VERIFIED status.
"""

from __future__ import annotations

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


def _find_repo_root(repo_name: str, candidate_roots: dict[str, Path] | None = None) -> Path | None:
    if candidate_roots and repo_name in candidate_roots:
        p = Path(candidate_roots[repo_name])
        if p.exists() and (p / ".git").exists():
            return p

    # Dynamic environment variable override
    import os

    env_dev = os.environ.get("HOWL_DEV_DIR")
    search_dirs: list[Path] = [Path.cwd(), Path.cwd().parent]
    if env_dev:
        search_dirs.append(Path(env_dev))

    # Search ancestor directories and their siblings portably
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        search_dirs.append(ancestor)
        sibling = ancestor / repo_name
        if sibling.exists() and (sibling / ".git").exists():
            return sibling

    for base in search_dirs:
        candidate = base / repo_name
        if candidate.exists() and (candidate / ".git").exists():
            return candidate
        if base.name == repo_name and (base / ".git").exists():
            return base

    return None


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
        # Check for hex commit hash in source_url or text
        commit_match = re.search(r"\b([a-f0-9]{7,40})\b", source_url)
        commit_ref = commit_match.group(1) if commit_match else "HEAD"

        try:
            # Check commit resolution
            subprocess.run(
                ["git", "cat-file", "-e", f"{commit_ref}^{{commit}}"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            findings.append(EvidenceFinding(
                code="COMMIT_UNRESOLVED",
                message=f"Git commit '{commit_ref}' cannot be resolved in repository '{repo_path.name}'",
                field="source_url_or_revision"
            ))

        # 5. Verify referenced file paths exist in the repository
        referenced_files = _extract_file_paths(exact_loc)
        for rel_file in referenced_files:
            # Check if file exists in working tree or at commit
            full_file = repo_path / rel_file
            file_exists = False
            if full_file.exists() and full_file.is_file():
                file_exists = True
            else:
                # Try git cat-file at the commit
                try:
                    p = subprocess.run(
                        ["git", "cat-file", "-e", f"{commit_ref}:{rel_file}"],
                        cwd=repo_path,
                        capture_output=True
                    )
                    if p.returncode == 0:
                        file_exists = True
                except Exception:
                    pass

            if file_exists:
                resolved_paths.append(str(rel_file))
            else:
                findings.append(EvidenceFinding(
                    code="PATH_NOT_FOUND",
                    message=f"Referenced path '{rel_file}' does not exist in repository '{repo_path.name}' at revision '{commit_ref}'",
                    field="exact_location"
                ))

    # Determine final status
    has_errors = any(f.severity == "ERROR" for f in findings)
    if has_errors:
        final_status = "UNRESOLVED"
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
