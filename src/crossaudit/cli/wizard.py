"""`crossaudit init` — the guided setup, from an empty directory to a first run.

It creates the project if it does not exist, makes it a git repository if it is
not one, settles who audits and who generates, takes the two keys, and turns a
sentence about the project into the rules it will be judged by. Everything is
shown before it is written, and the only thing here that reaches the network is
the one call that drafts the rules.

Interactive when it can be — arrow keys, framed panels — and completely
non-interactive when it cannot: piped stdin and CI take defaults rather than
hanging on a keypress that will never arrive.

Keys go to a 0600 file outside the repository and are never echoed, never put in
`crossaudit.yml`, and never committed.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ..config import CONFIG_NAME
from ..errors import ConfigDenial, Denial
from ..scaffold import AUDIT_TREE, CONFIG_TEMPLATE, SCIENCE_TREE, read, write_tree
from . import tui

DEFAULT_KEYS_FILE = Path.home() / ".crossaudit-keys.env"

VENDORS = {
    "anthropic": ("anthropic", "claude-sonnet-4-5", "https://api.anthropic.com"),
    "openai": ("openai_compat", "gpt-5.1", "https://api.openai.com"),
    "google": ("openai_compat", "gemini-2.5-pro",
               "https://generativelanguage.googleapis.com/v1beta/openai"),
    "deepseek": ("openai_compat", "deepseek-chat", "https://api.deepseek.com"),
    "other": ("openai_compat", "", ""),
}
VENDOR_HINTS = {
    "anthropic": "Claude", "openai": "GPT", "google": "Gemini",
    "deepseek": "DeepSeek", "other": "any OpenAI-compatible endpoint",
}

#: Models offered per vendor, most capable first. A list is not a promise that
#: every entry is available on your account — the last option always lets you
#: type an id, because a wizard that only offers what it knew when it shipped
#: goes stale the week after a release.
VENDOR_MODELS = {
    "anthropic": [
        ("claude-opus-5", "most capable"),
        ("claude-sonnet-5", "balanced"),
        ("claude-sonnet-4-5", "previous generation"),
        ("claude-haiku-4-5-20251001", "fastest, cheapest"),
    ],
    "openai": [
        ("gpt-5.1", "most capable"),
        ("gpt-5", "previous generation"),
        ("gpt-5-mini", "faster, cheaper"),
    ],
    "google": [
        ("gemini-2.5-pro", "most capable"),
        ("gemini-2.5-flash", "faster, cheaper"),
    ],
    "deepseek": [
        ("deepseek-reasoner", "reasoning"),
        ("deepseek-chat", "general"),
    ],
    "other": [],
}
TYPE_IT = "__type__"


def choose_model(vendor: str, default: str, *, role: str = "Auditor") -> str:
    """Pick a model from a list, or type one.

    Typing an exact model id from memory is the step people get wrong, and a
    wrong id fails much later with a provider error that says nothing about the
    wizard. Offer the ones we know and keep the escape hatch.
    """
    known = VENDOR_MODELS.get(vendor) or []
    if not known:
        return tui.text("Model id", default, placeholder="exactly as the vendor spells it")
    options = [tui.Option(m, m, hint) for m, hint in known]
    options.append(tui.Option(TYPE_IT, "something else", "type the id yourself"))
    picked = tui.select(f"{role} model:", options, default=0)
    if picked == TYPE_IT:
        return tui.text("Model id", default,
                        placeholder="exactly as the vendor spells it")
    return picked
# Kept for callers and tests that predate the arrow-key flow.
VENDOR_PRESETS = VENDORS


def keys_file() -> Path:
    """Where credentials are stored; overridable so a sandbox leaves no residue."""
    return Path(os.environ.get("CROSSAUDIT_KEYS_FILE", DEFAULT_KEYS_FILE)).expanduser()


def read_keys_file(path: Path | None = None) -> dict[str, str]:
    """Parse the `export NAME="value"` lines we wrote. Nothing else is executed.

    The file is shell-shaped so a person can `source` it, but reading it here
    parses rather than runs: a credentials file is the last thing that should be
    able to execute anything.
    """
    path = path or keys_file()
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        try:
            words = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if len(words) != 2 or words[0] != "export" or "=" not in words[1]:
            continue
        name, _, value = words[1].partition("=")
        if name.startswith("CROSSAUDIT_") and value:
            out[name] = value
    return out


def load_keys_into_env() -> list[str]:
    """Make the keys we wrote available to the process that needs them.

    The wizard writes this file and then hands off — to the console it starts, or
    to the next command. Expecting the person to `source` it in between is a seam
    that produces a 400 from a provider rather than a sentence about setup, and
    it is our file: we wrote it, we know where it is, we can read it.

    An exported variable always wins: someone who set a key deliberately in this
    shell meant that one.
    """
    loaded = []
    for name, value in read_keys_file().items():
        if not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def write_keys(pairs: dict[str, str]) -> Path:
    """Append keys to a 0600 file. Existing values are kept unless replaced."""
    path = keys_file()
    existing = read_keys_file(path)
    existing.update({k: v for k, v in pairs.items() if v})
    body = "# CrossAudit credentials. Never commit this file.\n" + "\n".join(
        f"export {k}={shlex.quote(v)}" for k, v in sorted(existing.items())) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o600)
    return path


def gh_available() -> tuple[bool, str]:
    if not shutil.which("gh"):
        return False, "gh CLI not installed"
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if proc.returncode != 0:
        return False, "gh installed but not authenticated (run: gh auth login)"
    return True, "gh authenticated"


def github_plan(science: str, audit: str) -> list[str]:
    """What pairing would do. Printed for review; `pair --apply` performs it."""
    return [
        f"gh repo create {science} --private",
        f"gh repo create {audit} --private        rules and reports live here",
        f"gh secret set CROSSAUDIT_AUDITOR_KEY --repo {audit}",
        f"gh api repos/{science}/branches/main/protection -X PUT",
        "crossaudit pair --apply                  does all of it, after showing you",
    ]


def prepare(target: Path) -> list[str]:
    """Create the directory and make it a repository. Returns what it did.

    The audit reads commits, so a project that is not a repository cannot be
    audited at all — better to make it one here than to fail later with a
    message about git.
    """
    done: list[str] = []
    if not target.exists():
        target.mkdir(parents=True)
        done.append(f"created {target}")
    if not (target / ".git").is_dir():
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(target),
                       check=True)
        done.append("git init — the ledger is git, and an audit reads commits")
    gitignore = target / ".gitignore"
    current = gitignore.read_text() if gitignore.is_file() else ""
    if ".crossaudit/" not in current:
        with open(gitignore, "a") as fh:
            fh.write("\n# CrossAudit's local state. The ledger is committed; this is not.\n"
                     ".crossaudit/\n")
        done.append("ignored .crossaudit/ — local state, not the ledger")
    return done


def commit_setup(target: Path, paths: list[str]) -> str:
    """Version only the files setup owns and return the new commit hash.

    An existing repository may already have unrelated changes staged.  A plain
    ``git commit`` would silently sweep those into CrossAudit's setup commit,
    so the pathspec is repeated with ``--only``.  New git users often have no
    author configured yet; in that case install an explicit repository-local
    automation identity.  The local setting matters beyond this one commit:
    later build rounds also commit their work, and must not fail only after the
    user has finished setup.
    """
    owned = sorted(set(paths))
    add = subprocess.run(["git", "add", "--", *owned], cwd=str(target),
                         capture_output=True, text=True)
    if add.returncode != 0:
        raise ConfigDenial(f"could not stage the setup files: {add.stderr.strip()[:200]}")

    name = subprocess.run(["git", "config", "user.name"], cwd=str(target),
                          capture_output=True, text=True).stdout.strip()
    email = subprocess.run(["git", "config", "user.email"], cwd=str(target),
                           capture_output=True, text=True).stdout.strip()
    for key, current, fallback in (
        ("user.name", name, "CrossAudit"),
        ("user.email", email, "crossaudit@local.invalid"),
    ):
        if current:
            continue
        configured = subprocess.run(["git", "config", key, fallback], cwd=str(target),
                                    capture_output=True, text=True)
        if configured.returncode != 0:
            raise ConfigDenial(f"could not configure the local git identity: "
                               f"{configured.stderr.strip()[:200]}")

    changed = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *owned],
                             cwd=str(target))
    if changed.returncode == 0:
        # Re-running --force with byte-identical answers has nothing to version.
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(target),
                              capture_output=True, text=True).stdout.strip()
    if changed.returncode != 1:
        raise ConfigDenial("could not inspect the staged setup files")

    commit = subprocess.run(
        ["git", "commit", "-q", "--only", "-m",
         "crossaudit: initialize supervised project", "--", *owned],
        cwd=str(target), capture_output=True, text=True)
    if commit.returncode != 0:
        raise ConfigDenial(f"could not commit the setup files: "
                           f"{commit.stderr.strip()[:200]}")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(target),
                          capture_output=True, text=True, check=True).stdout.strip()


def _distil(description: str, provider: str, model: str, base_url: str):
    """Draft rules on the auditor-side model, before any config file exists."""
    from .. import constitution as const_mod
    from ..providers import get_provider

    fn = get_provider(provider)

    def complete(*, system: str, prompt: str):
        return fn(model=model, system=system, prompt=prompt,
                  key_env="CROSSAUDIT_AUDITOR_KEY", base_url=base_url or None,
                  allow_custom=bool(os.environ.get("CROSSAUDIT_ALLOW_CUSTOM_ENDPOINT")))

    return const_mod.distil(description, complete=complete)


def run(target: Path, *, mode: str, force: bool = False) -> dict:
    """Guided setup. Returns a summary of what was written."""
    target = target.resolve()
    cfg_path = target / CONFIG_NAME
    if cfg_path.exists() and not force:
        raise ConfigDenial(f"{cfg_path} already exists; refusing to overwrite "
                           f"(pass --force if you mean it)")

    tui.banner("CrossAudit — setting up a supervised project",
               "Two models from different vendors, one ledger in git. "
               "Four questions, then it runs.")

    gitignore_existed = (target / ".gitignore").exists()
    for line in prepare(target):
        tui.ok(line)

    # ---- 1. the auditor ----------------------------------------------------
    tui.step(1, 4, "Who audits")
    tui.note("The model that reviews everything before it counts as done.")
    auditor_vendor = tui.select(
        "Auditor vendor:",
        [tui.Option(v, v, VENDOR_HINTS[v]) for v in VENDORS], default=0)
    provider, default_model, _url = VENDORS[auditor_vendor]
    model = choose_model(auditor_vendor, default_model)
    base_url = ""
    if auditor_vendor == "other":
        base_url = tui.text("OpenAI-compatible base URL",
                            placeholder="https://host/v1")
        provider = "openai_compat"

    # ---- 2. the generator --------------------------------------------------
    tui.step(2, 4, "Who generates")
    tui.note("The model that writes each build round. Its vendor is also recorded "
             "so same-source supervision can be refused before either key is used.")
    others = [v for v in VENDORS if v not in (auditor_vendor, "other")]
    generator_vendor = tui.select(
        "Generator vendor:",
        [tui.Option(v, v, VENDOR_HINTS[v]) for v in others]
        + [tui.Option("human", "human", "you write it yourself")], default=0)
    if generator_vendor.lower() == auditor_vendor.lower():
        raise ConfigDenial(
            f"auditor and generator are both {auditor_vendor!r}: that is "
            f"same-source supervision, which is the thing this protocol exists "
            f"to avoid")
    generator_provider = ""
    generator_model = ""
    if generator_vendor != "human":
        generator_provider, generator_default_model, _generator_url = VENDORS[
            generator_vendor]
        generator_model = choose_model(generator_vendor, generator_default_model,
                                       role="Generator")

    # ---- 3. keys -----------------------------------------------------------
    tui.step(3, 4, "API keys")
    tui.note(f"Written to {keys_file()} with mode 600, never placed in the "
             f"repository. Leave blank to export them yourself.")
    tui.note("Shown as you type so you can see a mistake — set CROSSAUDIT_HIDE_KEYS=1 "
             "if someone is looking over your shoulder.")
    auditor_key = tui.secret(f"{auditor_vendor} key — the auditor")
    generator_key = ""
    if generator_vendor != "human":
        generator_key = tui.secret(f"{generator_vendor} key — the generator "
                                   f"(leave blank to export it yourself)")
    written = None
    if auditor_key or generator_key:
        written = write_keys({"CROSSAUDIT_AUDITOR_KEY": auditor_key,
                              "CROSSAUDIT_GENERATOR_KEY": generator_key})
        # The keys arrived after main() looked for them, and the console this run
        # is about to start inherits this environment. Load them now, or the very
        # first thing the person types into the console fails on a missing key
        # they just supplied.
        load_keys_into_env()
        tui.ok(f"keys written to {written} (mode 600)")

    # ---- 4. the rules, spoken rather than written --------------------------
    tui.step(4, 4, "What this is, and what would be a mistake")
    tui.note("Say it in your own words. The rules are drafted from this, shown to "
             "you, and committed only if you agree — you never write markdown.")
    const_name = "AUDIT_RULES.md"
    const_path = target / const_name
    description = tui.text(
        "your project, in a sentence or three",
        placeholder="e.g. a review of the PV industry; every figure must trace "
                    "to a source")

    drafted = False
    if description.strip():
        try:
            draft = _distil(description, provider, model or default_model, base_url)
            rows = [draft.project_summary, tui.dim(f"domain: {draft.domain}"), ""]
            for r in draft.rules:
                mark = (tui.red("BLOCKER") if r.severity == "BLOCKER"
                        else tui.dim("advisory"))
                rows.append(f"{tui.bold(r.id)}  [{mark}]  {r.title}")
                rows.append(f"    {r.criterion}")
                if r.from_user:
                    rows.append(tui.dim(f'    from you: "{r.from_user}"'))
            tui.panel("Drafted rules", rows)
            if tui.confirm("Commit these as the project's rules?", default=True):
                const_path.write_text(draft.render(target.name))
                drafted = True
                tui.ok(f"{const_name} written — change it any time by saying so: "
                       f'crossaudit amend "from now on ..."')
        except Denial as exc:
            tui.warn(f"could not draft rules: {exc.reason}")
            tui.note("Falling back to the starter template; edit it, or use "
                     "`crossaudit amend` once a key is in place.")
    if not drafted and not const_path.exists():
        const_path.write_text(read(const_name))
        tui.ok(f"{const_name} written from the starter template")

    # ---- configuration and shape -------------------------------------------
    science_repo = tui.text("Project name (owner/name, or a label)", target.name)
    audit_repo = "" if mode == "local" else f"{science_repo}-audit"

    cfg_path.write_text(CONFIG_TEMPLATE.format(
        science_repo=science_repo,
        audit_repo_line=(f"audit_repo: {audit_repo}" if audit_repo
                         else "# audit_repo: (local ledger)"),
        constitution=const_name,
        max_rounds=3,
        auditor_vendor=auditor_vendor,
        auditor_provider=provider,
        auditor_model=model or default_model,
        base_url_line=f"  base_url: {base_url}\n" if base_url else "",
        generator_vendor=generator_vendor,
        generator_details=(
            f"  provider: {generator_provider}\n"
            f"  model: {generator_model}\n"
            f"  key_env: CROSSAUDIT_GENERATOR_KEY"
            if generator_vendor != "human" else
            "  # Human-written changes are committed first, then `crossaudit run`."
        ),
        permissive_minimum="false" if mode == "local" else "true",
        state_dir=".crossaudit",
    ))
    tui.ok(f"{CONFIG_NAME} written")
    owned = [CONFIG_NAME, const_name]
    if not gitignore_existed:
        owned.append(".gitignore")
    owned.extend(write_tree(target, SCIENCE_TREE))
    if mode == "local":
        owned.extend(write_tree(target, AUDIT_TREE))

    setup_commit = commit_setup(target, owned)
    tui.ok(f"setup committed — {setup_commit[:12]}")

    # ---- what to do next ---------------------------------------------------
    tui.banner("Ready", str(target))
    rows = []
    if written:
        rows.append(f"source {written}")
        rows.append(tui.dim("    load the keys into this shell"))
    rows += [
        "crossaudit doctor",
        tui.dim("    check everything, offline and read-only"),
        'crossaudit build "…"',
        tui.dim("    say what to build; the loop writes and audits it"),
        "crossaudit console",
        tui.dim("    two windows in a browser, live, and it outlives the window"),
    ]
    tui.panel("Next", rows)

    if mode != "local":
        tui.panel("Two repositories (privilege separation)",
                  github_plan(science_repo, audit_repo or f"{science_repo}-audit"))
        gh_ok, detail = gh_available()
        if not gh_ok:
            tui.warn(f"{detail} — install from https://cli.github.com first")

    return {"config": str(cfg_path), "constitution": str(const_path),
            "keys_file": str(written) if written else None, "mode": mode,
            "setup_commit": setup_commit}
