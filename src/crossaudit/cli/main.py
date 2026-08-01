"""The CLI. Verbs mirror the loop; exit codes are the contract.

Every verb prints human text by default and a versioned object under --json.
Nothing here writes to a remote without an explicit --apply, and no verb
invents a default when configuration is missing: absent config denies.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from .. import RECEIPT_SCHEMA, __version__, _selfid
from ..auditor import dcl_source_digest, run_audit
from ..config import CONFIG_NAME, Config, heterogeneity, load
from ..controller import StateStore
from ..dcl import run_checks
from ..errors import (EXIT_BLOCKED, EXIT_CONFIG, EXIT_ESCALATED, EXIT_INTEGRITY,
                      EXIT_OK, ConfigDenial, Denial)
from ..gitio import (changed_paths, entries, git, is_repo, materialise,
                     parent, resolve)
from ..receipt import build as build_receipt
from ..receipt import digest as receipt_digest
from ..receipt import load as load_receipt
from ..receipt import verify as verify_receipt
from ..receipt.verify import admit as admit_receipt
from . import wizard
from .talk import cmd_routing, cmd_talk

ALLOW_CUSTOM_ENV = "CROSSAUDIT_ALLOW_CUSTOM_ENDPOINT"


def _allow_custom(args: argparse.Namespace) -> bool:
    """Sending a key to a non-builtin origin is opt-in, by flag or environment.

    Both spellings exist because the conversational surface has no flags; they
    must mean the same thing, or one verb would send a key where another
    refused to.
    """
    return bool(getattr(args, "allow_custom_endpoint", False)
                or os.environ.get(ALLOW_CUSTOM_ENV))

GETTING_STARTED = """\
CrossAudit {version} — cross-vendor audit loop for agentic science

Nothing is configured yet in this directory. One command sets it up; it will
ask for the auditing model, the two API keys, and your rules markdown, and it
writes keys to a 0600 file outside the repository.

    crossaudit init              guided setup, right here
    crossaudit init --github     the same, plus the two-repository plan

Then there is one command to remember:

    crossaudit run               audit your latest commit; everything else is automatic

It reads the increment from the commit itself, runs the deterministic checks,
runs the model audit when a key is present, writes the ledger, and tells you
what to do next. The precise tools underneath it, when you want them:

    crossaudit doctor · check · audit · verify · status

