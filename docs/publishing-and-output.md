# Artifact Publishing, Multi-Format Rendering & Output Management

HowlWriter extends from an editorial and verification pipeline into a complete writing production system capable of taking a verified artifact from specification to polished local deliverables and publishing to explicitly requested destinations.

---

## 1. Core Principles

1. **Destination-Neutral Publishing:** The publishing architecture separates the rendered document from destination-specific APIs via a typed `ArtifactPublisher` protocol.
2. **Human Authority Boundary:** HowlWriter does not publish unverified or failed drafts without explicit human intent. Publishing requires a verification status of `READY` or `PASS`, unless overridden by the user.
3. **Deterministic Output & Collision Safety:** Finished files default to the standard `output/` directory, which is gitignored to avoid repository bloat while preserving an empty `output/.gitkeep`. Existing deliverables are never overwritten silently.
4. **Hermetic Testing & Zero Credential Leakage:** Google Docs and cloud adapters operate using narrowly scoped OAuth2 credentials stored in `~/.howlwriter/credentials/` with strict `0600` filesystem permissions. Tests use a hermetic in-memory test double (`FakeGoogleDocsAdapter`, kept in `tests/fakes/`, not in the installed package).

---

## 2. Artifact Publishing Architecture

### The Publisher Protocol

```python
class ArtifactPublisher(Protocol):
    """Protocol for destination-neutral artifact publishing."""

    @property
    def destination_type(self) -> PublishDestination:
        """The destination type handled by this publisher."""
        ...

    def publish(
        self,
        artifact: PublicationArtifact,
        context: PublishContext,
    ) -> PublishResult:
        """Publish the artifact to the destination."""
        ...
```

### Destination Registry

Publishers register in `PublisherRegistry` (`howlwriter.publishing.registry`):

```python
from howlwriter.publishing import get_publisher, PublishDestination

publisher = get_publisher(PublishDestination.GOOGLE_DOCS)
result = publisher.publish(artifact, context)
```

### Human Authority Gate

Every publishing operation validates the verification status of the artifact. If the verification report has warnings, failures, or is `UNVERIFIED`, publication is blocked:

```
Refusing to publish unverified artifact: Verification status is BLOCKED.
Provide explicit authorization via --allow-unverified to proceed.
```

---

## 3. Google Docs Publishing

### Scopes & Authorization

HowlWriter adheres to the principle of least privilege. It never requests broad account access:
- `https://www.googleapis.com/auth/documents`: Create and edit documents.
- `https://www.googleapis.com/auth/drive.file`: Access only files created or opened by HowlWriter.

### Local Credential Storage

- Tokens are stored locally at: `~/.howlwriter/credentials/google_token.json`
- Directory permissions: `0700` (`rwx------`)
- Token file permissions: `0600` (`rw-------`)
- Tokens and client secrets are gitignored and never committed.

### CLI Authentication Management

```bash
# Check current authentication status
howlwriter google status

# Launch browser OAuth2 consent flow
howlwriter google auth

# Revoke credentials and remove local token
howlwriter google logout
```

### Folder Targeting & Update Modes

HowlWriter supports organizing documents into specific cloud folders and updating existing files:

```bash
# Create a new document in a specific folder
howlwriter publish draft.md --destination google_docs --title "Cybersecurity Report" --folder <folder-id>

# Replace an existing document's content. WARNING: this deletes the whole body
# (tables, images, headings, formatting) and inserts plain text. It is only
# safe for documents that are plain text. See "Existing documents" below.
howlwriter publish draft.md --destination google_docs --update-doc <doc-id> --update-mode replace

# Append to an existing document
howlwriter publish draft.md --destination google_docs --update-doc <doc-id> --update-mode append
```

#### Existing documents: what `--update-doc` does and does not do

`--update-mode replace` issues one `batchUpdate` containing a `deleteContentRange`
over the entire body followed by a plain-text `insertText`. `--update-mode append`
inserts one plain-text block with a dated separator at the end of the document.
Neither mode reads or preserves structure: **replace will destroy tables, images,
heading/paragraph styles, lists and page structure**, and Markdown is inserted as
literal text rather than being converted to Google Docs formatting. Do not use
`replace` on a rich document.

