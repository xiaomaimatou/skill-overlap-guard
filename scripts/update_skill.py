"""Update a single skill from its remote source.

Usage:
    python update_skill.py <skill_name> [--dry-run]

Flow:
    1. Validate skill_name + sources.json completeness.
    2. Clone <url> --depth 1 --branch <branch> into .tmp/<uuid>/ (same volume).
    3. Resolve <clone>/<subpath>; ensure it stays inside clone root and is a
       valid skill dir (has SKILL.md).
    4. Rename current <central>/<skill_name> -> .backup/<name>-<ts>-<uuid>/
    5. Rename <clone>/<subpath> -> <central>/<skill_name>  (atomic).
    6. Update sources.json with new installed_revision.
    7. On any failure after step 4, try to rename the backup back.

Exit codes:
    0 success
    2 bad input / sources.json incomplete
    4 remote/git failure
    5 filesystem failure during swap (potentially partial; check stderr)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from _common import (
    backup_root,
    cleanup_dir,
    die,
    emit_json,
    load_sources,
    run_git,
    safe_resolve_subpath,
    save_sources,
    skills_manager_root,
    skills_root,
    tmp_root,
    validate_skill_name,
)

REQUIRED_VALUE_FIELDS = ("url", "branch")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="update_skill.py")
    parser.add_argument("name")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve remote revision and report what would happen. No FS changes.")
    args = parser.parse_args(argv[1:])

    name = validate_skill_name(args.name)
    if name == skills_manager_root().name:
        die("refusing to update skills-manager itself", code=2)

    data = load_sources()
    rec = data["skills"].get(name)
    if rec is None:
        die(f"{name!r} is not in sources.json. Run sources.py claim-remote first.", code=2)
    if not rec.get("url"):
        die(f"{name!r} is a local skill, nothing to update.", code=2)
    missing = [f for f in REQUIRED_VALUE_FIELDS if not rec.get(f)]
    if "subpath" not in rec:
        missing.append("subpath")
    if missing:
        die(
            f"{name!r} record is incomplete (missing: {', '.join(missing)}). "
            f"Re-run sources.py claim-remote to repair.",
            code=2,
        )

    subpath_cleaned = rec["subpath"].replace("\\", "/").strip("/")
    if ".." in subpath_cleaned.split("/"):
        die(f"refusing subpath with traversal: {rec['subpath']!r}", code=2)

    central = skills_root() / name
    if not central.is_dir():
        die(f"skill directory missing: {central}", code=2)

    run_uuid = uuid.uuid4().hex[:12]
    clone_root = tmp_root() / run_uuid
    clone_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        clone = run_git([
            "clone", "--depth", "1", "--branch", rec["branch"],
            rec["url"], str(clone_root),
        ], timeout=300)
        if clone.returncode != 0:
            die(f"git clone failed: {(clone.stderr or clone.stdout).strip()[:500]}", code=4)

        rev = run_git(["rev-parse", "HEAD"], cwd=clone_root)
        if rev.returncode != 0:
            die("failed to determine remote HEAD revision", code=4)
        new_revision = rev.stdout.strip()

        new_skill_dir = safe_resolve_subpath(clone_root, rec["subpath"])
        if not new_skill_dir.is_dir():
            die(f"subpath not found in clone: {rec['subpath']}", code=4)
        if not (new_skill_dir / "SKILL.md").is_file() and not (new_skill_dir / "skill.md").is_file():
            die(f"no SKILL.md at {new_skill_dir}; subpath wrong?", code=4)

        if args.dry_run:
            emit_json({
                "skill": name,
                "would_update": new_revision != rec.get("installed_revision"),
                "old_revision": rec.get("installed_revision"),
                "new_revision": new_revision,
            })
            return

        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_dir = backup_root() / f"{name}-{ts}-{run_uuid}"

        try:
            os.replace(central, backup_dir)
        except OSError as e:
            die(f"failed to move current skill to backup: {e}", code=5)

        try:
            os.replace(new_skill_dir, central)
        except OSError as e:
            try:
                os.replace(backup_dir, central)
            except OSError as e2:
                die(
                    f"INSTALL FAILED AND ROLLBACK FAILED. "
                    f"Skill is at {backup_dir}; manual recovery needed. "
                    f"install_error={e} rollback_error={e2}",
                    code=5,
                )
            die(f"install failed (rolled back): {e}", code=5)

        old_revision = rec.get("installed_revision")
        rec["installed_revision"] = new_revision
        rec.pop("installed_content_hash", None)
        data["skills"][name] = rec
        try:
            save_sources(data)
        except Exception as e:
            try:
                cleanup_dir(central)
                os.replace(backup_dir, central)
            except OSError as e2:
                die(
                    f"sources.json write failed AND rollback failed. "
                    f"New skill files are at {central}; backup is at {backup_dir}. "
                    f"sources_error={e} rollback_error={e2}",
                    code=5,
                )
            die(f"sources.json write failed (filesystem rolled back): {e}", code=5)

        emit_json({
            "skill": name,
            "updated": True,
            "old_revision": old_revision,
            "new_revision": new_revision,
            "backup": str(backup_dir),
        })
    finally:
        cleanup_dir(clone_root)


if __name__ == "__main__":
    main(sys.argv)
