"""Read a candidate SKILL.md into the existing Capability Profile parser.

This module resolves and reads source content only.  It never places a Skill
under an installation root, executes its code, or invokes an installer.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from capability_parser import parse_capability_profile


def _github_raw_url(source: dict) -> str:
    value = str(source.get("source", ""))
    if value.startswith("https://raw.githubusercontent.com/"):
        return value
    if value.startswith("https://github.com/"):
        pieces = value.rstrip("/").split("/")
        if len(pieces) >= 8 and pieces[5] in {"blob", "tree"} and pieces[-1].casefold() == "skill.md":
            owner, repo, branch = pieces[3], pieces[4], pieces[6]
            return "https://raw.githubusercontent.com/" + "/".join([owner, repo, branch, *pieces[7:]])
    repo = str(source.get("repo", ""))
    if not repo or "/" not in repo:
        raise ValueError("GitHub source does not identify an owner/repo")
    # A bare owner/repo has no proven nested path.  The safe read-only probe is
    # root SKILL.md on main; callers report a failed probe rather than guessing.
    return f"https://raw.githubusercontent.com/{repo}/main/SKILL.md"


def _read_url(url: str) -> str:
    with urlopen(url, timeout=15) as response:  # nosec B310 - URL is GitHub-normalized above
        return response.read().decode("utf-8", errors="replace")


def load_candidate_profile(source: dict, fetch_text=None) -> dict:
    """Parse a local or GitHub candidate without installing or modifying it."""
    source_type = source.get("source_type", "")
    if source_type == "local_path":
        path = Path(str(source.get("path") or source.get("source") or "")).expanduser()
        skill_dir = path.parent if path.name.casefold() == "skill.md" else path
        profile = parse_capability_profile(skill_dir)
        return {**profile, "source_type": source_type, "source_url": str(path), "skill_dir": str(skill_dir)}
    if source_type not in {"github", "github_shorthand"}:
        raise ValueError("candidate source must be a local path or GitHub source")

    source_url = _github_raw_url(source)
    text = (fetch_text or _read_url)(source_url)
    if not text.strip():
        raise ValueError("candidate SKILL.md is empty")
    with TemporaryDirectory(prefix="skill-manager-source-") as temporary:
        skill_dir = Path(temporary) / "candidate"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
        profile = parse_capability_profile(skill_dir)
    return {**profile, "source_type": source_type, "source_url": source_url}
