"""Shared HTTP plumbing and the egress policy."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ..errors import ConfigDenial, ProviderDenial

CONNECT_TIMEOUT_S = 30.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


@dataclass
class Reply:
    """A model reply plus the commitments a receipt records instead of raw text."""

    text: str
    request_id: str | None
    request_sha256: str
    response_sha256: str
    raw: dict = field(default_factory=dict, repr=False)

    def commitments(self, retention: str) -> dict:
        out = {"request_sha256": self.request_sha256,
               "response_sha256": self.response_sha256,
               "provider_request_id": self.request_id}
        if retention == "sealed":
            out["raw_retained"] = False   # 0.x keeps commitments only; see roadmap
        return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise ProviderDenial(f"provider attempted a redirect to {newurl!r}; refused "
                             f"(a redirect can move a key to another host)")


def egress_check(url: str, *, builtin_origin: str, allow_custom: bool,
                 allow_insecure_localhost: bool = False) -> str:
    """Return the origin, or deny. Called before every request."""
    parts = urllib.parse.urlparse(url)
    if not parts.scheme or not parts.netloc:
        raise ConfigDenial(f"provider endpoint {url!r} is not an absolute URL")
    origin = f"{parts.scheme}://{parts.netloc}"
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        if not (allow_insecure_localhost and host in LOOPBACK):
            raise ConfigDenial(
                f"refusing plaintext {parts.scheme}:// to {host!r}; only HTTPS is "
                f"allowed (loopback needs --allow-insecure-localhost)")
    if origin != builtin_origin and not allow_custom:
        raise ConfigDenial(
            f"endpoint {origin} is not this provider's built-in origin "
            f"({builtin_origin}); pass --allow-custom-endpoint to send a key there",
            origin=origin)
    return origin


def request_json(url: str, payload: dict, headers: dict, *, timeout: float = CONNECT_TIMEOUT_S
                 ) -> tuple[dict, str | None]:
    """POST JSON, refuse redirects, cap the response. Never logs the payload."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, body, {"content-type": "application/json", **headers})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ProviderDenial("provider response exceeded the size cap")
            rid = resp.headers.get("request-id") or resp.headers.get("x-request-id")
            return json.loads(data.decode("utf-8")), rid
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", "replace")
        raise ProviderDenial(f"provider returned HTTP {exc.code}", status=exc.code,
                             detail=detail[:300]) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        raise ProviderDenial(f"provider unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProviderDenial(f"provider returned non-JSON: {exc}") from exc


def read_key(env_name: str) -> str:
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    # Say which of the two situations this is. "Export it" is unhelpful advice to
    # someone who already gave the wizard a key: their problem is that the file
    # holding it was never loaded here.
    from ..cli.wizard import keys_file, read_keys_file

    path = keys_file()
    if env_name in read_keys_file(path):
        raise ConfigDenial(
            f"${env_name} is not set in this process, though {path} has it. "
            f"Load it with `source {path}`, or restart whatever is running so it "
            f"picks the file up", env=env_name, keys_file=str(path))
    raise ConfigDenial(
        f"no API key in ${env_name}. Run `crossaudit init` to store one, or "
        f"export it yourself — it never goes in crossaudit.yml", env=env_name)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