Docs: installer-design/ in the repository.
"""


def _emit(obj: dict, as_json: bool, human: str = "") -> None:
    if as_json:
        print(json.dumps({"crossaudit": __version__, **obj}, indent=2, sort_keys=True))
    elif human:
        print(human)


def _skills_manifest(cfg: Config) -> dict:
    """House skills in force, by path and hash, for the receipt."""
    from .. import skills as skills_mod

    try:
        return skills_mod.manifest(skills_mod.load(cfg.root))
    except Denial:
        return {}                     # a broken skill is reported by doctor, not here


def _state(cfg: Config) -> StateStore:
    """The state store lives beside the configuration, never in site-packages."""
    return StateStore(cfg.root / cfg.state_dir / "state.json")


# ----------------------------------------------------------------- doctor
def _offer(args, prompt: str) -> bool:
    """In --fix mode on a terminal, ask; otherwise never touch anything."""
    if not getattr(args, "fix", False) or not sys.stdin.isatty():
        return False
    return input(f"       fix now — {prompt} [Y/n] ").strip().lower() in ("", "y", "yes")


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[dict] = []
    ok = True

    def add(name: str, passed: bool, detail: str, fix: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        checks.append({"check": name, "ok": passed, "detail": detail, "fix": fix})

    ident = _selfid.identity()
    add("python", sys.version_info >= (3, 10),
        f"{sys.version.split()[0]}", "CrossAudit requires Python 3.10+")
    add("install", ident["install_mode"] != "unknown",
        f"{ident['install_mode']}, code digest {ident['code_digest_sha256'][:12]}",
        "reinstall from a wheel if this says unknown")
    if ident["install_mode"] not in _selfid.ADMISSIBLE_MODES:
        checks.append({"check": "admission-capable", "ok": False,
                       "detail": f"install mode {ident['install_mode']} may verify but "
                                 f"never admit",
                       "fix": "install the built wheel to admit receipts"})
    add("git", shutil.which("git") is not None, shutil.which("git") or "not found",
        "install git")

    try:
        cfg = load()
    except ConfigDenial as exc:
        add("config", False, exc.reason, f"run `crossaudit init` to write {CONFIG_NAME}")
        print(_render_doctor(checks, False))
        if _offer(args, "run the setup wizard here"):
            wizard.run(Path("."), mode="local", force=False)
            print("\nSetup written — running doctor again:\n")
            return cmd_doctor(args)
        return EXIT_CONFIG

    add("config", True, str(cfg.path))
    const = cfg.root / cfg.constitution
    add("constitution", const.is_file(), str(const),
        "point `constitution:` at your rules markdown")
    if const.is_file():
        from ..auditor import known_rules
        rules = known_rules(const.read_text())
        add("constitution rules", bool(rules),
            f"{len(rules)} rule IDs parsed" if rules else "no CA-* rule headings found",
            "each rule needs a '### CA-AREA-NNN' heading, or every citation is unknown")

    het_ok, why = heterogeneity(cfg)
    add("heterogeneity (I1)", het_ok, why,
        "declare generator.vendor, and make it differ from auditor.vendor")

    key_present = bool(os.environ.get(cfg.auditor.key_env, "").strip())
    if not key_present and _offer(args, f"enter the auditor API key (hidden, saved to "
                                        f"{wizard.keys_file()})"):
        import getpass
        entered = getpass.getpass("       auditor API key: ").strip()
        if entered:
            written = wizard.write_keys({cfg.auditor.key_env: entered})
            os.environ[cfg.auditor.key_env] = entered
            key_present = True
            print(f"       saved; future shells: source {written}")
    add("auditor key", key_present,
        f"${cfg.auditor.key_env} " + ("is set" if key_present else "is empty"),
        f"source {wizard.keys_file()} or export {cfg.auditor.key_env}")

    add("provider", cfg.auditor.provider in ("anthropic", "openai_compat", "replay"),
        f"{cfg.auditor.provider}:{cfg.auditor.model}", "check auditor.provider")

    state_dir = cfg.root / cfg.state_dir
    writable = os.access(state_dir.parent, os.W_OK)
    add("state store", writable, str(state_dir / "state.json"),
        "the controller must be able to persist consumed receipts")

    repo_ok = is_repo(cfg.root)
    if not repo_ok and _offer(args, f"run git init in {cfg.root}"):
        git("init", "-q", "-b", "main", cwd=cfg.root)
        repo_ok = is_repo(cfg.root)
    add("science repo is git", repo_ok, str(cfg.root),
        "run `git init` — the ledger is git, not a directory")
    if repo_ok:
        const_committed = bool(git("log", "-1", "--format=%H", "--", cfg.constitution,
                                   cwd=cfg.root, check=False))
        if not const_committed and _offer(args, f"commit {cfg.constitution} so audits "
                                                f"can cite its version"):
            git("add", "--", cfg.constitution, cwd=cfg.root)
            git("commit", "-q", "-m", "constitution: initial version", cwd=cfg.root)
            const_committed = True
        add("constitution committed", const_committed,
            "audits cite the commit that versioned the rules (I3)",
            f"git add {cfg.constitution} && git commit")

    if args.online:
        gh_ok, gh_detail = wizard.gh_available()
        add("gh cli", gh_ok, gh_detail, "install gh and run `gh auth login`")

    # The tier this deployment can honestly claim, from evidence rather than
    # from configuration. Reported always: a system that only mentions its
    # weaknesses when asked is not being honest, it is being quiet.
    from .. import admission as adm

    caps = _state(cfg).capabilities()
    verdict = adm.assess(root=cfg.root, paired=bool(cfg.audit_repo),
                         controller_persistent=caps["persistent"],
                         controller_atomic=caps["atomic"], online=args.online)
    checks.append({"check": "admission tier", "ok": True,
                   "detail": f"{verdict.tier} — {adm.TIER_MEANING[verdict.tier]}",
                   "fix": ""})
    for s in verdict.shortfalls:
        checks.append({"check": "  toward enforced", "ok": True, "detail": s,
                       "fix": ""})

    _emit({"ok": ok, "checks": checks, "verifier": ident,
           "admission": verdict.as_dict() if args.online or True else {}}, args.json,
          _render_doctor(checks, ok))
    return EXIT_OK if ok else EXIT_CONFIG


def _render_doctor(checks: list[dict], ok: bool) -> str:
    lines = ["crossaudit doctor", "=" * 60]
    for c in checks:
        mark = "PASS" if c["ok"] else "FAIL"
        lines.append(f"[{mark}] {c['check']:22s} {c['detail']}")
        if not c["ok"] and c["fix"]:
            lines.append(f"       -> {c['fix']}")
    lines.append("=" * 60)
    lines.append("ready" if ok else "not ready — fix the FAIL lines above")
    return "\n".join(lines)


# ------------------------------------------------------------------ check
def cmd_check(args: argparse.Namespace) -> int:
    cfg = load()
    root = Path(args.path or cfg.root).resolve()
    if args.sha:
        sha, _tree = resolve(cfg.root, args.sha)
        files, notes = materialise(cfg.root, sha, args.scope or "")
        where = f"{sha[:12]} (from the git tree)"
    else:
        files, notes = {}, []
        for p in sorted(root.rglob("*")):
            if p.is_symlink():
                raise ConfigDenial(f"refusing to read through a symlink: {p}")
            if p.is_file():
                files[str(p.relative_to(root))] = p.read_bytes()
        where = f"{root} (working tree)"
    result = run_checks(files, cfg.checks, notes, cfg.plugins).as_dict()
    human = [f"deterministic layer over {where}",
             f"verdict: {result['verdict']}  ({result['total_hard_failures']} hard failures)"]
    for f in result["findings"]:
        human.append(f"  [{f['severity']}] {f['rule']} {f['artifact']}: {f['observation']}")
    _emit(result, args.json, "\n".join(human))
    return EXIT_BLOCKED if result["total_hard_failures"] else EXIT_OK


# ------------------------------------------------------------------ audit
def cmd_audit(args: argparse.Namespace) -> int:
    cfg = load()
    if not is_repo(cfg.root):
        raise ConfigDenial(f"{cfg.root} is not a git repository")
    sha, tree = resolve(cfg.root, args.sha or "HEAD")

    # Local mode writes the ledger into the audited repository, so HEAD moves
    # when a report is committed. Auditing that commit would audit the audit —
    # a self-referential cycle that inflates the ledger and audits nothing.
    changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", sha,
                  cwd=cfg.root, check=False).splitlines()
    if changed and all(p.startswith(cfg.ledger_dir.rstrip("/") + "/") for p in changed):
        raise ConfigDenial(
            f"{sha[:12]} only touches the ledger ({cfg.ledger_dir}/): this is an audit "
            f"artefact, not an increment. Audit the science commit instead, or move the "
            f"ledger to the audit repository (github-pair mode).")

    store = _state(cfg)
    cycle = store.open_or_advance(cfg.science_repo, sha, parent(cfg.root, sha))
    if cycle.get("already_admitted"):
        raise ConfigDenial(f"{sha[:12]} was already admitted; open a new increment")

    files, notes = materialise(cfg.root, sha, args.scope or "")
    const_path = cfg.root / cfg.constitution
    if not const_path.is_file():
        raise ConfigDenial(f"constitution not found: {const_path}")
    constitution = const_path.read_text()
    const_commit = git("log", "-1", "--format=%H", "--", cfg.constitution,
                       cwd=cfg.root, check=False) or ""
    if not const_commit:
        raise ConfigDenial(
            f"{cfg.constitution} is not committed: an audit must cite the commit that "
            f"versioned the rules (I3). Commit it first.")

    outcome = run_audit(cfg=cfg, sha=sha, round_=cycle["round"], files=files, notes=notes,
                        constitution=constitution, constitution_commit=const_commit,
                        escalation_lock=bool(cycle.get("blocked_by_escalation")),
                        offline=args.offline,
                        allow_custom_endpoint=_allow_custom(args),
                        retention=args.retention)

    # Ledger write, in the only order that can be honest: report first, then a
    # receipt that binds the report's commit.
    base = cfg.root / cfg.ledger_dir / f"{sha[:12]}-r{cycle['round']}"
    ledger, attempt = base, 2
    while ledger.exists():
        ledger = Path(f"{base}.{attempt}")
        attempt += 1
    ledger.mkdir(parents=True)
    report_path = ledger / "report.md"
    report_path.write_text(outcome.report)
    (ledger / "checks.json").write_text(json.dumps(outcome.dcl, indent=2))

    report_commit = ""
    if args.write_ledger:
        git("add", "--", str(report_path.relative_to(cfg.root)), cwd=cfg.root)
        git("commit", "-q", "-m", f"audit report {sha[:12]} r{cycle['round']}", cwd=cfg.root)
        report_commit = git("rev-parse", "HEAD", cwd=cfg.root)

    manifest = {path: __import__("hashlib").sha256(data).hexdigest()
                for path, data in files.items()}
    receipt = build_receipt(
        cfg=cfg, subject={"sha": sha, "tree": tree, "scope": args.scope or ""},
        cycle=cycle, manifest=manifest, constitution_path=cfg.constitution,
        constitution_bytes=const_path.read_bytes(), constitution_commit=const_commit,
        dcl_source_sha256=dcl_source_digest(), prompt_sha256=outcome.prompt_sha256,
        checks=cfg.checks, skills=_skills_manifest(cfg),
        verdict=outcome.verdict, exchange=outcome.exchange,
        retention=args.retention, report_bytes=report_path.read_bytes(),
        report_commit=report_commit, cycle_path=str(ledger.relative_to(cfg.root)),
        audit_repo=cfg.audit_repo or "local", mode=args.mode,
        integrity=outcome.integrity)
    (ledger / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True))

    # Second phase of the ordering rule: the report was committed first so the
    # receipt could bind its commit; now the receipt itself joins the ledger. A
    # receipt can never contain the hash of the commit that carries it, which is
    # why this is two commits rather than one.
    if args.write_ledger:
        rel = ledger.relative_to(cfg.root)
        git("add", "--", str(rel / "receipt.json"), str(rel / "checks.json"), cwd=cfg.root)
        git("commit", "-q", "-m",
            f"audit receipt {sha[:12]} r{cycle['round']} ({outcome.verdict})", cwd=cfg.root)

    status = store.record_verdict(cycle["cycle_id"], sha, outcome.verdict,
                                  receipt_digest(receipt), cfg.max_rounds)
    result = {"verdict": outcome.verdict, "cycle_status": status,
              "cycle_id": cycle["cycle_id"], "round": cycle["round"],
              "integrity": outcome.integrity, "receipt": str(ledger / "receipt.json"),
              "report": str(report_path),
              "invalid_reason": outcome.invalid_reason}
    human = (f"{outcome.verdict}  (cycle {cycle['cycle_id']} round {cycle['round']}"
             f" -> {status})\n  report:  {report_path}\n  receipt: {ledger}/receipt.json")
    if outcome.invalid_reason:
        human += f"\n  audit rejected: {outcome.invalid_reason}"
    _emit(result, args.json, human)
    # The cycle's status outranks the round's verdict: a BLOCKED round that
    # exhausted the budget has escalated, and a caller scripting the loop needs
    # to hear that rather than plan another revision.
    if status == "ESCALATED":
        return EXIT_ESCALATED
    return {"PASS": EXIT_OK, "BLOCKED": EXIT_BLOCKED}.get(outcome.verdict, EXIT_ESCALATED)


# ----------------------------------------------------------------- verify
def cmd_verify(args: argparse.Namespace) -> int:
    cfg = load()
    path = Path(args.receipt).resolve()
    receipt = load_receipt(path)
    evidence = verify_receipt(
        receipt, science_root=Path(args.science_root or cfg.root).resolve(),
        audit_root=Path(args.audit_root or cfg.root).resolve(),
        expect_repo=args.expect_repo or cfg.science_repo,
        expect_sha=args.expect_sha or receipt["subject"]["sha"], cfg=cfg)
    out = {"verified": True, **evidence, "admitted": False}
    if args.admit:
        out.update(admit_receipt(receipt, _state(cfg), evidence))
    human = (f"VERIFIED  receipt {evidence['receipt_digest'][:16]} for "
             f"{evidence['sha'][:12]}"
             + ("\nADMITTED  consumed once; the cycle is closed" if args.admit
                else "\n(dry run: nothing consumed)"))
    _emit(out, args.json, human)
    return EXIT_OK


# ----------------------------------------------------------------- status
def cmd_status(args: argparse.Namespace) -> int:
    cfg = load()
    snap = _state(cfg).snapshot()
    cycles = snap.get("cycles", {})
    rows = [{"cycle_id": cid, "status": c["status"], "round": c["round"],
             "active_sha": c["active_sha"][:12], "consumed": len(c.get("consumed", []))}
            for cid, c in sorted(cycles.items())]
    human = ["cycle            status     round  sha           consumed",
             "-" * 60]
    human += [f"{r['cycle_id']:16s} {r['status']:10s} {r['round']:5d}  "
              f"{r['active_sha']}  {r['consumed']}" for r in rows] or ["(no cycles yet)"]
    _emit({"cycles": rows}, args.json, "\n".join(human))
    return EXIT_OK


# ---------------------------------------------------------------- resolve
def cmd_resolve(args: argparse.Namespace) -> int:
    """The human principal rules on an escalated cycle. Interactive only: this
    is a human act and must not be scriptable by the agents themselves."""
    if not sys.stdin.isatty():
        raise ConfigDenial("resolve is a human act; it refuses to run without a terminal")
    cfg = load()
    action = "reopen" if args.reopen else "close"
    c = _state(cfg).resolve_escalation(args.cycle_id, action, args.because)
    print(f"ruling recorded: {args.cycle_id} {action} — {args.because}")
    print(f"cycle is now {c['status']} (round {c['round']}); "
          + ("run `crossaudit run` to re-audit." if action == "reopen"
             else "the increment stays out of the record."))
    return EXIT_OK


def cmd_skills(args: argparse.Namespace) -> int:
    """Show the house skills, or write a starter one.

    Skills shape how the generator works. They are deliberately not rules: the
    auditor never sees them, so nothing here can move the bar the work is judged
    against — that is what `amend` is for, and why it leaves a dated record.
    """
    from .. import skills as skills_mod

    cfg = load()
    base = cfg.root / skills_mod.SKILLS_DIR
    if args.new:
        base.mkdir(parents=True, exist_ok=True)
        target = base / f"{args.new}.md"
        if target.exists():
            raise ConfigDenial(f"{target} already exists")
        target.write_text(skills_mod.TEMPLATE)
        print(f"wrote {target.relative_to(cfg.root)} — edit it, commit it, and the "
              f"generator follows it from the next round.")
        return EXIT_OK

    house = skills_mod.load(cfg.root)
    if not house:
        print(f"No skills yet. `crossaudit skills --new house-style` writes one.\n"
              f"A skill is guidance on how to work: conventions, the shape of a good\n"
              f"output, worked examples. The standards your work is judged by are the\n"
              f"Constitution instead, because those need a dated record when they move.")
        return EXIT_OK
    rows = [{"name": s.name, "path": s.path, "applies_to": list(s.applies_to),
             "sha256": s.digest} for s in house]
    human = ["house skills (guidance for the generator; the auditor never sees them)",
             "-" * 72]
    for s in house:
        scope = ", ".join(s.applies_to) if s.applies_to else "every round"
        human.append(f"  {s.name:22s} {scope}")
        human.append(f"  {'':22s} {s.path}  {s.digest[:12]}")
    _emit({"skills": rows}, args.json, "\n".join(human))
    return EXIT_OK


def cmd_console(args: argparse.Namespace) -> int:
    """The console, optionally outliving the terminal that started it.

    Default behaviour is to keep running after the window closes and to reattach
    on the next invocation: closing a tab was never meant to end a build, and
    neither should closing a shell.
    """
    import signal

    from ..console import daemon, serve

    cfg = load()

    if args.stop:
        print(daemon.stop(cfg))
        return EXIT_OK

    running = daemon.live(cfg)
    if args.status:
        if running:
            print(f"  console running (pid {running['pid']}) — {daemon.url_for(running)}")
        else:
            print("  no console running here")
        return EXIT_OK

    if running and not args.foreground:
        # Reattach rather than start a rival: two consoles would race on the
        # working tree and on the round budget.
        print(f"\n  A console is already running for this project (pid "
              f"{running['pid']}).\n  {daemon.url_for(running)}\n\n"
              f"  Stop it with `crossaudit console --stop`.", flush=True)
        return EXIT_OK

    if not args.foreground:
        try:
            info = daemon.spawn(cfg, args.port)
        except TimeoutError as exc:
            raise ConfigDenial(str(exc)) from exc
        print(f"\n  CrossAudit console — running in the background (pid "
              f"{info['pid']})\n  {daemon.url_for(info)}\n\n"
              "  It keeps running when you close this window, and a build keeps\n"
              "  going with it. Come back with `crossaudit console` for the URL,\n"
              "  or end it with `crossaudit console --stop`.", flush=True)
        return EXIT_OK

    # Foreground: this is the process the daemon actually runs.
    url, httpd = serve(cfg, port=args.port, register=True,
                       idle_timeout=float("inf") if os.environ.get(
                           "CROSSAUDIT_CONSOLE_CHILD") else 900.0)
    print(f"\n  CrossAudit console — read/write over loopback\n  {url}\n\n"
          "  Loopback only, and the token above is required on every request.\n"
          "  Ctrl-C to stop.", flush=True)

    def bye(*_a) -> None:
        daemon.clear_run(cfg)
        httpd.shutdown()

    signal.signal(signal.SIGTERM, bye)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  closed")
    finally:
        daemon.clear_run(cfg)
    return EXIT_OK


def _cmd_pair(args: argparse.Namespace) -> int:
    from .pair import cmd_pair

    return cmd_pair(args)


def _cmd_build(args: argparse.Namespace) -> int:
    from .build import cmd_build

    return cmd_build(args)


# ------------------------------------------------------------------ amend
def cmd_amend(args: argparse.Namespace) -> int:
    """Change the rules by saying what should change. Same path as `talk`'s
    amendment lane, reachable directly when the user already knows the lane."""
    from .talk import lane_amendment
    from ..router import Routing, record
    from .talk import _routing_path

    cfg = load()
    text = " ".join(args.words).strip()
    if not text:
        raise ConfigDenial('say what should change: crossaudit amend "from now on ..."')
    routing = Routing(utterance=text, lane="amendment", confidence=1.0,
                      reasoning="named explicitly by the user", restated=text)
    executed = lane_amendment(cfg, routing, assume_yes=args.yes)
    record(_routing_path(cfg), routing, executed)
    return EXIT_OK


# ------------------------------------------------------------------ watch
def cmd_watch(args: argparse.Namespace) -> int:
    from .watch import run_watch

    return run_watch(load())


# ------------------------------------------------------------------- init
def cmd_init(args: argparse.Namespace) -> int:
    summary = wizard.run(Path(args.path or "."), mode="github" if args.github else "local",
                         force=args.force)
    _emit(summary, args.json)
    return EXIT_OK


# -------------------------------------------------------------------- run
def _step(n: int, total: int, label: str) -> None:
    print(f"  [{n}/{total}] {label:24s}", end="", flush=True)


def _done(msg: str) -> None:
    print(f"ok — {msg}")


def cmd_run(args: argparse.Namespace) -> int:
    """The guided verb: audit the latest commit, narrate every step, decide
    nothing the commit itself cannot decide. `audit` remains the precise tool;
    `run` is the one you can give a colleague with no explanation."""
    try:
        cfg = load()
    except ConfigDenial:
        if sys.stdin.isatty():
            print("Nothing is configured here yet — starting setup.\n")
            wizard.run(Path("."), mode="local", force=False)
            print("\nSetup done. Run `crossaudit run` again to audit your latest commit.")
            return EXIT_OK
        raise

    if not is_repo(cfg.root):
        raise ConfigDenial(f"{cfg.root} is not a git repository; the loop audits commits")

    sha, tree = resolve(cfg.root, args.sha or "HEAD")
    subject = git("log", "-1", "--format=%s", cwd=cfg.root, check=False)

    # The increment is what the commit changed, minus the loop's own artefacts.
    own = {cfg.constitution, "crossaudit.yml", ".gitignore"}
    prefix_own = (cfg.ledger_dir.rstrip("/") + "/", cfg.state_dir.rstrip("/") + "/",
                  ".github/")
    def science_of(s: str) -> list[str]:
        picked = [f for f in changed_paths(cfg.root, s)
                  if f not in own and not f.startswith(prefix_own)]
        if cfg.scope_dirs:
            # The deployment names its science directories (the reference
            # implementation always did: pushes under experiments/ trigger).
            # Tooling and housekeeping commits outside them are not increments
            # and are not forced through the experiment format.
            picked = [f for f in picked
                      if f.split("/", 1)[0] in cfg.scope_dirs]
        return picked

    def enclose(paths: list[str], s: str) -> list[str]:
        """Widen a diff to the increments it touched.

        A revision commit often changes results.json alone, but an increment is
        the whole experiment directory: metadata, summary and data are read
        together, and checks that see only the diff would report the untouched
        files as missing. So the scope is every file under the directories the
        commit touched, taken from the tree, which is also the containment
        property the roadmap asks for at directory granularity.
        """
        dirs = {str(Path(f).parent) for f in paths}
        dirs = {d for d in dirs if d not in (".", "")}
        if not dirs:
            return paths
        widened = {f for _m, f, _b in entries(cfg.root, s)
                   if str(Path(f).parent) in dirs
                   and f not in own and not f.startswith(prefix_own)}
        return sorted(widened | set(paths))

    science = science_of(sha)
    if not science and not args.sha:
        # HEAD is a ledger or config commit (the loop's own bookkeeping moves
        # HEAD in local mode). Walk back to the newest commit that actually
        # changed science, instead of asking the user to think about it.
        for cand in git("log", "--format=%H", "-n", "50", cwd=cfg.root,
                        check=False).splitlines()[1:]:
            found = science_of(cand)
            if found:
                sha, tree = resolve(cfg.root, cand)
                subject = git("log", "-1", "--format=%s", sha, cwd=cfg.root, check=False)
                science = found
                print(f"  (HEAD is ledger bookkeeping; auditing the newest science "
                      f"commit instead: {sha[:12]})")
                break
    if not science:
        raise ConfigDenial(
            f"{sha[:12]} ({subject!r}) changed no science files — only rules, "
            f"configuration or ledger. Commit your experiment, then run again.")

    dirty = git("status", "--porcelain", cwd=cfg.root, check=False)
    from ..providers.registry import NEEDS_KEY
    key_present = bool(os.environ.get(cfg.auditor.key_env, "").strip())
    key_needed = NEEDS_KEY.get(cfg.auditor.provider, True)
    offline = key_needed and not key_present
    if not offline:
        het_ok, het_why = heterogeneity(cfg)
        if not het_ok:
            # Refused before a cycle opens or a request leaves: a same-vendor
            # pair is same-source supervision, the thing this protocol exists
            # to prevent (I1).
            raise ConfigDenial(het_why)

    print("CrossAudit — one increment through the loop")
    print("=" * 60)
    print(f"  commit     {sha[:12]}  {subject!r}")
    touched = len(science)
    science = enclose(science, sha)
    scope_note = (f"{len(science)} file(s) in the touched experiment folder(s)"
                  if len(science) != touched else f"{len(science)} file(s)")
    print(f"  increment  {scope_note}, resolved from the commit")
    const_commit = git("log", "-1", "--format=%H", "--", cfg.constitution,
                       cwd=cfg.root, check=False)
    if not const_commit:
        raise ConfigDenial(f"{cfg.constitution} is not committed; commit it first "
                           f"(an audit must cite the rules' commit)")
    from ..auditor import known_rules
    const_text = (cfg.root / cfg.constitution).read_text()
    print(f"  rules      {cfg.constitution} @ {const_commit[:12]} "
          f"({len(known_rules(const_text))} rules)")
    print(f"  auditor    {cfg.auditor.provider}:{cfg.auditor.model} "
          f"({'no key needed' if not key_needed else 'key found' if key_present else 'key MISSING -> deterministic checks only'})")
    if dirty:
        print("  note       uncommitted changes exist; the audit reads the COMMIT, "
              "not your working tree")
    print()

    store = _state(cfg)
    cycle = store.open_or_advance(cfg.science_repo, sha, parent(cfg.root, sha))
    if cycle.get("already_admitted"):
        print("  This commit was already audited, passed, and admitted. Nothing to do.")
        return EXIT_OK
    if cycle.get("blocked_by_escalation"):
        print("  An earlier round ESCALATED: a human decision is pending, and new "
              "commits cannot route around it.")
        print(f"  You are the human here. Rule on it:  crossaudit resolve "
              f"{cycle['cycle_id']} --reopen --because '<why>'")
        return EXIT_ESCALATED
    if not cycle.get("awaiting_verdict") and cycle["active_sha"] == sha:
        print(f"  Already audited (round {cycle['round']}, status {cycle['status']}).")
        print(f"  Commit a fix and run again. To re-audit this same commit (a dispute "
              f"or second opinion), use: crossaudit audit --sha {sha[:12]}")
        return EXIT_OK

    total = 2 if offline else 3
    _step(1, total, "deterministic checks")
    files, notes = materialise(cfg.root, sha, "", only=science)
    outcome = run_audit(cfg=cfg, sha=sha, round_=cycle["round"], files=files, notes=notes,
                        constitution=const_text, constitution_commit=const_commit,
                        offline=offline,
                        allow_custom_endpoint=_allow_custom(args),
                        retention="sealed")
    hard = outcome.dcl["total_hard_failures"]
    _done("clean" if hard == 0 else f"{hard} hard failure(s)")
    if not offline:
        _step(2, total, "model audit")
        if outcome.invalid_reason:
            _done(f"rejected ({outcome.invalid_reason[:60]})")
        elif outcome.model_reply is None:
            _done("did not run")
        else:
            n = len(outcome.model_reply.get("findings", []))
            b = sum(1 for f in outcome.model_reply["findings"]
                    if f["severity"] == "BLOCKER")
            _done(f"reply valid, {n} finding(s), {b} blocking")

    _step(total, total, "ledger")
    # Append-only with legitimate re-audits: a resumed or human-reopened round
    # re-runs the same round number, so the directory takes the next attempt
    # suffix instead of overwriting anything. The voided attempt stays visible
    # beside its replacement, which is what an append-only ledger means.
    base = cfg.root / cfg.ledger_dir / f"{sha[:12]}-r{cycle['round']}"
    ledger, attempt = base, 2
    while ledger.exists():
        ledger = Path(f"{base}.{attempt}")
        attempt += 1
    ledger.mkdir(parents=True)
    (ledger / "report.md").write_text(outcome.report)
    (ledger / "checks.json").write_text(json.dumps(outcome.dcl, indent=2))
    rel = ledger.relative_to(cfg.root)
    git("add", "--", str(rel / "report.md"), str(rel / "checks.json"), cwd=cfg.root)
    git("commit", "-q", "-m", f"audit report {sha[:12]} r{cycle['round']}", cwd=cfg.root)
    report_commit = git("rev-parse", "HEAD", cwd=cfg.root)
    manifest = {p_: __import__("hashlib").sha256(b).hexdigest()
                for p_, b in files.items()}
    receipt = build_receipt(
        cfg=cfg, subject={"sha": sha, "tree": tree, "scope": "changed-paths"},
        cycle=cycle, manifest=manifest, constitution_path=cfg.constitution,
        constitution_bytes=const_text.encode(), constitution_commit=const_commit,
        dcl_source_sha256=dcl_source_digest(), prompt_sha256=outcome.prompt_sha256,
        checks=cfg.checks, skills=_skills_manifest(cfg),
        verdict=outcome.verdict, exchange=outcome.exchange,
        retention="sealed", report_bytes=outcome.report.encode(),
        report_commit=report_commit, cycle_path=str(rel),
        audit_repo=cfg.audit_repo or "local", mode="local",
        integrity=outcome.integrity)
    (ledger / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True))
    git("add", "--", str(rel / "receipt.json"), cwd=cfg.root)
    git("commit", "-q", "-m",
        f"audit receipt {sha[:12]} r{cycle['round']} ({outcome.verdict})", cwd=cfg.root)
    status = store.record_verdict(cycle["cycle_id"], sha, outcome.verdict,
                                  receipt_digest(receipt), cfg.max_rounds)
    _done("report + receipt committed")

    print()
    print(f"  VERDICT: {outcome.verdict}   (cycle {cycle['cycle_id'][:8]}, "
          f"round {cycle['round']} of {cfg.max_rounds})")
    print()
    if outcome.verdict == "BLOCKED":
        blockers = [f for f in outcome.dcl["findings"] if f["severity"] == "BLOCKER"]
        if outcome.model_reply:
            blockers += [f for f in outcome.model_reply["findings"]
                         if f["severity"] == "BLOCKER"]
        print("  What blocked it:")
        for f in blockers:
            print(f"    - [{f['rule']}] {f['artifact']}: {f['observation'][:100]}")
        print()
        if status == "ESCALATED":
            print("  Round budget exhausted: this increment is now in human hands (I5).")
        else:
            print("  Fix these, commit, and run `crossaudit run` again "
                  f"(round {cycle['round'] + 1} of {cfg.max_rounds}).")
    elif outcome.verdict == "PASS":
        print("  Next: consume the receipt to admit this increment:")
        print(f"    crossaudit verify {rel}/receipt.json --admit")
    elif outcome.verdict == "DCL_ONLY":
        print("  Checks passed, but no model reviewed this (no API key), so it can")
        print("  never be PASS. Add a key (`crossaudit init --force`), then re-run.")
    else:
        print(f"  Escalated: {outcome.invalid_reason or 'a human decision is needed'}")
        print(f"  Report: {rel}/report.md")
    if status == "ESCALATED":
        return EXIT_ESCALATED
    return {"PASS": EXIT_OK, "BLOCKED": EXIT_BLOCKED}.get(outcome.verdict, EXIT_ESCALATED)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crossaudit", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version",
                   version=f"crossaudit {__version__} (receipt schema {RECEIPT_SCHEMA})")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="verb")

    i = sub.add_parser("init", help="guided setup: keys, rules, configuration")
    i.add_argument("path", nargs="?",
                   help="directory to set up; created if it does not exist "
                        "(default: here)")
    i.add_argument("--github", action="store_true", help="also plan the repository pair")
    i.add_argument("--force", action="store_true", help="overwrite an existing config")
    i.set_defaults(func=cmd_init)

    r = sub.add_parser("run", help="audit your latest commit; everything else is automatic")
    r.add_argument("--sha", help="a specific commit instead of HEAD")
    r.add_argument("--allow-custom-endpoint", action="store_true",
                   help=argparse.SUPPRESS)
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("doctor", help="preflight; --fix walks you through repairs")
    d.add_argument("--online", action="store_true", help="also probe gh")
    d.add_argument("--fix", action="store_true",
                   help="offer to repair each failure interactively")
    d.set_defaults(func=cmd_doctor)

    c = sub.add_parser("check", help="run the deterministic layer, no model involved")
    c.add_argument("path", nargs="?", help="directory to check")
    c.add_argument("--sha", help="check a commit's tree instead of the working directory")
    c.add_argument("--scope", help="path prefix within the tree")
    c.set_defaults(func=cmd_check)

    a = sub.add_parser("audit", help="one full cycle: checks, model audit, report, receipt")
    a.add_argument("--sha", help="commit to audit (default HEAD)")
    a.add_argument("--scope", help="path prefix within the tree")
    a.add_argument("--offline", action="store_true",
                   help="deterministic layer only; yields DCL_ONLY, never PASS")
    a.add_argument("--write-ledger", action="store_true",
                   help="commit the report so the receipt can bind its commit")
    a.add_argument("--allow-custom-endpoint", action="store_true",
                   help="permit a non-builtin provider origin (sends your key there)")
    a.add_argument("--retention", choices=("sealed", "redacted", "no-raw"),
                   default="sealed")
    a.add_argument("--mode", choices=("local", "github-pair"), default="local")
    a.add_argument("--force", action="store_true", help="reuse an existing cycle directory")
    a.set_defaults(func=cmd_audit)

    v = sub.add_parser("verify", help="re-derive every binding; --admit to consume")
    v.add_argument("receipt")
    v.add_argument("--admit", action="store_true", help="consume the receipt, once")
    v.add_argument("--science-root")
    v.add_argument("--audit-root")
    v.add_argument("--expect-repo")
    v.add_argument("--expect-sha")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("status", help="where each cycle stands")
    s.set_defaults(func=cmd_status)

    w = sub.add_parser("watch", help="live view: generator, auditor, and their conversation")
    w.set_defaults(func=cmd_watch)

    sk = sub.add_parser("skills", help="house guidance for the generator")
    sk.add_argument("--new", metavar="NAME", help="write a starter skill")
    sk.set_defaults(func=cmd_skills)

    co = sub.add_parser("console", help="read-only ledger in a browser (loopback)")
    co.add_argument("--port", type=int, default=0, help="0 picks a free port")
    co.add_argument("--foreground", action="store_true",
                    help="run here and stop when this window closes")
    co.add_argument("--stop", action="store_true", help="stop the running console")
    co.add_argument("--status", action="store_true", help="is one running?")
    co.set_defaults(func=cmd_console)

    pr = sub.add_parser("pair", help="create the two repositories (plan, then --apply)")
    pr.add_argument("--science", help="owner/name for the work repository")
    pr.add_argument("--audit", help="owner/name for the audit repository")
    pr.add_argument("--public", action="store_true")
    pr.add_argument("--apply", action="store_true", help="actually create them")
    pr.set_defaults(func=_cmd_pair)

    b = sub.add_parser("build", help='say what to build; the loop writes and audits it')
    b.add_argument("words", nargs="*")
    b.set_defaults(func=_cmd_build)

    tk = sub.add_parser("talk", help="say what you want; the program routes it")
    tk.add_argument("words", nargs="+")
    tk.add_argument("--yes", action="store_true", help="skip confirmations")
    tk.set_defaults(func=cmd_talk)

    rt = sub.add_parser("routing", help="every routing decision ever made")
    rt.add_argument("--limit", type=int, default=50)
    rt.set_defaults(func=cmd_routing)

    am = sub.add_parser("amend", help='change the rules: amend "from now on ..."')
    am.add_argument("words", nargs="+")
    am.add_argument("--yes", action="store_true")
    am.set_defaults(func=cmd_amend)

    res = sub.add_parser("resolve", help="rule on an escalated cycle (human only)")
    res.add_argument("cycle_id")
    g = res.add_mutually_exclusive_group(required=True)
    g.add_argument("--reopen", action="store_true", help="return it to the loop")
    g.add_argument("--close", action="store_true", help="end it without admission")
    res.add_argument("--because", required=True, help="the reason; it enters the ledger")
    res.set_defaults(func=cmd_resolve)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "verb", None):
        # First-run funnel: pip cannot run a wizard at install time (and must
        # not — constraint 7), so the first bare invocation is the doorway.
        try:
            load()
        except Denial:
            if sys.stdin.isatty():
                print("CrossAudit is installed but this directory is not set up.")
                if input("Set it up now? [Y/n] ").strip().lower() in ("", "y", "yes"):
                    wizard.run(Path("."), mode="local", force=False)
                    print("\nNow: `crossaudit doctor --fix` to finish, then "
                          "`crossaudit run`.")
                    return EXIT_OK
            print(GETTING_STARTED.format(version=__version__))
            return EXIT_OK
        print(GETTING_STARTED.format(version=__version__))
        return EXIT_OK
    try:
        return args.func(args)
    except Denial as exc:
        if getattr(args, "json", False):
            print(json.dumps(exc.as_dict(), indent=2, sort_keys=True))
        else:
            print(f"DENIED ({exc.kind}): {exc.reason}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
