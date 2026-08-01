"""The console outliving its terminal, and being found again afterwards.

Closing a window was never supposed to end a build. These tests hold the three
things that makes true: a second invocation reattaches instead of racing, a
stale record is not mistaken for a running process, and a build cut off
mid-round says so rather than reading as finished.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from crossaudit.config import load
from crossaudit.console import daemon, serve
from crossaudit.console.progress import Tracker

CONFIG = (
    "version: 1\nscience_repo: t/p\nconstitution: AUDIT_RULES.md\n"
    "auditor: {vendor: openai, provider: openai_compat, model: m,"
    " key_env: CROSSAUDIT_AUDITOR_KEY}\ngenerator: {vendor: anthropic}\n"
    "scope: {dirs: [work]}\nledger: {dir: cycles}\nstate: {dir: .crossaudit}\n"
    "checks: [parseable]\n")


@pytest.fixture()
def cfg(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / "AUDIT_RULES.md").write_text("### CA-X-001\n**BLOCKER.** be exact\n\nx\n")
    (root / "crossaudit.yml").write_text(CONFIG)
    return load(root / "crossaudit.yml")


@pytest.fixture()
def running(cfg):
    url, httpd = serve(cfg, port=0, register=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield cfg, url
    httpd.shutdown()
    daemon.clear_run(cfg)


# ------------------------------------------------------------- finding it again
def test_a_running_console_can_be_found_by_a_later_invocation(running):
    cfg, url = running
    info = daemon.live(cfg)
    assert info is not None
    assert daemon.url_for(info) == url          # the same URL, token and all
    assert info["pid"] == os.getpid()


def test_the_run_file_is_not_world_readable(running):
    """It carries a session token; a credential readable by anyone on the box is
    a credential."""
    cfg, _url = running
    mode = daemon.run_path(cfg).stat().st_mode & 0o777
    assert mode == 0o600


def test_the_run_file_lives_outside_the_ledger(cfg, running):
    """A token committed to the ledger would be a token published."""
    _cfg, _url = running
    assert daemon.run_path(cfg).is_relative_to(cfg.root / cfg.state_dir)
    assert cfg.state_dir not in (cfg.ledger_dir,)


def test_nothing_is_found_when_nothing_is_running(cfg):
    assert daemon.live(cfg) is None


def test_a_stale_record_is_not_a_running_console(cfg):
    """A crash leaves the file behind; liveness is proven by the port answering,
    never by the file existing."""
    daemon.write_run(cfg, pid=999999, port=1, token="stale")
    assert daemon.read_run(cfg) is not None      # the file is there
    assert daemon.live(cfg) is None              # and it means nothing
    assert not daemon.run_path(cfg).exists()     # and it is cleaned up


def test_a_corrupt_record_is_survived(cfg):
    p = daemon.run_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert daemon.read_run(cfg) is None and daemon.live(cfg) is None


def test_stopping_when_nothing_runs_says_so(cfg):
    assert "no console" in daemon.stop(cfg)


# -------------------------------------------------------- interrupted builds
def test_a_build_in_flight_from_a_dead_process_reads_as_interrupted(cfg):
    daemon.mark_build(cfg, "write the section")
    # Rewrite the flag as if another, now-dead process had left it.
    flag = json.loads(daemon.flag_path(cfg).read_text())
    flag["pid"] = 999999
    daemon.flag_path(cfg).write_text(json.dumps(flag))
    found = daemon.interrupted(cfg)
    assert found and found["task"] == "write the section"


def test_our_own_running_build_is_not_reported_as_interrupted(cfg):
    daemon.mark_build(cfg, "still going")
    assert daemon.interrupted(cfg) is None


def test_a_finished_build_leaves_nothing_behind(cfg):
    daemon.mark_build(cfg, "done soon")
    daemon.unmark_build(cfg)
    assert daemon.interrupted(cfg) is None
    assert not daemon.flag_path(cfg).exists()


def test_the_state_endpoint_surfaces_an_interruption(running):
    cfg, url = running
    daemon.mark_build(cfg, "cut off mid-round")
    flag = json.loads(daemon.flag_path(cfg).read_text())
    flag["pid"] = 999999
    daemon.flag_path(cfg).write_text(json.dumps(flag))

    import urllib.request

    with urllib.request.urlopen(url.replace("/?", "/api/state?"), timeout=5) as r:
        data = json.loads(r.read())
    assert data["interrupted"]["task"] == "cut off mid-round"
    daemon.unmark_build(cfg)


# ---------------------------------------------------------------- idle policy
def test_a_running_build_keeps_the_console_alive(cfg, monkeypatch):
    """The whole point: a closed window must not end a build. Idleness is only
    grounds for shutting down when nothing is in flight."""
    import crossaudit.console.server as server_mod

    tracker = Tracker()
    tracker.start("long job")
    monkeypatch.setattr(server_mod, "TRACKER", tracker)

    url, httpd = serve(cfg, port=0, idle_timeout=0.05)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        import time
        import urllib.request

        time.sleep(0.4)                          # well past the idle timeout
        with urllib.request.urlopen(url.replace("/?", "/api/state?"), timeout=5) as r:
            assert r.status == 200               # still up, because work is running
    finally:
        httpd.shutdown()
        daemon.clear_run(cfg)
