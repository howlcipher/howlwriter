from pathlib import Path

from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.humanize.detector import detect
from howlwriter.humanize.rewriter import ModelHumanizerRewriter
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD
from howlwriter.pipeline.howl import run_howl_pipeline
from src.control_plane.agent_execution import FakeAgentBackend

CORPUS_DIR = Path(__file__).parent.parent / "fixtures" / "dogfood_corpus"


def test_dogfood_corpus_contains_all_15_samples():
    files = list(CORPUS_DIR.glob("*.md"))
    assert len(files) == 15, f"Expected 15 dogfood files, found {len(files)}"


def test_generic_ai_buzzwords_detected_cleanly():
    doc_path = CORPUS_DIR / "01_generic_ai_buzzwords.md"
    doc = Document.parse(doc_path.read_text(encoding="utf-8"))
    config = default_config()

    findings = detect(doc, config)
    lint_matches = LintEngine().run(doc, config)

    # Should detect multiple AI style markers ("delve", "tapestry", "in conclusion", empty transitions)
    assert len(findings) >= 2
    assert any(f.rule_code == AI_STYLE_BANNED_WORD for f in findings)
    assert len(lint_matches) >= 2


def test_clean_human_prose_has_no_lint_findings():
    doc_path = CORPUS_DIR / "03_clean_human_prose.md"
    doc = Document.parse(doc_path.read_text(encoding="utf-8"))
    config = default_config()

    findings = detect(doc, config)
    lint_matches = LintEngine().run(doc, config)

    # High quality human writing should have zero findings
    assert len(findings) == 0
    assert len(lint_matches) == 0


def test_clean_human_prose_not_churned_by_humanizer():
    doc_path = CORPUS_DIR / "03_clean_human_prose.md"
    text = doc_path.read_text(encoding="utf-8")
    doc = Document.parse(text)

    # Humanizer returns untouched prose when no AI issues exist
    fake_backend = FakeAgentBackend(
        agent_id="mock_humanizer",
        default_stdout=f"""```yaml
resulting_text: |
{chr(10).join('  ' + line for line in text.splitlines())}
changes_made: []
rationale: "Text is already clean human writing; no edits required."
```""",
    )

    rewriter = ModelHumanizerRewriter()
    result = rewriter.rewrite(doc, default_config(), custom_backend=fake_backend)

    assert result.document.text.strip() == text.strip()
    assert (
        result.changes == []
        or all("no edits" in c.description.lower() for c in result.changes)
    )


def test_technical_terms_survive_humanization():
    doc_path = CORPUS_DIR / "04_technical_exact_terms.md"
    text = doc_path.read_text(encoding="utf-8")
    doc = Document.parse(text)

    fake_backend = FakeAgentBackend(
        agent_id="mock_humanizer",
        default_stdout="""```yaml
resulting_text: |
  # Linux Kernel Memory Management

  The Linux virtual memory subsystem uses `mmap` with `MAP_ANONYMOUS` to allocate private address space.
  High-performance event loops rely on `epoll_wait` with edge-triggered notifications (`EPOLLET`).
  Non-blocking I/O paths avoid kernel buffer copies using `O_DIRECT`
  and lockless ring buffers with `CAS` atomic loops.
changes_made:
  - "replaced 'utilizes' with 'uses'"
rationale: "Preserved all technical primitives."
```""",
    )

    rewriter = ModelHumanizerRewriter()
    result = rewriter.rewrite(doc, default_config(), custom_backend=fake_backend)

    # Verify exact technical terms survived
    for term in ["mmap", "MAP_ANONYMOUS", "epoll_wait", "EPOLLET", "O_DIRECT", "CAS"]:
        assert term in result.document.text


def test_numbers_percentages_dates_survive_pipeline():
    doc_path = CORPUS_DIR / "05_prose_with_numbers.md"

    fake_backend = FakeAgentBackend(
        agent_id="mock_humanizer",
        default_stdout="""```yaml
resulting_text: |
  # Infrastructure Migration Metrics

  During Q3, 12 engineers migrated 45 microservices to cloud clusters.
  The migration spanned 3 regional data centers and decommissioned 14 legacy server racks.
changes_made:
  - "tightened phrasing"
rationale: "Preserved all metrics."
```""",
    )

    res = run_howl_pipeline(doc_path, default_config(), custom_backend=fake_backend)

    for num in ["12", "45", "3", "14"]:
        assert num in res.final_document.text
    assert res.report.meaning_preservation == "PASS"
    assert res.report.status == "READY"


def test_code_and_quotes_preserved():
    doc_path = CORPUS_DIR / "15_code_and_quotes.md"
    text = doc_path.read_text(encoding="utf-8")

    fake_backend = FakeAgentBackend(
        agent_id="mock_humanizer",
        default_stdout=f"""```yaml
resulting_text: |
{chr(10).join('  ' + line for line in text.splitlines())}
changes_made: []
rationale: "Preserved code blocks and quote attribution."
```""",
    )

    res = run_howl_pipeline(doc_path, default_config(), custom_backend=fake_backend)

    assert "async def fetch_all" in res.final_document.text
    assert "Edsger W. Dijkstra" in res.final_document.text
