from src.control_plane.role_binding import extract_structured_output


def test_extracts_from_fenced_yaml_with_commentary_before_and_after():
    raw = """Here is my humanization analysis and rewrite:

```yaml
resulting_text: "Clean, natural prose without fluff."
changes_made:
  - "eliminated empty phrase"
rationale: "Better cadence."
```

I hope this helps your document! Let me know if you need further adjustments."""

    parsed = extract_structured_output(raw)
    assert parsed is not None
    assert parsed["resulting_text"] == "Clean, natural prose without fluff."
    assert len(parsed["changes_made"]) == 1


def test_extracts_from_codex_transcript_envelope():
    raw = """OpenAI Codex v0.150.1
--------
workdir: /workspace
model: gpt-5.6
approval: never
sandbox: read-only
--------
user
Rewrite this prompt.
codex
```yaml
resulting_text: "Target humanized text."
changes_made: []
rationale: "Already clean."
```
tokens used
4,521"""

    parsed = extract_structured_output(raw)
    assert parsed is not None
    assert parsed["resulting_text"] == "Target humanized text."


def test_extracts_json_with_nested_objects_and_arrays():
    raw = """{"verdict": "PASS", "differences": [{"kind": "none", "severity": "info"}], "score": 1.0}"""

    parsed = extract_structured_output(raw)
    assert parsed is not None
    assert parsed["verdict"] == "PASS"
    assert len(parsed["differences"]) == 1


def test_rejects_unstructured_prose_containing_random_braces():
    raw = "In C programming, functions look like void main() { printf(\"hello\"); } but this is not JSON."

    parsed = extract_structured_output(raw)
    # Invalid JSON inside braces must return None, not throw exception or garbage
    assert parsed is None


def test_rejects_empty_or_whitespace_only_outputs():
    assert extract_structured_output("") is None
    assert extract_structured_output("   \n\t  ") is None
