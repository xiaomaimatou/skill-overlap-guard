"""Read-only file manifest and scanner-cache key helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _file_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    return suffix[1:] if suffix else "no_extension"


def build_manifest(skill_dir: Path) -> dict:
    root = Path(skill_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"skill directory not found: {skill_dir}")
    files: list[dict] = []
    type_summary: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        kind = _file_type(path)
        files.append({"path": relative, "size": path.stat().st_size, "sha256": digest, "type": kind})
        type_summary[kind] = type_summary.get(kind, 0) + 1
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {
        "files": files,
        "file_count": len(files),
        "file_type_summary": dict(sorted(type_summary.items())),
        "content_hash": "sha256:" + hashlib.sha256(canonical).hexdigest(),
        "read_only": True,
    }


def scanner_cache_key(commit: str | None, content_hash: str, scanner_version: str, ruleset_version: str) -> str:
    values = [str(commit or ""), str(content_hash), str(scanner_version), str(ruleset_version)]
    return "sha256:" + hashlib.sha256("\n".join(values).encode()).hexdigest()
