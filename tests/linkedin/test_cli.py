"""`howlwriter linkedin` end to end through the real argument parser, in a temporary repository."""

import json

import pytest

from howlwriter.cli.main import build_parser, main


@pytest.fixture
def repo(tmp_path, capsys):
    path = tmp_path / "repo"
    assert main(["linkedin", "--repo", str(path), "init"]) == 0
    capsys.readouterr()
    return path


def run(repo, capsys, *argv, expect=0):
    code = main(["linkedin", "--repo", str(repo), *argv])
    captured = capsys.readouterr()
    assert code == expect, captured.out + captured.err
    return captured


def run_json(repo, capsys, *argv, expect=0):
    return json.loads(run(repo, capsys, *argv, "--json", expect=expect).out)


def add(repo, capsys, tmp_path, title="CLI post", text="Hello from the CLI.", *extra):
    source = tmp_path / "text.txt"
    source.write_text(text, encoding="utf-8")
    return run_json(repo, capsys, "add", "--title", title, "--text-file", str(source), *extra)


def test_init_writes_safe_defaults_and_is_repeatable(repo, capsys):
    payload = run_json(repo, capsys, "init")
    assert payload["created"] == []
    assert payload["config"]["publishing_enabled"] is False and payload["config"]["dry_run"] is True
    assert (repo / "publisher.yaml").is_file() and (repo / "posts").is_dir()


def test_repository_is_required(capsys, monkeypatch):
    monkeypatch.delenv("HOWLWRITER_LINKEDIN_REPO", raising=False)
    assert main(["linkedin", "list"]) == 1
    assert "--repo" in capsys.readouterr().err


def test_repository_can_come_from_the_environment(repo, capsys, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_LINKEDIN_REPO", str(repo))
    assert main(["linkedin", "list"]) == 0
    assert "no posts" in capsys.readouterr().out


def test_draft_lifecycle_through_the_cli(repo, capsys, tmp_path):
    post = add(repo, capsys, tmp_path, "CLI post", "Hello.", "--date", "2099-01-05", "--url", "https://example.com/a")
    assert post["state"] == "DRAFT" and post["urls"] == ["https://example.com/a"]
    post_id = post["id"]

    assert [p["id"] for p in run_json(repo, capsys, "list")["posts"]] == [post_id]
    assert run_json(repo, capsys, "list", "--state", "archived")["posts"] == []
    assert "Hello." in run(repo, capsys, "show", post_id).out

    validation = run_json(repo, capsys, "validate", post_id)
    assert validation["ok"] is True
    assert "URL_NOT_IN_TEXT" in {finding["code"] for finding in validation["findings"]}

    assert run_json(repo, capsys, "submit", post_id)["state"] == "READY_FOR_REVIEW"
    moved = run_json(repo, capsys, "reschedule", post_id, "--date", "2099-01-06", "--time", "09:00", "--actor", "owner")
    assert (moved["scheduled_date"], moved["scheduled_time"]) == ("2099-01-06", "09:00")
    assert moved["history"][-1]["actor"] == "owner"

    queue = run_json(repo, capsys, "queue")
    assert queue["paused"] is False and queue["queue"][0]["id"] == post_id

    edited_text = tmp_path / "new.txt"
    edited_text.write_text("Changed text.", encoding="utf-8")
    edited = run_json(repo, capsys, "edit", post_id, "--text-file", str(edited_text))
    assert edited["state"] == "DRAFT" and edited["text"] == "Changed text."

    assert run_json(repo, capsys, "archive", post_id)["state"] == "ARCHIVED"
    assert run_json(repo, capsys, "queue")["queue"] == []


def test_cli_cannot_approve_or_schedule_without_the_trusted_boundary(repo, capsys, tmp_path):
    """There is deliberately no approve command, and schedule refuses an unapproved post."""
    post_id = add(repo, capsys, tmp_path, "Unapproved", "Hello.", "--date", "2099-01-05")["id"]
    run(repo, capsys, "submit", post_id)
    assert "cannot move" in run(repo, capsys, "schedule", post_id, expect=1).err
    with pytest.raises(SystemExit) as usage:
        main(["linkedin", "--repo", str(repo), "approve", post_id])
    assert usage.value.code == 1
    capsys.readouterr()
    parser = build_parser()
    subcommands = parser._subparsers._group_actions[0].choices["linkedin"]._subparsers._group_actions[0].choices
    assert not {"approve", "publish", "run", "send"} & set(subcommands)


def test_validate_exits_nonzero_on_blocking_findings(repo, capsys, tmp_path):
    post_id = add(repo, capsys, tmp_path, "Long", "x" * 3001)["id"]
    payload = run_json(repo, capsys, "validate", post_id, expect=1)
    assert payload["ok"] is False
    assert "blocking findings" in run(repo, capsys, "submit", post_id, expect=1).err


def test_unsupported_time_and_collisions_are_rejected(repo, capsys, tmp_path):
    add(repo, capsys, tmp_path, "First", "One.", "--date", "2099-01-05")
    source = tmp_path / "text.txt"
    for extra, fragment in (
        (["--date", "2099-01-05"], "already holds"),
        (["--date", "2099-01-06", "--time", "10:17"], "not a supported slot"),
        (["--date", "2000-01-01"], "past"),
        (["--date", "2099-02-30"], "date"),
    ):
        result = run(repo, capsys, "add", "--title", "Second", "--text-file", str(source), *extra, expect=1)
        assert fragment in result.err
    assert len(run_json(repo, capsys, "list")["posts"]) == 1


def test_pause_resume_and_evaluate(repo, capsys):
    run(repo, capsys, "pause", "--reason", "vacation")
    evaluation = run_json(repo, capsys, "evaluate", "--at", "2099-01-05T13:30:00Z")
    assert (evaluation["action"], evaluation["reason"]) == ("NOTHING", "PAUSED")
    assert evaluation["dry_run"] is True and evaluation["publishing_enabled"] is False
    assert "scheduling is PAUSED" in run(repo, capsys, "queue").out
    run(repo, capsys, "resume")
    text = run(repo, capsys, "evaluate", "--at", "2099-01-05T13:30:00Z").out
    assert "NO_POST_DUE" in text and "Nothing was changed or sent" in text


def test_bulk_reschedule_plans_before_applying(repo, capsys, tmp_path):
    first = add(repo, capsys, tmp_path, "First", "One.", "--date", "2099-01-05")["id"]
    add(repo, capsys, tmp_path, "Second", "Two.", "--date", "2099-01-06")
    plan = run_json(repo, capsys, "reschedule-all", "--shift-days", "7")
    assert plan["applied"] is False and len(plan["moves"]) == 2
    assert run_json(repo, capsys, "show", first)["scheduled_date"] == "2099-01-05"
    applied = run_json(repo, capsys, "reschedule-all", "--shift-days", "7", "--apply")
    assert applied["applied"] is True
    assert run_json(repo, capsys, "show", first)["scheduled_date"] == "2099-01-12"
    refused = run_json(repo, capsys, "reschedule-all", "--time", "03:33", "--apply", expect=1)
    assert refused["applied"] is False and refused["conflicts"]


def test_image_requires_alt_text_and_must_live_in_media(repo, capsys, tmp_path):
    source = tmp_path / "text.txt"
    source.write_text("With image.", encoding="utf-8")
    inside = repo / "media" / "chart.png"
    inside.write_bytes(b"\x89PNG fake")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"\x89PNG fake")
    base = ["add", "--title", "Image", "--text-file", str(source)]
    assert "--alt" in run(repo, capsys, *base, "--image", str(inside), expect=1).err
    assert "inside" in run(repo, capsys, *base, "--image", str(outside), "--alt", "A chart", expect=1).err
    post = run_json(repo, capsys, *base, "--image", str(inside), "--alt", "A chart")
    assert post["media"][0]["path"] == "media/chart.png" and len(post["media"][0]["sha256"]) == 64


