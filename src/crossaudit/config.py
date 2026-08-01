"""`crossaudit.yml`: the one configuration file, schema-validated on load.

Credentials never appear here. The file names the *environment variable* that
carries a key; the value is read at call time and never echoed, never logged,
never written into a receipt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .errors import ConfigDenial

CONFIG_NAME = "crossaudit.yml"

#: Isolation dimensions, in the paper's own terms (I1). Recorded as evidence
#: per deployment, and compared against `isolation.minimum` before admission.
ISOLATION_DIMS = ("parametric", "contextual", "permissive")

_ALLOWED_TOP = {"version", "science_repo", "audit_repo", "constitution", "max_rounds",
                "auditor", "generator", "isolation", "state", "ledger", "scope",
                "checks", "plugins"}
_ALLOWED_ROLE = {"provider", "model", "base_url", "key_env", "vendor"}


@dataclass(frozen=True)
class Role:
    provider: str
    model: str
    vendor: str
    key_env: str
    base_url: str | None = None


@dataclass(frozen=True)
class Config:
    path: Path
    science_repo: str
    audit_repo: str | None
    constitution: str
    max_rounds: int
    auditor: Role
    generator_vendor: str | None
    isolation_minimum: dict
    state_dir: str
    ledger_dir: str
    scope_dirs: list[str] | None
    checks: list[str]
    plugins: list[str] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.path.parent


def _role(raw: dict, name: str, where: Path) -> Role:
    unknown = set(raw) - _ALLOWED_ROLE
    if unknown:
        raise ConfigDenial(f"{name}: unknown keys {sorted(unknown)}", file=str(where))
    for req in ("provider", "model", "vendor", "key_env"):
        if not raw.get(req):
            raise ConfigDenial(f"{name}.{req} is required", file=str(where))
    return Role(provider=raw["provider"], model=raw["model"], vendor=raw["vendor"],
                key_env=raw["key_env"], base_url=raw.get("base_url"))


def find(start: Path | None = None) -> Path:
    """Nearest crossaudit.yml from `start` upward. Absent = denial, not a default."""
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if (d / CONFIG_NAME).is_file():
            return d / CONFIG_NAME
    raise ConfigDenial(f"no {CONFIG_NAME} found from {cur} upward — run `crossaudit init`")


def load(path: Path | None = None) -> Config:
    p = path or find()
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigDenial(f"{CONFIG_NAME} is not valid YAML: {exc}", file=str(p)) from exc
    if not isinstance(raw, dict):
        raise ConfigDenial(f"{CONFIG_NAME} must be a mapping", file=str(p))

    unknown = set(raw) - _ALLOWED_TOP
    if unknown:
        raise ConfigDenial(f"unknown top-level keys {sorted(unknown)}", file=str(p))
    if raw.get("version") != 1:
        raise ConfigDenial(f"config version {raw.get('version')!r} unsupported (expected 1)",
                           file=str(p))
    for req in ("science_repo", "constitution", "auditor"):
        if not raw.get(req):
            raise ConfigDenial(f"{req} is required", file=str(p))

    auditor = _role(raw["auditor"] or {}, "auditor", p)
    gen = raw.get("generator") or {}
    generator_vendor = gen.get("vendor")

    iso_raw = raw.get("isolation") or {}
    minimum = iso_raw.get("minimum") or {}
    if set(minimum) - set(ISOLATION_DIMS):
        raise ConfigDenial(f"isolation.minimum keys must be within {list(ISOLATION_DIMS)}",
                           file=str(p))
    if not all(isinstance(v, bool) for v in minimum.values()):
        raise ConfigDenial("isolation.minimum values must be booleans", file=str(p))

    rounds = raw.get("max_rounds", 3)
    if not isinstance(rounds, int) or rounds < 1:
        raise ConfigDenial("max_rounds must be a positive integer", file=str(p))

    # State is mutable and local (gitignored); the ledger is immutable and
    # committed. They must not share a directory: one has to be ignored and the
    # other has to be committable, and a single path cannot be both.
    state_dir = (raw.get("state") or {}).get("dir", ".crossaudit")
    ledger_dir = (raw.get("ledger") or {}).get("dir", "cycles")
    s, l = Path(state_dir), Path(ledger_dir)
    if s == l or s in l.parents or l in s.parents:
        raise ConfigDenial(
            f"state.dir ({state_dir}) and ledger.dir ({ledger_dir}) overlap: the state "
            f"store is gitignored and the ledger must be committable, so one directory "
            f"cannot serve both", file=str(p))

    scope_dirs = (raw.get("scope") or {}).get("dirs")
    if scope_dirs is not None and (not isinstance(scope_dirs, list)
                                   or not all(isinstance(d, str) and d for d in scope_dirs)):
        raise ConfigDenial("scope.dirs must be a list of directory names", file=str(p))

    checks = raw.get("checks") or ["schema", "units", "convergence", "provenance"]
    if not isinstance(checks, list) or not all(isinstance(c, str) for c in checks):
        raise ConfigDenial("checks must be a list of names", file=str(p))

    return Config(
        path=p,
        science_repo=raw["science_repo"],
        audit_repo=raw.get("audit_repo"),
        constitution=raw["constitution"],
        max_rounds=rounds,
        auditor=auditor,
        generator_vendor=generator_vendor,
        isolation_minimum={d: bool(minimum.get(d, False)) for d in ISOLATION_DIMS},
        state_dir=state_dir,
        ledger_dir=ledger_dir,
        scope_dirs=scope_dirs,
        checks=checks,
        plugins=raw.get("plugins") or [],
    )


def heterogeneity(cfg: Config) -> tuple[bool, str]:
    """I1 asserted from configuration. Unknown generator vendor cannot assert it."""
    if not cfg.generator_vendor:
        return False, "generator vendor not declared: I1 cannot be asserted from config"
    if cfg.generator_vendor.strip().lower() == cfg.auditor.vendor.strip().lower():
        return False, (f"I1 violated: auditor vendor {cfg.auditor.vendor!r} equals "
                       f"generator vendor {cfg.generator_vendor!r}")
    return True, f"{cfg.generator_vendor} -> {cfg.auditor.vendor}"
