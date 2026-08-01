"""The setup screen: pleasant when it owns the terminal, harmless when it does not.

Every one of these is about the fallback. A wizard that blocks on a keypress in
CI, or writes escape codes into a log, has traded a working tool for a prettier
demo — and the failure only shows up somewhere nobody is watching.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from crossaudit.cli import tui, wizard


# ------------------------------------------------------------ key decoding
@pytest.mark.parametrize("raw,expect", [
    (b"\x1b[A", tui.UP), (b"k", tui.UP),
    (b"\x1b[B", tui.DOWN), (b"j", tui.DOWN),
    (b"\r", tui.ENTER), (b"\n", tui.ENTER),
    (b"\x1b", tui.ESCAPE), (b"\x03", tui.ESCAPE), (b"\x04", tui.ESCAPE),
    (b"q", tui.OTHER), (b"\x1b[C", tui.OTHER),
])
def test_keys_decode_to_intents(raw, expect):
    assert tui.decode(raw) == expect


# ------------------------------------------------------------- the fallback
def test_nothing_is_interactive_without_a_terminal(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert not tui.interactive()


def test_select_takes_the_default_rather_than_waiting(monkeypatch, capsys):
    """The important one: in CI this must return, not block on a keypress that
    can never arrive."""
    monkeypatch.setattr(tui, "interactive", lambda: False)
    options = [tui.Option("a", "first"), tui.Option("b", "second")]
    assert tui.select("pick:", options, default=1) == "b"
    assert "second" in capsys.readouterr().out


def test_text_returns_its_default_without_stdin(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert tui.text("name", "fallback") == "fallback"


def test_secret_never_guesses_a_credential(monkeypatch):
    """A default password would be worse than none."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert tui.secret("key") == ""


def test_confirm_honours_its_default_without_stdin(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert tui.confirm("go?", default=True) is True
    assert tui.confirm("go?", default=False) is False


# ----------------------------------------------------------------- colour
def test_no_colour_outside_a_terminal(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert tui.green("ok") == "ok" and "\033" not in tui.bold("x")


def test_no_color_environment_variable_is_obeyed(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")
    assert tui.blue("ok") == "ok"


# ------------------------------------------------------------------ layout
def test_width_counts_what_the_terminal_shows_not_what_python_stores():
    assert tui._visible("abc") == 3
    assert tui._visible(tui.bold("abc")) == 3          # escapes take no columns
    assert tui._visible("光伏") == 4                    # CJK is double-width


def test_wrapping_does_not_overflow_on_chinese():
    lines = tui.wrap("光伏产业综述 所有数字必须能追到文献来源", 12)
    assert all(tui._visible(line) <= 12 for line in lines)


def test_wrapping_an_empty_string_still_yields_a_line():
    assert tui.wrap("", 20) == [""]


# ------------------------------------------------------- the mkdir step
def test_init_creates_the_directory_and_the_repository(tmp_path: Path):
    target = tmp_path / "brand-new"
    done = wizard.prepare(target)
    assert target.is_dir() and (target / ".git").is_dir()
    assert any("created" in d for d in done)
    assert any("git init" in d for d in done)


def test_preparing_an_existing_repository_changes_nothing_it_owns(tmp_path: Path):
    target = tmp_path / "already"
    target.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
    (target / "README.md").write_text("mine\n")
    wizard.prepare(target)
    assert (target / "README.md").read_text() == "mine\n"


def test_the_local_state_directory_is_ignored_but_the_ledger_is_not(tmp_path: Path):
    target = tmp_path / "proj"
    wizard.prepare(target)
    ignored = (target / ".gitignore").read_text()
    assert ".crossaudit/" in ignored
    assert "cycles" not in ignored          # the ledger is committed, deliberately


def test_preparing_twice_does_not_duplicate_the_ignore_rule(tmp_path: Path):
    target = tmp_path / "proj"
    wizard.prepare(target)
    wizard.prepare(target)
    assert (target / ".gitignore").read_text().count(".crossaudit/") == 1
