"""Tests for web API academic pipeline and background jobs."""

import time
import pytest
from fastapi.testclient import TestClient
from howlwriter.web.app import create_app

client = TestClient(create_app())


def test_validate_spec_endpoint():
    spec_data = {
        "title": "Quantum Error Correction",
        "topic": "Overview of surface codes and syndrome measurement",
        "target_words": 1500,
        "word_tolerance_percent": 10.0,
        "citation_style": "apa7",
        "source_requirements": {
            "minimum_sources": 3,
            "prefer_primary_sources": True,
            "scholarly_or_authoritative": True,
            "allowed_types": [],
        },
        "requirements": ["Explain syndrome measurement", "Discuss physical vs logical qubits"],
        "outline": ["Introduction", "Surface Codes", "Syndrome Extraction", "Conclusion"],
    }

    res = client.post("/api/academic/validate", json={"spec": spec_data})
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert len(data["errors"]) == 0
    assert "yaml_preview" in data
    assert "Quantum Error Correction" in data["yaml_preview"]


def test_generate_paper_job_lifecycle():
    spec_data = {
        "title": "Test Paper Spec",
        "topic": "Test academic workflow through background job",
        "target_words": 500,
        "word_tolerance_percent": 10.0,
        "citation_style": "apa7",
        "source_requirements": {
            "minimum_sources": 1,
            "prefer_primary_sources": True,
            "scholarly_or_authoritative": True,
            "allowed_types": [],
        },
        "requirements": ["Requirement 1"],
        "outline": ["Section 1", "Section 2"],
    }

    # Start job in deterministic mode for test speed & isolation
    res = client.post(
        "/api/academic/generate",
        json={"spec": spec_data, "deterministic_only": True},
    )
    assert res.status_code == 200
    job_info = res.json()
    job_id = job_info["job_id"]
    assert job_id.startswith("job-")

    # Poll status until complete
    max_wait = 25
    start = time.time()
    completed = False
    while time.time() - start < max_wait:
        res_poll = client.get(f"/api/jobs/{job_id}")
        assert res_poll.status_code == 200
        poll_data = res_poll.json()
        if poll_data["status"] == "COMPLETED":
            completed = True
            assert poll_data["result"] is not None
            assert len(poll_data["result"]["paper_text"]) > 0
            assert poll_data["result"]["run_id"].startswith("hw-")
            assert len(poll_data["result"]["sources"]) > 0
            break
        elif poll_data["status"] == "FAILED":
            pytest.fail(f"Job failed: {poll_data.get('error_message')}")
        time.sleep(0.2)

    assert completed is True
