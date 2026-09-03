# Native Exporter Architecture & Implementation Plan

## Overview
This document outlines the planned design for native academic document export (DOCX, PDF, and LaTeX) in HowlWriter. Following the Academic Semantic Grounding and Provenance Truthfulness Remediation milestone, heavy binary/layout dependencies are deferred to avoid dependency bloat and maintain isolated determinism during ongoing audits.

## Target Export Formats
1. **Academic DOCX (APA 7th Edition)**
   - Strict 1-inch margins, 12pt Times New Roman / 11pt Calibri.
   - Running head, page numbers, title page layout.
   - Hanging indents (0.5 in) for References section.
   - Native tables with standard APA 7 horizontal borders (top, header bottom, table bottom; no vertical lines).
2. **Academic PDF**
   - Headless Chromium or lightweight typst/weasyprint engine.
   - Deterministic typography, page breaks, and embedded fonts.
3. **LaTeX / BibTeX**
   - Clean, standard LaTeX document class (`article` or `apa7`).
   - Separate `.bib` file populated directly from `sources.json`.

## Architecture & Interfaces

```text
Document + Sources + Provenance
           │
           ▼
   [Exporter Protocol]
     ├── DocxExporter (python-docx / docx-template)
     ├── PdfExporter (Typst CLI or Weasyprint)
     └── LatexExporter (pure Python template)
           │
           ▼
    Exported Artifacts
     ├── paper.docx
     ├── paper.pdf
     └── paper.tex + references.bib
```

### Proposed Interface
```python
class DocumentExporter(Protocol):
    def export(
        self,
        document: Document,
        sources: list[Source],
        provenance: GenerationProvenance,
        output_path: Path,
        *,
        style: str = "apa7",
    ) -> Path: ...
```

## Sidecar Integration
When an export format is generated, the provenance manifest and sidecars are bundled alongside or embedded:
- In DOCX: Custom document properties include `RunId`, `ProvenanceSHA256`, `GitRevision`.
- Beside files: `.provenance.json` and `.manifest.txt` remain identical and accompany the binary export.

## Dependencies Evaluation
- **DOCX**: `python-docx` (lightweight, pure Python + lxml).
- **PDF**: Prefer `typst` CLI wrapper (zero heavy Python C-extensions, fast compilation) over large Qt/wkhtmltopdf toolchains.
- **LaTeX**: Zero extra dependencies (templated string generation).

## Rollout Phases
1. **Phase 1 (Post-Audit)**: Implement `LatexExporter` using standard library only.
2. **Phase 2**: Add optional dependency extra `howlwriter[docx]` introducing `python-docx` for native APA 7 Word files.
3. **Phase 3**: Integrate PDF rendering via Typst backend.
