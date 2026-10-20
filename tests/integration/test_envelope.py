"""Recovering the draft from a writer reply whose YAML does not parse."""

from types import SimpleNamespace

from howlwriter.integration.envelope import salvage, writer_envelope

# What a small local model returned: only the heading is indented under the
# block scalar, so the YAML fails and the raw reply used to become the draft.
BROKEN = """```yaml
body_markdown: |
  # Why Backups Matter

Backups protect against loss when a disk fails.

Test a restore now and then.
claims_made:
  - claim: "Backups protect against loss."
    source_id: ""
word_count_estimate: 14
warnings: []
```"""


def test_salvage_recovers_the_body_and_the_keys_that_parse():
    recovered = salvage(BROKEN)
    body = recovered["body_markdown"]
    assert body.startswith("# Why Backups Matter\n\nBackups protect")
    assert body.endswith("Test a restore now and then.")
    for envelope_text in ("body_markdown", "claims_made", "```", "word_count_estimate"):
        assert envelope_text not in body
    assert recovered["claims_made"] == [{"claim": "Backups protect against loss.", "source_id": ""}]
    assert recovered["word_count_estimate"] == 14


def test_salvage_keeps_fences_inside_the_body():
    reply = "```yaml\nbody_markdown: |\n  # Setup\n\n```bash\nmake\n```\n\nDone.\nwarnings: []\n```"
    assert salvage(reply)["body_markdown"] == "# Setup\n\n```bash\nmake\n```\n\nDone."


def test_salvage_keeps_the_body_when_the_tail_is_broken():
    reply = "body_markdown: |\n  Text.\nclaims_made:\n  - claim: \"unterminated\n"
    assert salvage(reply) == {"body_markdown": "Text."}


def test_salvage_leaves_plain_prose_to_the_caller():
    assert salvage("Just a paragraph of prose.") == {}


def test_writer_envelope_prefers_parsed_output_then_salvage_then_raw():
    parsed = SimpleNamespace(structured_output={"body_markdown": "Parsed."}, raw_output=BROKEN)
    assert writer_envelope(parsed)["body_markdown"] == "Parsed."

    unparsed = SimpleNamespace(structured_output=None, raw_output=BROKEN)
    assert writer_envelope(unparsed)["body_markdown"].startswith("# Why Backups Matter")

    prose = SimpleNamespace(structured_output={}, raw_output="```\nPlain draft.\n```")
    assert writer_envelope(prose) == {"body_markdown": "Plain draft."}