def test_invalid_config_and_corrupt_post_fail_loudly(repo, capsys, tmp_path):
    post_id = add(repo, capsys, tmp_path)["id"]
    (repo / "posts" / "junk.json").write_text("{")
    listing = run_json(repo, capsys, "list", expect=1)
    assert listing["invalid"][0]["path"] == "posts/junk.json" and listing["posts"][0]["id"] == post_id
    (repo / "publisher.yaml").write_text("schema: howlwriter.linkedin_publisher_config/v1\nmax_posts_per_day: 5\n")
    assert "max_posts_per_day" in run(repo, capsys, "evaluate", expect=1).err


def test_unknown_post_and_path_like_ids_are_errors(repo, capsys):
    assert "no post" in run(repo, capsys, "show", "missing-post", expect=1).err
    assert "invalid post ID" in run(repo, capsys, "show", "../../etc/passwd", expect=1).err


def test_reconcile_requires_an_explicit_outcome(repo, capsys, tmp_path):
    post_id = add(repo, capsys, tmp_path)["id"]
    with pytest.raises(SystemExit) as usage:
        main(["linkedin", "--repo", str(repo), "reconcile", post_id])
    assert usage.value.code == 1
    capsys.readouterr()
    assert "UNCERTAIN" in run(repo, capsys, "reconcile", post_id, "--not-published", expect=1).err


def test_commands_appear_in_the_interop_descriptor(capsys):
    assert main(["interop", "--json"]) == 0
    paths = {tuple(command["path"]) for command in json.loads(capsys.readouterr().out)["commands"]}
    assert {("linkedin", "add"), ("linkedin", "evaluate"), ("linkedin", "reschedule-all")} <= paths
