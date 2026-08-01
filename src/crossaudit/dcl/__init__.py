"""The deterministic check layer: no learned component, and it goes first (I4).

A hard failure here is final — no model may waive it. The runner returns a
structured result whose `hard_failures` count is what the verdict synthesiser
treats as dominating.
"""
from __future__ import annotations

from .framework import CheckResult, Finding, run_checks

__all__ = ["run_checks", "CheckResult", "Finding"]
