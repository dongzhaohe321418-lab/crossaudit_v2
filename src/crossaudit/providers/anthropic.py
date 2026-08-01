"""Anthropic Messages API, over stdlib urllib."""
from __future__ import annotations

from ..errors import ProviderDenial
from .base import Reply, egress_check, read_key, request_json, sha256_text

BUILTIN_ORIGIN = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


def complete(*, model: str, system: str, prompt: str, key_env: str,
             base_url: str | None = None, allow_custom: bool = False,
             max_tokens: int = 4096, timeout: float = 120.0) -> Reply:
    origin = (base_url or BUILTIN_ORIGIN).rstrip("/")
    url = f"{origin}/v1/messages"
    egress_check(url, builtin_origin=BUILTIN_ORIGIN, allow_custom=allow_custom)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
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
