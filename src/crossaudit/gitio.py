"""Git reads, with the tree as the only source of truth.

Every path here is materialised from a git object, never from the working
directory: a working tree can differ from the commit under audit, and an audit
that reads uncommitted bytes is auditing something no third party can replay.
Symlinks are refused rather than followed, so an increment cannot point the
auditor at /etc or at a file outside the tree.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import ConfigDenial, IntegrityDenial

MAX_BLOB_BYTES = 512 * 1024


def git(*args: str, cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise ConfigDenial(f"git {' '.join(args)} failed: {proc.stderr.strip()[:200]}",
                           cwd=str(cwd))
    return proc.stdout.strip()


def is_repo(path: Path) -> bool:
    return subprocess.run(["git", "-C", str(path), "rev-parse", "--git-dir"],
                          capture_output=True).returncode == 0


def resolve(repo: Path, rev: str) -> tuple[str, str]:
    """(commit sha, tree sha) for a revision, both full length."""
    sha = git("rev-parse", f"{rev}^{{commit}}", cwd=repo)
    tree = git("rev-parse", f"{rev}^{{tree}}", cwd=repo)
    if len(sha) != 40:
        raise ConfigDenial(f"could not resolve {rev!r} to a full commit sha", repo=str(repo))
    return sha, tree


def parent(repo: Path, sha: str) -> str | None:
    out = git("rev-list", "--parents", "-n", "1", sha, cwd=repo).split()
    return out[1] if len(out) > 1 else None


def changed_paths(repo: Path, sha: str) -> list[str]:
    """The paths this commit touched: the increment, as git already knows it.

    Scope derived from the commit itself rather than asked of the user. A first
    commit has no parent, so everything in the tree counts as introduced.
    """
    if parent(repo, sha):
        raw = git("diff-tree", "--no-commit-id", "--name-only", "-r", sha, cwd=repo,
                  check=False)
    else:
        raw = git("ls-tree", "-r", "--name-only", sha, cwd=repo, check=False)
    return [line for line in raw.splitlines() if line.strip()]


def entries(repo: Path, sha: str, prefix: str = "") -> list[tuple[str, str, str]]:
    """(mode, path, blob-sha) for every file in the commit's tree under prefix."""
    args = ["ls-tree", "-r", "-z", sha]
    if prefix:
        args += ["--", prefix]
    raw = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    if raw.returncode != 0:
        raise ConfigDenial(f"git ls-tree failed: {raw.stderr.strip()[:200]}", repo=str(repo))
    out = []
    for rec in raw.stdout.split("\0"):
        if not rec.strip():
            continue
        meta, path = rec.split("\t", 1)
        mode, otype, blob = meta.split()
        if otype != "blob":
            continue
        out.append((mode, path, blob))
    return out


def read_blob(repo: Path, blob: str, *, limit: int = MAX_BLOB_BYTES) -> tuple[bytes, bool]:
    """Blob bytes and whether they were truncated at `limit`."""
    proc = subprocess.run(["git", "cat-file", "blob", blob], cwd=str(repo),
                          capture_output=True)
    if proc.returncode != 0:
        raise IntegrityDenial(f"cannot read blob {blob[:12]}", repo=str(repo))
    data = proc.stdout
    return (data[:limit], True) if len(data) > limit else (data, False)


def materialise(repo: Path, sha: str, prefix: str = "",
                only: list[str] | None = None) -> tuple[dict[str, bytes], list[str]]:
    """Read an increment straight out of the tree.

    Returns (path -> bytes, notes). Symlinks and submodules are refused; a
    truncated blob is reported, and truncation must never end in PASS (I8).
    """
    files: dict[str, bytes] = {}
    notes: list[str] = []
    wanted = set(only) if only is not None else None
    for mode, path, blob in entries(repo, sha, prefix):
        if wanted is not None and path not in wanted:
            continue

        if mode == "120000":
            raise IntegrityDenial(f"increment contains a symlink: {path}", sha=sha)
        if mode == "160000":
            raise IntegrityDenial(f"increment contains a submodule: {path}", sha=sha)
        data, truncated = read_blob(repo, blob)
        if truncated:
            notes.append(f"truncated: {path}")
        files[path] = data
    return files, notes


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                           ancestor, descendant], capture_output=True).returncode == 0


def commit_exists(repo: Path, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0
