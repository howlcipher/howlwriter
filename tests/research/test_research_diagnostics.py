import io
import json
import socket
import urllib.error
import urllib.request

from howlwriter.academic.research import (
    AcademicResearcher,
    fetch_arxiv_sources,
    fetch_crossref_sources,
)
from howlwriter.academic.research_diagnostics import classify_exception, summarize
from howlwriter.academic.spec import AssignmentSpec


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, fn):
    monkeypatch.setattr(urllib.request, "urlopen", fn)


def test_crossref_empty_result_is_not_a_failure(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: _Resp(json.dumps({"message": {"items": []}}).encode()))
    diags = []
    assert fetch_crossref_sources("zero trust", diagnostics=diags) == []
    assert [(d.provider, d.outcome) for d in diags] == [("crossref", "no_results")]
    assert not diags[0].failed


def test_crossref_http_429_is_rate_limited_and_retryable(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("https://api.crossref.org/works?x=secret", 429, "Too Many", {}, None)

    _patch(monkeypatch, boom)
    diags = []
    assert fetch_crossref_sources("q", diagnostics=diags) == []
    d = diags[0]
    assert d.failed and d.category == "rate_limited" and d.retryable is True
    assert "http" not in d.message.lower().replace("http 429", "")  # no URLs leak


def test_timeout_and_network_and_parse_categories(monkeypatch):
    assert classify_exception(socket.timeout())[0] == "timeout"
    assert classify_exception(urllib.error.URLError("dns failure"))[:2] == ("network", True)
    assert classify_exception(urllib.error.HTTPError("u", 404, "nf", {}, None))[:2] == ("http_error", False)
    assert classify_exception(urllib.error.HTTPError("u", 503, "x", {}, None))[:2] == ("http_error", True)
    assert classify_exception(json.JSONDecodeError("bad", "", 0))[:2] == ("parse_error", False)

    _patch(monkeypatch, lambda *a, **k: _Resp(b"not xml"))
    diags = []
    fetch_arxiv_sources("q", diagnostics=diags)
    assert diags[0].category == "parse_error"


def test_url_with_query_is_redacted_from_message():
    exc = urllib.error.URLError("failed to reach https://api.example.com/x?token=abc123 now")
    _, _, msg = classify_exception(exc)
    assert "abc123" not in msg and "<url>" in msg


def test_researcher_collects_failures_and_continues(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("offline")

    _patch(monkeypatch, boom)
    r = AcademicResearcher()
    sources = r.execute_research(AssignmentSpec(title="T", topic="zero trust architecture"))
    assert sources == []
    summary = summarize(r.diagnostics)
    assert summary["providers"]["crossref"]["failed"] >= 1
    assert summary["providers"]["arxiv"]["failed"] >= 1
    assert all(f["fallback_continued"] for f in summary["failures"])


def test_fetchers_still_work_without_diagnostics_argument(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("offline")

    _patch(monkeypatch, boom)
    assert fetch_crossref_sources("q") == []
    assert fetch_arxiv_sources("q") == []
