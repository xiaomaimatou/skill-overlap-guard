"""Audit unclaimed sibling skills and collect source evidence.

Usage:
    python audit_unclaimed.py            # auto-claim trusted/explicit matches; emit WebSearch hints
    python audit_unclaimed.py --dry-run  # report only, do not modify sources.json

Per-skill flow (ordered gates, stop at first verified match):
    1. Cheap, offline: read <skill>/.git/config. If a github.com remote is found,
       claim the skill as that repo at its current branch + revision (subpath="").
    2. Cheap, offline: scan local SKILL.md for github.com URLs, then verify any
       candidates through the same raw + similarity flow as other remote hints.
    3. WebSearch (agent side): unresolved skills include a distinctive
       `search_query_hint` so the agent can search the web and judge source
       identity from repository/page context.

Confidence rules (from similarity.py):
    - "high" in trusted/explicit gates -> auto-claim; installed_revision is set
      only on exact content match.
    - "low" / no candidates -> no_match (likely user-authored or unknown).

We deliberately do NOT auto claim-local on no_match; the user decides.

Finally (when NOT --dry-run), runs `inventory.scan(check_remote=True)` once
and attaches the result as `inventory_after` so callers see the updated
landscape in a single command — no separate inventory.py invocation needed.

Output (stdout, JSON):
    {
      "summary": { "total_unclaimed": N, "auto_claimed": K, ..., "dry_run": false },
      "reports": [ {per-skill report}, ... ],
      "inventory_after": [ {inventory entry}, ... ] | null
    }

Per-skill unresolved reports (`needs_review`, `no_match`, or
`git_remote_unsupported`) also include a `search_query_hint` field (string or
null). When the script cannot resolve a skill on its own, callers can feed this
phrase into agent-driven WebSearch.

Exit codes:
    0  finished (regardless of how many auto-claims happened)
    3  sources.json corrupted (raised by load_sources)
    4  git CLI missing (raised by run_git when ls-remote needed)
"""
from __future__ import annotations

import argparse
import configparser
import re
import sys
from pathlib import Path

from _common import (
    emit_json,
    fetch_remote_skill_md,
    load_sources,
    parse_frontmatter,
    run_git,
    save_sources,
    skills_manager_root,
    skills_root,
)
from check_remote import fetch_remote_sha
from similarity import classify, first_n_lines, normalize, ratio
import inventory


def detect_git_remote(skill_dir: Path) -> str | None:
    """Return the remote URL recorded in <skill>/.git/config, or None."""
    git_cfg = skill_dir / ".git" / "config"
    if not git_cfg.is_file():
        return None
    cp = configparser.ConfigParser()
    try:
        cp.read(git_cfg, encoding="utf-8")
    except configparser.Error:
        return None
    for section in cp.sections():
        if section.startswith("remote "):
            url = cp[section].get("url")
            if url:
                return url
    return None


def normalize_github_url(url: str) -> str | None:
    """Normalize a remote URL to https://github.com/<owner>/<repo>, or None
    if the URL is not on github.com."""
    s = url.strip().removesuffix(".git").rstrip("/")
    if s.startswith("git@github.com:"):
        rest = s[len("git@github.com:"):]
        return f"https://github.com/{rest}"
    if s.startswith("https://github.com/") or s.startswith("http://github.com/"):
        rest = s.split("github.com/", 1)[1]
        return f"https://github.com/{rest}"
    return None


def audit_via_git_dir(skill_dir: Path) -> dict | None:
    """If <skill>/.git points at a github remote, build a claim record.

    Returns None if .git/ absent or remote not on github.com. Returns a
    report dict (decision = auto_claim or git_remote_unsupported) otherwise.
    """
    raw_remote = detect_git_remote(skill_dir)
    if raw_remote is None:
        return None

    normalized = normalize_github_url(raw_remote)
    if normalized is None:
        return {
            "method": "git_dir",
            "decision": "git_remote_unsupported",
            "candidates": [{"source": "git_dir", "raw_remote": raw_remote}],
            "claim_record": None,
            "error": f"git remote is not on github.com: {raw_remote}",
        }

    head_rev = run_git(["rev-parse", "HEAD"], cwd=skill_dir, timeout=10)
    branch_proc = run_git(["symbolic-ref", "--short", "HEAD"], cwd=skill_dir, timeout=10)
    if head_rev.returncode != 0 or branch_proc.returncode != 0:
        return {
            "method": "git_dir",
            "decision": "git_remote_unsupported",
            "candidates": [{"source": "git_dir", "url": normalized}],
            "claim_record": None,
            "error": "git rev-parse / symbolic-ref failed (detached HEAD?)",
        }

    record = {
        "url": normalized,
        "branch": branch_proc.stdout.strip(),
        "subpath": "",
        "installed_revision": head_rev.stdout.strip(),
    }
    return {
        "method": "git_dir",
        "decision": "auto_claim",
        "candidates": [{"source": "git_dir", **record}],
        "claim_record": record,
        "error": None,
    }


