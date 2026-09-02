# HowlPlane Timeout Gap: Subprocess Agent `--print-timeout` Mismatch

## Executive Summary

During long-form academic generation and complex outline expansions, model execution occasionally fails at exactly 300 seconds with:
```
Error: timeout waiting for response
```
even when the invoking caller (e.g., HowlWriter's `ModelAcademicWriter` or `OutlineWriter`) explicitly specified `timeout_seconds=600`.

Investigation reveals that the timeout abort originates from the inner CLI agent (`agy`), rather than the outer Python `subprocess.run` harness in HowlPlane.

---

## Root Cause Analysis

In HowlPlane's `src/control_plane/agent_execution.py`:

```python
class AgyBackend(SubprocessAgentBackend):
    def __init__(self):
        super().__init__("agy", "agy", lambda t, c, r, p: ["agy", "-p", p, "--mode", "accept-edits"])
```

When HowlPlane's `SubprocessAgentBackend.execute()` executes:
```python
completed = subprocess.run(
    args=cmd_args,
    cwd=str(target_cwd),
    capture_output=True,
    text=True,
    env=env,
    timeout=timeout_seconds,
)
```
the outer `subprocess.run` honors `timeout=timeout_seconds` (e.g. 600s). However, `agy`'s CLI default for print mode is:
```
--print-timeout    Timeout for print mode wait (default 5m0s)
```
Because `--print-timeout` was omitted from the command construction, `agy` enforces its own internal 5-minute (300-second) deadline. When reasoning or generation exceeds 300s:
1. `agy` terminates its own session, writes `Error: timeout waiting for response` to stderr/stdout, and exits with code 1.
2. HowlPlane detects the error string, marks `is_timeout = True`, and returns a failed `AgentExecutionResult` after only 300s of elapsed execution.
3. The outer 600-second harness budget is never utilized.

---

## Recommended HowlPlane Patch

In `howlplane/src/control_plane/agent_execution.py`:

1. Update `build_command` and `SubprocessAgentBackend.execute` to pass `timeout_seconds` to the command builder:

```python
    def build_command(
        self, task: TaskSpec, cwd: Path, role: str, prompt: str, timeout_seconds: int = 300
    ) -> List[str]:
        if self._builder:
            try:
                return self._builder(task, cwd, role, prompt, timeout_seconds=timeout_seconds)
            except TypeError:
                return self._builder(task, cwd, role, prompt)
        return [self.binary_name, prompt]
```

2. In `AgyBackend`, forward `--print-timeout`:

```python
class AgyBackend(SubprocessAgentBackend):
    def __init__(self):
        def _cmd(t, c, r, p, timeout_seconds=300):
            return [
                "agy",
                "-p", p,
                "--mode", "accept-edits",
                "--print-timeout", f"{timeout_seconds}s",
            ]
        super().__init__("agy", "agy", _cmd)
```

This aligns the internal `agy` execution deadline with the caller's requested role timeout, allowing full utilization of configured generation windows.
