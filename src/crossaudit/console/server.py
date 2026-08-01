"""`crossaudit console` — two windows, one input, and the ledger between them.

The generator is the main window, the auditor the side window, and the single
input at the bottom is the black box: you type as you would to any assistant and
the router decides which side hears it. The routing decision is shown where it
happened, because a box whose sorting is invisible is asking for trust it has
not earned.

Opening a port inside a tool that holds API keys is a real attack surface, and
the defences are structural rather than promised:

* **loopback only**, bound to 127.0.0.1.
* **a per-session token on every request, and no cookies at all.** CSRF needs a
  credential the browser attaches for you; there is none to ride.
* **Host pinned to localhost**, which is what turns away DNS rebinding.
* **a strict inline-only CSP**, so nothing on the page can fetch or exfiltrate.
* **one write path, and it is narrow.** `/api/say` accepts a sentence and
  nothing else, and hands it to the same router `crossaudit talk` uses. The
  console can cause nothing the CLI could not — that is the console rule.
* **keys are reported present or absent, never rendered.**
* **idle shutdown**, so a forgotten port closes itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..config import Config
from ..controller import StateStore
from ..errors import Denial
from ..router import history as routing_history
from . import daemon, overview
from .page import PAGE
from .progress import TRACKER
from .streams import both

IDLE_TIMEOUT_S = 900.0
STREAM_POLL_S = 0.1          # fallback for changes made by another local process
STREAM_HEARTBEAT_S = 15.0
MAX_UTTERANCE = 4000
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


class _ChangeSignal:
    """A versioned wake-up shared by every live SSE connection."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._version = 0

    def current(self) -> int:
        with self._condition:
            return self._version

    def notify(self) -> None:
        with self._condition:
            self._version += 1
            self._condition.notify_all()

    def wait(self, version: int, timeout: float) -> int:
        with self._condition:
            self._condition.wait_for(lambda: self._version != version,
                                     timeout=timeout)
            return self._version


STREAM_CHANGES = _ChangeSignal()
TRACKER.subscribe(STREAM_CHANGES.notify)


def snapshot(cfg: Config) -> dict:
    from .. import admission as adm
    from .. import skills as skills_mod

    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    states = store.snapshot().get("cycles", {})
    caps = store.capabilities()
    tier = adm.assess(root=cfg.root, paired=bool(cfg.audit_repo),
                      controller_persistent=caps["persistent"],
                      controller_atomic=caps["atomic"], online=False)
    const = cfg.root / cfg.constitution
    gen_stream, aud_stream = both(cfg)
    audits = overview.read_cycles(cfg)
    try:
        house = [s.name for s in skills_mod.load(cfg.root)]
    except Denial:
        house = []
    return {
        "project": cfg.science_repo,
        "rules": const.read_text().count("\n### ") if const.is_file() else 0,
        "skills": house,
        "auditor": f"{cfg.auditor.provider}:{cfg.auditor.model}",
        "generator": cfg.generator_vendor or "unset",
        # Presence, never the value: a console that can show a key can leak one.
        "key_present": bool(os.environ.get(cfg.auditor.key_env, "").strip()),
        "cycles": [{"id": cid, "status": c["status"], "round": c["round"],
                    "sha": c["active_sha"]} for cid, c in sorted(states.items())],
        "tier": tier.as_dict(),
        # Every figure below is derived from the ledger; where it cannot answer,
        # the answer is absent rather than a confident zero.
        "metrics": overview.metrics(cfg, audits),
        "pipeline": overview.pipeline(cfg, audits),
        "findings": overview.findings_by_severity(audits),
        "top_rules": overview.top_rules(audits),
        "escalations": overview.escalations(cfg),
        "disputes": overview.disputes(cfg),
        "routing": routing_history(cfg.root / cfg.ledger_dir / "routing.jsonl", 40),
        "generator_stream": gen_stream,
        "auditor_stream": aud_stream,
        # In-flight work, if any. Ephemeral by construction: the ledger is still
        # the record, and this vanishes with the process.
        "progress": TRACKER.snapshot(),
        # A build that was in flight when a previous process ended. The ledger
        # holds the rounds that were committed; only this can say one was cut off.
        "interrupted": daemon.interrupted(cfg),
    }