Structure-preserving revision of an existing document is not implemented. A safe
design needs, at minimum: reading the document structure, targeting a named range
or bookmark rather than the whole body, applying paragraph/text styles through
`updateParagraphStyle`/`updateTextStyle` requests, showing a dry-run diff, and a
human approval gate. That is tracked as a follow-up milestone in `ROADMAP.md`.

---

## 4. Local Output Management

### Output Directory Structure

- Production outputs are written to `output/` relative to the project root.
- The directory is tracked via `output/.gitkeep`.
- `.gitignore` ignores all generated files:
  ```gitignore
  output/*
  !output/.gitkeep
  ```

### Safe Naming & Path Sanitization

Filenames are sanitized via `safe_filename()` in `howlwriter.output.naming`:
- Converts titles to lowercase kebab-case.
- Rejects directory traversal sequences (`..`) and path separators (`/`, `\`) with `PathTraversalError`.
- Prohibits reserved Windows filenames (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`).

### Collision Safety

If a file already exists at the target path:
```bash
# By default, collisions raise an error:
OutputCollisionError: File already exists: output/research-paper.docx. Use --overwrite to replace.

# To overwrite safely:
howlwriter paper assignment.yaml --format docx --overwrite
```

### Publication Manifest

Every run that writes deliverables creates or updates `output/publication-manifest.json`:

```json
{
  "run_id": "hw-20260911-200453-f80ebc",
  "generated_at": "2026-09-11T20:04:56.023944+00:00",
  "deliverables": [
    {
      "format": "md",
      "path": "output/cybersecurity-regulations.md",
      "sha256": "0d0917e59a01...",
      "byte_size": 1020
    },
    {
      "format": "docx",
      "path": "output/cybersecurity-regulations.docx",
      "sha256": "80e179d920ad...",
      "byte_size": 37148
    },
    {
      "format": "pdf",
      "path": "output/cybersecurity-regulations.pdf",
      "sha256": "501189e5fb19...",
      "byte_size": 25401
    }
  ]
}
```

---

## 5. Multi-Format Renderers

### Markdown Renderer (`rendering/markdown.py`)
- Standard GitHub Flavored Markdown.
- Optional YAML frontmatter containing metadata: title, authors, date, citation style, word count, and run ID.

### APA 7 DOCX Renderer (`rendering/docx.py`)
Generates native Word documents meeting APA 7 student/professional guidelines:
- 1-inch margins on all sides.
- Times New Roman 12pt typography.
- APA 7 Headings (Level 1: Centered Bold; Level 2: Flush Left Bold; Level 3: Flush Left Bold Italic).
- References section formatted with strict **0.5-inch hanging indents**.
- Native tables with standard APA 3-border format (top border, column header bottom border, table bottom border; zero vertical borders).
- Embedded clickable hyperlinks.

### PDF Renderer (`rendering/pdf.py`)
- Primary engine: **Playwright headless Chromium** with CSS Paged Media (`@page`) rules, page numbering, running heads, and clean typography.
- Fallback engine: **ReportLab** for environments where Chromium is unavailable.

### Combined Document Assembly (`rendering/combined.py`)
For multi-part assignments (such as Discussion Posts with Peer Responses):
- Aggregates individual sections into a unified document structure (`CombinedDocument`).
- Embeds individual section word counts.
- Consolidates and deduplicates citations into a single shared References page at the end of the document.

---

## 6. CLI Usage Summary

```bash
# Generate all three formats from an assignment spec
howlwriter paper assignment.yaml --format md,docx,pdf --output-dir output/

# Generate deliverables and publish to Google Docs in one step
howlwriter paper assignment.yaml --format docx --publish google_docs

# Manually publish an existing draft or deliverable
howlwriter publish output/final_draft.md --destination google_docs --title "Final Paper"

# Publish with unverified override when intentionally bypassing gates
howlwriter publish draft.md --destination google_docs --allow-unverified
```
