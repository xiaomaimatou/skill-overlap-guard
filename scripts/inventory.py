"""List every sibling skill, with metadata.

Usage:
    python inventory.py                    # cheap scan only
    python inventory.py --check-remote     # also runs ls-remote concurrently

Output (stdout, JSON array): one entry per skill directory.
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
"""
from __future__ import annotations

import argparse
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


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="inventory.py")
    p.add_argument("--check-remote", action="store_true",
                   help="Also run git ls-remote concurrently for claimed remote skills.")
    args = p.parse_args(argv[1:])
    entries = scan(check_remote=args.check_remote)
    emit_json(entries)


if __name__ == "__main__":
    main(sys.argv)
