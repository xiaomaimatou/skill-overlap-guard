"""GitHub Code Search helper for the audit pipeline.

Used as the third gate of `audit_unclaimed.py`: when the built-in whitelist
fails to identify a skill, search GitHub for a matching SKILL.md.

Public surface:
    gh_available() -> bool
    extract_query_phrase(description: str) -> str | None
    search_skill_md(phrase: str, max_results: int = 50) -> tuple[list[Candidate], str | None]

A `Candidate` is a dict: {"owner", "repo", "branch", "subpath"}.

Network failures (rate limit, no network, gh not installed, gh not logged in)
all return ("", error_msg) — never raise. Callers are expected to short-circuit
on repeated errors (audit does this via a circuit breaker).
"""
from __future__ import annotations

import json
import re
import subprocess


def gh_available() -> bool:
    """True iff `gh` CLI is on PATH and we have an authenticated context.

    Authentication isn't strictly required for code search (unauthenticated
    searches just have a tighter rate limit), but unauthenticated calls also
    return zero results for many queries, so we treat "not logged in" as
    unavailable and let the caller skip gracefully.
    """
    try:
        out = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def extract_query_phrase(description: str, min_words: int = 8, max_words: int = 12) -> str | None:
    """Pick a contiguous span of original words from a description."""
    if not description:
        return None
    cleaned = re.sub(r"\s+", " ", description).strip()
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'\-]*", cleaned)
    if len(tokens) < min_words:
        return None

    return " ".join(tokens[:max_words])


def _gh_search_code(query: str, max_results: int, timeout: int = 20) -> tuple[list | None, str | None]:
    """Run `gh search code` and return parsed JSON or an error string."""
    try:
        out = subprocess.run(
            [
                "gh", "search", "code", query,
                "--filename", "SKILL.md",
                "--json", "repository,path,url",
                "--limit", str(max_results),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None, "gh CLI not found"
    except subprocess.TimeoutExpired:
        return None, "gh search code timed out"
    if out.returncode != 0:
        msg = (out.stderr.strip() or out.stdout.strip() or "unknown gh error")[:500]
        return None, f"gh search code error: {msg}"
    try:
        return json.loads(out.stdout), None
    except json.JSONDecodeError as e:
        return None, f"gh search code returned non-json: {e}"


def _repo_full_name(repo: dict) -> str:
    return (
        repo.get("nameWithOwner")
        or repo.get("fullName")
        or repo.get("full_name")
        or ""
    )


def _repo_default_branch(repo: dict) -> str:
    ref = repo.get("defaultBranchRef")
    if isinstance(ref, dict) and ref.get("name"):
        return ref["name"]
    return repo.get("default_branch") or repo.get("defaultBranch") or "main"


def search_skill_md(phrase: str, max_results: int = 50) -> tuple[list[dict], str | None]:
    """Search GitHub for SKILL.md files containing the phrase.

    Returns (candidates, error). On success, `candidates` is a list of dicts:
        {"owner": str, "repo": str, "branch": str, "subpath": str, "path": str}
    `branch` falls back to "main" when the API doesn't expose default_branch
    inline (the caller can repair via ls-remote later).
    """
    data, err = _gh_search_code(phrase, max_results=max_results)
    if err:
        return [], err
    items = data or []
    out: list[dict] = []
    for item in items[:max_results]:
        repo = (item.get("repository") or {})
        full_name = _repo_full_name(repo)
        if "/" not in full_name:
            continue
        owner, repo_name = full_name.split("/", 1)
        branch = _repo_default_branch(repo)
        path = item.get("path") or ""
        if not path.endswith("SKILL.md") and not path.endswith("skill.md"):
            continue
        subpath = path.rsplit("/", 1)[0] if "/" in path else ""
        out.append({
            "owner": owner,
            "repo": repo_name,
            "branch": branch,
            "subpath": subpath,
            "path": path,
        })
    return out, None
