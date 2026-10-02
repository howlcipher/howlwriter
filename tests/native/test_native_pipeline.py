"""Native Writer path: Dream export -> request -> bounded provider -> copy package."""

import json
from pathlib import Path

import pytest

from howlwriter.cli.main import main
from howlwriter.native.contracts import ContractError, WriterRequest
from howlwriter.native.engine import WriterExecutionError, amend, command_provider, write_copy
from howlwriter.native.intake import dream_role, request_from_dream, request_from_operator

SCHEMAS = Path(__file__).parents[2] / "src" / "howlwriter" / "schemas"


def _request(dream_candidate, copy_spec):
    return request_from_dream(dream_candidate, copy_spec)


def _write(dream_candidate, copy_spec, command_config, mode):
    provider = command_provider(str(command_config(mode)))
    return write_copy(_request(dream_candidate, copy_spec), provider)


def test_dream_export_becomes_request_without_adapter(dream_candidate, copy_spec):
    request = _request(dream_candidate, copy_spec)
    assert request.source_idea_id == dream_candidate["candidate_id"]
    assert request.source_run_id == dream_candidate["source_run_id"]
    assert request.source_component == "howldream"
    assert request.source_component_role == "GENERATED"
    assert "Do not claim production adoption." in request.factual_constraints
    assert "resume.json#ach-cicd" in request.canonical_evidence_refs
    assert request.request_id.startswith("wreq-")
    # The id is content-derived, so the round trip is stable.
    assert WriterRequest.from_dict(request.to_dict()).request_id == request.request_id


def test_dream_role_never_inflates_to_generated(dream_candidate):
    dream_candidate["provenance"]["execution"] = {"inference_occurred": False}
    assert dream_role(dream_candidate) == "SELECTED"
    dream_candidate["provenance"]["participation"] = [{"operation": "CLUSTERED"}]
    assert dream_role(dream_candidate) == "CLUSTERED"


@pytest.mark.parametrize("mutate,message", [
    (lambda c: c["provenance"].update(producer_component="howlcreate"), "producer_component"),
    (lambda c: c.update(status="REJECTED"), "REJECTED"),
    (lambda c: c.update(authority={"type": "ADVISORY", "executable": True}), "non-executable"),
])
def test_dream_intake_rejects_untrusted_candidates(dream_candidate, copy_spec, mutate, message):
    mutate(dream_candidate)
    with pytest.raises(ContractError, match=message):
        _request(dream_candidate, copy_spec)


def test_request_bounds_are_enforced(copy_spec):
    copy_spec["items"] = copy_spec["items"] * 21
    with pytest.raises(ContractError):
        request_from_operator({**copy_spec, "source_idea_id": "x", "source_run_id": "y", "title": "t"})


def test_tampered_request_id_is_rejected(dream_candidate, copy_spec):
    value = _request(dream_candidate, copy_spec).to_dict()
    value["audience"] = "someone else"
    with pytest.raises(ContractError, match="request_id"):
        WriterRequest.from_dict(value)


def test_bounded_provider_produces_structured_package(dream_candidate, copy_spec, command_config):
    request = _request(dream_candidate, copy_spec)
    package = write_copy(request, command_provider(str(command_config("echo")))).to_dict()
    assert package["schema_version"] == "howlwriter.copy_package/v1"
    assert package["writer_proposal_id"].startswith("wp-")
    assert package["lineage"] == {
        "source_component": "howldream",
        "source_idea_id": dream_candidate["candidate_id"],
        "source_run_id": dream_candidate["source_run_id"],
        "writer_request_id": request.request_id,
        "writer_proposal_id": package["writer_proposal_id"],
    }
    assert package["factual_status"] == "FACTUALLY_PRESERVED"
    assert [p["origin"] for p in package["proposals"]] == ["MODEL", "MODEL"]
    assert package["proposals"][0]["evidence_refs"] == ["resume.json#ach-cicd"]
    execution = package["execution"]
    assert execution["actual_provider"] == "claude"
    assert execution["model"] == "claude-fake-model"
    assert execution["usage"] == {"input_tokens": 120, "output_tokens": 45}
    assert execution["cost"] == pytest.approx(0.0123)
    assert execution["remote"] is True
    assert execution["agent_backend_used"] is False
    assert package["contribution"] == {
        "component": "howlwriter", "operation": "TRANSFORMED_COPY", "inference_occurred": True,
        "proposals_from_model": 2, "proposals_unchanged": 0,
    }