def _read_local_skill_md(skill_dir: Path) -> tuple[str, str] | None:
    """Returns (full_text, head_text) normalized, or None if no SKILL.md."""
    local_md = skill_dir / "SKILL.md"
    if not local_md.is_file():
        local_md = skill_dir / "skill.md"
    if not local_md.is_file():
        return None
    text = normalize(local_md.read_text(encoding="utf-8", errors="replace"))
    return text, first_n_lines(text, 120)


GITHUB_URL_RE = re.compile(
    r"https?://github\.com/([\w.\-]+)/([\w.\-]+)(?:/(?:tree|blob)/([^\s)>\"]+))?"
)


def embedded_github_candidates(text: str) -> list[dict]:
    """Extract GitHub source candidates mentioned inside local SKILL.md text."""
    candidates: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for match in GITHUB_URL_RE.finditer(text):
        owner, repo, path = match.groups()
        repo = repo.removesuffix(".git")
        branch = "main"
        subpath = ""
        if path:
            parts = [p for p in path.strip("/").split("/") if p]
            if parts:
                branch = parts[0]
                sub_parts = parts[1:]
                if sub_parts and sub_parts[-1].lower() == "skill.md":
                    sub_parts = sub_parts[:-1]
                subpath = "/".join(sub_parts)
        candidate = {
            "url": f"https://github.com/{owner}/{repo}",
            "branch": branch,
            "subpath": subpath,
        }
        key = (candidate["url"], candidate["branch"], candidate["subpath"])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _verify_and_build_claim(local_text: str, local_head: str, candidate: dict,
                              source_label: str,
                              resolve_revision: bool = True) -> tuple[dict, dict | None]:
    """Fetch raw + score similarity. Returns (candidate_with_scores, claim_record_or_none).

    `candidate` must include url, branch, subpath. `claim_record_or_none` is set
    when confidence is "high". The recorded `installed_revision` is only set
    to the remote HEAD SHA when similarity is exactly 1.0 (local content
    matches upstream HEAD); otherwise it's left as None so downstream tools
    correctly treat the skill as needing an update rather than "up to date".
    """
    text, err = fetch_remote_skill_md(candidate["url"], candidate["branch"], candidate["subpath"])
    if err:
        return ({"source": source_label, **candidate, "error": err}, None)
    rt = normalize(text)
    full = ratio(local_text, rt)
    head = ratio(local_head, first_n_lines(rt, 120))
    conf = classify(full, head)
    enriched = {
        "source": source_label,
        **candidate,
        "full_ratio": round(full, 4),
        "head_ratio": round(head, 4),
        "confidence": conf,
    }
    if conf != "high":
        return (enriched, None)

    # similarity = 1.0 means local SKILL.md byte-equals upstream HEAD's SKILL.md
    # (modulo frontmatter / whitespace normalization). In any other case the
    # local copy is an ancestor / fork / locally-edited version, and recording
    # remote HEAD would silently lie about installed_revision.
    is_exact_match = full >= 1.0 and head >= 1.0
    if is_exact_match and resolve_revision:
        sha, err = fetch_remote_sha(candidate["url"], candidate["branch"])
        if err:
            enriched["error"] = f"matched but cannot resolve revision: {err}"
            return (enriched, None)
        installed_revision: str | None = sha
    elif is_exact_match:
        installed_revision = None
        enriched["installed_revision_deferred"] = (
            "exact match; revision resolution deferred until final winner selection"
        )
    else:
        installed_revision = None
        enriched["installed_revision_unknown"] = (
            f"local content differs from upstream HEAD (similarity={round(full, 4)}); "
            "recording installed_revision=null so update_skill will re-align"
        )

    record = {
        "url": candidate["url"],
        "branch": candidate["branch"],
        "subpath": candidate["subpath"],
        "installed_revision": installed_revision,
    }
    return (enriched, record)


