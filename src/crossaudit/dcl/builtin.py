"""Builtin deterministic checks, ported from checks/ and made tree-driven.

Each is mechanical: the same bytes always yield the same findings, and nothing
here consults a model. Rule IDs match the shipped Constitution template.
"""
from __future__ import annotations

import json
from typing import Mapping

import yaml

from .framework import ADVISORY, BLOCKER, Finding, register


def _load_json(files: Mapping[str, bytes], name: str) -> tuple[dict | None, list[Finding]]:
    raw = files.get(name)
    if raw is None:
        return None, []
    try:
        return json.loads(raw.decode("utf-8")), []
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [Finding(BLOCKER, "CA-META-001", name, f"unparsable JSON: {exc}")]


def _results_files(files: Mapping[str, bytes]) -> list[str]:
    return [p for p in files if p.endswith("results.json")]


def check_schema(files: Mapping[str, bytes]) -> list[Finding]:
    """Every increment declares metadata and results, and both must parse."""
    out: list[Finding] = []
    results = _results_files(files)
    if not results:
        out.append(Finding(BLOCKER, "CA-META-001", "increment",
                           "no results.json in the audited scope"))
    metas = [p for p in files if p.endswith("metadata.yml")]
    if not metas:
        out.append(Finding(BLOCKER, "CA-META-001", "increment",
                           "no metadata.yml in the audited scope"))
    for m in metas:
        try:
            doc = yaml.safe_load(files[m].decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            out.append(Finding(BLOCKER, "CA-META-001", m, f"unparsable YAML: {exc}"))
            continue
        if not isinstance(doc, dict):
            out.append(Finding(BLOCKER, "CA-META-001", m, "metadata is not a mapping"))
            continue
        for req in ("code_version", "inputs"):
            if req not in doc:
                out.append(Finding(BLOCKER, "CA-META-001", m,
                                   f"metadata is missing required field {req!r}"))
    for r in results:
        doc, errs = _load_json(files, r)
        out.extend(errs)
        if doc is not None and "quantities" not in doc:
            out.append(Finding(BLOCKER, "CA-META-001", r,
                               "results.json has no 'quantities' list"))
    return out


def check_units(files: Mapping[str, bytes]) -> list[Finding]:
    """CA-DATA-001: every numeric entry carries a unit and a source."""
    out: list[Finding] = []
    for r in _results_files(files):
        doc, _ = _load_json(files, r)
        if not isinstance(doc, dict):
            continue
        for i, q in enumerate(doc.get("quantities") or []):
            if not isinstance(q, dict):
                out.append(Finding(BLOCKER, "CA-DATA-001", r,
                                   f"quantities[{i}] is not a mapping"))
                continue
            for field in ("unit", "source"):
                if not q.get(field):
                    out.append(Finding(
                        BLOCKER, "CA-DATA-001", r,
                        f"quantities[{i}] ({q.get('name', '?')}) has no {field}"))
    return out


def check_convergence(files: Mapping[str, bytes]) -> list[Finding]:
    """CA-METH-002: unconverged numbers are not results."""
    out: list[Finding] = []
    for r in _results_files(files):
        doc, _ = _load_json(files, r)
        if not isinstance(doc, dict):
            continue
        conv = doc.get("convergence")
        if conv is None:
            continue
        if not isinstance(conv, dict):
            out.append(Finding(BLOCKER, "CA-METH-002", r, "convergence is not a mapping"))
            continue
        if conv.get("converged") is not True:
            out.append(Finding(BLOCKER, "CA-METH-002", r,
                               "convergence.converged is not true"))
        achieved, threshold = conv.get("achieved"), conv.get("threshold")
        if isinstance(achieved, (int, float)) and isinstance(threshold, (int, float)):
            if conv.get("converged") is True and achieved > threshold:
                out.append(Finding(
                    BLOCKER, "CA-METH-002", r,
                    f"converged is true but achieved {achieved} exceeds threshold {threshold}"))
    return out


def check_provenance(files: Mapping[str, bytes]) -> list[Finding]:
    """CA-DATA-003: a quantity's source must be among the declared inputs."""
    out: list[Finding] = []
    declared: set[str] = set()
    code_versions: set[str] = set()
    for m in (p for p in files if p.endswith("metadata.yml")):
        try:
            doc = yaml.safe_load(files[m].decode("utf-8")) or {}
        except Exception:                                  # reported by check_schema
            continue
        if isinstance(doc, dict):
            for item in doc.get("inputs") or []:
                declared.add(str(item).split("@")[0])
            if doc.get("code_version"):
                code_versions.add(str(doc["code_version"]))
    if not declared:
        return out
    for r in _results_files(files):
        doc, _ = _load_json(files, r)
        if not isinstance(doc, dict):
            continue
        for i, q in enumerate(doc.get("quantities") or []):
            if not isinstance(q, dict):
                continue
            src = str(q.get("source") or "")
            if not src:
                continue                                   # reported by check_units
            path, _, rev = src.partition("@")
            if path not in declared:
                out.append(Finding(
                    BLOCKER, "CA-DATA-003", r,
                    f"quantities[{i}] source {src!r} is not among the declared inputs"))
            elif rev and code_versions and rev not in code_versions:
                out.append(Finding(
                    ADVISORY, "CA-DATA-003", r,
                    f"quantities[{i}] source revision {rev!r} differs from the declared "
                    f"code_version {sorted(code_versions)}"))
    return out


register("schema", check_schema)
register("units", check_units)
register("convergence", check_convergence)
register("provenance", check_provenance)
