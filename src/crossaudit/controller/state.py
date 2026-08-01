"""Controller state machine with an explicit, atomically-mutated store.

Two properties this module exists to guarantee, both of which the pre-package
implementation only approximated:

**The store's location is injected, never inferred.** The old module resolved
its state as `Path(__file__).parent / "state.json"`, which under a wheel would
put a deployment's mutable ledger inside site-packages, and under a CI job
would put it inside a throwaway checkout — where "consumed" survives nothing.
`StateStore` takes a path and keeps it.

**Every mutation is a read-modify-write inside an exclusive lock.** Admission
is a single-use claim; two concurrent verifiers must not both see an unconsumed
receipt. The lock is an `O_EXCL` file with the holder's pid and a stale-break
timeout, and the state file is replaced by atomic rename after fsync, so a
crash mid-write leaves the previous state intact rather than a truncated file.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..errors import ConfigDenial, IntegrityDenial

STATE_FILENAME = "state.json"
LOCK_TIMEOUT_S = 30.0
LOCK_STALE_S = 120.0

OPEN, BLOCKED, PASSED, ESCALATED, CONSUMED = "OPEN", "BLOCKED", "PASSED", "ESCALATED", "CONSUMED"
TERMINAL = frozenset({CONSUMED})


def cycle_id_for(repo: str, root_sha: str) -> str:
    return hashlib.sha256(f"{repo}\n{root_sha}".encode()).hexdigest()[:16]


class StateStore:
    """Cycle state on disk. One instance per state file; safe across processes."""

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    # ---------------------------------------------------------------- storage
    def _read(self) -> dict:
        if not self.path.exists():
            return {"schema": 1, "cycles": {}, "history": []}
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise IntegrityDenial(f"state file is corrupt: {exc}", path=str(self.path)) from exc
        if not isinstance(data, dict) or "cycles" not in data:
            raise IntegrityDenial("state file has no cycles map", path=str(self.path))
        return data

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + f".tmp{os.getpid()}")
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)          # atomic within a filesystem
        dir_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)                 # the rename itself must survive a crash
        finally:
            os.close(dir_fd)

    @contextmanager
    def _locked(self) -> Iterator[dict]:
        """Exclusive read-modify-write. Yields state; writes it back on clean exit."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time():.0f}".encode())
                os.close(fd)
                break
            except FileExistsError:
                age = time.time() - self.lock_path.stat().st_mtime if self.lock_path.exists() else 0
                if age > LOCK_STALE_S:
                    self.lock_path.unlink(missing_ok=True)   # holder died; break it
                    continue
                if time.monotonic() > deadline:
                    raise ConfigDenial(
                        "could not acquire the controller lock; another verifier is "
                        "mid-transaction", lock=str(self.lock_path))
                time.sleep(0.05)
        try:
            state = self._read()
            yield state
            self._write(state)
        finally:
            self.lock_path.unlink(missing_ok=True)

    @staticmethod
    def _log(state: dict, event: str, **kw: object) -> None:
        state.setdefault("history", []).append({"t": int(time.time()), "event": event, **kw})

    # ------------------------------------------------------------------ reads
    def snapshot(self) -> dict:
        return self._read()

    def cycle(self, cycle_id: str) -> dict | None:
        c = self._read()["cycles"].get(cycle_id)
        return dict(c, cycle_id=cycle_id) if c else None

    # -------------------------------------------------------------- mutations
    def open_or_advance(self, repo: str, sha: str, parent_sha: str | None) -> dict:
        """New root commit opens a cycle; a child of an active sha advances it.

        Identity follows the commit graph, never changed-path sets, so a nonce
        file cannot reset a round.
        """
        with self._locked() as state:
            cycles = state["cycles"]
            for cid, c in cycles.items():
                if c["active_sha"] == sha and c["status"] == OPEN and c.get("awaiting_verdict"):
                    # This round was opened and never reached a verdict: the audit
                    # crashed, the provider timed out, the machine died. Re-entering
                    # resumes it. Incrementing here would let transient failures
                    # spend the revision budget and escalate a healthy increment.
                    self._log(state, "resume_open_round", cycle=cid, sha=sha,
                              round=c["round"])
                    return dict(c, cycle_id=cid)
                if c["active_sha"] == sha and c["status"] in (OPEN, BLOCKED):
                    c["round"] += 1
                    c["status"] = OPEN
                    c["awaiting_verdict"] = True
                    self._log(state, "readvance_same_sha", cycle=cid, sha=sha, round=c["round"])
                    return dict(c, cycle_id=cid)
                if c["active_sha"] == sha and c["status"] == ESCALATED:
                    self._log(state, "blocked_by_escalation", cycle=cid, sha=sha)
                    return dict(c, cycle_id=cid, blocked_by_escalation=True)
                if c["active_sha"] == sha and c["status"] == CONSUMED:
                    self._log(state, "already_admitted", cycle=cid, sha=sha)
                    return dict(c, cycle_id=cid, already_admitted=True)
            for cid, c in cycles.items():
                if parent_sha and c["active_sha"] == parent_sha:
                    if c["status"] == ESCALATED:
                        self._log(state, "blocked_by_escalation", cycle=cid, sha=sha,
                                  parent=parent_sha)
                        return dict(c, cycle_id=cid, blocked_by_escalation=True)
                    if c["status"] in (BLOCKED, OPEN):
                        c["round"] += 1
                        c["active_sha"] = sha
                        c["status"] = OPEN
                        c["awaiting_verdict"] = True
                        self._log(state, "advance", cycle=cid, sha=sha, round=c["round"])
                        return dict(c, cycle_id=cid)
            cid = cycle_id_for(repo, sha)
            c = {"repo": repo, "root_sha": sha, "active_sha": sha, "parent_receipt": "",
                 "round": 1, "status": OPEN, "consumed": [], "awaiting_verdict": True}
            cycles[cid] = c
            self._log(state, "open", cycle=cid, sha=sha)
            return dict(c, cycle_id=cid)

    def record_verdict(self, cycle_id: str, sha: str, verdict: str,
                       receipt_hash: str, max_rounds: int) -> str:
        with self._locked() as state:
            c = state["cycles"].get(cycle_id)
            if c is None:
                raise IntegrityDenial("unknown cycle", cycle_id=cycle_id)
            if c["active_sha"] != sha:
                self._log(state, "stale_verdict_ignored", cycle=cycle_id, sha=sha,
                          verdict=verdict)
                return c["status"]
            if c["status"] == CONSUMED:
                # An admitted cycle is closed; a late verdict cannot reopen it.
                self._log(state, "verdict_after_admission_ignored", cycle=cycle_id, sha=sha)
                return c["status"]
            if verdict == "PASS":
                c["status"] = PASSED
            elif verdict in ("ESCALATE", "DCL_ONLY"):
                c["status"] = ESCALATED
            else:
                c["status"] = ESCALATED if c["round"] >= max_rounds else BLOCKED
            c["parent_receipt"] = receipt_hash
            c["awaiting_verdict"] = False
            self._log(state, "verdict", cycle=cycle_id, sha=sha, verdict=verdict,
                      round=c["round"], status=c["status"], receipt=receipt_hash[:16])
            return c["status"]

    def admit(self, cycle_id: str, sha: str, receipt_hash: str) -> None:
        """Consume a receipt, once. Raises IntegrityDenial rather than returning a string.

        Freshness, status, binding and replay are all checked *inside* the lock,
        so two processes cannot both observe an unconsumed receipt.
        """
        with self._locked() as state:
            c = state["cycles"].get(cycle_id)
            if c is None:
                raise IntegrityDenial("unknown cycle", cycle_id=cycle_id)
            if c["status"] != PASSED:
                raise IntegrityDenial(f"cycle status is {c['status']}, not PASSED",
                                      cycle_id=cycle_id, status=c["status"])
            if c["active_sha"] != sha:
                raise IntegrityDenial(
                    f"stale: receipt sha {sha[:12]} is not the cycle's active "
                    f"{c['active_sha'][:12]}", cycle_id=cycle_id)
            if receipt_hash in c["consumed"]:
                raise IntegrityDenial("receipt already consumed (replay)", cycle_id=cycle_id)
            if c["parent_receipt"] != receipt_hash:
                raise IntegrityDenial("receipt is not the cycle's recorded latest receipt",
                                      cycle_id=cycle_id)
            c["consumed"].append(receipt_hash)
            c["status"] = CONSUMED
            self._log(state, "admit", cycle=cycle_id, sha=sha, receipt=receipt_hash[:16])

    def resolve_escalation(self, cycle_id: str, action: str, reason: str) -> dict:
        """The human principal rules on an escalation (I6's other half).

        Escalation hands an increment to a human; this is the verb the human
        answers with. `reopen` returns the increment to the loop for another
        audit round; `close` ends the cycle without admission. Either way the
        decision and its stated reason enter the ledger, because a ruling that
        leaves no record is exactly what this protocol exists to prevent.
        """
        if action not in ("reopen", "close"):
            raise IntegrityDenial(f"unknown resolution {action!r}; use reopen or close")
        if not reason.strip():
            raise IntegrityDenial("a resolution must state its reason; it becomes ledger")
        with self._locked() as state:
            c = state["cycles"].get(cycle_id)
            if c is None:
                raise IntegrityDenial("unknown cycle", cycle_id=cycle_id)
            if c["status"] != ESCALATED:
                raise IntegrityDenial(f"cycle is {c['status']}, not ESCALATED; only an "
                                      f"escalated cycle needs a human ruling")
            if action == "reopen":
                c["status"] = OPEN
                c["awaiting_verdict"] = True
            else:
                c["status"] = BLOCKED
                c["closed_by_human"] = True
            self._log(state, "human_resolution", cycle=cycle_id, action=action,
                      reason=reason[:400])
            return dict(c, cycle_id=cycle_id)

    # ------------------------------------------------------- self-attestation
    def capabilities(self) -> dict:
        """What this store can actually promise, tested rather than declared.

        The admission tier turns on two properties of the controller, and a
        configuration file claiming them proves nothing. Both are probed here:
        persistence by asking whether the store lives outside any ephemeral
        checkout, and atomicity by exercising the lock this process would rely
        on. A store that cannot demonstrate both never supports enforced
        admission, however it is configured.
        """
        ephemeral_markers = ("/tmp/", "/var/folders/", "/runner/work/",
                             "/home/runner/", "/private/tmp/")
        path = str(self.path)
        persistent = not any(m in path for m in ephemeral_markers)

        atomic = False
        detail = ""
        try:
            with self._locked() as state:
                state.setdefault("cycles", {})
                # If the lock is real, a second acquisition from this process
                # must fail while we hold it.
                try:
                    fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                    detail = "the lock did not exclude a second holder"
                except FileExistsError:
                    atomic = True
        except Exception as exc:                       # noqa: BLE001
            detail = f"the store could not be locked: {exc}"

        return {"path": path, "persistent": persistent, "atomic": atomic,
                "why_not": detail or ("" if persistent else
                                      "the store is in a location that does not "
                                      "outlive the run that wrote it")}

    def mark_deadlettered(self, cycle_id: str, issue_ref: str) -> None:
        with self._locked() as state:
            c = state["cycles"].get(cycle_id)
            if c is not None:
                c["deadlettered"] = issue_ref
                self._log(state, "deadletter", cycle=cycle_id, issue=issue_ref)

    def stuck_cycles(self, max_age_s: int) -> list[dict]:
        state = self._read()
        last: dict[str, int] = {}
        for h in state.get("history", []):
            if "cycle" in h:
                last[h["cycle"]] = h["t"]
        now = int(time.time())
        return [dict(c, cycle_id=cid) for cid, c in state["cycles"].items()
                if c["status"] in (OPEN, BLOCKED) and not c.get("deadlettered")
                and now - last.get(cid, now) > max_age_s]
