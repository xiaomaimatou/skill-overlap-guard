"""Audit unclaimed sibling skills and auto-claim the high-confidence ones.

Usage:
    python audit_unclaimed.py            # auto-claim high-confidence matches
    python audit_unclaimed.py --dry-run  # report only, do not modify sources.json

Per-skill flow (ordered gates, stop at first verified match):
    1. Cheap, offline: read <skill>/.git/config. If a github.com remote is found,
       claim the skill as that repo at its current branch + revision (subpath="").
    2. Cheap, offline: scan local SKILL.md for github.com URLs, then verify any
       candidates through the same raw + similarity flow as other remote hints.
    3. Whitelist lookup: try each entry in KNOWN_UPSTREAMS + whitelist.json.
       For each candidate, fetch upstream SKILL.md via raw.githubusercontent.com
       and run difflib similarity vs. the local SKILL.md.
    4. GitHub Code Search (only if `gh` CLI is available and authenticated):
       extract a distinctive phrase from the SKILL.md description, search for
       other SKILL.md files containing it, then verify each candidate via the
       same raw + similarity flow. A circuit breaker disables this gate after
       repeated API failures so a single network outage doesn't slow audits.

Confidence rules (from similarity.py):
    - "high"  -> auto-claim; installed_revision is set only on exact content match.
    - "mid"   -> needs_review, surface candidates to the user.
    - "low" / no candidates -> no_match (likely user-authored or unknown).

We deliberately do NOT auto claim-local on no_match; the user decides.

After all skills are processed, derive whitelist additions from the new
auto-claims: any (url, branch) that produced >=2 claims with a consistent
subpath template (e.g. "skills/{name}") is appended to whitelist.json so the
next audit can skip Code Search for that source.

Finally (when NOT --dry-run), runs `inventory.scan(check_remote=True)` once
and attaches the result as `inventory_after` so callers see the updated
landscape in a single command — no separate inventory.py invocation needed.

Output (stdout, JSON):
    {
      "summary": { "total_unclaimed": N, "auto_claimed": K, ..., "dry_run": false,
                   "search_used": bool, "search_disabled_reason": str | null,
                   "whitelist_appended": [ {url, branch, subpath_template}, ... ] },
      "reports": [ {per-skill report}, ... ],
      "inventory_after": [ {inventory entry}, ... ] | null
    }

Per-skill reports with `decision in {needs_review, no_match}` also include a
`search_query_hint` field (string or null). When the script cannot resolve a
skill on its own (e.g. `gh` CLI unavailable, or upstream not on GitHub),
callers can feed this phrase into an agent-driven WebSearch as a fallback —
useful precisely when the in-script Code Search gate couldn't run.

Exit codes:
    0  finished (regardless of how many auto-claims happened)
    3  sources.json corrupted (raised by load_sources)
    4  git CLI missing (raised by run_git when ls-remote needed)
"""
from __future__ import annotations

import argparse
import configparser
import json
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
    split_owner_repo,
)
from check_remote import fetch_remote_sha
from similarity import classify, first_n_lines, normalize, ratio
import gh_search
import inventory


KNOWN_UPSTREAMS: list[dict] = [
    {
        "url": "https://github.com/obra/superpowers",
        "branch": "main",
        "subpath_template": "skills/{name}",
    },
]

SEARCH_FAILURE_BUDGET = 3


def whitelist_path() -> Path:
    return skills_manager_root() / "whitelist.json"


def load_whitelist() -> list[dict]:
    """Load dynamically-learned whitelist entries. Tolerates a missing file."""
    p = whitelist_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    entries = data.get("entries") if isinstance(data, dict) else data
    return [e for e in (entries or []) if isinstance(e, dict)]


