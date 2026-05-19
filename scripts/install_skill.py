"""Install a new skill from a GitHub URL and register it in sources.json.

Usage:
    python install_skill.py <github-url> [--name <override>] [--branch <override>]

Supported URL forms:
    https://github.com/<owner>/<repo>
    https://github.com/<owner>/<repo>.git
    https://github.com/<owner>/<repo>/tree/<branch>/<subpath...>
    https://github.com/<owner>/<repo>/blob/<branch>/<subpath...>/SKILL.md
    https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<subpath...>/SKILL.md
    git@github.com:<owner>/<repo>(.git)

Flow:
    1. Parse URL into (repo_url, branch, subpath). branch may be None.
    2. If branch is None, ls-remote --symref to detect the default branch.
    3. Clone --depth 1 --branch <branch> into .tmp/<uuid>/.
    4. Resolve <subpath> safely (no traversal); ensure SKILL.md exists.
    5. Resolve final skill name: --name override > frontmatter `name` field.
    6. If <skills_root>/<name> already exists, move it to .backup/<name>-<ts>-<uuid>/.
    7. Atomic rename <clone>/<subpath> -> <skills_root>/<name>.
    8. Capture installed_revision via rev-parse HEAD.
    9. Write sources.json record. On any post-rename failure, try to roll back.

Exit codes:
    0 success
    2 bad input / unrecognized URL / SKILL.md not found at subpath
    4 git failure (network, clone, rev-parse)
    5 filesystem failure during swap (potentially partial; check stderr)

Note: We deliberately do NOT write installed_content_hash. update_skill.py
strips that field on every update; staying consistent with that choice.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, unquote

from _common import (
    backup_root,
    cleanup_dir,
    die,
    emit_json,
    load_sources,
    read_skill_md,
    run_git,
    safe_resolve_subpath,
    save_sources,
    skills_manager_root,
    skills_root,
    tmp_root,
    validate_skill_name,
)


def parse_github_url(raw: str) -> dict:
    """Returns {repo_url, branch (None=detect later), subpath}.

    Dies with exit 2 on unrecognized URLs.
    """
    s = raw.strip()
    if not s:
        die("empty URL", code=2)

    if s.startswith("git@github.com:"):
        rest = s[len("git@github.com:"):]
        rest = rest.removesuffix(".git").rstrip("/")
        parts = rest.split("/", 1)
        if len(parts) != 2 or not all(parts):
            die(f"unrecognized SSH URL: {raw}", code=2)
        owner, repo = parts
        return {
            "repo_url": f"https://github.com/{owner}/{repo}",
            "branch": None,
            "subpath": "",
        }

    try:
        u = urlsplit(s)
    except ValueError as e:
        die(f"cannot parse URL: {e}", code=2)

    host = (u.netloc or "").lower()
    path = unquote(u.path or "").strip("/")
    parts = path.split("/") if path else []

    if host == "raw.githubusercontent.com":
        if len(parts) < 4:
            die(f"unrecognized raw URL: {raw}", code=2)
        owner, repo, branch, *rest = parts
        sub = "/".join(rest)
        if sub.endswith("/SKILL.md") or sub.endswith("/skill.md"):
            sub = sub.rsplit("/", 1)[0]
        elif sub in ("SKILL.md", "skill.md"):
            sub = ""
        return {
            "repo_url": f"https://github.com/{owner}/{repo}",
            "branch": branch,
            "subpath": sub,
        }

    if host in ("github.com", "www.github.com"):
        if len(parts) < 2:
            die(f"unrecognized GitHub URL: {raw}", code=2)
        owner, repo = parts[0], parts[1]
        repo = repo.removesuffix(".git")
        rest = parts[2:]
        branch: str | None = None
        sub = ""
        if rest:
            kind = rest[0]
            if kind in ("tree", "blob") and len(rest) >= 2:
                branch = rest[1]
                sub = "/".join(rest[2:])
                if kind == "blob" and (sub.endswith("/SKILL.md") or sub.endswith("/skill.md")):
                    sub = sub.rsplit("/", 1)[0]
                elif kind == "blob" and sub in ("SKILL.md", "skill.md"):
                    sub = ""
            else:
                die(
                    f"unrecognized GitHub path segment {kind!r} in {raw}; "
                    f"expected /tree/<branch>/... or /blob/<branch>/...",
                    code=2,
                )
        return {
            "repo_url": f"https://github.com/{owner}/{repo}",
            "branch": branch,
            "subpath": sub,
        }

    die(f"unsupported host {host!r}; only github.com / raw.githubusercontent.com / git@github.com supported", code=2)
    return {}


def detect_default_branch(repo_url: str) -> str:
    """Use `git ls-remote --symref <url> HEAD` to find the default branch."""
    out = run_git(["ls-remote", "--symref", repo_url, "HEAD"], timeout=30)
    if out.returncode != 0:
        die(
            f"git ls-remote failed (cannot detect default branch): "
            f"{(out.stderr or out.stdout).strip()[:500]}",
            code=4,
        )
    for line in out.stdout.splitlines():
        if line.startswith("ref:"):
            m = re.match(r"ref:\s+refs/heads/(\S+)\s+HEAD", line)
            if m:
                return m.group(1)
    die(f"could not detect default branch from ls-remote output for {repo_url}", code=4)
    return ""


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="install_skill.py")
    p.add_argument("url", help="GitHub URL pointing at a repo or a skill subpath")
    p.add_argument("--name", default=None,
                   help="Override skill name (default: read from SKILL.md frontmatter)")
    p.add_argument("--branch", default=None,
                   help="Override branch (useful for branch names containing '/')")
    args = p.parse_args(argv[1:])
    if args.name and validate_skill_name(args.name) == skills_manager_root().name:
        die("refusing to install or replace skills-manager itself", code=2)

    parsed = parse_github_url(args.url)
    repo_url = parsed["repo_url"]
    branch = args.branch or parsed["branch"]
    subpath = parsed["subpath"]

    if branch is None:
        branch = detect_default_branch(repo_url)

    run_uuid = uuid.uuid4().hex[:12]
    clone_root = tmp_root() / run_uuid
    clone_root.parent.mkdir(parents=True, exist_ok=True)

    backup_dir: Path | None = None
    central: Path | None = None
    moved_into_central = False

    try:
        clone = run_git(
            ["clone", "--depth", "1", "--branch", branch, repo_url, str(clone_root)],
            timeout=300,
        )
        if clone.returncode != 0:
            die(f"git clone failed: {(clone.stderr or clone.stdout).strip()[:500]}", code=4)

        skill_dir_in_clone = safe_resolve_subpath(clone_root, subpath)
        if not skill_dir_in_clone.is_dir():
            die(f"subpath not found in clone: {subpath!r}", code=2)
        has_md, fm = read_skill_md(skill_dir_in_clone)
        if not has_md:
            hint = (
                "the repository root has no SKILL.md; "
                "please point the URL at the skill subdirectory (.../tree/<branch>/<subpath>)"
                if not subpath
                else f"no SKILL.md at subpath {subpath!r}; check the URL"
            )
            die(hint, code=2)

        name = args.name or fm.get("name", "").strip()
        if not name:
            die(
                "could not determine skill name: SKILL.md frontmatter has no `name` field. "
                "Re-run with --name <name>.",
                code=2,
            )
        name = validate_skill_name(name)
        if name == skills_manager_root().name:
            die("refusing to install or replace skills-manager itself", code=2)

        rev = run_git(["rev-parse", "HEAD"], cwd=clone_root)
        if rev.returncode != 0:
            die("failed to determine remote HEAD revision", code=4)
        installed_revision = rev.stdout.strip()

        central = skills_root() / name

        if central.exists():
            ts = time.strftime("%Y%m%d-%H%M%S")
            backup_dir = backup_root() / f"{name}-{ts}-{run_uuid}"
            try:
                os.replace(central, backup_dir)
            except OSError as e:
                die(f"failed to move existing skill to backup: {e}", code=5)

        try:
            os.replace(skill_dir_in_clone, central)
            moved_into_central = True
        except OSError as e:
            if backup_dir is not None:
                try:
                    os.replace(backup_dir, central)
                except OSError as e2:
                    die(
                        f"INSTALL FAILED AND ROLLBACK FAILED. "
                        f"Old skill is at {backup_dir}; manual recovery needed. "
                        f"install_error={e} rollback_error={e2}",
                        code=5,
                    )
            die(f"install failed (rolled back): {e}", code=5)

        try:
            data = load_sources()
            data["skills"][name] = {
                "url": repo_url,
                "branch": branch,
                "subpath": subpath,
                "installed_revision": installed_revision,
            }
            save_sources(data)
        except SystemExit:
            raise
        except Exception as e:
            try:
                cleanup_dir(central)
                if backup_dir is not None:
                    os.replace(backup_dir, central)
            except OSError as e2:
                die(
                    f"sources.json write failed AND filesystem rollback failed. "
                    f"Skill files are installed at {central}; original (if any) is at {backup_dir}. "
                    f"sources_error={e} rollback_error={e2}",
                    code=5,
                )
            die(f"sources.json write failed (filesystem rolled back): {e}", code=5)

        emit_json({
            "installed": name,
            "url": repo_url,
            "branch": branch,
            "subpath": subpath,
            "installed_revision": installed_revision,
            "path": str(central),
            "backup": str(backup_dir) if backup_dir else None,
        })
    finally:
        cleanup_dir(clone_root)


if __name__ == "__main__":
    main(sys.argv)
