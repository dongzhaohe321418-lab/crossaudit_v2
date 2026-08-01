"""Keeping the console alive across a closed window, and finding it again.

Closing a browser tab never stopped a build — it runs in a thread of the console
process. What stopped it was closing the terminal. So the console can now detach
from the terminal that started it, and a later `crossaudit console` finds the
running one and hands back its URL instead of starting a second server.

Three things this has to get right, and each is a small honesty problem:

* **Reattaching, not restarting.** Two consoles on one project would race on the
  working tree and the round budget. If a live daemon is found, its URL is
  returned; the second invocation starts nothing.
* **A stale run file is not a running daemon.** A crash leaves the file behind,
  so liveness is proven by asking the port, not by trusting the file.
* **An interrupted build must say so.** The tracker is in memory and dies with
  the process; the ledger keeps every committed round but cannot know a run was
  cut off mid-round. A flag written when a build starts, and removed when it
  ends, lets a restarted console say "this was interrupted" rather than quietly
  presenting a half-finished loop as finished.

The run file holds a session token, so it is written 0600 and lives in the state
directory, which is gitignored: a credential in the ledger would be a credential
published.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import Config

RUN_FILE = "console.json"
BUILD_FLAG = "build-in-flight.json"


def run_path(cfg: Config) -> Path:
    return cfg.root / cfg.state_dir / RUN_FILE


def flag_path(cfg: Config) -> Path:
    return cfg.root / cfg.state_dir / BUILD_FLAG


# ------------------------------------------------------------------ run file
def write_run(cfg: Config, *, pid: int, port: int, token: str) -> Path:
    p = run_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pid": pid, "port": port, "token": token,
                             "started": int(time.time()),
                             "root": str(cfg.root)}, indent=1))
    p.chmod(0o600)                     # it carries the session token
    return p


def read_run(cfg: Config) -> dict | None:
    p = run_path(cfg)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def clear_run(cfg: Config) -> None:
    run_path(cfg).unlink(missing_ok=True)


def responding(port: int, token: str, timeout: float = 1.5) -> bool:
    """Liveness is proven by the port answering, never by the file existing."""
    url = f"http://127.0.0.1:{port}/api/state?t={token}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def live(cfg: Config) -> dict | None:
    """The running console for this project, if there is one."""
    info = read_run(cfg)
    if not info:
        return None
    if not responding(info["port"], info["token"]):
        clear_run(cfg)                 # stale: the process is gone
        return None
    return info


def url_for(info: dict) -> str:
    return f"http://127.0.0.1:{info['port']}/?t={info['token']}"


# -------------------------------------------------------------------- detach
def spawn(cfg: Config, port: int) -> dict:
    """Start a console detached from this terminal, and wait for it to answer.

    A new session means the daemon does not receive the terminal's SIGHUP when
    the window closes, which is the whole point.
    """
    env = dict(os.environ, CROSSAUDIT_CONSOLE_CHILD="1")
    log = cfg.root / cfg.state_dir / "console.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as fh:
        subprocess.Popen(
            [sys.executable, "-m", "crossaudit.cli.main", "console",
             "--port", str(port), "--foreground"],
            cwd=str(cfg.root), env=env, stdout=fh, stderr=fh,
            stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):                # up to ~6s for the port to come up
        time.sleep(0.1)
        info = read_run(cfg)
        if info and responding(info["port"], info["token"]):
            return info
    raise TimeoutError(f"the console did not come up; see {log}")


def stop(cfg: Config) -> str:
    info = read_run(cfg)
    if not info:
        return "no console was running"
    pid = info.get("pid")
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, TypeError):
        clear_run(cfg)
        return "no console was running (stale record cleared)"
    for _ in range(30):
        time.sleep(0.1)
        if not responding(info["port"], info["token"]):
            break
    clear_run(cfg)
    return f"stopped the console on port {info['port']}"


# ------------------------------------------------------- interrupted builds
def mark_build(cfg: Config, task: str) -> None:
    p = flag_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"task": task, "started": int(time.time()),
                             "pid": os.getpid()}))


def unmark_build(cfg: Config) -> None:
    flag_path(cfg).unlink(missing_ok=True)


def interrupted(cfg: Config) -> dict | None:
    """A build that was in flight when the process ended.

    The ledger holds the rounds that were committed; what it cannot know is that
    a round was cut off. This says so rather than letting a half-finished loop
    read as a finished one.
    """
    p = flag_path(cfg)
    if not p.is_file():
        return None
    try:
        info = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    pid = info.get("pid")
    if pid and pid != os.getpid():
        try:
            os.kill(pid, 0)            # still alive: it is running, not interrupted
            return None
        except ProcessLookupError:
            pass
        except PermissionError:
            return None
    elif pid == os.getpid():
        return None
    return info
