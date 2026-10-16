"""Browser-assisted research and lab observation, with three authorization levels.

Built on Playwright (the library, driven in-process) rather than a custom
browser-control engine. The browser is a dedicated Chromium profile under
the project workspace -- never the user's daily browser -- launched visible by
default, connected over Playwright's private pipe (no remote-debugging port
is opened, so nothing listens on the network).

Modes
-----
``research``     navigate allowlisted sites, read pages, capture title/URL/
                 retrieval time, take screenshots. Read-only.
``observe``      the same against an approved lab interface, recorded as
                 observation evidence. Read-only.
``interactive``  click and fill on an approved lab origin. Every state-changing
                 action is queued and runs only after the user approves it.

Enforcement is in the network layer, not in good intentions:

* every request is routed through an allowlist check; a navigation to an
  origin outside the allowlist is aborted (and recorded as blocked);
* in ``research`` and ``observe`` every non-GET/HEAD request is aborted, so
  nothing can change server state even if a page script tries;
* in ``interactive`` mode non-GET requests are permitted only to the
  approved interactive origins, and only while an approved action runs;
* service workers and downloads are disabled;
* actions whose target looks like submitting graded work ("submit
  assignment", "turn in", "submit for grading") are refused outright -- the
  user submits coursework, never HowlWriter.

Page text is untrusted data. It is stored as evidence and shown to the user;
nothing in this module acts on it. Text that looks like an instruction to an
agent is flagged on the evidence item.

Credentials: ``fill`` with ``secret=True`` takes its value from an
environment variable named by the user and records the action with the
value redacted. Secrets are never written to the action log or evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable
from urllib.parse import urlsplit
import uuid

from howlwriter.projects import models as m
from howlwriter.projects.workspace import ProjectWorkspace, utc_now
from howlwriter.voice.identity import privacy

MODES = ("research", "observe", "interactive")
READ_ONLY_MODES = ("research", "observe")
STATE_CHANGING = ("click", "fill", "press", "select")
MAX_PAGE_TEXT = 60_000
SUBMISSION_PATTERN = re.compile(
    r"submit\s+(?:the\s+|your\s+|my\s+)?(?:assignment|attempt|quiz|exam|for grading|work|lab)|"
    r"\bturn\s*in\b|final\s+submission|submit\s+grade|post\s+grade",
    re.I,
)
INJECTION_PATTERN = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above) instructions|you are (?:an? )?(?:ai|assistant|agent)\b|"
    r"system prompt|as an ai\b|(?:assistant|agent)s? (?:must|should) (?:now )?(?:click|delete|submit|run)",
    re.I,
)


class BrowserPolicyError(PermissionError):
    pass


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BrowserPolicyError(f"only http(s) URLs are allowed, not {url[:80]!r}")
    port = parts.port
    default = {"http": 80, "https": 443}[parts.scheme]
    host = parts.hostname.lower()
    return f"{parts.scheme}://{host}" + (f":{port}" if port and port != default else "")


@dataclass
class BrowserPolicy:
    mode: str = "research"
    allowed_origins: list[str] = field(default_factory=list)  # exact origins, or https://*.domain (research)
    interactive_origins: list[str] = field(default_factory=list)  # exact origins only

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise BrowserPolicyError(f"mode must be one of {', '.join(MODES)}")
        self.allowed_origins = [self._normalize(o) for o in self.allowed_origins]
        self.interactive_origins = [origin_of(o) for o in self.interactive_origins]
        if self.mode == "interactive":
            if not self.interactive_origins:
                raise BrowserPolicyError("interactive mode needs at least one approved lab origin")
            if any("*" in o for o in self.allowed_origins):
                raise BrowserPolicyError("interactive mode does not accept wildcard origins")
        if not self.allowed_origins and not self.interactive_origins:
            raise BrowserPolicyError("no approved origins: pass --allow https://site.example")

    @staticmethod
    def _normalize(origin: str) -> str:
        if "*." in origin:
            scheme, _, host = origin.partition("://")
            if scheme not in ("http", "https") or not host.startswith("*.") or "/" in host:
                raise BrowserPolicyError(f"bad wildcard origin {origin!r}; use https://*.example.org")
            return f"{scheme}://{host.lower()}"
        return origin_of(origin)

    def allows(self, url: str) -> bool:
        try:
            origin = origin_of(url)
        except BrowserPolicyError:
            return url.startswith(("about:", "data:", "blob:"))
        if origin in self.interactive_origins:
            return True
        for allowed in self.allowed_origins:
            if allowed == origin:
                return True
            if "*." in allowed and self.mode == "research":
                scheme, _, suffix = allowed.partition("://*.")
                if origin.startswith(scheme + "://") and (
                    urlsplit(origin).hostname == suffix or urlsplit(origin).hostname.endswith("." + suffix)
                ):
                    return True
        return False

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "allowed_origins": self.allowed_origins,
            "interactive_origins": self.interactive_origins,
        }


@dataclass
class PendingAction:
    action: m.BrowserAction
    selector: str
    value: str | None = None
    secret_env: str | None = None


class BrowserSession:
    """One controlled browser for one project. Not thread-safe; see BrowserController."""

    def __init__(
        self,
        workspace: ProjectWorkspace,
        policy: BrowserPolicy,
        *,
        headless: bool = False,
        launcher: Callable[..., Any] | None = None,
    ) -> None:
        self.workspace = workspace
        self.policy = policy
        self.headless = headless
        self._launcher = launcher
        self._playwright = None
        self._context = None
        self.page = None
        self.state = "stopped"  # stopped | running | paused
        self.blocked: list[dict] = []
        self.pending: dict[str, PendingAction] = {}
        self._executing: str | None = None
        self.session_id = uuid.uuid4().hex[:12]

    # --- lifecycle --------------------------------------------------------

    @property
    def profile_dir(self) -> Path:
        return self.workspace.directory / "browser" / "profile"

    def start(self) -> None:
        if self.state != "stopped":
            return
        privacy.ensure_private_dir(self.profile_dir)
        if self._launcher is not None:
            self._context = self._launcher(self)
        else:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                accept_downloads=False,
                service_workers="block",
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-sync",
                    "--disable-background-networking",
                    "--password-store=basic",
                ],
            )
        self._context.route("**/*", self._route)
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.state = "running"
        self._log("start", url="", outcome="ok", changed_state=False, decision="auto")

    def stop(self) -> None:
        if self.state == "stopped":
            return
        try:
            if self._context is not None:
                self._context.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()
            self._context = self._playwright = self.page = None
            self.state = "stopped"
            self.pending.clear()
            self._log("stop", url="", outcome="ok", changed_state=False, decision="auto")

    def pause(self) -> None:
        if self.state == "running":
            self.state = "paused"

    def resume(self) -> None:
        if self.state == "paused":
            self.state = "running"

    def set_read_only(self) -> None:
        """Drop back from interactive to observe; pending actions are denied."""
        for action_id in list(self.pending):
            self.deny(action_id, reason="session switched to read-only")
        if self.policy.mode == "interactive":
            self.policy = BrowserPolicy(
                mode="observe", allowed_origins=self.policy.allowed_origins + self.policy.interactive_origins
            )

    # --- network enforcement ------------------------------------------------

    def _route(self, route, request) -> None:
        url = request.url
        method = request.method.upper()
        reason = ""
        if not self.policy.allows(url):
            reason = "origin not approved"
        elif method not in ("GET", "HEAD", "OPTIONS"):
            if self.policy.mode in READ_ONLY_MODES:
                reason = f"{method} blocked in read-only {self.policy.mode} mode"
            elif origin_of(url) not in self.policy.interactive_origins:
                reason = f"{method} to a non-lab origin"
            elif self._executing is None:
                reason = f"{method} outside an approved action"
        if reason:
            self.blocked.append(
                {
                    "at": utc_now(),
                    "url": url[:300],
                    "method": method,
                    "reason": reason,
                    "navigation": request.is_navigation_request(),
                }
            )
            route.abort("blockedbyclient")
        else:
            route.continue_()

    # --- helpers --------------------------------------------------------------

    def _require_running(self) -> None:
        if self.state == "paused":
            raise BrowserPolicyError("the browser session is paused; resume it first")
        if self.state != "running":
            raise BrowserPolicyError("the browser session is not running")

    def _log(
        self,
        kind: str,
        *,
        url: str,
        outcome: str,
        changed_state: bool,
        decision: str,
        target: str = "",
        title: str = "",
        evidence_ids: list[str] | None = None,
        error: str = "",
        value_redacted: bool = False,
        action_id: str | None = None,
    ) -> m.BrowserAction:
        now = utc_now()
        action = m.BrowserAction(
            action_id=action_id or "act-" + uuid.uuid4().hex[:12],
            mode=self.policy.mode,
            kind=kind,
            url=url[:500],
            target=target[:300],
            value_redacted=value_redacted,
            requested_at=now,
            decided_at=now,
            decision=decision,
            performed_at=now if outcome == "ok" else "",
            outcome=outcome,
            page_title=title[:200],
            changed_state=changed_state,
            evidence_ids=evidence_ids or [],
            error=error[:300],
        )
        self.workspace.append_action(action)
        return action

    def _evidence(
        self,
        *,
        kind: str,
        excerpt: str,
        observation: dict,
        location: str,
        limitations: list[str],
        status: str,
    ) -> m.EvidenceItem:
        url = self.page.url
        origin = origin_of(url)
        source_id = "web-" + hashlib.sha256(origin.encode("utf-8")).hexdigest()[:12]
        locator = {"url": url, "at": utc_now(), "kind": kind}
        item = m.EvidenceItem(
            evidence_id="ev-" + hashlib.sha256(repr(sorted(locator.items())).encode()).hexdigest()[:12],
            source_id=source_id,
            source_path=url,
            source_type="browser",
            category=m.REFERENCE if self.policy.mode == "research" else m.EXPERIMENTAL,
            method=f"playwright-chromium/{self.policy.mode}",
            status=status,
            location=location,
            locator=locator,
            excerpt=excerpt[:900],
            observation={"mode": self.policy.mode, "session_id": self.session_id, **observation},
            confidence="high",
            limitations=limitations,
            extracted_at=locator["at"],
            citation=f"{observation.get('title') or origin}, {url}, retrieved {locator['at'][:10]}",
            kind=kind,
        )
        evidence = self.workspace.load_evidence()
        evidence[item.evidence_id] = item
        self.workspace.save_evidence(evidence)
        sources = self.workspace.load_sources()
        if source_id not in sources:
            sources[source_id] = m.SourceRecord(
                source_id=source_id,
                path=origin,
                suffix="",
                size=0,
                mtime=0.0,
                category=item.category,
                category_source="browser",
                category_reason=f"browser {self.policy.mode} session",
                adapter="playwright",
                status="extracted",
            )
        sources[source_id].evidence_count += 1
        self.workspace.save_sources(sources)
        return item

    # --- read-only actions ------------------------------------------------------

    def navigate(self, url: str) -> m.BrowserAction:
        self._require_running()
        if not self.policy.allows(url):
            self.blocked.append(
                {
                    "at": utc_now(),
                    "url": url[:300],
                    "method": "GET",
                    "reason": "origin not approved",
                    "navigation": True,
                }
            )
            return self._log(
                "navigate",
                url=url,
                outcome="blocked",
                changed_state=False,
                decision="denied",
                error="origin not approved",
            )
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            final = self.page.url
            if not self.policy.allows(final):
                self.page.goto("about:blank")
                return self._log(
                    "navigate",
                    url=final,
                    outcome="blocked",
                    changed_state=False,
                    decision="denied",
                    error="redirected outside the approved origins",
                )
            return self._log(
                "navigate",
                url=final,
                outcome="ok",
                changed_state=False,
                decision="auto",
                title=self.page.title(),
            )
        except Exception as error:
            return self._log(
                "navigate",
                url=url,
                outcome="failed",
                changed_state=False,
                decision="auto",
                error=f"{type(error).__name__}: {error}",
            )

    def read(self) -> m.EvidenceItem:
        self._require_running()
        title = self.page.title()
        text = self.page.inner_text("body", timeout=10_000)[:MAX_PAGE_TEXT]
        headings = [h.strip() for h in self.page.locator("h1, h2, h3").all_inner_texts()[:40] if h.strip()]
        flagged = bool(INJECTION_PATTERN.search(text))
        limitations = ["page content is untrusted; visiting a page does not establish that it is accurate"]
        if flagged:
            limitations.append(
                "page contains text addressed to an AI agent; it was treated as data and not followed"
            )
        status = m.EXTRACTED if self.policy.mode == "research" else m.DIRECTLY_OBSERVED
        item = self._evidence(
            kind="web_page" if self.policy.mode == "research" else "lab_observation",
            excerpt=" ".join(text.split())[:900],
            observation={
                "title": title,
                "url": self.page.url,
                "headings": headings,
                "text": text[:20000],
                "prompt_injection_suspected": flagged,
                "changed_state": False,
            },
            location=f"{title or 'page'} ({self.page.url})",
            limitations=limitations,
            status=status,
        )
        self._log(
            "read",
            url=self.page.url,
            outcome="ok",
            changed_state=False,
            decision="auto",
            title=title,
            evidence_ids=[item.evidence_id],
        )
        return item

    def screenshot(self, label: str = "page") -> m.EvidenceItem:
        self._require_running()
        directory = self.workspace.cache_dir("browser")
        safe = re.sub(r"[^a-z0-9_-]+", "-", label.lower())[:40] or "page"
        path = directory / f"{utc_now().replace(':', '')}-{safe}.png"
        self.page.screenshot(path=str(path), full_page=True)
        os.chmod(path, 0o600)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        title = self.page.title()
        item = self._evidence(
            kind="screenshot",
            excerpt=f"screenshot of {title or self.page.url}",
            observation={
                "title": title,
                "url": self.page.url,
                "file": path.name,
                "sha256": digest,
                "changed_state": False,
            },
            location=f"screenshot {path.name}",
            limitations=["image content is not described automatically"],
            status=m.DIRECTLY_OBSERVED,
        )
        self._log(
            "screenshot",
            url=self.page.url,
            outcome="ok",
            changed_state=False,
            decision="auto",
            title=title,
            evidence_ids=[item.evidence_id],
        )
        return item

    # --- state-changing actions (interactive, approval required) -----------------

    def request(
        self, kind: str, selector: str, value: str | None = None, *, secret_env: str | None = None
    ) -> str:
        """Queue a state-changing action. Returns its id; nothing happens until approve()."""
        self._require_running()
        if kind not in STATE_CHANGING:
            raise BrowserPolicyError(f"unknown action {kind!r}")
        if self.policy.mode != "interactive":
            raise BrowserPolicyError(f"{kind} is not permitted in {self.policy.mode} mode (read-only)")
        url = self.page.url
        if origin_of(url) not in self.policy.interactive_origins:
            raise BrowserPolicyError(f"{origin_of(url)} is not an approved interactive lab origin")
        label = self._describe(selector)
        if SUBMISSION_PATTERN.search(f"{selector} {label}"):
            self._log(
                kind,
                url=url,
                target=f"{selector} ({label})",
                outcome="blocked",
                changed_state=False,
                decision="denied",
                error="submitting graded work is never automated",
            )
            raise BrowserPolicyError(
                "refused: this control appears to submit graded work; the user must do that"
            )
        action = m.BrowserAction(
            action_id="act-" + uuid.uuid4().hex[:12],
            mode="interactive",
            kind=kind,
            url=url,
            target=f"{selector} ({label})"[:300],
            value_redacted=bool(secret_env),
            requested_at=utc_now(),
            decision="pending",
        )
        self.pending[action.action_id] = PendingAction(
            action, selector, None if secret_env else value, secret_env
        )
        return action.action_id

    def _describe(self, selector: str) -> str:
        try:
            locator = self.page.locator(selector).first
            text = (
                locator.inner_text(timeout=3000)
                or locator.get_attribute("value", timeout=1000)
                or locator.get_attribute("aria-label", timeout=1000)
                or ""
            )
            return " ".join(text.split())[:120]
        except Exception:
            return ""

    def deny(self, action_id: str, reason: str = "denied by the user") -> m.BrowserAction:
        pending = self.pending.pop(action_id, None)
        if pending is None:
            raise BrowserPolicyError(f"no pending action {action_id}")
        action = pending.action
        action.decision, action.decided_at, action.outcome, action.error = (
            "denied",
            utc_now(),
            "blocked",
            reason,
        )
        self.workspace.append_action(action)
        return action

    def approve(self, action_id: str) -> m.BrowserAction:
        self._require_running()
        pending = self.pending.pop(action_id, None)
        if pending is None:
            raise BrowserPolicyError(f"no pending action {action_id}")
        action = pending.action
        action.decision, action.decided_at = "approved", utc_now()
        before = self._snapshot()
        self._executing = action_id
        try:
            locator = self.page.locator(pending.selector).first
            if action.kind == "click":
                locator.click(timeout=10_000)
            elif action.kind == "fill":
                value = (
                    os.environ.get(pending.secret_env, "") if pending.secret_env else (pending.value or "")
                )
                locator.fill(value, timeout=10_000)
            elif action.kind == "press":
                locator.press(pending.value or "Enter", timeout=10_000)
            elif action.kind == "select":
                locator.select_option(pending.value or "", timeout=10_000)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass
            action.outcome = "ok"
        except Exception as error:
            action.outcome, action.error = "failed", f"{type(error).__name__}: {str(error)[:200]}"
        finally:
            self._executing = None
        action.performed_at = utc_now()
        after = self._snapshot()
        action.page_title = after.get("title", "")[:200]
        action.changed_state = action.kind in ("click", "press", "select") or before != after
        if action.outcome == "ok":
            item = self._evidence(
                kind="lab_action_result",
                excerpt=f"after {action.kind} on {action.target}: "
                + " ".join(after.get("text", "").split())[:700],
                observation={
                    "title": after.get("title", ""),
                    "url": self.page.url,
                    "action_id": action.action_id,
                    "action": action.kind,
                    "target": action.target,
                    "text": after.get("text", "")[:20000],
                    "changed_state": action.changed_state,
                    "performed_by": "HowlWriter browser automation, approved by the user",
                },
                location=f"lab result after action {action.action_id}",
                limitations=[
                    "this result was produced by automation the user approved, not performed by hand"
                ],
                status=m.DIRECTLY_OBSERVED,
            )
            action.evidence_ids = [item.evidence_id]
        self.workspace.append_action(action)
        return action

    def _snapshot(self) -> dict:
        try:
            return {
                "url": self.page.url,
                "title": self.page.title(),
                "text": self.page.inner_text("body", timeout=5000)[:MAX_PAGE_TEXT],
            }
        except Exception:
            return {}

    def status(self) -> dict:
        return {
            "state": self.state,
            "policy": self.policy.to_dict(),
            "session_id": self.session_id,
            "url": self.page.url if self.page is not None else "",
            "pending": [p.action.to_dict() for p in self.pending.values()],
            "blocked": self.blocked[-20:],
        }


class BrowserController:
    """Runs one BrowserSession on its own thread (Playwright's sync API is thread-bound).

    Web routes and other threads call `call(name, *args)`; the call runs on
    the browser thread and its result or exception comes back.
    """

    def __init__(self, session: BrowserSession) -> None:
        import queue

        self.session = session
        self._jobs: "queue.Queue" = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="howlwriter-browser", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            name, args, kwargs, done = job
            try:
                done["result"] = getattr(self.session, name)(*args, **kwargs)
            except Exception as error:
                done["error"] = error
            done["event"].set()

    def call(self, name: str, *args, timeout: float = 120.0, **kwargs):
        done: dict[str, Any] = {"event": threading.Event()}
        self._jobs.put((name, args, kwargs, done))
        if not done["event"].wait(timeout):
            raise TimeoutError(f"browser call {name} did not finish in {timeout:.0f} s")
        if "error" in done:
            raise done["error"]
        return done.get("result")

    def close(self) -> None:
        try:
            self.call("stop", timeout=30)
        finally:
            self._jobs.put(None)
            self._thread.join(timeout=10)
