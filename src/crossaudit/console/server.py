"""`crossaudit console` — the ledger, read-only, in a browser (DESIGN.md P1).

The box is opaque to interact with and glass on the inside; this is the window.
It renders what the CLI already emits, on stdlib alone, and it cannot do
anything the CLI could not — that is the console's iron rule inherited from the
paper's roadmap: the front-end writes nothing of its own.

Opening a port inside a tool that holds API keys is a real attack surface, so
the defences are not optional:

* **loopback only.** Bound to 127.0.0.1, never 0.0.0.0.
* **a per-session token on every request, and no cookies.** Without cookie
  auth there is nothing for a foreign page to ride: CSRF needs a credential the
  browser attaches automatically, and there is none.
* **Host header pinned to localhost.** This is the DNS-rebinding defence: an
  attacker's domain resolving to 127.0.0.1 still arrives with the wrong Host.
* **a strict CSP with everything inline.** No external fetches, so nothing on
  the page can exfiltrate what it renders.
* **read-only, structurally.** There is no write path in this module; the
  routes call the same read functions `status`, `routing` and `watch` use.
* **keys are never rendered.** The console reports whether a key is present,
  never its value, and the receipt view shows bindings, not credentials.
* **idle shutdown.** A forgotten port closes itself.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import Config
from ..controller import StateStore
from ..router import history as routing_history

IDLE_TIMEOUT_S = 900.0
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"}

PAGE = """<!doctype html>
<meta charset="utf-8"><title>CrossAudit — ledger</title>
<style>
:root{color-scheme:light dark;--fg:#111;--dim:#666;--line:#ddd;--bg:#fff;
--red:#c0392b;--green:#1e8449;--amber:#b9770e;--blue:#2874a6}
@media(prefers-color-scheme:dark){:root{--fg:#e6e6e6;--dim:#999;--line:#333;--bg:#151515}}
body{font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
margin:0;color:var(--fg);background:var(--bg)}
header{padding:16px 24px;border-bottom:1px solid var(--line)}
h1{font-size:15px;margin:0;font-weight:600}
.sub{color:var(--dim);font-size:12px;margin-top:3px}
main{display:grid;grid-template-columns:minmax(240px,1fr) 2fr;gap:0;
min-height:calc(100vh - 62px)}
section{padding:18px 24px;overflow:auto}
section+section{border-left:1px solid var(--line)}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);
margin:0 0 10px;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{padding:5px 8px 5px 0;text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:500;border-bottom:1px solid var(--line)}
tr+tr td{border-top:1px solid var(--line)}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.PASS,.PASSED,.CONSUMED{color:var(--green)}.BLOCKED{color:var(--red)}
.ESCALATED,.DCL_ONLY{color:var(--amber)}.OPEN{color:var(--blue)}
.pill{display:inline-block;padding:1px 7px;border:1px solid var(--line);
border-radius:9px;font-size:11px;color:var(--dim)}
.u{color:var(--dim);font-size:12px;margin-top:2px}
.empty{color:var(--dim);font-style:italic}
footer{padding:10px 24px;border-top:1px solid var(--line);color:var(--dim);font-size:12px}
</style>
<header>
  <h1>CrossAudit — ledger</h1>
  <div class="sub" id="sub">read-only · loopback only · nothing here can change anything</div>
</header>
<main>
  <section>
    <h2>Cycles</h2><div id="cycles"></div>
    <h2 style="margin-top:22px">Admission</h2><div id="tier"></div>
  </section>
  <section>
    <h2>Routing decisions</h2><div id="routing"></div>
    <h2 style="margin-top:22px">Exchange</h2><div id="watch"></div>
  </section>
</main>
<footer>Everything on this page came from git and the controller's store.
Actions live in the CLI, deliberately: this window writes nothing.</footer>
<script>
const T = new URLSearchParams(location.search).get('t') || '';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function get(p){const r = await fetch(p + '?t=' + encodeURIComponent(T));
  if(!r.ok) throw new Error(r.status); return r.json();}
function table(head, rows){
  if(!rows.length) return '<div class="empty">nothing yet</div>';
  return '<table><tr>' + head.map(h => '<th>' + esc(h) + '</th>').join('') + '</tr>'
    + rows.join('') + '</table>';}
async function draw(){
  try{
    const d = await get('/api/state');
    document.getElementById('sub').textContent =
      d.project + ' · ' + d.rules + ' rules · auditor ' + d.auditor
      + ' · key ' + (d.key_present ? 'present' : 'absent');
    document.getElementById('cycles').innerHTML = table(
      ['cycle','status','round','commit'],
      d.cycles.map(c => '<tr><td class="mono">' + esc(c.id.slice(0,8)) + '</td>'
        + '<td class="' + esc(c.status) + '">' + esc(c.status) + '</td>'
        + '<td>' + c.round + '</td><td class="mono">' + esc(c.sha.slice(0,12))
        + '</td></tr>'));
    document.getElementById('tier').innerHTML =
      '<div><span class="pill">' + esc(d.tier.tier) + '</span> ' + esc(d.tier.means)
      + '</div>' + (d.tier.shortfalls.length
        ? '<div class="u">toward enforced:<ul style="margin:4px 0 0 16px;padding:0">'
          + d.tier.shortfalls.map(s => '<li>' + esc(s) + '</li>').join('') + '</ul></div>'
        : '');
    document.getElementById('routing').innerHTML = table(
      ['lane','conf','what was said / done'],
      d.routing.map(r => '<tr><td>' + esc(r.lane) + '</td><td>'
        + Math.round(r.confidence*100) + '%</td><td>' + esc(r.utterance)
        + '<div class="u">→ ' + esc(r.executed) + '</div></td></tr>'));
    document.getElementById('watch').innerHTML = table(
      ['time','lane','event'],
      d.events.map(e => '<tr><td class="mono">' + esc(e[0]) + '</td><td>'
        + esc(e[1]) + '</td><td>' + esc(e[2]) + '</td></tr>'));
  }catch(e){
    document.getElementById('sub').textContent =
      'disconnected (' + e.message + ') — the console closes itself when idle';
  }
}
draw(); setInterval(draw, 4000);
</script>
"""


def snapshot(cfg: Config) -> dict:
    """Everything the page renders, from the ledger and the store."""
    import os

    from .. import admission as adm
    from ..cli.watch import gather

    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    cycles = store.snapshot().get("cycles", {})
    caps = store.capabilities()
    tier = adm.assess(root=cfg.root, paired=bool(cfg.audit_repo),
                      controller_persistent=caps["persistent"],
                      controller_atomic=caps["atomic"], online=False)
    const = cfg.root / cfg.constitution
    rules = const.read_text().count("\n### ") if const.is_file() else 0
    return {
        "project": cfg.science_repo,
        "rules": rules,
        "auditor": f"{cfg.auditor.provider}:{cfg.auditor.model}",
        # Presence, never the value: a console that can show a key is a console
        # that can leak one.
        "key_present": bool(os.environ.get(cfg.auditor.key_env, "").strip()),
        "cycles": [{"id": cid, "status": c["status"], "round": c["round"],
                    "sha": c["active_sha"]} for cid, c in sorted(cycles.items())],
        "tier": tier.as_dict(),
        "routing": routing_history(cfg.root / cfg.ledger_dir / "routing.jsonl", 40),
        "events": gather(cfg).get("events", [])[-40:],
    }


def make_handler(cfg: Config, token: str, touch) -> type:
    class Handler(BaseHTTPRequestHandler):
        server_version = "crossaudit-console"

        def _deny(self, code: int, why: str) -> None:
            self.send_response(code)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(why.encode())

        def _authorised(self, query: dict) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in ALLOWED_HOSTS:
                return False                    # DNS rebinding arrives with a foreign Host
            supplied = (query.get("t") or [""])[0]
            return secrets.compare_digest(supplied, token)

        def do_GET(self) -> None:               # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if not self._authorised(query):
                self._deny(403, "forbidden: this console is loopback-only and needs "
                                "the session token from the URL it printed")
                return
            touch()
            if parsed.path == "/":
                body = PAGE.encode()
                ctype = "text/html; charset=utf-8"
            elif parsed.path == "/api/state":
                body = json.dumps(snapshot(cfg)).encode()
                ctype = "application/json"
            else:
                self._deny(404, "no such page")
                return
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

        def do_POST(self) -> None:               # noqa: N802
            # Structural, not a policy: there is no write path in this module.
            self._deny(405, "this console is read-only; actions live in the CLI")

        def log_message(self, *args) -> None:    # noqa: D102
            pass

    return Handler


def serve(cfg: Config, port: int = 0) -> tuple[str, ThreadingHTTPServer]:
    """Start the console. Returns (url with token, server)."""
    token = secrets.token_urlsafe(24)
    last = [time.monotonic()]

    def touch() -> None:
        last[0] = time.monotonic()

    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, token, touch))
    actual = httpd.server_address[1]

    def idle_watch() -> None:
        while True:
            time.sleep(5)
            if time.monotonic() - last[0] > IDLE_TIMEOUT_S:
                httpd.shutdown()
                return

    threading.Thread(target=idle_watch, daemon=True).start()
    return f"http://127.0.0.1:{actual}/?t={token}", httpd
