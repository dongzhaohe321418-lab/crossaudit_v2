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
from .page import PAGE
from .streams import both

IDLE_TIMEOUT_S = 900.0
MAX_UTTERANCE = 4000
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def snapshot(cfg: Config) -> dict:
    from .. import admission as adm
    from .. import skills as skills_mod

    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    cycles = store.snapshot().get("cycles", {})
    caps = store.capabilities()
    tier = adm.assess(root=cfg.root, paired=bool(cfg.audit_repo),
                      controller_persistent=caps["persistent"],
                      controller_atomic=caps["atomic"], online=False)
    const = cfg.root / cfg.constitution
    gen_stream, aud_stream = both(cfg)
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
                    "sha": c["active_sha"]} for cid, c in sorted(cycles.items())],
        "tier": tier.as_dict(),
        "routing": routing_history(cfg.root / cfg.ledger_dir / "routing.jsonl", 40),
        "generator_stream": gen_stream,
        "auditor_stream": aud_stream,
    }


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
    log = talk_mod._routing_path(cfg)
    if not routing.certain:
        router_mod.record(log, routing, "asked for clarification")
        return {"asked": True, "lane": routing.lane, "confidence": routing.confidence,
                "reasoning": routing.reasoning,
                "clarify": routing.clarify or "Is this about the work, or about the "
                                              "standards it is judged by?"}
    lanes = {
        "amendment": lambda: talk_mod.lane_amendment(cfg, routing, assume_yes=True),
        "query": lambda: talk_mod.lane_query(cfg, routing),
        "generator": lambda: talk_mod.lane_generator(cfg, routing),
        "dispute": lambda: talk_mod.lane_dispute(cfg, routing),
        "resolve": lambda: talk_mod.lane_resolve(cfg, routing, assume_yes=True),
        "project": lambda: talk_mod.lane_project(cfg, routing),
    }
    try:
        executed = lanes[routing.lane]()
    except Denial as exc:
        router_mod.record(log, routing, f"denied: {exc.reason}")
        return {"asked": False, "lane": routing.lane, "confidence": routing.confidence,
                "reasoning": routing.reasoning, "executed": f"refused — {exc.reason}"}
    router_mod.record(log, routing, executed)
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
            else:
                self._deny(404, "no such page")

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
            self._send(json.dumps(result).encode(), "application/json")

        def log_message(self, *args) -> None:                       # noqa: D102
            pass

    return Handler


def serve(cfg: Config, port: int = 0) -> tuple[str, ThreadingHTTPServer]:
    """Start the console. Returns (url carrying the session token, server)."""
    token = secrets.token_urlsafe(24)
    last = [time.monotonic()]

    def touch() -> None:
        last[0] = time.monotonic()

    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, token, touch))

    def idle_watch() -> None:
        while True:
            time.sleep(5)
            if time.monotonic() - last[0] > IDLE_TIMEOUT_S:
                httpd.shutdown()
                return

    threading.Thread(target=idle_watch, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}/?t={token}", httpd
