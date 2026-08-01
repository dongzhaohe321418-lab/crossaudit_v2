"""The dashboard's figures, and the push that keeps them current.

A supervision dashboard is the last place a number should be invented, so these
tests are mostly about what it refuses to claim: no step is green before it
happened, no metric is confident about something the ledger never recorded, and
a stream frame only goes out when something actually changed.
"""
from __future__ import annotations

import json
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

from crossaudit.config import load
from crossaudit.console import overview

CONFIG = (
    "version: 1\nscience_repo: t/p\nconstitution: AUDIT_RULES.md\n"
    "auditor: {vendor: openai, provider: openai_compat, model: m,"
    " key_env: CROSSAUDIT_AUDITOR_KEY}\ngenerator: {vendor: anthropic}\n"
    "scope: {dirs: [work]}\nledger: {dir: cycles}\nstate: {dir: .crossaudit}\n"
    "checks: [parseable]\n")

REPORT = """# Audit Report — t/p@{sha}

| | |
|---|---|
| verdict | **{verdict}** |
| round | {round} |
| constitution | `abc123def456` |
| auditor | `openai_compat:gpt` |

## Model findings

{findings}
"""

BLOCKER = ("### [BLOCKER] CA-TXT-001 — work/a.md\n"
           "The summary states 0.052 while the data records 0.044.\n")
ADVISORY = ("### [ADVISORY] CA-REP-001 — work/meta.yml\n"
            "No extraction procedure recorded.\n")


@pytest.fixture()
def cfg(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / "AUDIT_RULES.md").write_text("### CA-TXT-001\n**BLOCKER.** exact\n\nx\n")
    (root / "crossaudit.yml").write_text(CONFIG)
    return load(root / "crossaudit.yml")


def add_audit(cfg, sha: str, verdict: str, findings: str = "", round_: int = 1):
    d = cfg.root / cfg.ledger_dir / f"{sha}-r{round_}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.md").write_text(REPORT.format(sha=sha, verdict=verdict,
                                               round=round_, findings=findings))
    return d


# ------------------------------------------------------------------- reading
def test_an_empty_ledger_yields_no_audits(cfg):
    assert overview.read_cycles(cfg) == []


def test_reports_are_read_back_with_their_verdicts_and_findings(cfg):
    add_audit(cfg, "aaaaaaaaaaaa", "BLOCKED", BLOCKER + "\n" + ADVISORY)
    add_audit(cfg, "bbbbbbbbbbbb", "PASS")
    audits = overview.read_cycles(cfg)
    assert [a.verdict for a in audits] == ["BLOCKED", "PASS"]
    assert audits[0].blockers == 1 and len(audits[0].findings) == 2
    assert audits[0].auditor == "openai_compat:gpt"


# ------------------------------------------------------------------ metrics
def test_metrics_on_an_empty_project_claim_nothing(cfg):
    rows = {m["label"]: m for m in overview.metrics(cfg, [])}
    assert rows["Audits"]["value"] == 0
    # No share can be computed from nothing, and none is shown.
    assert rows["Passed"].get("badge") == ""


def test_metrics_count_what_the_ledger_holds(cfg):
    add_audit(cfg, "a" * 12, "PASS")
    add_audit(cfg, "b" * 12, "BLOCKED", BLOCKER)
    add_audit(cfg, "c" * 12, "PASS")
    rows = {m["label"]: m for m in overview.metrics(cfg, overview.read_cycles(cfg))}
    assert rows["Audits"]["value"] == 3
    assert rows["Passed"]["value"] == 2 and rows["Passed"]["badge"] == "67%"
    assert rows["Blocked"]["value"] == 1


def test_every_metric_says_what_it_means(cfg):
    for m in overview.metrics(cfg, []):
        assert m["note"], f"{m['label']} has no explanation"


# ----------------------------------------------------------------- pipeline
def test_an_unaudited_project_shows_every_step_pending(cfg):
    steps = overview.pipeline(cfg, [])
    assert [s["state"] for s in steps] == ["pending"] * 5
    assert [s["title"] for s in steps] == ["Commit", "Checks", "Audit", "Verdict",
                                           "Admission"]


