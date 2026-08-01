"""Model access: three stdlib adapters, no vendor SDKs (constraint 1).

Egress rules, applied before any request leaves (installer-design 05a):
  * only HTTPS, and only to the adapter's built-in origin unless the operator
    passes --allow-custom-endpoint;
  * redirects are refused outright — a redirect can move an API key to another
    host;
  * connect/read timeouts and a response size cap are always set;
  * plaintext HTTP only for an explicitly allowed loopback address.
"""
from __future__ import annotations

from .base import Reply, egress_check, request_json
from .registry import get_provider, list_providers

__all__ = ["get_provider", "list_providers", "Reply", "egress_check", "request_json"]
