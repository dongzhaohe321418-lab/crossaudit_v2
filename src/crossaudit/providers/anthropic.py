"""Anthropic Messages API, over stdlib urllib."""
from __future__ import annotations

import re

from ..errors import ProviderDenial
from .base import Reply, egress_check, read_key, request_json, sha256_text

BUILTIN_ORIGIN = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


def _supports_temperature(model: str) -> bool:
    """Claude 5-series models reject the formerly accepted control."""
    match = re.match(r"^claude-[a-z0-9]+-(\d+)(?:-|$)", model.lower())
    return not match or int(match.group(1)) < 5


def complete(*, model: str, system: str, prompt: str, key_env: str,
             base_url: str | None = None, allow_custom: bool = False,
             max_tokens: int = 4096, timeout: float = 120.0) -> Reply:
    origin = (base_url or BUILTIN_ORIGIN).rstrip("/")
    url = f"{origin}/v1/messages"
    # Loopback HTTP is useful for explicitly authorised local-compatible
    # providers and end-to-end testing. It still fails the custom-origin check
    # unless the caller opted in, so a configured URL can never redirect a key
    # there by accident.
    egress_check(url, builtin_origin=BUILTIN_ORIGIN, allow_custom=allow_custom,
                 allow_insecure_localhost=True)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    if _supports_temperature(model):
        payload["temperature"] = 0
    headers = {"x-api-key": read_key(key_env), "anthropic-version": API_VERSION}
    data, rid = request_json(url, payload, headers, timeout=timeout)
    try:
        text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    except (KeyError, TypeError) as exc:
        raise ProviderDenial(f"unexpected Anthropic response shape: {exc}") from exc
    if not text.strip():
        raise ProviderDenial("Anthropic returned an empty completion")
    return Reply(text=text, request_id=rid or data.get("id"),
                 request_sha256=sha256_text(system + "\n" + prompt),
                 response_sha256=sha256_text(text), raw={"usage": data.get("usage", {})})