def test_a_blocked_increment_never_shows_a_green_verdict(cfg):
    add_audit(cfg, "a" * 12, "BLOCKED", BLOCKER)
    steps = {s["title"]: s for s in overview.pipeline(cfg, overview.read_cycles(cfg))}
    assert steps["Verdict"]["state"] == "failed"
    # Admission was never reached, which is not the same as having failed it.
    assert steps["Admission"]["state"] == "pending"
    assert "not reached" in steps["Admission"]["detail"]


def test_a_pass_waits_at_admission_rather_than_claiming_it(cfg):
    add_audit(cfg, "a" * 12, "PASS")
    steps = {s["title"]: s for s in overview.pipeline(cfg, overview.read_cycles(cfg))}
    assert steps["Verdict"]["state"] == "done"
    assert steps["Admission"]["state"] == "current"
    assert "verify the receipt" in steps["Admission"]["detail"]


def test_a_dcl_only_verdict_shows_the_audit_step_as_unfinished(cfg):
    add_audit(cfg, "a" * 12, "DCL_ONLY")
    steps = {s["title"]: s for s in overview.pipeline(cfg, overview.read_cycles(cfg))}
    assert steps["Audit"]["state"] == "current"
    assert "cannot be PASS" in steps["Audit"]["detail"]


# ----------------------------------------------------------------- findings
def test_findings_are_grouped_with_blockers_first(cfg):
    add_audit(cfg, "a" * 12, "BLOCKED", BLOCKER + "\n" + ADVISORY)
    add_audit(cfg, "b" * 12, "BLOCKED", BLOCKER)
    fb = overview.findings_by_severity(overview.read_cycles(cfg))
    assert fb["total"] == 3
    assert fb["rows"][0]["severity"] == "BLOCKER" and fb["rows"][0]["count"] == 2
    assert abs(sum(r["share"] for r in fb["rows"]) - 1.0) < 1e-9


def test_the_rules_that_catch_things_are_ranked(cfg):
    add_audit(cfg, "a" * 12, "BLOCKED", BLOCKER + "\n" + ADVISORY)
    add_audit(cfg, "b" * 12, "BLOCKED", BLOCKER)
    top = overview.top_rules(overview.read_cycles(cfg))
    assert top[0] == {"rule": "CA-TXT-001", "count": 2}


def test_nothing_recorded_means_no_bars(cfg):
    assert overview.findings_by_severity([])["total"] == 0
    assert overview.top_rules([]) == []


# -------------------------------------------------------------- escalations
def test_an_escalation_carries_the_reason_it_stopped(cfg):
    from crossaudit.controller import StateStore

    sha = "a" * 40
    add_audit(cfg, sha[:12], "DCL_ONLY")
    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    c = store.open_or_advance(cfg.science_repo, sha, None)
    store.record_verdict(c["cycle_id"], sha, "DCL_ONLY", "r", 3)
    rows = overview.escalations(cfg)
    assert len(rows) == 1 and "no model audit ran" in rows[0]["why"]


def test_a_quiet_project_has_nothing_waiting(cfg):
    assert overview.escalations(cfg) == []


# ------------------------------------------------------------------- stream
@pytest.fixture()
def console(cfg):
    from crossaudit.console import daemon, serve

    url, httpd = serve(cfg, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield cfg, url
    httpd.shutdown()
    daemon.clear_run(cfg)


def test_the_stream_pushes_a_first_frame_immediately(console):
    cfg, url = console
    stream = url.replace("/?", "/api/stream?")
    with urllib.request.urlopen(stream, timeout=5) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        line = r.readline().decode()
        assert line.startswith("data: ")
        payload = json.loads(line[len("data: "):])
        assert "metrics" in payload and "pipeline" in payload


def test_the_stream_sends_again_when_the_ledger_changes(console):
    cfg, url = console
    stream = url.replace("/?", "/api/stream?")
    with urllib.request.urlopen(stream, timeout=8) as r:
        first = json.loads(r.readline().decode()[6:])
        r.readline()                                   # the blank separator
        add_audit(cfg, "f" * 12, "PASS")               # something happens
        line = r.readline().decode()
        while not line.startswith("data: "):
            line = r.readline().decode()
        second = json.loads(line[6:])
    assert first["metrics"][0]["value"] == 0
    assert second["metrics"][0]["value"] == 1


def test_the_stream_needs_the_token_like_every_other_route(console):
    import urllib.error

    cfg, url = console
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(url.split("?")[0] + "api/stream", timeout=5)
    assert e.value.code == 403
