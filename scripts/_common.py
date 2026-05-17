"""Shared helpers for skills-manager scripts.

Keep this tiny. Anything import-heavy or domain-specific should stay in the
script that owns it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,63}$")


def skills_manager_root() -> Path:
    """Directory of skills-manager itself (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def skills_root() -> Path:
    """Directory that contains all sibling skills (e.g. ~/.cursor/skills/)."""
    return skills_manager_root().parent


def sources_path() -> Path:
    return skills_manager_root() / "sources.json"


def tmp_root() -> Path:
    p = skills_manager_root() / ".tmp"
    p.mkdir(exist_ok=True)
    return p


def backup_root() -> Path:
    p = skills_manager_root() / ".backup"
    p.mkdir(exist_ok=True)
    return p


def validate_skill_name(name: str) -> str:
    """Reject path traversal / weird names. Returns the name on success."""
    if not isinstance(name, str) or not SKILL_NAME_RE.match(name):
        die(f"invalid skill name: {name!r}", code=2)
    return name


def load_sources() -> dict[str, Any]:
    p = sources_path()
    if not p.exists():
        return {"version": 1, "skills": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"sources.json is corrupted: {e}. Refusing to proceed.", code=3)
    if not isinstance(data, dict) or "skills" not in data:
        die("sources.json missing 'skills' key", code=3)
    return data


def save_sources(data: dict[str, Any]) -> None:
    """Atomic write: tmp file in same dir, then os.replace."""
    p = sources_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def parse_frontmatter(text: str) -> dict[str, str]:
    """Tiny YAML-ish frontmatter parser. We only need name + description.

    Handles:
        ---
        name: foo
        description: bar
        ---
    And the common multi-line style:
        description: >-
          multi
          line
    Returns {} if no frontmatter.
    """
    text = text.replace("\r\n", "\n").lstrip()
    if not text.startswith("---"):
        return {}
    rest = text[3:]
    end = rest.find("\n---")
    if end < 0:
        return {}
    block = rest[:end]
    out: dict[str, str] = {}
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in (">-", ">", "|", "|-") or val == "":
            block_lines: list[str] = []
            i += 1
            base_indent = None
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "":
                    block_lines.append("")
                    i += 1
                    continue
                if re.match(r"^[A-Za-z_][A-Za-z0-9_\-]*\s*:", nxt) and not nxt.startswith(" "):
                    break
                indent = len(nxt) - len(nxt.lstrip(" "))
                if base_indent is None:
                    if indent == 0:
                        break
                    base_indent = indent
                if indent < base_indent:
                    break
                block_lines.append(nxt[base_indent:])
                i += 1
            joined = " ".join(s.strip() for s in block_lines if s.strip())
            if val == "" and not joined:
                out[key] = ""
            else:
                out[key] = joined
            continue
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'") and len(val) >= 2:
            val = val[1:-1]
        out[key] = val
        i += 1
    return out


def read_skill_md(skill_dir: Path) -> tuple[bool, dict[str, str]]:
    """Returns (has_skill_md, frontmatter_fields)."""
    for cand in ("SKILL.md", "skill.md"):
        p = skill_dir / cand
        if p.is_file():
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return True, {}
            return True, parse_frontmatter(txt)
    return False, {}


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def emit_json(obj: Any) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    json.dump(obj, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def run_git(args: list[str], cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    """Invoke `git` with safe defaults. Dies (exit 4) on missing CLI or timeout."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        die("git CLI not found on PATH", code=4)
    except subprocess.TimeoutExpired:
        die(f"git {' '.join(args)} timed out", code=4)


def safe_resolve_subpath(clone_root: Path, subpath: str) -> Path:
    """Resolve clone_root/subpath while refusing traversal that escapes the root."""
    if subpath:
        cleaned = subpath.replace("\\", "/").strip("/")
        if not cleaned or ".." in cleaned.split("/"):
            die(f"refusing subpath with traversal: {subpath!r}", code=2)
        target = (clone_root / cleaned).resolve()
    else:
        target = clone_root.resolve()
    root_resolved = clone_root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        die(f"subpath escapes clone root: {target}", code=2)
    return target


def cleanup_dir(p: Path) -> None:
    """Best-effort recursive delete that retries with chmod for read-only files."""
    if not p.exists():
        return

    def _onerror(func, path, exc_info):
        try:
            os.chmod(path, 0o700)
            func(path)
        except OSError:
            pass

    shutil.rmtree(p, onerror=_onerror)


def split_owner_repo(url: str) -> tuple[str, str] | None:
    """Given https://github.com/<owner>/<repo>(...), return (owner, repo) or None."""
    s = url.removeprefix("https://github.com/").removeprefix("http://github.com/")
    parts = s.strip("/").split("/")
    if len(parts) < 2 or not all(parts[:2]):
        return None
    return parts[0], parts[1]


def fetch_remote_skill_md(repo_url: str, branch: str, subpath: str,
                           timeout: int = 15) -> tuple[str, str | None]:
    """Fetch upstream SKILL.md text via raw.githubusercontent.com.

    Returns (text, error). On success error is None. Used by both the audit
    pipeline (similarity scoring against candidates) and `sources.py
    claim-remote` (content verification before recording a revision).
    """
    parsed = split_owner_repo(repo_url)
    if not parsed:
        return "", f"cannot parse owner/repo from: {repo_url}"
    owner, repo = parsed
    sub = (subpath or "").strip("/")
    sub_part = f"/{sub}" if sub else ""
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}{sub_part}/SKILL.md"
    try:
        with urllib.request.urlopen(raw_url, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return "", f"HTTP {e.code} for {raw_url}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "", f"network error fetching {raw_url}: {e}"