def test_package_matches_published_schema(dream_candidate, copy_spec, command_config):
    jsonschema = pytest.importorskip("jsonschema")
    request = _request(dream_candidate, copy_spec)
    package = write_copy(request, command_provider(str(command_config("echo")))).to_dict()
    package_schema = json.loads((SCHEMAS / "howlwriter.copy_package.v1.schema.json").read_text())
    request_schema = json.loads((SCHEMAS / "howlwriter.request.v1.schema.json").read_text())
    jsonschema.validate(package, package_schema)
    jsonschema.validate(request.to_dict(), request_schema)


def test_unit_drift_from_provider_is_flagged(dream_candidate, copy_spec, command_config):
    package = _write(dream_candidate, copy_spec, command_config, "drift")
    statuses = {p.item_id: p.factual_status for p in package.proposals}
    assert statuses["verification"] == "FACTUAL_UNIT_DRIFT"
    assert statuses["scope"] == "FACTUAL_UNIT_DRIFT"
    assert package.factual_status == "FACTUAL_UNIT_DRIFT"


def test_scope_upgrade_from_provider_is_conflict(dream_candidate, copy_spec, command_config):
    package = _write(dream_candidate, copy_spec, command_config, "upgrade")
    assert package.proposals[0].factual_status == "FACTUAL_CONFLICT"


def test_missing_proposal_keeps_current_copy_and_says_so(dream_candidate, copy_spec, command_config):
    package = _write(dream_candidate, copy_spec, command_config, "skip")
    first = package.proposals[0]
    assert first.origin == "UNCHANGED"
    assert first.proposed_text == first.current_text
    assert package.contribution["proposals_unchanged"] == 1


def test_provider_failure_is_structured_and_sanitized(dream_candidate, copy_spec, command_config):
    with pytest.raises(WriterExecutionError) as caught:
        _write(dream_candidate, copy_spec, command_config, "fail")
    assert caught.value.failure["category"] == "RATE_LIMIT"
    assert caught.value.failure["retryable"] is True
    assert caught.value.execution["parse_status"] == "FAILED"


def test_malformed_reply_is_repairable_failure(dream_candidate, copy_spec, command_config):
    with pytest.raises(WriterExecutionError) as caught:
        _write(dream_candidate, copy_spec, command_config, "garbage")
    assert caught.value.failure["category"] == "MALFORMED_RESPONSE"
    assert caught.value.execution["model"] == "claude-fake-model"


@pytest.mark.parametrize("argv", [["ollama", "run", "x"], ["claude", "--local"], ["bash", "-c", "x"]])
def test_local_inference_and_shell_commands_are_denied(tmp_path, argv):
    from howl_provider_core import ProviderError

    config = tmp_path / "local.json"
    config.write_text(json.dumps({"argv": argv, "remote": True}))
    with pytest.raises(ProviderError):
        command_provider(str(config))


def test_non_remote_command_is_denied(tmp_path):
    from howl_provider_core import ProviderError

    config = tmp_path / "local.json"
    config.write_text(json.dumps({"argv": ["claude"], "remote": False}))
    with pytest.raises(ProviderError, match="remote"):
        command_provider(str(config))