def start_build(cfg: Config, task: str, *, before_start=None) -> dict:
    """Run a build in the background so the browser can watch it happen.

    The loop is the same one the CLI runs — the console watches it, it does not
    reimplement it, because a second copy could drift on the only thing that
    matters: when the loop stops.
    """
    import threading

    from ..cli.build import preflight, resolve_task, run_loop

    preflight(cfg)
    resolved = resolve_task(cfg, task.split())
    if before_start is not None:
        # The console uses this seam to commit its routing decision before the
        # worker thread can begin making generator/auditor commits.
        before_start(resolved)
    run = TRACKER.start(resolved)
    daemon.mark_build(cfg, resolved)

    def work() -> None:
        try:
            code = run_loop(cfg, resolved,
                            on_step=lambda a, txt, d="": TRACKER.step(a, txt, d))
            TRACKER.finish({0: "passed", 11: "escalated"}.get(code, "blocked"))
        except Denial as exc:
            TRACKER.finish("refused", exc.reason)
        except Exception as exc:                                  # noqa: BLE001
            TRACKER.finish("failed", f"{type(exc).__name__}: {exc}")
        finally:
            daemon.unmark_build(cfg)

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "task": resolved.splitlines()[0][:80]}


def say(cfg: Config, text: str) -> dict:
    """Route one sentence and run its lane — the same path `talk` takes.

    Confirmations are assumed here because the browser is the confirmation: a
    person typed the sentence and pressed a button. Everything else, including
    the refusal to act below the confidence floor, is unchanged.
    """
    from .. import router as router_mod
    from ..cli import talk as talk_mod

    routing = router_mod.route(text, complete=talk_mod._auditor_complete(cfg),
                               context=talk_mod._context(cfg))
    if not routing.certain:
        talk_mod._record_routing(cfg, routing, "asked for clarification")
        return {"asked": True, "lane": routing.lane, "confidence": routing.confidence,
                "reasoning": routing.reasoning,
                "clarify": routing.clarify or "Is this about the work, or about the "
                                              "standards it is judged by?"}
    def generator_lane() -> str:
        if TRACKER.running:
            return ("a build is already running; watch it above, or wait for it "
                    "to finish")
        def record_before_start(resolved: str) -> None:
            nonlocal route_recorded
            talk_mod._record_routing(
                cfg, routing, f"building: {resolved.splitlines()[0][:80]}")
            route_recorded = True

        started = start_build(cfg, routing.restated,
                              before_start=record_before_start)
        return f"building: {started['task']}"

    route_recorded = False
    lanes = {
        "amendment": lambda: talk_mod.lane_amendment(cfg, routing, assume_yes=True),
        "query": lambda: talk_mod.lane_query(cfg, routing),
        "generator": generator_lane,
        "dispute": lambda: talk_mod.lane_dispute(cfg, routing),
        "resolve": lambda: talk_mod.lane_resolve(cfg, routing, assume_yes=True),
        "project": lambda: talk_mod.lane_project(cfg, routing),
    }
    try:
        executed = lanes[routing.lane]()
    except Denial as exc:
        if not route_recorded:
            talk_mod._record_routing(cfg, routing, f"denied: {exc.reason}")
        return {"asked": False, "lane": routing.lane, "confidence": routing.confidence,
                "reasoning": routing.reasoning, "executed": f"refused — {exc.reason}"}
    if not route_recorded:
        talk_mod._record_routing(cfg, routing, executed)
    return {"asked": False, "lane": routing.lane, "confidence": routing.confidence,
            "reasoning": routing.reasoning, "executed": executed}


