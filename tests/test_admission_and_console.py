"""2.0: what a deployment may claim, and the window that shows it.

The admission tests exist because "enforced" is the word a supervision system is
most tempted to use prematurely. The console tests exist because opening a port
inside a tool that holds API keys is a real attack surface, and the defences
have to be tested as refusals, not described in a docstring.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from crossaudit import admission as adm
from crossaudit.controller import StateStore

FULL_PROTECTION = {
    "reachable": True, "protected": True,
    "required_checks": [adm.CHECK_NAME], "admission_required": True,
    "app_bound": True, "enforce_admins": True, "allows_force_push": False,
}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    subprocess.run(["git", "remote", "add", "origin",
                    "https://github.com/owner/proj.git"], cwd=r, check=True)
    return r


def assess(repo: Path, monkeypatch, protection=None, **kw):
    if protection is not None:
        monkeypatch.setattr(adm, "probe_branch_protection", lambda *a, **k: protection)
    opts = {"paired": True, "controller_persistent": True, "controller_atomic": True,
            "online": True, **kw}
    return adm.assess(root=repo, **opts)


# ------------------------------------------------------------------- tiers
def test_a_repository_with_no_remote_is_local_and_says_why(tmp_path: Path):
    r = tmp_path / "solo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    a = adm.assess(root=r, paired=False, controller_persistent=True,
                   controller_atomic=True)
    assert a.tier == adm.LOCAL
    assert any("rewritten" in s for s in a.shortfalls)


def test_everything_in_place_is_enforced(repo, monkeypatch):
    a = assess(repo, monkeypatch, FULL_PROTECTION)
    assert a.enforced and a.tier == adm.ENFORCED


@pytest.mark.parametrize("missing,expect", [
    ({"admission_required": False}, "not among the required checks"),
    ({"app_bound": False}, "any writer can post a green status"),
    ({"enforce_admins": False}, "administrators can bypass"),
    ({"allows_force_push": True}, "rewritten after the fact"),
])
def test_each_missing_platform_guarantee_denies_enforced(repo, monkeypatch,
                                                         missing, expect):
    a = assess(repo, monkeypatch, {**FULL_PROTECTION, **missing})
    assert not a.enforced
    assert any(expect in s for s in a.shortfalls), a.shortfalls


def test_an_ephemeral_controller_cannot_reach_enforced(repo, monkeypatch):
    a = assess(repo, monkeypatch, FULL_PROTECTION, controller_persistent=False)
    assert not a.enforced
    assert any("throwaway checkout" in s for s in a.shortfalls)


def test_a_non_atomic_controller_cannot_reach_enforced(repo, monkeypatch):
    a = assess(repo, monkeypatch, FULL_PROTECTION, controller_atomic=False)
    assert not a.enforced
    assert any("both admit the same receipt" in s for s in a.shortfalls)


def test_a_single_repository_cannot_reach_enforced(repo, monkeypatch):
    a = assess(repo, monkeypatch, FULL_PROTECTION, paired=False)
    assert not a.enforced
    assert any("no privilege separation" in s for s in a.shortfalls)


def test_not_probing_the_platform_never_counts_in_favour(repo):
    """A gate nobody looked at is not a gate."""
    a = adm.assess(root=repo, paired=True, controller_persistent=True,
                   controller_atomic=True, online=False)
    assert not a.enforced
    assert any("not probed" in s for s in a.shortfalls)


def test_paired_but_ungated_is_called_notification_not_enforced(repo, monkeypatch):
    a = assess(repo, monkeypatch, {"reachable": True, "protected": False,
                                   "why": "no rule"})
    assert a.tier == adm.NOTIFICATION
    assert "nothing is refused" in adm.TIER_MEANING[a.tier]


def test_every_tier_states_what_it_means():
    for tier in (adm.LOCAL, adm.REMOTE, adm.PAIRED, adm.NOTIFICATION, adm.ENFORCED):
        assert adm.TIER_MEANING[tier]


# ------------------------------------------------- controller self-attestation
def test_the_controller_proves_its_own_atomicity(tmp_path: Path):
    caps = StateStore(tmp_path / "state.json").capabilities()
    assert caps["atomic"], caps["why_not"]


def test_a_store_in_a_throwaway_location_reports_itself_impersistent():
    caps = StateStore("/tmp/crossaudit-ephemeral-test/state.json").capabilities()
    assert not caps["persistent"]
    assert "outlive" in caps["why_not"]


# ----------------------------------------------------------------- console
@pytest.fixture()
def console(tmp_path: Path):
    from crossaudit.config import load
    from crossaudit.console import serve

    root = tmp_path / "proj"
    (root).mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / "AUDIT_RULES.md").write_text("### CA-X-001\n**BLOCKER.** be exact\n\nx\n")
    (root / "crossaudit.yml").write_text(
        "version: 1\nscience_repo: t/p\nconstitution: AUDIT_RULES.md\n"
        "auditor: {vendor: openai, provider: openai_compat, model: m,"
        " key_env: CROSSAUDIT_AUDITOR_KEY}\ngenerator: {vendor: anthropic}\n"
        "ledger: {dir: cycles}\nstate: {dir: .crossaudit}\n"
        "checks: [parseable]\n")
    cfg = load(root / "crossaudit.yml")
    url, httpd = serve(cfg, port=0)
    import threading

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield url
    httpd.shutdown()


def fetch(url: str, **headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read().decode(), dict(r.headers)


def test_the_console_serves_its_page_with_the_token(console):
    status, body, headers = fetch(console)
    assert status == 200 and "CrossAudit" in body
    assert "default-src 'none'" in headers["content-security-policy"]


def test_without_the_token_everything_is_refused(console):
    bare = console.split("?")[0]
    with pytest.raises(urllib.error.HTTPError) as e:
        fetch(bare)
    assert e.value.code == 403


def test_a_wrong_token_is_refused(console):
    with pytest.raises(urllib.error.HTTPError) as e:
        fetch(console.split("?")[0] + "?t=guess")
    assert e.value.code == 403


def test_a_foreign_host_header_is_refused_even_with_the_token(console):
    """The DNS-rebinding defence: the attacker's name resolves to 127.0.0.1, but
    the request still carries their Host."""
    with pytest.raises(urllib.error.HTTPError) as e:
        fetch(console, Host="evil.example.com")
    assert e.value.code == 403


def test_the_only_write_path_is_the_one_input(console):
    """The console gained exactly one write path — the sentence box — and it is
    narrow on purpose: everything it can cause, the CLI could already do."""
    req = urllib.request.Request(console, data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 404                      # POST anywhere else: no route


def test_the_input_needs_the_token_like_everything_else(console):
    bare = console.split("?")[0] + "api/say"
    req = urllib.request.Request(bare, data=b'{"text":"hello"}', method="POST",
                                 headers={"content-type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403


def test_the_input_refuses_an_empty_or_oversized_sentence(console):
    url = console.replace("/?t=", "/api/say?t=")
    for payload, code in ((b'{"text":"   "}', 400),
                          (b'{"text":"' + b"x" * 5000 + b'"}', 413)):
        req = urllib.request.Request(url, data=payload, method="POST",
                                     headers={"content-type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == code


def test_the_two_windows_are_reconstructed_from_the_ledger(console):
    _s, body, _h = fetch(console.replace("/?", "/api/state?"))
    data = json.loads(body)
    # Two streams, not a stored chat: what exists is commits, reports and receipts.
    assert "generator_stream" in data and "auditor_stream" in data
    assert isinstance(data["generator_stream"], list)
    assert data["generator"] and data["auditor"]


def test_the_state_endpoint_reports_key_presence_never_the_key(console, monkeypatch):
    monkeypatch.setenv("CROSSAUDIT_AUDITOR_KEY", "sk-secret-value-123")
    _s, body, _h = fetch(console.replace("/?", "/api/state?"))
    assert "sk-secret-value-123" not in body
    data = json.loads(body)
    assert data["key_present"] in (True, False)
    assert "tier" in data and "shortfalls" in data["tier"]


def test_the_console_binds_to_loopback_only(console):
    assert console.startswith("http://127.0.0.1:")