def audit_via_embedded_urls(skill_dir: Path, local_text: str, local_head: str) -> dict:
    """Try GitHub URLs written inside local SKILL.md before generic sources."""
    report: dict = {
        "method": "embedded_url",
        "decision": "no_match",
        "candidates": [],
        "claim_record": None,
        "error": None,
    }

    md_path = skill_dir / "SKILL.md"
    if not md_path.is_file():
        md_path = skill_dir / "skill.md"
    if not md_path.is_file():
        report["error"] = "no SKILL.md to inspect for embedded GitHub URLs"
        return report

    raw_text = md_path.read_text(encoding="utf-8", errors="replace")
    best_high_record: dict | None = None
    best_high_full: float = -1.0
    has_mid = False

    for cand_input in embedded_github_candidates(raw_text):
        enriched, record = _verify_and_build_claim(local_text, local_head, cand_input, "embedded_url")
        report["candidates"].append(enriched)
        if record is not None and enriched.get("full_ratio", 0) > best_high_full:
            best_high_record = record
            best_high_full = enriched["full_ratio"]
        elif enriched.get("confidence") == "mid":
            has_mid = True

    if best_high_record is not None:
        report["decision"] = "auto_claim"
        report["claim_record"] = best_high_record
    elif has_mid:
        report["decision"] = "needs_review"

    return report


def query_hint_for(skill_dir: Path) -> str | None:
    """Build a phrase suitable for agent-driven WebSearch."""
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        md = skill_dir / "skill.md"
    if not md.is_file():
        return None
    fm = parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
    return extract_query_phrase(fm.get("description", ""))


def extract_query_phrase(description: str, min_words: int = 8, max_words: int = 12) -> str | None:
    """Pick a contiguous span of original words from a description."""
    if not description:
        return None
    cleaned = re.sub(r"\s+", " ", description).strip()
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'\-]*", cleaned)
    if len(tokens) < min_words:
        return None
    return " ".join(tokens[:max_words])


def audit_one(name: str, skill_dir: Path) -> dict:
    """Returns a per-skill report dict."""
    git_report = audit_via_git_dir(skill_dir)
    if git_report is not None:
        return {"name": name, **git_report}

    local = _read_local_skill_md(skill_dir)
    if local is None:
        return {
            "name": name,
            "method": "websearch",
            "decision": "no_match",
            "candidates": [],
            "claim_record": None,
            "error": "no SKILL.md to compare",
        }
    local_text, local_head = local

    embedded_report = audit_via_embedded_urls(skill_dir, local_text, local_head)
    if embedded_report["decision"] in ("auto_claim", "needs_review"):
        return {"name": name, **embedded_report}

    return {
        "name": name,
        "method": "websearch",
        "decision": "no_match",
        "candidates": embedded_report["candidates"],
        "claim_record": None,
        "error": embedded_report.get("error"),
    }


def run_audit(dry_run: bool = False) -> dict:
    data = load_sources()
    self_name = skills_manager_root().name

    reports: list[dict] = []
    auto_claimed_now: list[str] = []
    for child in sorted(skills_root().iterdir()):
        if not child.is_dir():
            continue
        if child.name == self_name or child.name.startswith("."):
            continue
        if child.name in data["skills"]:
            continue

        rep = audit_one(child.name, child)
        if rep["decision"] in ("needs_review", "no_match", "git_remote_unsupported"):
            rep["search_query_hint"] = query_hint_for(child)
        reports.append(rep)
        if rep["decision"] == "auto_claim" and not dry_run:
            data["skills"][child.name] = rep["claim_record"]
            auto_claimed_now.append(child.name)

    if auto_claimed_now and not dry_run:
        save_sources(data)

    # After-audit inventory: reflect the new state to the user in a single call.
    # Skipped in --dry-run because sources.json wasn't touched, so inventory
    # would just print the pre-audit state and confuse the reader.
    inventory_after: list[dict] | None = None
    if not dry_run:
        inventory_after = inventory.scan(check_remote=True)

    summary = {
        "total_unclaimed": len(reports),
        "auto_claimed": sum(1 for r in reports if r["decision"] == "auto_claim"),
        "needs_review": sum(1 for r in reports if r["decision"] == "needs_review"),
        "no_match": sum(1 for r in reports if r["decision"] == "no_match"),
        "git_remote_unsupported": sum(
            1 for r in reports if r["decision"] == "git_remote_unsupported"
        ),
        "dry_run": dry_run,
    }
    return {
        "summary": summary,
        "reports": reports,
        "inventory_after": inventory_after,
    }


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="audit_unclaimed.py")
    p.add_argument("--dry-run", action="store_true",
                    help="Report only; do not write sources.json.")
    args = p.parse_args(argv[1:])
    emit_json(run_audit(dry_run=args.dry_run))


if __name__ == "__main__":
    main(sys.argv)
