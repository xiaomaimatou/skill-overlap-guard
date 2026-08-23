"""List every sibling skill, with metadata.

Usage:
    python inventory.py                    # cheap scan only
    python inventory.py --check-remote     # also runs ls-remote concurrently
    python inventory.py --check-remote --audit-unclaimed
                                           # audit unknown sources, then list

Default output (stdout, JSON array): one entry per skill directory.
    {
      "name": "brainstorming",
      "path": "<abs path>",
      "has_skill_md": true,
      "description": "...",
      "claimed": true,
      "type": "remote",                 # "remote" | "local" | "unclaimed"
      "source": { "url": "...", ... } | null,
      "update_status": "up_to_date" | "update_available"
                     | "local" | "unclaimed" | "unknown" | "error" | null,
      "remote_revision": "..." | null,
      "check_error": null | "..."
    }

Notes:
- Skips the skills-manager directory itself and dotted directories.
- With --check-remote, ls-remote is run in parallel with a small thread pool.
- With --audit-unclaimed, output is `{ "entries": [...], "audit": {...} }`.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from _common import (
    emit_json,
    load_sources,
    read_skill_md,
    skills_manager_root,
    skills_root,
)
from check_remote import fetch_remote_sha


EXCLUDED_DIRECTORY_NAMES = {".system", ".backup", ".tmp", "cache", "caches"}


def inventory_scope(root: Path) -> str:
    """Return a stable label for a configured skills root."""
    parts = root.parts
    if ".agents" in parts:
        return "project" if root.parent.name == ".agents" else "agents"
    if ".codex" in parts:
        return "codex"
    if root.parent.name == "agents":
        return "agents"
    if root.parent.name == "codex":
        return "codex"
    return "custom"


def is_excluded_skill_path(path: Path, root: Path) -> bool:
    """Keep protected, generated, and temporary directories out of governance."""
    return any(part in EXCLUDED_DIRECTORY_NAMES for part in path.relative_to(root).parts)


def skill_content_hash(skill_md: Path) -> str:
    return "sha256:" + hashlib.sha256(skill_md.read_bytes()).hexdigest()


def discover_skills(roots: list[Path]) -> list[dict]:
    """Recursively discover SKILL.md files under the configured roots.

    The returned records intentionally do not consult sources.json. That keeps
    discovery read-only and reusable by audit and pre-install checks.
    """
    records: list[dict] = []
    records_by_dir: dict[Path, dict] = {}

    for root in roots:
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            skill_dir = skill_md.parent
            if is_excluded_skill_path(skill_dir, root):
                continue
            has_md, frontmatter = read_skill_md(skill_dir)
            if not has_md:
                continue
            name = frontmatter.get("name", "").strip() or skill_dir.name
            record = {
                "name": name,
                "description": frontmatter.get("description", ""),
                "path": str(skill_dir),
                "scope": inventory_scope(root),
                "parent_skill": None,
                "children": [],
                "content_hash": skill_content_hash(skill_md),
            }
            records.append(record)
            records_by_dir[skill_dir.resolve()] = record

    for skill_dir, record in records_by_dir.items():
        parent_dir = skill_dir.parent
        while parent_dir in records_by_dir or parent_dir.parent != parent_dir:
            parent = records_by_dir.get(parent_dir)
            if parent is not None:
                record["parent_skill"] = parent["name"]
                parent["children"].append(record["name"])
                break
            parent_dir = parent_dir.parent

    for record in records:
        record["children"].sort()
    return sorted(records, key=lambda item: (item["scope"], item["path"]))


def classify(rec: dict | None) -> str:
    if rec is None:
        return "unclaimed"
    if rec.get("url"):
        return "remote"
    return "local"


def scan(check_remote: bool) -> list[dict]:
    root = skills_root()
    self_name = skills_manager_root().name
    data = load_sources()
    skills_rec = data["skills"]

    entries: list[dict] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name == self_name or child.name.startswith("."):
            continue

        has_md, fm = read_skill_md(child)
        rec = skills_rec.get(child.name)
        kind = classify(rec)
        status = "local" if kind == "local" else ("unclaimed" if kind == "unclaimed" else None)

        entries.append({
            "name": child.name,
            "path": str(child),
            "has_skill_md": has_md,
            "description": fm.get("description", "") if has_md else "",
            "claimed": rec is not None,
            "type": kind,
            "source": rec,
            "update_status": status,
            "remote_revision": None,
            "check_error": None,
        })

    if not check_remote:
        return entries

    remote_entries = [e for e in entries if e["type"] == "remote"]
    if not remote_entries:
        return entries

    def _check(e: dict) -> tuple[str, str, str | None]:
        rec = e["source"]
        branch = (rec or {}).get("branch") or "main"
        url = (rec or {}).get("url") or ""
        sha, err = fetch_remote_sha(url, branch)
        return e["name"], sha, err

    max_workers = min(8, len(remote_entries))
    name_to_entry = {e["name"]: e for e in remote_entries}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_check, e) for e in remote_entries]
        for fut in as_completed(futures):
            name, sha, err = fut.result()
            e = name_to_entry[name]
            installed = (e["source"] or {}).get("installed_revision") or ""
            if err:
                e["update_status"] = "error"
                e["check_error"] = err
            else:
                e["remote_revision"] = sha
                if not installed:
                    # installed_revision missing / null means claim-remote or
                    # audit recorded that local content doesn't match upstream
                    # HEAD; treat as "needs update" rather than "unknown" so
                    # the user is prompted to re-align via update_skill.
                    e["update_status"] = "update_available"
                elif installed == sha:
                    e["update_status"] = "up_to_date"
                else:
                    e["update_status"] = "update_available"

    return entries


def audit_metadata(payload: dict) -> dict:
    summary = payload.get("summary") or {}
    return {
        "ran": True,
        "auto_claimed": summary.get("auto_claimed", 0),
        "needs_review": summary.get("needs_review", 0),
        "no_match": summary.get("no_match", 0),
        "git_remote_unsupported": summary.get("git_remote_unsupported", 0),
        "reports": payload.get("reports", []),
    }


def scan_with_audit(check_remote: bool) -> dict:
    initial = scan(check_remote=False)
    if not any(e["type"] == "unclaimed" for e in initial):
        entries = scan(check_remote=check_remote) if check_remote else initial
        return {"entries": entries, "audit": {"ran": False}}

    import audit_unclaimed

    payload = audit_unclaimed.run_audit(dry_run=False)
    entries = payload.get("inventory_after") or scan(check_remote=check_remote)
    return {"entries": entries, "audit": audit_metadata(payload)}


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="inventory.py")
    p.add_argument("--check-remote", action="store_true",
                   help="Also run git ls-remote concurrently for claimed remote skills.")
    p.add_argument("--audit-unclaimed", action="store_true",
                   help="Audit unclaimed skills first; outputs {entries, audit}.")
    args = p.parse_args(argv[1:])
    if args.audit_unclaimed:
        emit_json(scan_with_audit(check_remote=args.check_remote))
    else:
        emit_json(scan(check_remote=args.check_remote))


if __name__ == "__main__":
    main(sys.argv)
