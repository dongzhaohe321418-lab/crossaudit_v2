"""OpenAI-compatible chat completions.

One adapter reaches OpenAI and every service that speaks the same route. The
compatibility promised is narrow and versioned: a non-streaming JSON
request/reply with a system and a user message. It is not a promise about any
provider's extensions, and `base_url` is opt-in precisely because "compatible"
says nothing about who is on the other end.
"""
from __future__ import annotations

from ..errors import ProviderDenial
from .base import Reply, egress_check, read_key, request_json, sha256_text

BUILTIN_ORIGIN = "https://api.openai.com"


def _completion_token_parameter(model: str) -> str:
    """Return the token-limit field accepted by this OpenAI model family.

    GPT-5 and o-series chat-completions models reject the legacy
    ``max_tokens`` field.  Older OpenAI-compatible services generally still
    expect it, so keep the compatibility decision deliberately narrow.
    """
    lowered = model.lower()
    modern_families = ("gpt-5", "o1", "o3", "o4")
    return ("max_completion_tokens" if lowered.startswith(modern_families)
            else "max_tokens")


def _uses_modern_completion_controls(model: str) -> bool:
    return _completion_token_parameter(model) == "max_completion_tokens"


def complete(*, model: str, system: str, prompt: str, key_env: str,
             base_url: str | None = None, allow_custom: bool = False,
             max_tokens: int = 4096, timeout: float = 120.0) -> Reply:
    origin = (base_url or BUILTIN_ORIGIN).rstrip("/")
    url = f"{origin}/v1/chat/completions"
    egress_check(url, builtin_origin=BUILTIN_ORIGIN, allow_custom=allow_custom,
                 allow_insecure_localhost=True)
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
    }
    # GPT-5 and o-series models only accept their default temperature. Omitting
    # the field preserves that default; legacy chat models retain deterministic
    # temperature=0 behaviour.
    if not _uses_modern_completion_controls(model):
        payload["temperature"] = 0
    payload[_completion_token_parameter(model)] = max_tokens
    headers = {"authorization": f"Bearer {read_key(key_env)}"}
    data, rid = request_json(url, payload, headers, timeout=timeout)
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderDenial(f"unexpected chat-completions response shape: {exc}") from exc
    if not text.strip():
        raise ProviderDenial("provider returned an empty completion")
    return Reply(text=text, request_id=rid or data.get("id"),
                 request_sha256=sha256_text(system + "\n" + prompt),
                 response_sha256=sha256_text(text), raw={"usage": data.get("usage", {})})