def save_whitelist(entries: list[dict]) -> None:
    p = whitelist_path()
    tmp = p.with_suffix(".json.tmp")
    payload = {"version": 1, "entries": entries}
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def merged_upstreams() -> list[dict]:
    """KNOWN_UPSTREAMS + whitelist.json, deduped by (url, branch, template)."""
    seen: set[tuple[str, str, str]] = set()
    merged: list[dict] = []
    for entry in [*KNOWN_UPSTREAMS, *load_whitelist()]:
        key = (entry.get("url", ""), entry.get("branch", ""), entry.get("subpath_template", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    return merged


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
                              source_label: str) -> tuple[dict, dict | None]:
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
    if is_exact_match:
        sha, err = fetch_remote_sha(candidate["url"], candidate["branch"])
        if err:
            enriched["error"] = f"matched but cannot resolve revision: {err}"
            return (enriched, None)
        installed_revision: str | None = sha
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


def audit_via_whitelist(name: str, local_text: str, local_head: str,
                         upstreams: list[dict]) -> dict:
    """Try each upstream entry, fetch raw, score similarity."""
    report: dict = {
        "method": "whitelist",
        "decision": "no_match",
        "candidates": [],
        "claim_record": None,
        "error": None,
    }

    best_high_record: dict | None = None
    best_high_full: float = -1.0
    has_mid = False

    for entry in upstreams:
        sub = entry["subpath_template"].format(name=name)
        cand_input = {"url": entry["url"], "branch": entry["branch"], "subpath": sub}
        enriched, record = _verify_and_build_claim(local_text, local_head, cand_input, "whitelist")
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


def audit_via_search(name: str, skill_dir: Path, local_text: str, local_head: str,
                      breaker: dict) -> dict:
    """Third gate: GitHub Code Search. Mutates breaker on failure."""
    report: dict = {
        "method": "search",
        "decision": "no_match",
        "candidates": [],
        "claim_record": None,
        "error": None,
    }

    description = ""
    md_path = skill_dir / "SKILL.md"
    if md_path.is_file():
        fm = parse_frontmatter(md_path.read_text(encoding="utf-8", errors="replace"))
        description = fm.get("description", "")
    phrase = gh_search.extract_query_phrase(description)
    if not phrase:
        report["error"] = "description too short / generic for a search phrase"
        return report

    items, err = gh_search.search_skill_md(phrase)
    if err:
        breaker["failures"] += 1
        report["error"] = err
        return report

    best_high_record: dict | None = None
    best_high_full: float = -1.0
    has_mid = False
    for item in items:
        cand_input = {
            "url": f"https://github.com/{item['owner']}/{item['repo']}",
            "branch": item["branch"],
            "subpath": item["subpath"],
        }
        enriched, record = _verify_and_build_claim(local_text, local_head, cand_input, "search")
        enriched["upstream_path"] = item.get("path", "")
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
    """Build a phrase suitable for an agent-driven WebSearch fallback.

    Used to populate `search_query_hint` on no_match / needs_review reports so
    callers without `gh` CLI can still get a useful starting query (e.g.
    feed it into the agent's WebSearch tool).
    """
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        md = skill_dir / "skill.md"
    if not md.is_file():
        return None
    fm = parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
    return gh_search.extract_query_phrase(fm.get("description", ""))


def audit_one(name: str, skill_dir: Path, upstreams: list[dict],
                search_enabled: bool, breaker: dict) -> dict:
    """Returns a per-skill report dict."""
    git_report = audit_via_git_dir(skill_dir)
    if git_report is not None:
        return {"name": name, **git_report}

    local = _read_local_skill_md(skill_dir)
    if local is None:
        return {
            "name": name,
            "method": "whitelist",
            "decision": "no_match",
            "candidates": [],
            "claim_record": None,
            "error": "no SKILL.md to compare",
        }
    local_text, local_head = local

    embedded_report = audit_via_embedded_urls(skill_dir, local_text, local_head)
    if embedded_report["decision"] in ("auto_claim", "needs_review"):
        return {"name": name, **embedded_report}

    wl_report = audit_via_whitelist(name, local_text, local_head, upstreams)
    if wl_report["decision"] == "auto_claim":
        return {"name": name, **wl_report}

    if not search_enabled or breaker["failures"] >= SEARCH_FAILURE_BUDGET:
        wl_report["candidates"] = [*embedded_report["candidates"], *wl_report["candidates"]]
        return {"name": name, **wl_report}

    search_report = audit_via_search(name, skill_dir, local_text, local_head, breaker)
    if search_report["decision"] == "auto_claim":
        return {"name": name, **search_report}

    if search_report["decision"] == "needs_review" or wl_report["decision"] == "needs_review":
        wl_report["decision"] = "needs_review"
    wl_report["candidates"] = [
        *embedded_report["candidates"],
        *wl_report["candidates"],
        *search_report["candidates"],
    ]
    if search_report.get("error"):
        wl_report["error"] = wl_report.get("error") or search_report["error"]
    return {"name": name, **wl_report}


def derive_whitelist_additions(reports: list[dict], existing: list[dict]) -> list[dict]:
    """Find (url, branch) that produced >=2 search-sourced claims with the
    same subpath template like 'skills/{name}'. Skip patterns we already have.
    """
    seen_keys = {
        (e.get("url", ""), e.get("branch", ""), e.get("subpath_template", ""))
        for e in existing
    }

    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for r in reports:
        if r.get("decision") != "auto_claim" or r.get("method") != "search":
            continue
        rec = r.get("claim_record") or {}
        url = rec.get("url", "")
        branch = rec.get("branch", "")
        sub = rec.get("subpath", "")
        if not url or not branch:
            continue
        groups.setdefault((url, branch), []).append((r["name"], sub))

    additions: list[dict] = []
    for (url, branch), pairs in groups.items():
        if len(pairs) < 2:
            continue
        templates = {sub.replace(name, "{name}") for name, sub in pairs if name in sub}
        if len(templates) != 1:
            continue
        template = next(iter(templates))
        if (url, branch, template) in seen_keys:
            continue
        additions.append({
            "url": url,
            "branch": branch,
            "subpath_template": template,
        })
    return additions


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="audit_unclaimed.py")
    p.add_argument("--dry-run", action="store_true",
                    help="Report only; do not write sources.json or whitelist.json.")
    args = p.parse_args(argv[1:])

    data = load_sources()
    self_name = skills_manager_root().name
    upstreams = merged_upstreams()

    search_disabled_reason: str | None = None
    if not gh_search.gh_available():
        search_disabled_reason = "gh CLI not available or not authenticated"
    search_enabled = search_disabled_reason is None

    breaker = {"failures": 0}

    reports: list[dict] = []
    auto_claimed_now: list[str] = []
    for child in sorted(skills_root().iterdir()):
        if not child.is_dir():
            continue
        if child.name == self_name or child.name.startswith("."):
            continue
        if child.name in data["skills"]:
            continue

        rep = audit_one(child.name, child, upstreams, search_enabled, breaker)
        if rep["decision"] in ("needs_review", "no_match"):
            rep["search_query_hint"] = query_hint_for(child)
        reports.append(rep)
        if rep["decision"] == "auto_claim" and not args.dry_run:
            data["skills"][child.name] = rep["claim_record"]
            auto_claimed_now.append(child.name)

    if auto_claimed_now and not args.dry_run:
        save_sources(data)

    existing_whitelist = load_whitelist()
    whitelist_additions = derive_whitelist_additions(reports, [*KNOWN_UPSTREAMS, *existing_whitelist])
    if whitelist_additions and not args.dry_run:
        save_whitelist([*existing_whitelist, *whitelist_additions])

    if breaker["failures"] >= SEARCH_FAILURE_BUDGET and search_disabled_reason is None:
        search_disabled_reason = f"search disabled mid-run after {breaker['failures']} consecutive failures"

    # After-audit inventory: reflect the new state to the user in a single call.
    # Skipped in --dry-run because sources.json wasn't touched, so inventory
    # would just print the pre-audit state and confuse the reader.
    inventory_after: list[dict] | None = None
    if not args.dry_run:
        inventory_after = inventory.scan(check_remote=True)

    summary = {
        "total_unclaimed": len(reports),
        "auto_claimed": sum(1 for r in reports if r["decision"] == "auto_claim"),
        "needs_review": sum(1 for r in reports if r["decision"] == "needs_review"),
        "no_match": sum(1 for r in reports if r["decision"] == "no_match"),
        "git_remote_unsupported": sum(
            1 for r in reports if r["decision"] == "git_remote_unsupported"
        ),
        "dry_run": args.dry_run,
        "search_used": search_enabled,
        "search_disabled_reason": search_disabled_reason,
        "search_failures": breaker["failures"],
        "whitelist_appended": whitelist_additions,
    }
    emit_json({
        "summary": summary,
        "reports": reports,
        "inventory_after": inventory_after,
    })


if __name__ == "__main__":
    main(sys.argv)
