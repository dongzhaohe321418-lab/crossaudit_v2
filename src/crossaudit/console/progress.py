"""Live progress for a running build, without inventing a second source of truth.

A build takes minutes: the generator writes, the auditor reads, and a blocked
round goes round again. Blocking the browser for that is the wrong shape — but
so is streaming a narrative the ledger does not have. The rule this module keeps
is the same one the console keeps: **progress is a view of work in flight, and
the record is still the ledger.**

So an entry here is ephemeral by construction. It lives in memory, it is dropped
when the run ends, and nothing downstream reads it. If the process dies
mid-build the progress vanishes and the ledger still holds every committed
round — which is the correct asymmetry. A progress log that outlived the run
would be a second history, unversioned and unaudited, and the first thing anyone
would do is trust it.

One build at a time, per project. Two concurrent builds would race on the
working tree and on the round budget, and the honest answer to "start another"
is that one is already running.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Step:
    t: float
    actor: str          # generator | auditor | loop | done
    text: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"t": self.t, "actor": self.actor, "text": self.text,
                "detail": self.detail}


@dataclass
class Run:
    task: str
    started: float = field(default_factory=time.time)
    steps: list[Step] = field(default_factory=list)
    finished: bool = False
    outcome: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {"task": self.task, "started": self.started,
                "steps": [s.as_dict() for s in self.steps],
                "finished": self.finished, "outcome": self.outcome,
                "error": self.error,
                "elapsed": round((time.time() if not self.finished
                                  else self.steps[-1].t if self.steps
                                  else time.time()) - self.started)}


class Tracker:
    """The one in-flight build, and its steps. Thread-safe; deliberately tiny."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run: Run | None = None
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> None:
        """Wake a view when progress changes; the ledger remains the record."""
        with self._lock:
            self._listeners.append(listener)

    def _changed(self) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._run is not None and not self._run.finished

    def start(self, task: str) -> Run:
        with self._lock:
            if self._run is not None and not self._run.finished:
                raise RuntimeError("a build is already running in this project")
            self._run = Run(task=task)
            run = self._run
        self._changed()
        return run

    def step(self, actor: str, text: str, detail: str = "") -> None:
        with self._lock:
            if self._run is not None:
                self._run.steps.append(Step(time.time(), actor, text, detail))
        self._changed()

    def finish(self, outcome: str, error: str = "") -> None:
        with self._lock:
            if self._run is not None:
                self._run.finished = True
                self._run.outcome = outcome
                self._run.error = error
                self._run.steps.append(Step(time.time(), "done", outcome, error))
        self._changed()

    def snapshot(self) -> dict | None:
        with self._lock:
            return self._run.as_dict() if self._run is not None else None

    def clear(self) -> None:
        with self._lock:
            self._run = None
        self._changed()


#: One tracker per process. The console is a single-project window, and a build
#: is a single-project act.
TRACKER = Tracker()
