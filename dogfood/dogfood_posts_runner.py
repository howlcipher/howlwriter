#!/usr/bin/env python3
"""Runner for the 20 real post workflows in the HowlWriter dogfood campaign."""

import os
import subprocess
import sys
import time
from pathlib import Path

# Paths are derived from this file so the runner works from any checkout.
DOGFOOD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOGFOOD_DIR.parent
HOWLWRITER_BIN = os.environ.get(
    "HOWLWRITER_BIN", str(REPO_ROOT / ".venv" / "bin" / "howlwriter")
)
POSTS_DIR = DOGFOOD_DIR / "posts"

# 20 Posts configurations with provider rotation and command variety
POST_CONFIGS = [
    # 5 Technical / Engineering
    {
        "id": "post_01",
        "file": "post_01_conn_pooling.md",
        "cmd": "howl",
        "humanizer": "agy",
        "reviewer": "codex",
        "category": "Technical: DB Connection Pooling",
    },
    {
        "id": "post_02",
        "file": "post_02_postmortems.md",
        "cmd": "howl",
        "humanizer": "codex",
        "reviewer": "agy",
        "category": "Technical: Blameless Postmortems",
    },
    {
        "id": "post_03",
        "file": "post_03_ai_code_review.md",
        "cmd": "humanize",
        "humanizer": "devin_cli",
        "reviewer": "agy",
        "category": "Technical: AI Code Review",
    },
    {
        "id": "post_04",
        "file": "post_04_backpressure.md",
        "cmd": "howl",
        "humanizer": "agy",
        "reviewer": "devin_cli",
        "category": "Technical: Distributed Backpressure",
    },
    {
        "id": "post_05",
        "file": "post_05_cicd_caching.md",
        "cmd": "humanize",
        "humanizer": "codex",
        "reviewer": "devin_cli",
        "category": "Technical: CI/CD Caching",
    },
    # 5 Opinion / Professional
    {
        "id": "post_06",
        "file": "post_06_remote_async.md",
        "cmd": "howl",
        "humanizer": "agy",
        "reviewer": "codex",
        "category": "Opinion: Remote Work Async",
    },
    {
        "id": "post_07",
        "file": "post_07_generalist_engineers.md",
        "cmd": "howl",
        "humanizer": "codex",
        "reviewer": "agy",
        "category": "Opinion: Generalist Systems Engineers",
    },
    {
        "id": "post_08",
        "file": "post_08_learning_tech.md",
        "cmd": "humanize",
        "humanizer": "agy",
        "reviewer": "codex",
        "category": "Opinion: Senior Engineers Learning",
    },
    {
        "id": "post_09",
        "file": "post_09_ten_x_myth.md",
        "cmd": "howl",
        "humanizer": "devin_cli",
        "reviewer": "codex",
        "category": "Opinion: Myth of 10x Engineer",
    },
    {
        "id": "post_10",
        "file": "post_10_reading_code.md",
        "cmd": "howl",
        "humanizer": "agy",
        "reviewer": "devin_cli",
        "category": "Opinion: Reading Code 80%",
    },
    # 5 Project / Development
    {
        "id": "post_11",
        "file": "post_11_dogfooding_howlwriter.md",
        "cmd": "howl",
        "humanizer": "codex",
        "reviewer": "agy",
        "category": "Project: Dogfooding HowlWriter",
    },
    {
        "id": "post_12",
        "file": "post_12_howlplane_orchestration.md",
        "cmd": "humanize",
        "humanizer": "agy",
        "reviewer": "codex",
        "category": "Project: HowlPlane Multi-Provider",
    },
    {
        "id": "post_13",
        "file": "post_13_howlframe_vm.md",
        "cmd": "howl",
        "humanizer": "devin_cli",
        "reviewer": "agy",
        "category": "Project: HowlFrame Bytecode VM",
    },
    {
        "id": "post_14",
        "file": "post_14_deterministic_ai_tools.md",
        "cmd": "howl",
        "humanizer": "agy",
        "reviewer": "codex",
        "category": "Project: Verifiable AI Tools",
    },
    {
        "id": "post_15",
        "file": "post_15_provenance_graph.md",
        "cmd": "humanize",
        "humanizer": "codex",
        "reviewer": "devin_cli",
        "category": "Project: Provenance Graph",
    },
    # 5 Bad AI-Style Drafts
    {
        "id": "post_16",
        "file": "post_16_ai_landscape_cloud.md",
        "cmd": "howl",
        "humanizer": "agy",
        "reviewer": "codex",
        "category": "Bad AI: Cloud Landscape / Tapestry",
    },
    {
        "id": "post_17",
        "file": "post_17_ai_synergy_devops.md",
        "cmd": "howl",
        "humanizer": "codex",
        "reviewer": "agy",
        "category": "Bad AI: DevOps Labyrinth / Synergy",
    },
    {
        "id": "post_18",
        "file": "post_18_ai_burgeoning_microservices.md",
        "cmd": "humanize",
        "humanizer": "agy",
        "reviewer": "codex",
        "category": "Bad AI: Burgeoning Microservices",
    },
    {
        "id": "post_19",
        "file": "post_19_ai_transformative_agents.md",
        "cmd": "howl",
        "humanizer": "devin_cli",
        "reviewer": "agy",
        "category": "Bad AI: Autonomous AI Agents Delve",
    },
    {
        "id": "post_20",
        "file": "post_20_ai_seamless_integration.md",
        "cmd": "howl",
        "humanizer": "agy",
        "reviewer": "devin_cli",
        "category": "Bad AI: Infrastructure Tapestry",
    },
]


def run_post(cfg: dict) -> dict:
    file_path = POSTS_DIR / cfg["file"]
    cmd_type = cfg["cmd"]
    env = os.environ.copy()
    env["HOWLPLANE_ROLE_WRITING_HUMANIZER"] = cfg["humanizer"]
    env["HOWLPLANE_ROLE_WRITING_FINAL_REVIEWER"] = cfg["reviewer"]
    env["PYTHONPATH"] = (
        f"{REPO_ROOT / 'src'}:"
        f"{os.environ.get('HOWLPLANE_ROOT', REPO_ROOT.parent / 'howlplane')}"
    )

    cmd = [HOWLWRITER_BIN, cmd_type, str(file_path)]
    print("\n=======================================================")
    print(f"Executing {cfg['id']}: {cfg['category']}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Providers: Humanizer={cfg['humanizer']} | Reviewer={cfg['reviewer']}")
    print("=======================================================")

    t0 = time.time()
    res = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        cwd=str(POSTS_DIR),
        timeout=300,
    )
    elapsed = round(time.time() - t0, 2)

    print(f"Exit Code: {res.returncode} (Duration: {elapsed}s)")
    if res.stdout:
        print("STDOUT:\n" + res.stdout)
    if res.stderr:
        print("STDERR:\n" + res.stderr)

    return {
        "id": cfg["id"],
        "category": cfg["category"],
        "cmd": cmd_type,
        "humanizer": cfg["humanizer"],
        "reviewer": cfg["reviewer"],
        "exit_code": res.returncode,
        "duration": elapsed,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }


def main():
    results = []
    for cfg in POST_CONFIGS:
        try:
            r = run_post(cfg)
            results.append(r)
        except Exception as exc:
            print(f"Exception executing {cfg['id']}: {exc}", file=sys.stderr)
            results.append({
                "id": cfg["id"],
                "category": cfg["category"],
                "error": str(exc),
            })
    print(f"\nCompleted all {len(results)} post workflows.")


if __name__ == "__main__":
    main()
