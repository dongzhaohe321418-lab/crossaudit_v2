"""Replay provider: a recorded transcript stands in for a live model.

Two honest uses, and one thing it must never be mistaken for.

Uses: exercising the whole loop deterministically in tests and CI, where no key
may exist; and re-running a past cycle against its recorded exchange.

Not: evidence about a model. A receipt minted through this adapter records
provider `replay`, so nothing downstream can mistake a fixture for an audit.
The transcript is keyed by the prompt digest, so a changed prompt misses rather
than silently reusing an answer to a different question.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..errors import ConfigDenial, ProviderDenial
from .base import Reply, sha256_text

ENV_DIR = "CROSSAUDIT_REPLAY_DIR"


def _dir() -> Path:
    raw = os.environ.get(ENV_DIR)
    if not raw:
        raise ConfigDenial(f"provider 'replay' needs ${ENV_DIR} pointing at a transcript "
                           f"directory", env=ENV_DIR)
    p = Path(raw)
    if not p.is_dir():
        raise ConfigDenial(f"${ENV_DIR} is not a directory: {p}")
    return p


def record(directory: Path, *, system: str, prompt: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    key = sha256_text(system + "\n" + prompt)
    path = directory / f"{key}.json"
    path.write_text(json.dumps({"request_sha256": key, "text": text}, indent=1))
    return path


def complete(*, model: str, system: str, prompt: str, key_env: str,
             base_url: str | None = None, allow_custom: bool = False,
             max_tokens: int = 4096, timeout: float = 120.0) -> Reply:
    key = sha256_text(system + "\n" + prompt)
    path = _dir() / f"{key}.json"
    if not path.is_file():
        raise ProviderDenial(
            f"no recorded reply for this exact prompt ({key[:12]}); the transcript "
            f"cannot answer a question it was not asked", digest=key)
    doc = json.loads(path.read_text())
    text = doc["text"]
    return Reply(text=text, request_id=f"replay:{key[:12]}", request_sha256=key,
                 response_sha256=sha256_text(text), raw={"replay": True})
