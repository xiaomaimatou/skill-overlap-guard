"""Normalize source and version evidence for read-only reports."""
from __future__ import annotations


def normalize_source(source: dict | None) -> dict:
    source = dict(source or {})
    return {
        "source_type": source.get("source_type", "unknown"),
        "repository": source.get("repo", ""),
        "url": source.get("source_url") or source.get("source", ""),
        "skill_path": source.get("path", ""),
        "branch": source.get("branch", ""),
        "commit": source.get("commit") or source.get("revision") or source.get("installed_revision"),
        "license": source.get("license", "unknown"),
        "last_update": source.get("last_update", "unknown"),
        "source_change_warning": source.get("source_change_warning", []),
    }


def compare_source(previous: dict | None, current: dict | None) -> list[str]:
    previous = normalize_source(previous)
    current = normalize_source(current)
    warnings: list[str] = []
    if previous["repository"] and current["repository"] and previous["repository"] != current["repository"]:
        warnings.append("repository_changed")
    if previous["url"] and current["url"] and previous["url"] != current["url"]:
        warnings.append("source_url_changed")
    if previous["commit"] and current["commit"] and previous["commit"] != current["commit"]:
        warnings.append("commit_changed")
    return warnings
