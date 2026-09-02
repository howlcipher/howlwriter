#!/usr/bin/env python3
"""Runner for the 10 real academic paper workflows in the HowlWriter dogfood campaign."""

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
PAPERS_DIR = DOGFOOD_DIR / "papers"

PAPER_CONFIGS = [
    # 3 Short Papers (700-1000 words)
    {
        "id": "paper_01",
        "file": "paper_01_zero_trust.yaml",
        "writer": "codex",
        "humanizer": "agy",
        "reviewer": "devin_cli",
        "title": "Zero Trust in Kubernetes (850w)",
    },
    {
        "id": "paper_02",
        "file": "paper_02_incident_automation.yaml",
        "writer": "agy",
        "humanizer": "codex",
        "reviewer": "devin_cli",
        "title": "Automated Incident Remediation (900w)",
    },
    {
        "id": "paper_03",
        "file": "paper_03_supply_chain.yaml",
        "writer": "devin_cli",
        "humanizer": "agy",
        "reviewer": "codex",
        "title": "Static Analysis in Supply Chains (800w)",
    },
    # 4 Medium Papers (1200-1800 words)
    {
        "id": "paper_04",
        "file": "paper_04_oauth_fapi.yaml",
        "writer": "codex",
        "humanizer": "agy",
        "reviewer": "devin_cli",
        "title": "OAuth 2.1 and FAPI (1400w)",
    },
    {
        "id": "paper_05",
        "file": "paper_05_agent_resilience.yaml",
        "writer": "agy",
        "humanizer": "devin_cli",
        "reviewer": "codex",
        "title": "Multi-Agent Failure Recovery (1500w)",
    },
    {
        "id": "paper_06",
        "file": "paper_06_slo_error_budgets.yaml",
        "writer": "devin_cli",
        "humanizer": "codex",
        "reviewer": "agy",
        "title": "SLOs and Error Budgets (1600w)",
    },
    {
        "id": "paper_07",
        "file": "paper_07_prompt_injection.yaml",
        "writer": "agy",
        "humanizer": "codex",
        "reviewer": "devin_cli",
        "title": "Defending Multi-Agent Prompt Injection (1450w)",
    },
    # 3 Substantial Papers (2000-2500 words)
    {
        "id": "paper_08",
        "file": "paper_08_ebpf_security.yaml",
        "writer": "codex",
        "humanizer": "agy",
        "reviewer": "devin_cli",
        "title": "eBPF Runtime Security (2200w)",
    },
    {
        "id": "paper_09",
        "file": "paper_09_memory_safety_rust.yaml",
        "writer": "agy",
        "humanizer": "codex",
        "reviewer": "devin_cli",
        "title": "Memory Safety: Rust vs C++ (2300w)",
    },
    {
        "id": "paper_10",
        "file": "paper_10_conways_law_platforms.yaml",
        "writer": "devin_cli",
        "humanizer": "agy",
        "reviewer": "codex",
        "title": "Conway's Law in Platform Engineering (2100w)",
    },
]


def run_paper(cfg: dict) -> dict:
    yaml_path = PAPERS_DIR / cfg["file"]
    out_md = PAPERS_DIR / f"{cfg['id']}_output.md"

    env = os.environ.copy()
    env["HOWLPLANE_ROLE_WRITING_WRITER"] = cfg["writer"]
    env["HOWLPLANE_ROLE_WRITING_HUMANIZER"] = cfg["humanizer"]
    env["HOWLPLANE_ROLE_WRITING_FINAL_REVIEWER"] = cfg["reviewer"]
    env["PYTHONPATH"] = (
        f"{REPO_ROOT / 'src'}:"
        f"{os.environ.get('HOWLPLANE_ROOT', REPO_ROOT.parent / 'howlplane')}"
    )

    cmd = [
        HOWLWRITER_BIN,
        "paper",
        str(yaml_path),
        "--out",
        str(out_md),
        "--save-artifacts",
    ]
    print("\n=======================================================")
    print(f"Executing Academic Paper: {cfg['id']} - {cfg['title']}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Providers: Writer={cfg['writer']} | Humanizer={cfg['humanizer']} | Reviewer={cfg['reviewer']}")
    print("=======================================================")

    t0 = time.time()
    res = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        cwd=str(PAPERS_DIR),
        timeout=600,
    )
    elapsed = round(time.time() - t0, 2)

    print(f"Exit Code: {res.returncode} (Duration: {elapsed}s)")
    if res.stdout:
        print("STDOUT:\n" + res.stdout)
    if res.stderr:
        print("STDERR:\n" + res.stderr)

    return {
        "id": cfg["id"],
        "title": cfg["title"],
        "writer": cfg["writer"],
        "humanizer": cfg["humanizer"],
        "reviewer": cfg["reviewer"],
        "exit_code": res.returncode,
        "duration": elapsed,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }


def main():
    paper_ids_to_run = sys.argv[1:] if len(sys.argv) > 1 else None
    configs = [c for c in PAPER_CONFIGS if not paper_ids_to_run or c["id"] in paper_ids_to_run]

    results = []
    for cfg in configs:
        try:
            r = run_paper(cfg)
            results.append(r)
        except Exception as exc:
            print(f"Exception executing {cfg['id']}: {exc}", file=sys.stderr)
            results.append({
                "id": cfg["id"],
                "title": cfg["title"],
                "error": str(exc),
            })
    print(f"\nCompleted {len(results)} paper workflow executions.")


if __name__ == "__main__":
    main()
