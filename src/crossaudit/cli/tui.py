"""Terminal primitives for the setup flow: boxes, arrow-key choices, prompts.

Written on the standard library alone. A dependency budget of one package is a
promise the whole design rests on, and "the setup screen looked nicer" is not a
reason to spend it — `termios` and a handful of ANSI escapes do everything a
first-run wizard needs.

The rule that keeps this honest: **every interactive primitive has a
non-interactive answer.** Piped stdin, a CI job, a Windows terminal without
`termios` — all of them fall back to plain prompts or to the caller's default,
and nothing here ever blocks a script waiting for a keypress that cannot come.
Colour goes away for the same reasons, plus `NO_COLOR`, because a wizard that
emits escape codes into a log file has made the log harder to read for the sake
of a machine that cannot see them.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

try:                                   # POSIX only; absence is a supported state
    import termios
    import tty
    HAVE_TERMIOS = True
except ImportError:                    # pragma: no cover - Windows
    HAVE_TERMIOS = False

WIDTH = 72

UP, DOWN, ENTER, ESCAPE, OTHER = "up", "down", "enter", "escape", "other"


def interactive() -> bool:
    """Can we take over the terminal? If not, callers use their defaults."""
    return bool(HAVE_TERMIOS and sys.stdin.isatty() and sys.stdout.isatty())


def coloured() -> bool:
    return bool(sys.stdout.isatty()) and not os.environ.get("NO_COLOR")


# ---------------------------------------------------------------- rendering
def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if coloured() else text


def dim(t: str) -> str:
    return c(t, "2")


def bold(t: str) -> str:
    return c(t, "1")


def green(t: str) -> str:
    return c(t, "32")


def amber(t: str) -> str:
    return c(t, "33")


def blue(t: str) -> str:
    return c(t, "36")


def red(t: str) -> str:
    return c(t, "31")


def _visible(text: str) -> int:
    """Length as the terminal sees it: escape codes take no columns."""
    out, i = 0, 0
    while i < len(text):
        if text[i] == "\033":
            while i < len(text) and text[i] != "m":
                i += 1
        else:
            out += 2 if ord(text[i]) > 0x2E80 else 1     # CJK is double-width
        i += 1
    return out


def banner(title: str, subtitle: str = "") -> None:
    print()
    print(dim("╭" + "─" * (WIDTH - 2) + "╮"))
    pad = WIDTH - 4 - _visible(title)
    print(dim("│ ") + bold(title) + " " * max(0, pad) + dim(" │"))
    if subtitle:
        for line in wrap(subtitle, WIDTH - 4):
            print(dim("│ ") + dim(line) + " " * max(0, WIDTH - 4 - _visible(line))
                  + dim(" │"))
    print(dim("╰" + "─" * (WIDTH - 2) + "╯"))


def _break(word: str, width: int) -> list[str]:
    """Split one over-long run by visible width.

    Chinese has no spaces, so a whole clause arrives as a single "word": wrapping
    on whitespace alone would leave it hanging off the right edge of the box.
    """
    pieces, current = [], ""
    for ch in word:
        if _visible(current + ch) > width and current:
            pieces.append(current)
            current = ch
        else:
            current += ch
    if current:
        pieces.append(current)
    return pieces


def wrap(text: str, width: int) -> list[str]:
    """Wrap on width as the terminal counts it, so CJK does not overflow."""
    lines, current = [], ""
    for word in text.split():
        for piece in (_break(word, width) if _visible(word) > width else [word]):
            candidate = f"{current} {piece}".strip()
            if _visible(candidate) > width and current:
                lines.append(current)
                current = piece
            else:
                current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def step(n: int, total: int, title: str) -> None:
    print()
    print(f"  {blue(f'[{n}/{total}]')} {bold(title)}")


def note(text: str) -> None:
    for line in wrap(text, WIDTH - 8):
        print(dim(f"        {line}"))


def ok(text: str) -> None:
    print(f"  {green('✓')} {text}")


def warn(text: str) -> None:
    print(f"  {amber('!')} {text}")


# ------------------------------------------------------------- key handling
def decode(raw: bytes) -> str:
    """One keypress as an intent. Pure, so it can be tested without a terminal."""
    if raw in (b"\r", b"\n"):
        return ENTER
    if raw in (b"\x1b[A", b"k"):
        return UP
    if raw in (b"\x1b[B", b"j"):
        return DOWN
    if raw in (b"\x1b", b"\x03", b"\x04"):
        return ESCAPE
    return OTHER


def read_key() -> tuple[str, bytes]:
    """Block for one keypress. Only called when `interactive()`."""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1)
        if ch == b"\x1b":
            # An escape sequence arrives in pieces; a lone ESC has none to follow.
            rest = os.read(fd, 2) if _pending(fd) else b""
            ch += rest
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return decode(ch), ch


def _pending(fd: int) -> bool:
    import select as _select

    return bool(_select.select([fd], [], [], 0.02)[0])


# ------------------------------------------------------------------ widgets
@dataclass
class Option:
    value: str
    label: str
    hint: str = ""


def select(title: str, options: list[Option], *, default: int = 0,
           footer: str = "") -> str:
    """Arrow-key choice, with a typed fallback when the terminal is not ours."""
    if not interactive():
        chosen = options[default]
        print(f"  {title} {dim('→')} {chosen.label} {dim('(default)')}")
        return chosen.value

    index = max(0, min(default, len(options) - 1))
    print(f"  {title}")
    hint = footer or "↑↓ to move · enter to choose"
    print(dim(f"  {hint}"))

    def render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\033[{len(options)}A")
        for i, opt in enumerate(options):
            marker = green("❯") if i == index else " "
            label = bold(opt.label) if i == index else opt.label
            tail = dim(f"  {opt.hint}") if opt.hint else ""
            sys.stdout.write(f"\r\033[K  {marker} {label}{tail}\n")
        sys.stdout.flush()

    sys.stdout.write("\033[?25l")                     # hide the cursor
    try:
        render(first=True)
        while True:
            key, _raw = read_key()
            if key == UP:
                index = (index - 1) % len(options)
            elif key == DOWN:
                index = (index + 1) % len(options)
            elif key == ENTER:
                return options[index].value
            elif key == ESCAPE:
                raise KeyboardInterrupt
            else:
                continue
            render()
    finally:
        sys.stdout.write("\033[?25h")                 # and always give it back
        sys.stdout.flush()


def text(prompt: str, default: str = "", *, placeholder: str = "") -> str:
    """One line of input. Returns the default when there is no terminal."""
    if not sys.stdin.isatty():
        return default
    shown = dim(f" [{default}]") if default else (dim(f" {placeholder}")
                                                  if placeholder else "")
    try:
        got = input(f"  {prompt}{shown}\n  {green('❯')} ").strip()
    except EOFError:
        return default
    return got or default


def fingerprint(value: str) -> str:
    """A credential described without being repeated: length and its last four.

    Enough to tell a truncated paste from a whole one, or the wrong key from the
    right one, without putting the secret back on screen a second time.
    """
    if not value:
        return "empty"
    tail = value[-4:] if len(value) > 8 else "…"
    return f"{len(value)} chars, ending {tail}"


def secret(prompt: str, *, hide: bool | None = None) -> str:
    """Ask for a credential.

    Visible by default. Hiding it means a typo or a truncated paste is invisible
    until the first API call fails, and that failure names the vendor rather than
    the mistake — so the common error is silent and the rare shoulder-surfer is
    the one who has to opt in, through CROSSAUDIT_HIDE_KEYS.
    """
    if not sys.stdin.isatty():
        return ""
    if hide is None:
        hide = bool(os.environ.get("CROSSAUDIT_HIDE_KEYS"))
    if hide:
        import getpass

        value = getpass.getpass(f"  {prompt}\n  ❯ ").strip()
    else:
        try:
            value = input(f"  {prompt}\n  {green('❯')} ").strip()
        except EOFError:
            return ""
    if value:
        print(dim(f"    got {fingerprint(value)}"))
    return value


def confirm(question: str, *, default: bool = True) -> bool:
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        got = input(f"  {question} {dim(suffix)} ").strip().lower()
    except EOFError:
        return default
    return default if not got else got in ("y", "yes")


def panel(title: str, rows: list[str]) -> None:
    """A framed block for reviewing something before it is written."""
    print()
    print(f"  {dim('┌─')} {bold(title)}")
    for row in rows:
        for line in wrap(row, WIDTH - 6):
            print(f"  {dim('│')} {line}")
    print(f"  {dim('└─')}")
