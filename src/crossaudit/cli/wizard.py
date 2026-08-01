"""`crossaudit init` — the guided terminal setup.

The operator's requirement: after installing, the program should walk the user
through the two API keys, the audit Constitution, and the GitHub side, in the
terminal. That guidance lives here, behind an explicit verb — never at install
time (constraint 7).

Keys are written to a 0600 file outside the repository and are never echoed,
never placed in `crossaudit.yml`, and never committed. The wizard refuses to
overwrite a non-empty target and prints exactly what it will do before doing it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import CONFIG_NAME
from ..errors import ConfigDenial, Denial
from ..scaffold import AUDIT_TREE, CONFIG_TEMPLATE, SCIENCE_TREE, read, write_tree

DEFAULT_KEYS_FILE = Path.home() / ".crossaudit-keys.env"


def keys_file() -> Path:
    """Where credentials are stored.

    Resolved at call time and overridable through CROSSAUDIT_KEYS_FILE, so a
    sandbox can keep everything it creates inside one directory and be deleted
    without residue.
    """
    return Path(os.environ.get("CROSSAUDIT_KEYS_FILE", DEFAULT_KEYS_FILE)).expanduser()

VENDOR_PRESETS = {
    "anthropic": ("anthropic", "claude-sonnet-4-5", "https://api.anthropic.com"),
    "openai": ("openai_compat", "gpt-5.1", "https://api.openai.com"),
    "google": ("openai_compat", "gemini-2.5-pro",
               "https://generativelanguage.googleapis.com/v1beta/openai"),
    "deepseek": ("openai_compat", "deepseek-chat", "https://api.deepseek.com"),
    "other": ("openai_compat", "", ""),
}


def _say(msg: str = "") -> None:
    print(msg, file=sys.stdout)


def _ask(prompt: str, default: str = "", *, secret: bool = False) -> str:
    if not sys.stdin.isatty():
        if default:
            return default
        raise ConfigDenial(f"init needs an answer for {prompt!r} but stdin is not a "
                           f"terminal; pass the matching flag instead")
    if secret:
        import getpass
        return getpass.getpass(f"{prompt}: ").strip()
    suffix = f" [{default}]" if default else ""
    got = input(f"{prompt}{suffix}: ").strip()
    return got or default


def _choose(prompt: str, options: list[str], default: str) -> str:
    _say(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        _say(f"  {i}) {opt}")
    raw = _ask("choose", default)
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    if raw in options:
        return raw
    raise ConfigDenial(f"{raw!r} is not one of {options}")


def write_keys(pairs: dict[str, str]) -> Path:
    """Append keys to a 0600 file. Existing values are kept unless replaced."""
    path = keys_file()
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip().startswith("export ") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.replace("export ", "").strip()] = v
    existing.update({k: f'"{v}"' for k, v in pairs.items() if v})
    body = "# CrossAudit credentials. Never commit this file.\n" + "\n".join(
        f"export {k}={v}" for k, v in sorted(existing.items())) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o600)
    return path


def github_plan(science: str, audit: str) -> list[str]:
    """The exact commands the 0.3 wizard will run, printed for review first.

    0.1 plans; it does not touch anyone's GitHub account. That boundary is the
    contract's, not shyness: remote writes wait for `--apply` in 0.3, and the
    admission tier they produce has to be named honestly when they land.
    """
    return [
        f"gh repo create {science} --private --clone   # then push the science shape:",
        "#   experiments/ (README + TEMPLATE increment), cycles/README, crossaudit.yml",
        f"gh repo create {audit} --private --clone     # then push the audit shape:",
        "#   AUDIT_RULES.md (the Constitution), cycles/ ledger README",
        f"gh secret set CROSSAUDIT_AUDITOR_KEY --repo {audit} < (your key, via stdin)",
        f"gh api repos/{science}/branches/main/protection -X PUT ...  # required check",
        "# then: crossaudit doctor --online   (re-reads the real rules, not the plan)",
    ]


def _distil_with_auditor(description: str, vendor: str, provider: str,
                         model: str, base_url: str):
    """Draft rules on the auditor-side model, before any config file exists.

    The wizard has the answers but not yet a Config, so the provider is bound
    from what was just chosen rather than loaded from disk.
    """
    from .. import constitution as const_mod
    from ..providers import get_provider

    fn = get_provider(provider)

    def complete(*, system: str, prompt: str):
        return fn(model=model, system=system, prompt=prompt,
                  key_env="CROSSAUDIT_AUDITOR_KEY", base_url=base_url or None,
                  allow_custom=bool(os.environ.get("CROSSAUDIT_ALLOW_CUSTOM_ENDPOINT")))

    return const_mod.distil(description, complete=complete)


def run(target: Path, *, mode: str, force: bool = False) -> dict:
    """Interactive setup. Returns a summary of what was written."""
    target = target.resolve()
    cfg_path = target / CONFIG_NAME
    if cfg_path.exists() and not force:
        raise ConfigDenial(f"{cfg_path} already exists; refusing to overwrite "
                           f"(pass --force if you mean it)")

    _say("CrossAudit setup")
    _say("=" * 60)
    _say("Three things to settle: who audits, what the rules are, and where the")
    _say("ledger lives. Nothing here is sent anywhere; keys go to a 0600 file")
    _say(f"at {keys_file()}, never into the repository.")

    # ---- 1. the auditor -----------------------------------------------------
    _say("\n[1/4] The Auditor — the model that reviews your work.")
    auditor_vendor = _choose("Auditor vendor:", list(VENDOR_PRESETS), "anthropic")
    provider, default_model, default_url = VENDOR_PRESETS[auditor_vendor]
    model = _ask("Auditor model", default_model)
    base_url = ""
    if auditor_vendor == "other":
        base_url = _ask("OpenAI-compatible base URL (e.g. https://host/v1)")
        provider = "openai_compat"

    _say("\n[2/4] The Generator — the model that produces the work being audited.")
    _say("      CrossAudit does not drive it; it needs the vendor name so that")
    _say("      heterogeneity (I1) can be asserted, and refused when violated.")
    generator_vendor = _choose("Generator vendor:", list(VENDOR_PRESETS)[:-1] + ["human"],
                               "anthropic" if auditor_vendor != "anthropic" else "openai")
    if generator_vendor.lower() == auditor_vendor.lower():
        raise ConfigDenial(
            f"auditor and generator are both {auditor_vendor!r}: that is same-source "
            f"supervision, which is the thing this protocol exists to avoid (I1)")

    # ---- 2. keys ------------------------------------------------------------
    _say("\n[3/4] API keys. Typed input is hidden and written to "
         f"{keys_file()} (chmod 600).")
    _say("      Leave blank to skip and export the variable yourself.")
    auditor_key = _ask("Auditor API key", secret=True)
    generator_key = ""
    if generator_vendor != "human":
        _say("      The generator key is stored for the full loop (0.5); it is not")
        _say("      used by this version, and storing it here means one process can")
        _say("      reach both — recorded in receipts as permissive: false.")
        generator_key = _ask("Generator API key (optional, press enter to skip)",
                             secret=True)
    written = None
    if auditor_key or generator_key:
        written = write_keys({"CROSSAUDIT_AUDITOR_KEY": auditor_key,
                              "CROSSAUDIT_GENERATOR_KEY": generator_key})

    # ---- 3. the Constitution -------------------------------------------------
    # ---- 4. the rules, spoken rather than written (DESIGN.md P3) ------------
    _say("\n[4/4] What this project is, and what you are most afraid of getting")
    _say("      wrong. Say it in your own words — the audit rules get drafted")
    _say("      from this, shown to you, and only committed if you agree.")
    const_name = "AUDIT_RULES.md"
    const_path = target / const_name
    description = _ask("\n  your project, in a sentence or three")

    drafted = False
    if description.strip():
        try:
            draft = _distil_with_auditor(description, auditor_vendor, provider,
                                         model or default_model, base_url)
            _say(f"\n  Understood: {draft.project_summary}")
            _say(f"  Domain: {draft.domain}")
            _say("\n  Drafted rules:\n")
            for r in draft.rules:
                _say(f"    {r.id}  [{r.severity}]  {r.title}")
                _say(f"          {r.criterion}")
                if r.from_user:
                    _say(f"          from you: \u201c{r.from_user}\u201d")
            if _ask("\n  Commit these as the project's rules? [Y/n]", "Y").lower() \
                    in ("", "y", "yes"):
                const_path.write_text(draft.render(target.name))
                drafted = True
                _say("  Rules written. Change them any time by saying so:")
                _say('    crossaudit amend "from now on ..."')
        except Denial as exc:
            _say(f"\n  Could not draft rules ({exc.reason}).")
            _say("  Falling back to the starter template; edit it or use "
                 "`crossaudit amend` later.")
    if not drafted and not const_path.exists():
        const_path.write_text(read("AUDIT_RULES.md"))

    science_repo = _ask("\nScience repository name (owner/name or a label)",
                        Path.cwd().name)
    audit_repo = _ask("Audit repository name (blank for a local ledger)",
                      "" if mode == "local" else f"{science_repo}-audit")

    permissive_min = "false" if mode == "local" else "true"
    cfg_text = CONFIG_TEMPLATE.format(
        science_repo=science_repo,
        audit_repo_line=f"audit_repo: {audit_repo}" if audit_repo else "# audit_repo: (local ledger)",
        constitution=const_name,
        max_rounds=3,
        auditor_vendor=auditor_vendor,
        auditor_provider=provider,
        auditor_model=model or default_model,
        base_url_line=f"  base_url: {base_url}\n" if base_url else "",
        generator_vendor=generator_vendor,
        permissive_minimum=permissive_min,
        state_dir=".crossaudit",
    )
    cfg_path.write_text(cfg_text)

    # The repository takes its shape now, not after reading documentation:
    # an experiments/ layout with a fill-in template, and the ledger directory
    # explained. Existing files are never overwritten.
    shaped = write_tree(target, SCIENCE_TREE)

    _say("\n" + "=" * 60)
    _say(f"wrote {cfg_path}")
    _say(f"wrote {const_path}")
    for rel in shaped:
        _say(f"wrote {rel}")
    if written:
        _say(f"wrote {written} (chmod 600)")
        _say(f"\n  Load the keys into this shell:  source {written}")
    if mode == "local":
        _say("\nMode: local. Both keys are reachable by one process, so receipts")
        _say("record permissive isolation as false and say so. This tier verifies")
        _say("and reports; it does not claim enforced admission.")
    else:
        _say("\nGitHub pairing plan (0.1 prints it; 0.3 runs it after --apply):")
        for step in github_plan(science_repo, audit_repo or f"{science_repo}-audit"):
            _say(f"  {step}")
        if not shutil.which("gh"):
            _say("\n  gh is not installed. The wizard requires an authenticated gh;")
            _say("  install it from https://cli.github.com and run: gh auth login")

    _say("\nNext:  crossaudit doctor        # preflight, offline, read-only")
    _say("       crossaudit check <dir>    # run the deterministic layer")
    return {"config": str(cfg_path), "constitution": str(const_path),
            "keys_file": str(written) if written else None, "mode": mode}


def gh_available() -> tuple[bool, str]:
    if not shutil.which("gh"):
        return False, "gh CLI not installed"
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if proc.returncode != 0:
        return False, "gh installed but not authenticated (run: gh auth login)"
    return True, "gh authenticated"
