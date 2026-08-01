"""Live build progress: visible while it runs, and never a second history.

The temptation with a progress feed is to let it become the record — it is
richer, it arrives sooner, and it reads better than a git log. These tests hold
the opposite line: progress is a view of work in flight, it lives only in
memory, and the ledger remains the thing anyone is held to.
"""
from __future__ import annotations

import threading
import time

import pytest

from crossaudit.console.progress import Tracker


def test_a_fresh_tracker_has_nothing_to_show():
    t = Tracker()
    assert t.snapshot() is None and not t.running


def test_steps_accumulate_in_order_while_a_run_is_in_flight():
    t = Tracker()
    t.start("write the section")
    t.step("generator", "writing")
    t.step("auditor", "reviewing the commit")
    snap = t.snapshot()
    assert t.running and not snap["finished"]
    assert [s["actor"] for s in snap["steps"]] == ["generator", "auditor"]
    assert snap["task"] == "write the section"


def test_finishing_records_the_outcome_and_stops_the_run():
    t = Tracker()
    t.start("x")
    t.step("generator", "writing")
    t.finish("passed")
    snap = t.snapshot()
    assert not t.running and snap["finished"] and snap["outcome"] == "passed"
    assert snap["steps"][-1]["actor"] == "done"


def test_a_failure_keeps_its_reason():
    t = Tracker()
    t.start("x")
    t.finish("refused", "the generator has no key")
    assert t.snapshot()["error"] == "the generator has no key"


def test_only_one_build_runs_at_a_time():
    """Two concurrent builds would race on the working tree and on the round
    budget; the honest answer is that one is already running."""
    t = Tracker()
    t.start("first")
    with pytest.raises(RuntimeError, match="already running"):
        t.start("second")
    t.finish("passed")
    t.start("second")                     # once it is done, the next may begin
    assert t.snapshot()["task"] == "second"


def test_steps_after_the_end_do_not_reopen_a_run():
    t = Tracker()
    t.start("x")
    t.finish("passed")
    t.step("generator", "a late straggler")
    assert not t.running and t.snapshot()["finished"]


def test_progress_is_memory_only_and_leaves_no_file(tmp_path, monkeypatch):
    """Ephemeral by construction: a progress log that outlived the run would be
    a second, unversioned history, and the first thing anyone would do is trust
    it."""
    monkeypatch.chdir(tmp_path)
    t = Tracker()
    t.start("x")
    t.step("generator", "writing")
    t.finish("passed")
    assert list(tmp_path.iterdir()) == []
    t.clear()
    assert t.snapshot() is None


def test_concurrent_steps_do_not_lose_entries():
    t = Tracker()
    t.start("x")

    def hammer(n: int) -> None:
        for i in range(50):
            t.step("generator", f"{n}-{i}")

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(t.snapshot()["steps"]) == 200


def test_elapsed_grows_while_running_and_freezes_when_done():
    t = Tracker()
    t.start("x")
    time.sleep(0.01)
    assert t.snapshot()["elapsed"] >= 0
    t.finish("passed")
    frozen = t.snapshot()["elapsed"]
    time.sleep(0.05)
    assert t.snapshot()["elapsed"] == frozen


def test_the_cli_and_the_console_drive_the_same_loop():
    """A second copy of the loop could drift on the only thing that matters:
    when it stops."""
    import inspect

    from crossaudit.cli import build as build_mod
    from crossaudit.console import server

    assert "run_loop" in inspect.getsource(build_mod.cmd_build)
    assert "run_loop" in inspect.getsource(server.start_build)


def test_no_string_literal_in_the_page_script_spans_a_line():
    """A stray real newline inside a JS string kills the whole script, and the
    only visible symptom is the form falling back to a native submit that drops
    the session token — which reads as a security failure rather than a typo.

    Scanned rather than counted: quotes nest inside each other and inside regex
    literals, so counting them per line cannot tell a bug from an apostrophe.
    """
    from crossaudit.console.page import PAGE

    script = PAGE.split("<script>")[1].split("</script>")[0]
    quote = None
    line = 1
    i = 0
    while i < len(script):
        ch = script[i]
        if ch == "\n":
            assert quote is None, f"string literal left open at line {line}"
            line += 1
        elif quote:
            if ch == "\\":
                i += 1                       # an escape consumes the next character
            elif ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == "/" and i + 1 < len(script) and script[i + 1] not in "/*":
            # A regex literal: skip it whole, quotes and all.
            j = i + 1
            while j < len(script) and script[j] not in "/\n":
                j += 2 if script[j] == "\\" else 1
            if j < len(script) and script[j] == "/":
                i = j
        i += 1
    assert quote is None, "the script ends inside a string literal"


def test_the_page_never_reaches_outside_itself():
    """The CSP forbids it, but the page should not even try: everything inline."""
    from crossaudit.console.page import PAGE

    for forbidden in ("http://", "https://", "<script src", "<link "):
        assert forbidden not in PAGE, f"page references {forbidden!r}"


def test_the_page_source_is_raw_so_javascript_escapes_survive():
    """PAGE holds JavaScript, and JavaScript is full of backslashes. A plain
    Python string eats them: \\s becomes an invalid escape, \\n becomes a real
    newline, and the script breaks in ways whose only symptom is the form
    silently falling back to a native submit."""
    import inspect

    from crossaudit.console import page as page_mod

    src = inspect.getsource(page_mod)
    assert 'PAGE = r"""' in src, "PAGE must be a raw string"


def test_the_page_javascript_still_contains_its_regexes():
    from crossaudit.console.page import PAGE

    assert r"/\s+/g" in PAGE          # would be mangled by a non-raw string
    assert r"[&<>\"]" in PAGE or '[&<>"]' in PAGE
