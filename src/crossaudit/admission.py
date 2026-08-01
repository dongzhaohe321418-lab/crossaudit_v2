"""The admission tier: what a deployment can honestly claim, and why.

Four tiers, and the whole point of this module is that a deployment is told
which one it is actually at rather than which one it hoped for. The word
"enforced" is the only one that means a merge can be refused, and it is the one
a system is most tempted to use prematurely.

    local        one history, yours to rewrite. Self-review, not accountability.
    remote       history out of unilateral control: you can be held to your own
                 record, because you can no longer quietly rebase it away.
    paired       privilege separation: the generator cannot reach the rules or
                 the reports, so the ledger can hold the two agents to account
                 against each other.
    enforced     a failed audit actually refuses the merge.

`enforced` needs four things at once, and every one of them is checked against
the platform rather than inferred from configuration:

1. a **persistent controller** whose state survives the workflow run that wrote
   it — a receipt consumed inside a throwaway checkout is not consumed;
2. that controller consuming receipts **atomically**, so two runs cannot both
   admit the same one;
3. an admission check that is **required** on the protected branch, and bound to
   a **verified App identity** — otherwise any writer can post a green status
   under the same name, and the gate is decorative;
4. **no direct push and no admin bypass**, or the gate is optional for exactly
   the people most able to route around it.

Anything less is reported as what it is. A system that says "enforced" when it
means "we posted a status" is worse than one that says nothing: it manufactures
confidence that the ledger cannot support.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

LOCAL, REMOTE, PAIRED, ENFORCED = "local", "remote", "paired", "enforced"
NOTIFICATION = "verified-notification"

TIER_MEANING = {
    LOCAL: "self-review; the history is yours to rewrite",
    REMOTE: "history out of unilateral control",
    PAIRED: "privilege separation between the two agents",
    NOTIFICATION: "the verdict is published and checkable, but nothing is refused",
    ENFORCED: "a failed audit refuses the merge",
}

CHECK_NAME = "crossaudit/admission"


@dataclass
class Assessment:
    tier: str
    reasons: list[str] = field(default_factory=list)
    shortfalls: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def enforced(self) -> bool:
        return self.tier == ENFORCED

    def as_dict(self) -> dict:
        return {"tier": self.tier, "means": TIER_MEANING[self.tier],
                "reasons": self.reasons, "shortfalls": self.shortfalls,
                "evidence": self.evidence}

    def render(self) -> str:
        lines = [f"admission tier: {self.tier}", f"  means: {TIER_MEANING[self.tier]}"]
        for r in self.reasons:
            lines.append(f"  + {r}")
        for s in self.shortfalls:
            lines.append(f"  - {s}")
        if not self.enforced:
            lines.append("  To claim enforced admission, close the gaps above; until "
                         "then this deployment publishes verdicts, it does not "
                         "refuse merges.")
        return "\n".join(lines)


def _gh(*args: str) -> tuple[int, str]:
    exe = shutil.which("gh")
    if not exe:
        return 127, "gh not installed"
    p = subprocess.run([exe, *args], capture_output=True, text=True)
    return p.returncode, (p.stdout if p.returncode == 0 else p.stderr).strip()


def _remote_repo(root: Path) -> str | None:
    p = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(root),
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    url = p.stdout.strip()
    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            return url[len(prefix):].removesuffix(".git")
    return None


def probe_branch_protection(repo: str, branch: str = "main") -> dict:
    """Read the rules that actually exist, not the plan that was printed.

    Plan text is not evidence: a wizard that printed a protection command has
    told you nothing about whether it succeeded, whether the plan permits it, or
    whether someone has since turned it off.
    """
    code, out = _gh("api", f"repos/{repo}/branches/{branch}/protection")
    if code == 127:
        return {"reachable": False, "why": "gh not installed"}
    if code != 0:
        low = out.lower()
        if "not protected" in low or "404" in low:
            return {"reachable": True, "protected": False,
                    "why": "the branch has no protection rule"}
        if "upgrade" in low or "not available" in low:
            return {"reachable": True, "protected": False,
                    "why": "protection is unavailable on this repository's plan"}
        return {"reachable": True, "protected": False, "why": out[:160]}
    try:
        rules = json.loads(out)
    except json.JSONDecodeError:
        return {"reachable": True, "protected": False, "why": "unreadable protection"}
    checks = rules.get("required_status_checks") or {}
    contexts = checks.get("contexts") or [
        c.get("context") for c in (checks.get("checks") or [])]
    apps = [c.get("app_id") for c in (checks.get("checks") or [])]
    return {
        "reachable": True,
        "protected": True,
        "required_checks": contexts,
        "admission_required": CHECK_NAME in contexts,
        "app_bound": any(a for a in apps),
        "enforce_admins": bool((rules.get("enforce_admins") or {}).get("enabled")),
        "allows_force_push": bool((rules.get("allow_force_pushes") or {}).get("enabled")),
    }


def assess(*, root: Path, paired: bool, controller_persistent: bool,
           controller_atomic: bool, branch: str = "main",
           online: bool = False) -> Assessment:
    """Decide the tier from evidence. Absent evidence never counts in favour."""
    reasons: list[str] = []
    shortfalls: list[str] = []
    evidence: dict = {}

    repo = _remote_repo(root)
    if not repo:
        return Assessment(LOCAL, ["a local repository with no remote"],
                          ["the history can be rewritten by whoever holds it, so it "
                           "cannot hold anyone to account"], {"remote": None})
    reasons.append(f"history is pushed to {repo}, out of unilateral control")
    evidence["remote"] = repo
    tier = REMOTE

    if paired:
        reasons.append("the rules and reports live in a repository the generator "
                       "cannot write to")
        tier = PAIRED
    else:
        shortfalls.append("one repository holds both the work and the rules that "
                          "judge it: no privilege separation between the agents")

    if controller_persistent and controller_atomic:
        reasons.append("receipts are consumed atomically in a store that outlives "
                       "the run that wrote it")
    else:
        if not controller_persistent:
            shortfalls.append("the controller's state does not outlive the run: a "
                              "receipt 'consumed' in a throwaway checkout is not "
                              "consumed")
        if not controller_atomic:
            shortfalls.append("receipt consumption is not atomic: two runs could "
                              "both admit the same receipt")

    if not online:
        shortfalls.append("branch protection was not probed (run doctor --online); "
                          "a gate nobody has looked at is not a gate")
        return Assessment(tier, reasons, shortfalls, evidence)

    # Once the platform has been probed, a paired deployment whose gate is not
    # real must be named for what it does — publish verdicts — rather than for
    # its repository topology, or "paired" gets read as "gated".
    def ungated() -> Assessment:
        return Assessment(NOTIFICATION if tier == PAIRED else tier,
                          reasons, shortfalls, evidence)

    prot = probe_branch_protection(repo, branch)
    evidence["protection"] = prot
    if not prot.get("reachable"):
        shortfalls.append(f"could not read the branch rules: {prot.get('why')}")
        return ungated()
    if not prot.get("protected"):
        shortfalls.append(f"the branch is not protected: {prot.get('why')}")
        return ungated()

    reasons.append(f"{branch} is protected")
    ok = True
    if prot.get("admission_required"):
        reasons.append(f"{CHECK_NAME} is a required check")
    else:
        ok = False
        shortfalls.append(f"{CHECK_NAME} is not among the required checks "
                          f"{prot.get('required_checks')}: the audit cannot refuse "
                          f"anything")
    if prot.get("app_bound"):
        reasons.append("the required check is bound to a verified App identity")
    else:
        ok = False
        shortfalls.append("the required check is not bound to an App: any writer "
                          "can post a green status under the same name")
    if prot.get("enforce_admins"):
        reasons.append("administrators are not exempt")
    else:
        ok = False
        shortfalls.append("administrators can bypass the gate, which makes it "
                          "optional for the people most able to route around it")
    if prot.get("allows_force_push"):
        ok = False
        shortfalls.append("force pushes are allowed: the audited history can be "
                          "rewritten after the fact")

    if ok and controller_persistent and controller_atomic and paired:
        return Assessment(ENFORCED, reasons, shortfalls, evidence)
    return ungated()
