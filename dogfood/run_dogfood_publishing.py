"""Realistic dogfooding of the Artifact Publishing, Source Integrity & Output Management milestone."""

import json
from pathlib import Path
import subprocess
import sys

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import load_assignment_spec, validate_assignment_spec
from howlwriter.domain.source import Source, SourceAuthority, SourceType
from howlwriter.publishing.google.fake import FakeGoogleDocsAdapter
from howlwriter.publishing.google.publisher import GoogleDocsPublisher
from howlwriter.publishing.registry import register_publisher
from howlwriter.research.integrity import SourceIntegrityVerifier


def main() -> int:
    print("=================================================================")
    print("HowlWriter Milestone Dogfood: Publishing, Integrity & Outputs")
    print("=================================================================")

    spec_path = Path("dogfood/papers/cybersecurity_regulations.yaml")
    assert spec_path.is_file(), f"Dogfood spec missing: {spec_path}"

    # 1. Spec validation
    print("\n1. Validating Assignment Specification...")
    spec = load_assignment_spec(spec_path)
    errors = validate_assignment_spec(spec)
    if errors:
        print(f"Validation errors: {errors}", file=sys.stderr)
        return 1
    print(f"✓ Spec '{spec.title}' valid.")
    print(f"  Target words: {spec.target_words} | Citation style: {spec.citation_style.upper()}")
    print(f"  Sections defined: {len(spec.sections)}")
    for sec in spec.sections:
        print(f"    - [{sec.id}] {sec.title} ({sec.target_words or 'N/A'} words)")

    # 2. Curate authoritative primary and regulatory sources
    print("\n2. Curating High-Authority Sources (Primary Law, Standard, Government)...")
    sources = [
        Source(
            id="S001",
            title="Regulation (EU) 2016/679 (General Data Protection Regulation)",
            authors=["European Parliament and Council of the European Union"],
            url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
            source_type=SourceType.WEBSITE,
            authority=SourceAuthority.PRIMARY_LAW,
            retrieved_text=(
                "Chapter V (Articles 44-49) governs transfers of personal data to third countries or international "
                "organisations. Transfers shall take place only if conditions laid down in Chapter V are complied with by the controller."
            ),
        ),
        Source(
            id="S002",
            title="The NIST Cybersecurity Framework 2.0 (CSF 2.0)",
            authors=["National Institute of Standards and Technology"],
            url="https://csrc.nist.gov/publications/detail/sp/800-53/rev-5/final",
            source_type=SourceType.REPORT,
            authority=SourceAuthority.STANDARD,
            retrieved_text=(
                "The Govern (GV) Function establishes and monitors the organization's cybersecurity risk management strategy, "
                "expectations, and policy. Subcategory GV.OC-01 mandates understanding the organizational context and compliance requirements."
            ),
        ),
        Source(
            id="S003",
            title="Binding Operational Directive 22-01: Reducing the Significant Risk of Known Exploited Vulnerabilities",
            authors=["Cybersecurity and Infrastructure Security Agency"],
            url="https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-341a",
            source_type=SourceType.REPORT,
            authority=SourceAuthority.GOVERNMENT,
            retrieved_text=(
                "BOD 22-01 requires federal civilian executive branch agencies to remediate vulnerabilities in CISA's Known Exploited "
                "Vulnerabilities (KEV) catalog within prescribed timelines (typically 14 to 21 days)."
            ),
        ),
        Source(
            id="S004",
            title="Schrems II and the Future of Transatlantic Data Transfers",
            authors=["Kuner, C."],
            doi="10.1093/idpl/ipaa018",
            source_type=SourceType.JOURNAL_ARTICLE,
            authority=SourceAuthority.SCHOLARLY,
            retrieved_text=(
                "The Court of Justice of the European Union (CJEU) ruling in Schrems II invalidated the EU-US Privacy Shield "
                "while upholding Standard Contractual Clauses (SCCs) subject to rigorous supplementary risk assessments."
            ),
        ),
    ]
    for s in sources:
        print(f"  - [{s.id}] ({s.authority.value}) {s.title}")

    # 3. Source & Citation Integrity Verification
    print("\n3. Verifying Source Operational Integrity & SSRF Protection...")
    verifier = SourceIntegrityVerifier(timeout_seconds=5.0)
    integrity_report = verifier.verify_all(sources)
    print(f"✓ Source Integrity Status: {integrity_report.status}")
    for f in integrity_report.findings:
        print(f"    [{f.source_id}] {f.source_title[:45]}... -> {f.access_status} (Severity: {f.severity})")

    # 4. Run Academic Pipeline and Generate Multi-Format Deliverables
    print("\n4. Running Academic Pipeline and Generating Deliverables (MD, DOCX, PDF)...")
    fake_adapter = FakeGoogleDocsAdapter()
    google_pub = GoogleDocsPublisher(adapter=fake_adapter)
    register_publisher("google_docs", google_pub)

    result = run_academic_pipeline(
        assignment=spec,
        existing_sources=sources,
        deterministic_only=True,
        verify_sources=True,
        output_formats=["md", "docx", "pdf"],
        output_dir="output",
        overwrite=True,
        publish="google_docs",
        publish_title="Cybersecurity Regulations and Governance Frameworks",
        allow_unverified=True,
    )

    print(f"✓ Pipeline run completed with status: {result.report.status}")
    print(f"  Body words generated: {result.report.actual_body_words} (Target: {result.report.target_words})")
    print(f"  Word count status:    {result.report.word_count_status}")
    print(f"  Citations in-text:    {result.report.in_text_citations}")
    print(f"  References rendered:  {result.report.reference_entries}")

    # 5. Inspect Local Deliverables & Manifest
    print("\n5. Inspecting Local Deliverables in output/...")
    assert len(result.local_deliverables) == 3, f"Expected 3 deliverables, got {len(result.local_deliverables)}"
    for d in result.local_deliverables:
        p = Path(d.path)
        assert p.is_file(), f"Deliverable file not found: {p}"
        assert p.stat().st_size > 0, f"File is empty: {p}"
        print(f"  - [{d.format.upper()}] {p.name} ({d.size_bytes:,} bytes, sha256: {d.sha256[:12]}...)")

    manifest_p = Path("output/publication-manifest.json")
    assert manifest_p.is_file(), "publication-manifest.json was not created"
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))
    print(f"✓ Publication manifest verified. Linked to Run ID: {manifest_data.get('run_id')}")

    # 6. Inspect Cloud Publication
    print("\n6. Inspecting Cloud Publication Result...")
    assert result.publish_result is not None, "Publication result is None"
    pub_res = result.publish_result
    assert pub_res.is_success, f"Publication failed: {pub_res.diagnostics}"
    print(f"✓ Destination: {pub_res.destination_type}")
    print(f"✓ Document ID: {pub_res.artifact_id}")
    print(f"✓ URL:         {pub_res.url}")
    print(f"✓ Published:   {pub_res.published_at}")

    # 7. Check Git Hygiene
    print("\n7. Verifying Git Hygiene & .gitignore conformance...")
    git_status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False)
    # Ensure generated files in output/ are NOT listed as untracked
    untracked_outputs = [line for line in git_status.stdout.splitlines() if line.strip().startswith("?? output/") and not line.endswith(".gitkeep")]
    assert untracked_outputs == [], f"Generated files in output/ are not ignored: {untracked_outputs}"
    print("✓ output/* files are properly ignored. output/.gitkeep tracked clean.")

    print("\n=================================================================")
    print("DOGFOOD WORKFLOW COMPLETED SUCCESSFULLY")
    print("=================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
