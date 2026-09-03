"""Every production humanizer call site must forward a structural realization.

`ModelHumanizerRewriter.rewrite` takes `realization` as an optional keyword, and
`_render_voice_profile` silently falls back to corpus-wide averages when it is
absent. A caller that forgets it therefore produces no error and no warning: it
just re-imposes the corpus-mean attractor that the realization engine exists to
break, while provenance still records a realization that never reached the
model. That failure is invisible in artifacts, so it is guarded structurally.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "howlwriter"


def _is_rewrite_call(node: ast.Call) -> bool:
    """Whether a call is `ModelHumanizerRewriter(...).rewrite(...)`."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "rewrite":
        return False
    receiver = func.value
    if isinstance(receiver, ast.Call):
        receiver = receiver.func
    return isinstance(receiver, ast.Name) and receiver.id == "ModelHumanizerRewriter"


def _model_humanizer_call_sites() -> list[tuple[Path, int, ast.Call]]:
    sites: list[tuple[Path, int, ast.Call]] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_rewrite_call(node):
                sites.append((path, node.lineno, node))
    return sites


def test_call_sites_are_discoverable():
    """Guard the guard: a matcher that finds nothing would pass vacuously."""
    assert len(_model_humanizer_call_sites()) >= 4


def test_every_humanizer_call_site_forwards_realization():
    missing = [
        f"{path.relative_to(SRC_ROOT.parents[1])}:{lineno}"
        for path, lineno, node in _model_humanizer_call_sites()
        if not any(kw.arg == "realization" for kw in node.keywords)
    ]
    assert not missing, (
        "ModelHumanizerRewriter().rewrite() called without realization= at: "
        + ", ".join(missing)
        + ". Without it the humanizer renders corpus-wide averages and pulls the "
        "draft back toward the mean."
    )