def make_handler(cfg: Config, token: str, touch) -> type:
    class Handler(BaseHTTPRequestHandler):
        server_version = "crossaudit-console"

        def _deny(self, code: int, why: str) -> None:
            body = why.encode()
            self.send_response(code)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.send_header("content-security-policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'")
            self.send_header("referrer-policy", "no-referrer")
            self.send_header("x-content-type-options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self, query: dict) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in ALLOWED_HOSTS:
                return False           # rebinding arrives with someone else's Host
            return secrets.compare_digest((query.get("t") or [""])[0], token)

        def do_GET(self) -> None:                                   # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorised(parse_qs(parsed.query)):
                self._deny(403, "forbidden: loopback-only, and the session token "
                                "from the printed URL is required")
                return
            touch()
            if parsed.path == "/":
                self._send(PAGE.encode(), "text/html; charset=utf-8")
            elif parsed.path == "/api/state":
                self._send(json.dumps(snapshot(cfg)).encode(), "application/json")
            elif parsed.path == "/api/stream":
                self._stream(cfg, touch)
            else:
                self._deny(404, "no such page")

        def _stream(self, cfg: Config, touch) -> None:
            """Push a snapshot whenever anything changes.

            The server re-derives often and sends rarely: a frame goes out only
            when the digest moves, so an idle project costs one heartbeat every
            fifteen seconds rather than a stream of identical payloads. Each push
            counts as activity, otherwise a browser watching a long build in
            silence would look idle and the console would shut itself down.
            """
            self.send_response(200)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("connection", "close")
            self.send_header("content-security-policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            last_digest = ""
            last_beat = time.monotonic()
            change_version = STREAM_CHANGES.current()
            try:
                while True:
                    payload = json.dumps(snapshot(cfg), sort_keys=True)
                    digest = hashlib.sha256(payload.encode()).hexdigest()
                    now = time.monotonic()
                    if digest != last_digest:
                        self.wfile.write(f"data: {payload}\n\n".encode())
                        self.wfile.flush()
                        last_digest, last_beat = digest, now
                        touch()
                    elif now - last_beat > STREAM_HEARTBEAT_S:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_beat = now
                        touch()
                    # Progress produced in this process wakes every connection
                    # immediately. The short timeout only catches git/controller
                    # writes made by another local CrossAudit process.
                    change_version = STREAM_CHANGES.wait(change_version,
                                                         STREAM_POLL_S)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return                      # the tab closed; nothing to clean up

        def do_POST(self) -> None:                                  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorised(parse_qs(parsed.query)):
                self._deny(403, "forbidden")
                return
            if parsed.path != "/api/say":
                self._deny(404, "the only write path here is /api/say")
                return
            touch()
            try:
                length = int(self.headers.get("content-length", 0))
            except ValueError:
                self._deny(400, "bad length")
                return
            if length > MAX_UTTERANCE:
                self._deny(413, "that is longer than anything this input is for")
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                text = str(payload.get("text", "")).strip()
            except (json.JSONDecodeError, ValueError):
                self._deny(400, "expected {\"text\": \"...\"}")
                return
            if not text:
                self._deny(400, "say something")
                return
            try:
                result = say(cfg, text)
            except Denial as exc:
                self._deny(400, exc.reason)
                return
            # Routing, amendments, disputes and resolutions change files other
            # than the in-memory progress tracker. Publish those immediately too.
            STREAM_CHANGES.notify()
            self._send(json.dumps(result).encode(), "application/json")

        def log_message(self, *args) -> None:                       # noqa: D102
            pass

    return Handler


def serve(cfg: Config, port: int = 0, *,
          idle_timeout: float = IDLE_TIMEOUT_S,
          register: bool = False) -> tuple[str, ThreadingHTTPServer]:
    """Start the console. Returns (url carrying the session token, server)."""
    token = secrets.token_urlsafe(24)
    last = [time.monotonic()]

    def touch() -> None:
        last[0] = time.monotonic()

    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, token, touch))

    def idle_watch() -> None:
        while True:
            time.sleep(5)
            # A closed window must never end a running build: idleness is only
            # grounds for shutting down when there is nothing in flight.
            if TRACKER.running:
                last[0] = time.monotonic()
                continue
            if time.monotonic() - last[0] > idle_timeout:
                httpd.shutdown()
                return

    threading.Thread(target=idle_watch, daemon=True).start()
    port_in_use = httpd.server_address[1]
    if register:
        # So a later invocation can find this console rather than start a rival.
        daemon.write_run(cfg, pid=os.getpid(), port=port_in_use, token=token)
    return f"http://127.0.0.1:{port_in_use}/?t={token}", httpd