def test_child_process_inherits_local_inference_prohibition(
    dream_candidate, copy_spec, tmp_path, monkeypatch
):
    import sys
    monkeypatch.delenv("HOWL_FORBID_LOCAL_INFERENCE", raising=False)
    script = tmp_path / "env_probe.py"
    script.write_text(
        "import json, os, sys\nsys.stdin.read()\n"
        "flag = os.environ.get('HOWL_FORBID_LOCAL_INFERENCE')\n"
        "print(json.dumps({'text': json.dumps({'proposals': [{'item_id': 'scope', "
        "'proposed_text': '56 Azure DevOps build/release definitions across 28 standardized repositories.', "
        "'uncertainty': 'flag=' + str(flag)}]})}))\n"
    )
    config = tmp_path / "probe.json"
    config.write_text(json.dumps({"argv": [sys.executable, str(script)], "remote": True,
                                  "output_format": "generic-json"}))
    package = write_copy(_request(dream_candidate, copy_spec), command_provider(str(config)))
    scope = next(p for p in package.proposals if p.item_id == "scope")
    assert scope.uncertainty == "flag=1"


def test_amend_records_operator_edit_without_crediting_writer(dream_candidate, copy_spec, command_config):
    request = _request(dream_candidate, copy_spec)
    package = write_copy(request, command_provider(str(command_config("drift")))).to_dict()
    amended = amend(package, request, "verification",
                    "Dry-run validated representative deployment paths for 25 of 28 repositories.",
                    reason="restore canonical unit")
    proposal = amended["proposals"][0]
    assert proposal["origin"] == "OPERATOR_EDITED"
    assert "deployment paths" in proposal["model_text"]
    assert proposal["amendments"][0]["previous_status"] == "FACTUAL_UNIT_DRIFT"
    assert proposal["factual_status"] == "FACTUALLY_PRESERVED"
    assert amended["contribution"]["proposals_operator_edited"] == 1


def test_cli_end_to_end(tmp_path, dream_candidate, copy_spec, command_config):
    candidate, spec = tmp_path / "candidate.json", tmp_path / "spec.json"
    candidate.write_text(json.dumps(dream_candidate))
    spec.write_text(json.dumps(copy_spec))
    req, pkg = tmp_path / "request.json", tmp_path / "package.json"
    assert main(["native", "request", "--from-dream", str(candidate), "--spec", str(spec),
                 "--out", str(req)]) == 0
    assert main(["native", "write", "--request", str(req), "--command-config",
                 str(command_config("echo")), "--out", str(pkg)]) == 0
    package = json.loads(pkg.read_text())
    assert package["source_idea_id"] == dream_candidate["candidate_id"]
    assert package["request_id"] == json.loads(req.read_text())["request_id"]


def test_cli_provider_failure_writes_failure_record(tmp_path, dream_candidate, copy_spec, command_config):
    candidate, spec = tmp_path / "candidate.json", tmp_path / "spec.json"
    candidate.write_text(json.dumps(dream_candidate))
    spec.write_text(json.dumps(copy_spec))
    req, failure = tmp_path / "request.json", tmp_path / "failure.json"
    main(["native", "request", "--from-dream", str(candidate), "--spec", str(spec), "--out", str(req)])
    code = main(["native", "write", "--request", str(req), "--command-config",
                 str(command_config("fail")), "--out", str(tmp_path / "p.json"),
                 "--failure-out", str(failure)])
    assert code == 3
    record = json.loads(failure.read_text())
    assert record["status"] == "FAILED"
    assert record["failure"]["category"] == "RATE_LIMIT"
    assert not (tmp_path / "p.json").exists()


def test_cli_check_exit_codes(tmp_path):
    source, proposal = tmp_path / "s.txt", tmp_path / "p.txt"
    source.write_text("Validated 25 of 28 repositories.")
    proposal.write_text("Validated 25 of 28 repositories.")
    assert main(["native", "check", "--source", str(source), "--proposal", str(proposal)]) == 0
    proposal.write_text("Validated 25/28 deployment paths.")
    assert main(["native", "check", "--source", str(source), "--proposal", str(proposal)]) == 4
