"""Persistent, non-authorizing user decisions for overlap audit pairs.

Decisions only annotate future reports.  They never perform, request, or grant
any change to an installed skill.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from _common import emit_json, skills_manager_root


ALLOWED_DECISIONS = {
    "keep_both", "ignore", "preferred_a", "preferred_b", "manual_review", "pending",
}


def decisions_path() -> Path:
    return skills_manager_root() / "decisions.json"


def normalize_pair(
    skill_a: str, skill_b: str, skill_a_hash: str = "", skill_b_hash: str = ""
) -> tuple[str, str, str, str]:
    """Return a canonical name-sorted pair, keeping each hash with its skill."""
    if not isinstance(skill_a, str) or not isinstance(skill_b, str) or not skill_a or not skill_b:
        raise ValueError("skill names must be non-empty strings")
    if skill_a == skill_b:
        raise ValueError("a decision requires two distinct skills")
    if skill_a <= skill_b:
        return skill_a, skill_b, str(skill_a_hash or ""), str(skill_b_hash or "")
    return skill_b, skill_a, str(skill_b_hash or ""), str(skill_a_hash or "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionRegistry:
    """Small JSON registry of human decisions, keyed by canonical skill pair."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else decisions_path()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "decisions": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"decision registry is invalid JSON: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
            raise ValueError("decision registry must contain a decisions list")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)

    def list(self) -> list[dict[str, Any]]:
        return sorted(
            (dict(record) for record in self._load()["decisions"] if isinstance(record, dict)),
            key=lambda record: (str(record.get("skill_a", "")), str(record.get("skill_b", ""))),
        )

    def set(
        self,
        skill_a: str,
        skill_b: str,
        skill_a_hash: str,
        skill_b_hash: str,
        relationship: str,
        decision: str,
        reason: str = "",
        ignore_future_warning: bool = False,
    ) -> dict[str, Any]:
        """Create or update one canonical pair decision; this has no skill side effects."""
        if decision not in ALLOWED_DECISIONS:
            raise ValueError(f"unsupported decision: {decision}")
        # preferred_a / preferred_b are user-facing positional choices.  Once
        # the pair is canonicalized, retain the same preferred *skill* rather
        # than retaining the now-reversed positional label.
        if skill_a > skill_b:
            decision = {"preferred_a": "preferred_b", "preferred_b": "preferred_a"}.get(
                decision, decision
            )
        a, b, a_hash, b_hash = normalize_pair(skill_a, skill_b, skill_a_hash, skill_b_hash)
        data = self._load()
        now = _now()
        replacement: dict[str, Any] | None = None
        retained: list[dict[str, Any]] = []
        for record in data["decisions"]:
            if isinstance(record, dict) and record.get("skill_a") == a and record.get("skill_b") == b:
                replacement = dict(record)
            elif isinstance(record, dict):
                retained.append(record)
        updated = {
            "skill_a": a,
            "skill_b": b,
            "skill_a_hash": a_hash,
            "skill_b_hash": b_hash,
            "relationship": str(relationship or ""),
            "decision": decision,
            "reason": str(reason or ""),
            "ignore_future_warning": bool(ignore_future_warning),
            "created_at": replacement.get("created_at", now) if replacement else now,
            "updated_at": now,
        }
        retained.append(updated)
        data["decisions"] = retained
        self._save(data)
        return dict(updated)

    def remove(self, skill_a: str, skill_b: str) -> bool:
        a, b, _, _ = normalize_pair(skill_a, skill_b)
        data = self._load()
        retained = [
            record for record in data["decisions"]
            if not (isinstance(record, dict) and record.get("skill_a") == a and record.get("skill_b") == b)
        ]
        removed = len(retained) != len(data["decisions"])
        if removed:
            data["decisions"] = retained
            self._save(data)
        return removed

    def status_for(
        self, skill_a: str, skill_b: str, skill_a_hash: str = "", skill_b_hash: str = ""
    ) -> dict[str, Any]:
        """Return report-only status; a changed source hash makes a decision stale."""
        a, b, a_hash, b_hash = normalize_pair(skill_a, skill_b, skill_a_hash, skill_b_hash)
        record = next(
            (item for item in self.list() if item.get("skill_a") == a and item.get("skill_b") == b),
            None,
        )
        if record is None:
            return {
                "decision_status": "pending", "decision": "pending", "decision_stale": False,
                "warning_suppressed": False,
            }
        stale = record.get("skill_a_hash", "") != a_hash or record.get("skill_b_hash", "") != b_hash
        if stale:
            return {
                "decision_status": "stale", "decision": record.get("decision"), "decision_stale": True,
                "warning_suppressed": False,
            }
        decision = record.get("decision", "pending")
        return {
            "decision_status": "confirmed", "decision": decision, "decision_stale": False,
            "warning_suppressed": bool(record.get("ignore_future_warning"))
            and decision in {"keep_both", "ignore"},
        }


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="decision_registry.py")
    parser.add_argument("--file", type=Path, default=decisions_path())
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("list")
    set_parser = subcommands.add_parser("set")
    set_parser.add_argument("skill_a")
    set_parser.add_argument("skill_b")
    set_parser.add_argument("decision", choices=sorted(ALLOWED_DECISIONS))
    set_parser.add_argument("--skill-a-hash", default="")
    set_parser.add_argument("--skill-b-hash", default="")
    set_parser.add_argument("--relationship", default="")
    set_parser.add_argument("--reason", default="")
    set_parser.add_argument("--ignore-future-warning", action="store_true")
    remove_parser = subcommands.add_parser("remove")
    remove_parser.add_argument("skill_a")
    remove_parser.add_argument("skill_b")
    args = parser.parse_args(argv[1:])
    registry = DecisionRegistry(args.file)
    if args.command == "list":
        emit_json(registry.list())
    elif args.command == "set":
        emit_json(registry.set(
            args.skill_a, args.skill_b, args.skill_a_hash, args.skill_b_hash,
            args.relationship, args.decision, args.reason, args.ignore_future_warning,
        ))
    else:
        emit_json({"removed": registry.remove(args.skill_a, args.skill_b)})


if __name__ == "__main__":
    main(sys.argv)
