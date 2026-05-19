"""Safe maintenance of sources.json.

Agents MUST use this script to mutate sources.json. Editing JSON by hand
risks corrupting the file.

Subcommands:
    list                            Print all entries (JSON).
    remove <name>                   Delete an entry.
    claim-local <name>              Mark <name> as a local/private skill ({} record).
    claim-remote <name> --url <u> [--branch <b>] [--subpath <s>] [--no-resolve]
                                    Register remote source. Computes installed_revision
                                    via `git ls-remote`. Pass --no-resolve to skip
                                    ls-remote (for offline/test use).

Exit codes:
    0  ok
    2  bad input
    3  sources.json corrupted
    4  remote operation failed
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _common import (
    die,
    emit_json,
    fetch_remote_skill_md,
    load_sources,
    normalize_github_repo_url,
    save_sources,
    skills_root,
    validate_skill_name,
)
from similarity import normalize, ratio


def cmd_list(_args: argparse.Namespace) -> None:
    data = load_sources()
    emit_json(data["skills"])


def cmd_remove(args: argparse.Namespace) -> None:
    name = validate_skill_name(args.name)
    data = load_sources()
    if name not in data["skills"]:
        die(f"{name!r} not in sources.json", code=2)
    del data["skills"][name]
    save_sources(data)
    emit_json({"removed": name})


def cmd_claim_local(args: argparse.Namespace) -> None:
    name = validate_skill_name(args.name)
    skill_dir = skills_root() / name
    if not skill_dir.is_dir():
        die(f"directory not found: {skill_dir}", code=2)
    data = load_sources()
    data["skills"][name] = {}
    save_sources(data)
    emit_json({"claimed_local": name})


def resolve_remote_revision(url: str, branch: str) -> str:
    """Run `git ls-remote <url> refs/heads/<branch>` and return the SHA."""
    target = f"refs/heads/{branch}"
    try:
        out = subprocess.run(
            ["git", "ls-remote", url, target],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        die("git CLI not found on PATH", code=4)
    except subprocess.TimeoutExpired:
        die(f"git ls-remote timed out for {url}", code=4)
    if out.returncode != 0:
        die(f"git ls-remote failed: {out.stderr.strip() or out.stdout.strip()}", code=4)
    for line in out.stdout.splitlines():
        sha = line.split()[0] if line.split() else ""
        if sha:
            return sha
    die(f"no revision returned for {url} {target}", code=4)
    return ""


def cmd_claim_remote(args: argparse.Namespace) -> None:
    name = validate_skill_name(args.name)
    skill_dir = skills_root() / name
    if not skill_dir.is_dir():
        die(f"directory not found: {skill_dir}", code=2)
    url = normalize_github_repo_url(args.url)
    if url is None:
        die(
            f"unsupported remote URL {args.url!r}; only GitHub repo URLs are supported",
            code=2,
        )
    branch = args.branch or "main"
    subpath = args.subpath or ""
    if subpath:
        cleaned = subpath.replace("\\", "/").strip("/")
        if ".." in cleaned.split("/"):
            die(f"subpath must not contain '..': {subpath!r}", code=2)
        subpath = cleaned

    revision: str | None
    verify_note: str | None = None

    if args.no_resolve:
        # Test / offline path: trust the caller. installed_revision will be
        # set to args.assume_revision verbatim, no content check.
        revision = args.assume_revision or ""
        if not revision:
            die("--no-resolve requires --assume-revision <sha>", code=2)
    else:
        # Default path: verify local SKILL.md actually matches upstream HEAD
        # before recording a revision. If it doesn't, installed_revision is
        # set to null so update_skill / inventory correctly flag the skill
        # as needing re-alignment instead of silently claiming "up to date".
        head_sha = resolve_remote_revision(url, branch)
        local_md = skill_dir / "SKILL.md"
        if not local_md.is_file():
            local_md = skill_dir / "skill.md"
        if not local_md.is_file():
            die(f"{name!r} has no SKILL.md to verify against upstream", code=2)
        local_text = normalize(local_md.read_text(encoding="utf-8", errors="replace"))
        remote_text, err = fetch_remote_skill_md(url, branch, subpath)
        if err:
            revision = None
            verify_note = f"could not fetch upstream SKILL.md: {err}; recorded installed_revision=null"
        else:
            r = ratio(local_text, normalize(remote_text))
            if r >= 1.0:
                revision = head_sha
                verify_note = "local content matches upstream HEAD"
            else:
                revision = None
                verify_note = (
                    f"local content differs from upstream HEAD (similarity={round(r, 4)}); "
                    "recorded installed_revision=null so update_skill will re-align"
                )

    data = load_sources()
    data["skills"][name] = {
        "url": url,
        "branch": branch,
        "subpath": subpath,
        "installed_revision": revision,
    }
    save_sources(data)
    payload = {
        "claimed_remote": name,
        "url": url,
        "branch": branch,
        "subpath": subpath,
        "installed_revision": revision,
    }
    if verify_note is not None:
        payload["verify_note"] = verify_note
    emit_json(payload)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sources.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    p_rm = sub.add_parser("remove")
    p_rm.add_argument("name")
    p_rm.set_defaults(func=cmd_remove)

    p_local = sub.add_parser("claim-local")
    p_local.add_argument("name")
    p_local.set_defaults(func=cmd_claim_local)

    p_remote = sub.add_parser("claim-remote")
    p_remote.add_argument("name")
    p_remote.add_argument("--url", required=True)
    p_remote.add_argument("--branch", default=None)
    p_remote.add_argument("--subpath", default=None)
    p_remote.add_argument("--no-resolve", action="store_true",
                          help="Skip git ls-remote; pair with --assume-revision")
    p_remote.add_argument("--assume-revision", default=None)
    p_remote.set_defaults(func=cmd_claim_remote)

    return p


def main(argv: list[str]) -> None:
    args = build_parser().parse_args(argv[1:])
    args.func(args)


if __name__ == "__main__":
    main(sys.argv)
