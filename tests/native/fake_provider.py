"""Deterministic stand-in for a remote CLI provider (claude --output-format json).

Reads the Writer prompt on stdin and prints a Claude-CLI-shaped JSON
envelope. The behaviour is chosen by argv[1] so tests stay hermetic.
"""

import json
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "echo"
prompt = sys.stdin.read()
data = json.loads(prompt.split("DATA:\n", 1)[1])

if mode == "fail":
    sys.stderr.write("Error: rate limit exceeded (429)\n")
    raise SystemExit(1)
if mode == "garbage":
    result = "I could not produce JSON today."
else:
    proposals = []
    for item in data["items"]:
        text = item["current_copy"]
        if mode == "drift":
            text = text.replace("repositories", "deployment paths")
        if mode == "upgrade":
            text = text.replace("Dry-run validated", "Deployed to production")
        if mode == "skip" and item is data["items"][0]:
            continue
        proposals.append({
            "item_id": item["item_id"],
            "proposed_text": text,
            "reason": "tightened for " + item["desired_copy_role"],
            "design_judgment": "lead with the artifact",
            "uncertainty": "",
        })
    result = "```json\n" + json.dumps({"proposals": proposals}) + "\n```"

print(json.dumps({
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": result,
    "session_id": "fake-session-0001",
    "total_cost_usd": 0.0123,
    "usage": {"input_tokens": 120, "output_tokens": 45},
    "modelUsage": {"claude-fake-model": {"inputTokens": 120}},
}))
