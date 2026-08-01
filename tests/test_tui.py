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


# ------------------------------------------------------------ credentials
def test_a_key_is_visible_as_you_type_by_default(monkeypatch, capsys):
    """Hiding it makes a typo or a truncated paste invisible until the first API
    call fails — and that failure names the vendor, not the mistake."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("CROSSAUDIT_HIDE_KEYS", raising=False)
    monkeypatch.setattr("builtins.input", lambda _p: "sk-ant-visible-9f2a")
    assert tui.secret("auditor key") == "sk-ant-visible-9f2a"
    assert "34 chars" not in capsys.readouterr().out    # fingerprint, not a lie


def test_the_fingerprint_lets_you_check_without_repeating_the_secret():
    fp = tui.fingerprint("sk-ant-api03-something-long-9f2a")
    assert "32 chars" in fp and fp.endswith("9f2a")
    assert "api03" not in fp                            # the middle never reappears
    assert tui.fingerprint("") == "empty"
    assert tui.fingerprint("short") == "5 chars, ending …"


def test_hiding_is_available_for_a_shared_screen(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("CROSSAUDIT_HIDE_KEYS", "1")
    called = {}

    def fake_getpass(prompt):
        called["hidden"] = True
        return "sk-hidden"

    monkeypatch.setattr("getpass.getpass", fake_getpass)
    assert tui.secret("key") == "sk-hidden" and called["hidden"]


# ------------------------------------------------------------ model choice
def test_every_vendor_offers_models_and_a_way_to_type_one(monkeypatch):
    """A wizard that only offers what it knew when it shipped goes stale the
    week after a release."""
    monkeypatch.setattr(tui, "interactive", lambda: False)
    for vendor, known in wizard.VENDOR_MODELS.items():
        if vendor == "other":
            continue
        assert known, f"{vendor} offers no models"
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        assert wizard.choose_model(vendor, "fallback") == known[0][0]


def test_an_unknown_vendor_falls_back_to_typing_the_id(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert wizard.choose_model("other", "my-model") == "my-model"


def test_the_type_it_option_leads_to_a_text_prompt(monkeypatch):
    monkeypatch.setattr(tui, "select", lambda *a, **k: wizard.TYPE_IT)
    monkeypatch.setattr(tui, "text", lambda *a, **k: "some-new-model")
    assert wizard.choose_model("anthropic", "d") == "some-new-model"


def test_model_ids_look_like_model_ids():
    for vendor, models in wizard.VENDOR_MODELS.items():
        for mid, hint in models:
            assert " " not in mid, f"{vendor}: {mid!r} has a space"
            assert hint, f"{vendor}: {mid} has no explanation"


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


# ------------------------------------------------------- the README is a contract
def test_every_command_the_readme_shows_actually_exists():
    """A README with a wrong command is worse than no README: the reader trusts
    it, and the tool has already spent their patience by the time it fails."""
    import re

    from crossaudit.cli.main import build_parser

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    parser = build_parser()
    real = set(next(a.choices for a in parser._actions if a.choices))
    used = set(re.findall(r"crossaudit ([a-z][a-z-]+)", readme))
    assert not (used - real), f"README shows commands that do not exist: {used - real}"


def test_the_readme_documents_every_user_facing_environment_variable():
    import re

    src = Path(__file__).resolve().parents[1] / "src"
    found: set[str] = set()
    for py in src.rglob("*.py"):
        found |= set(re.findall(r"CROSSAUDIT_[A-Z_]+", py.read_text()))
    # Internal plumbing a user never sets by hand.
    internal = {"CROSSAUDIT_CONSOLE_CHILD", "CROSSAUDIT_LOCKFILE",
                "CROSSAUDIT_REPLAY_DIR"}
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    documented = set(re.findall(r"CROSSAUDIT_[A-Z_]+", readme))
    assert not ((found - internal) - documented), \
        f"undocumented: {sorted((found - internal) - documented)}"


def test_the_readme_states_the_version_the_package_reports():
    from crossaudit import __version__

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert __version__ in readme, f"README does not mention {__version__}"


def test_the_readme_exit_codes_match_the_contract():
    from crossaudit import errors

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    for code in (errors.EXIT_OK, errors.EXIT_BLOCKED, errors.EXIT_ESCALATED,
                 errors.EXIT_CONFIG, errors.EXIT_INTEGRITY, errors.EXIT_PROVIDER):
        assert f"`{code}`" in readme, f"exit code {code} is not in the README table"


def test_the_readme_is_english_and_the_translation_is_linked():
    """The primary README is the one GitHub shows first; a translation that
    nobody can find from it is a translation nobody reads."""
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text()
    body = "\n".join(line for line in readme.splitlines()
                     if "README.zh-CN" not in line and "中文" not in line)
    cjk = sum(1 for ch in body if "一" <= ch <= "鿿")
    assert cjk == 0, f"{cjk} CJK characters outside the translation link"
    assert "README.zh-CN.md" in readme
    assert (root / "README.zh-CN.md").is_file()


def test_the_translation_points_back_at_the_english_one():
    root = Path(__file__).resolve().parents[1]
    assert "README.md" in (root / "README.zh-CN.md").read_text()


# --------------------------------------------- setup ends at the console
def test_setup_opens_the_console_when_it_finishes(tmp_path, monkeypatch):
    """Setup ends exactly where the work begins; making someone find the next
    command themselves is a gap for no reason."""
    import argparse

    import crossaudit.cli.main as main_mod

    opened = {}
    monkeypatch.setattr(main_mod, "_open_console",
                        lambda root: opened.setdefault("root", root) and {} or
                        {"console": "http://127.0.0.1:1/?t=x"})
    monkeypatch.setattr(main_mod.wizard, "run",
                        lambda *a, **k: {"config": str(tmp_path / "crossaudit.yml")})
    args = argparse.Namespace(path=str(tmp_path), github=False, force=False,
                              no_console=False, json=False)
    assert main_mod.cmd_init(args) == 0
    assert opened["root"] == tmp_path


def test_no_console_leaves_the_browser_alone(tmp_path, monkeypatch):
    import argparse

    import crossaudit.cli.main as main_mod

    called = []
    monkeypatch.setattr(main_mod, "_open_console", lambda root: called.append(root))
    monkeypatch.setattr(main_mod.wizard, "run",
                        lambda *a, **k: {"config": str(tmp_path / "crossaudit.yml")})
    args = argparse.Namespace(path=str(tmp_path), github=False, force=False,
                              no_console=True, json=False)
    main_mod.cmd_init(args)
    assert called == []


def test_a_missing_browser_never_fails_the_setup(tmp_path, monkeypatch, capsys):
    """A headless box has no browser, and that is not a setup failure — the URL
    is printed and the run still succeeds."""
    import subprocess

    import crossaudit.cli.main as main_mod

    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / "AUDIT_RULES.md").write_text("### CA-X-001\n**BLOCKER.** x\n\ny\n")
    (root / "crossaudit.yml").write_text(
        "version: 1\nscience_repo: t/p\nconstitution: AUDIT_RULES.md\n"
        "auditor: {vendor: openai, provider: openai_compat, model: m,"
        " key_env: CROSSAUDIT_AUDITOR_KEY}\ngenerator: {vendor: anthropic}\n"
        "ledger: {dir: cycles}\nstate: {dir: .crossaudit}\nchecks: [parseable]\n")

    from crossaudit.console import daemon

    monkeypatch.setattr(daemon, "live", lambda cfg: {"pid": 1, "port": 9,
                                                     "token": "t"})
    monkeypatch.setattr("webbrowser.open", lambda url: (_ for _ in ()).throw(
        RuntimeError("no browser here")))
    out = main_mod._open_console(root)
    assert out["console"].startswith("http://127.0.0.1:9/")
    assert out["console_opened"] is False
    assert "Open that URL" in capsys.readouterr().out


def test_a_console_that_will_not_start_is_reported_not_raised(tmp_path, capsys):
    """A project that cannot host a console is still a set-up project."""
    import crossaudit.cli.main as main_mod

    out = main_mod._open_console(tmp_path)      # no config here at all
    assert out == {"console": None}
    assert "crossaudit console" in capsys.readouterr().out
