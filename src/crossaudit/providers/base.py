"""Shared HTTP plumbing and the egress policy."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import sys
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


def tls_context() -> ssl.SSLContext:
    """A context that verifies, whatever this interpreter came with.

    `ssl.create_default_context()` already honours SSL_CERT_FILE and SSL_CERT_DIR.
    What it does not do is notice that it ended up with nothing: a python.org
    install whose `Install Certificates.command` was never run loads zero
    certificates and then fails every handshake. If that happened and `certifi`
    is importable we use it — an optional convenience, never a dependency.

    There is deliberately no way to turn verification off. A tool whose output is
    an attestation of who produced a verdict cannot accept an unverified peer:
    the receipt would name a vendor nobody checked.
    """
    bundle = os.environ.get("CROSSAUDIT_CA_BUNDLE", "").strip()
    if bundle:
        return ssl.create_default_context(cafile=bundle)
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        try:
            import certifi
        except ImportError:
            return ctx                      # tls_advice() explains it when it fails
        ctx.load_verify_locations(cafile=certifi.where())
    return ctx


def tls_advice() -> str:
    """What to do about a certificate failure, on this machine specifically."""
    paths = ssl.get_default_verify_paths()
    # Report what is actually in effect, not the path compiled into this build:
    # SSL_CERT_FILE overrides it, and naming a file that exists while the override
    # is the broken one reads as "certificates are fine, look elsewhere".
    override = os.environ.get("CROSSAUDIT_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    where = override or paths.cafile or paths.openssl_cafile or "(none)"
    via = ("CROSSAUDIT_CA_BUNDLE" if os.environ.get("CROSSAUDIT_CA_BUNDLE")
           else "SSL_CERT_FILE" if os.environ.get("SSL_CERT_FILE") else "")
    tail = "" if (where != "(none)" and os.path.exists(where)) else "   ← missing"
    lines = [
        "this Python cannot verify TLS certificates.",
        f"  interpreter  {sys.executable}",
        f"  trust store  {where}" + (f"  (from ${via})" if via else "") + tail,
        "",
        "Fix any one of these:",
    ]
    if sys.platform == "darwin":
        v = f"{sys.version_info.major}.{sys.version_info.minor}"
        lines.append(f'  · python.org install: run "/Applications/Python {v}/'
                     'Install Certificates.command"')
    lines += [
        "  · pip install certifi        (crossaudit picks it up automatically)",
        "  · export SSL_CERT_FILE=/path/to/ca-bundle.pem",
    ]
    lines += [
        "",
        "If your network inspects TLS (a corporate proxy or VPN), point",
        "CROSSAUDIT_CA_BUNDLE at your organisation's root certificate.",
        "Verification is never skipped: a receipt that names a vendor nobody",
        "authenticated would be attesting to nothing.",
    ]
    return "\n".join(lines)


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
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=tls_context()), _NoRedirect)
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
        _reraise_transport(exc)
    except json.JSONDecodeError as exc:
        raise ProviderDenial(f"provider returned non-JSON: {exc}") from exc


def _reraise_transport(exc: BaseException) -> "ProviderDenial":
    """Turn a transport failure into the most specific thing we can say about it.

    A certificate failure is a fixable setup problem on this machine, not an
    unreachable provider. Reported as the latter it sends people looking at their
    network, or at us, for something one command repairs.
    """
    if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
        raise ProviderDenial(f"{tls_advice()}\n\n  underlying: {exc.reason}",
                             tls=True) from exc
    raise ProviderDenial(f"provider unreachable: {exc}") from exc


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
