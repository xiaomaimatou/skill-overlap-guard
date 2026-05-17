"""Check whether a single remote skill has updates upstream.

Usage:
    python check_remote.py <skill_name>

Output (stdout, JSON):
    {
      "skill": "brainstorming",
      "installed_revision": "abc...",
      "remote_revision": "def...",
      "update_status": "up_to_date" | "update_available" | "error" | "unknown",
      "error": null
    }

Exit codes:
    0  status determined (up_to_date / update_available / unknown for local)
    2  bad input or skill not eligible (no url, not claimed, etc.)
    4  remote operation failed (network/git error)
"""
from __future__ import annotations

import subprocess
import sys

from _common import die, emit_json, load_sources, validate_skill_name


def fetch_remote_sha(url: str, branch: str) -> tuple[str, str | None]:
    """Return (sha, error_msg). On success error_msg is None."""
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
        return "", "git CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return "", f"git ls-remote timed out for {url}"
    if out.returncode != 0:
        msg = (out.stderr.strip() or out.stdout.strip() or "unknown git error")[:500]
        return "", msg
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts:
            return parts[0], None
    return "", f"no revision returned for {url} {target}"


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        die("usage: check_remote.py <skill_name>", code=2)
    name = validate_skill_name(argv[1])

    data = load_sources()
    rec = data["skills"].get(name)
    if rec is None:
        die(f"{name!r} is unclaimed (not in sources.json)", code=2)
    if not rec.get("url"):
        emit_json({
            "skill": name,
            "installed_revision": None,
            "remote_revision": None,
            "update_status": "unknown",
            "error": None,
            "note": "local skill, no remote to check",
        })
        return

    branch = rec.get("branch") or "main"
    installed = rec.get("installed_revision") or ""
    sha, err = fetch_remote_sha(rec["url"], branch)
    if err:
        emit_json({
            "skill": name,
            "installed_revision": installed or None,
            "remote_revision": None,
            "update_status": "error",
            "error": err,
        })
        sys.exit(0)

    # Missing installed_revision means claim recorded a content mismatch
    # vs upstream HEAD; surface as update_available so the user/agent runs
    # update_skill to re-align rather than thinking the skill is fine.
    if not installed:
        status = "update_available"
    elif installed == sha:
        status = "up_to_date"
    else:
        status = "update_available"
    emit_json({
        "skill": name,
        "installed_revision": installed or None,
        "remote_revision": sha,
        "update_status": status,
        "error": None,
    })


if __name__ == "__main__":
    main(sys.argv)
