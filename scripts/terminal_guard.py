"""Explicit, reversible zsh dry-run guard for `npx skills add`.

The guard never invokes the intercepted npx command.  It delegates candidate
selection to the same invocation contract used by the Codex entry point.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from capability_parser import parse_capability_profile
from inventory import discover_skills
from invocation_contract import build_dedup_context, resolve_request
from source_loader import load_candidate_profile


BEGIN_MARKER = "# BEGIN skill-manager terminal guard"
END_MARKER = "# END skill-manager terminal guard"
INTERCEPTED_EXIT = 86


def detect_skills_add(args: list[str]) -> dict:
    """Identify only npx `skills add <source>`; ordinary npx remains untouched."""
    values = list(args)
    index = 0
    while index < len(values) and values[index] in {"-y", "--yes"}:
        index += 1
    if index + 2 >= len(values) or values[index:index + 2] != ["skills", "add"]:
        return {"intercept": False, "source": ""}
    source = values[index + 2]
    return {"intercept": bool(source and not source.startswith("-")), "source": source}


def _guard_block() -> str:
    executable = sys.executable
    script = Path(__file__).resolve()
    return "\n".join((
        BEGIN_MARKER,
        "npx() {",
        f'  "{executable}" "{script}" intercept "$@"',
        "  local skill_manager_status=$?",
        f"  if [ \"$skill_manager_status\" -eq {INTERCEPTED_EXIT} ]; then",
        "    return 0",
        "  fi",
        "  if [ \"$skill_manager_status\" -eq 0 ]; then",
        "    command npx \"$@\"",
        "  else",
        "    return \"$skill_manager_status\"",
        "  fi",
        "}",
        END_MARKER,
        "",
    ))


def _remove_block(text: str) -> str:
    start = text.find(BEGIN_MARKER)
    if start < 0:
        return text
    end = text.find(END_MARKER, start)
    if end < 0:
        raise ValueError("terminal guard begin marker has no end marker")
    end = text.find("\n", end)
    end = len(text) if end < 0 else end + 1
    return text[:start] + text[end:]


def update_guard(action: str, zshrc: Path) -> str:
    """Enable, disable, or inspect only the marked guard block in a zshrc."""
    original = zshrc.read_text(encoding="utf-8") if zshrc.exists() else ""
    enabled = BEGIN_MARKER in original and END_MARKER in original
    if action == "status":
        return "enabled" if enabled else "disabled"
    if action == "enable":
        if enabled:
            return "already_enabled"
        if BEGIN_MARKER in original or END_MARKER in original:
            raise ValueError("terminal guard markers are incomplete")
        separator = "" if not original or original.endswith("\n") else "\n"
        zshrc.write_text(original + separator + _guard_block(), encoding="utf-8")
        return "enabled"
    if action == "disable":
        if not enabled:
            return "already_disabled"
        zshrc.write_text(_remove_block(original), encoding="utf-8")
        return "disabled"
    raise ValueError("action must be enable, disable, or status")


def _installed_profiles(skills_root: Path) -> list[dict]:
    profiles = []
    for record in discover_skills([skills_root]):
        profile = parse_capability_profile(Path(record["path"]), parent_skill=record["parent_skill"])
        profiles.append({**profile, "content_hash": record["content_hash"]})
    return profiles


def run_dry_run(
    args: list[str], candidate_profile: dict, installed_profiles: list[dict], **candidate_options,
) -> dict:
    """Return the shared read-only dedup context for an intercepted command."""
    detected = detect_skills_add(args)
    if not detected["intercept"]:
        return {"intercepted": False, "dedup_started": False, "installer_called": False, "message": "npx passthrough"}
    request = resolve_request(f"npx skills add {detected['source']}")
    context = build_dedup_context(request, candidate_profile, installed_profiles, **candidate_options)
    return {
        **context,
        "intercepted": True,
        "dedup_started": True,
        "installer_called": False,
        "message": "Skill Overlap Guard detected Skill installation. Installation has NOT been executed.",
    }


def _live_dry_run(args: list[str], skills_root: Path) -> dict:
    detected = detect_skills_add(args)
    if not detected["intercept"]:
        return {"intercepted": False, "message": "npx passthrough", "installer_called": False}
    request = resolve_request(f"npx skills add {detected['source']}")
    try:
        candidate = load_candidate_profile(request["source"])
        report = run_dry_run(args, candidate, _installed_profiles(skills_root))
    except (OSError, ValueError) as exc:
        report = {
            **request,
            "intercepted": True,
            "dedup_started": True,
            "installer_called": False,
            "message": f"Skill Overlap Guard detected Skill installation. Source inspection is blocked: {exc}. Installation has NOT been executed.",
        }
    return report


def main(argv: list[str]) -> int:
    # The wrapper forwards arbitrary npx arguments verbatim.  Parse this
    # action before argparse so flags such as `-y` remain npx flags.
    if len(argv) >= 2 and argv[1] == "intercept":
        report = _live_dry_run(argv[2:], Path.home() / ".agents" / "skills")
        if report["intercepted"]:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return INTERCEPTED_EXIT
        return 0
    parser = argparse.ArgumentParser(prog="terminal_guard.py")
    parser.add_argument("action", choices=("enable", "disable", "status"))
    parser.add_argument("--zshrc", type=Path, default=Path.home() / ".zshrc")
    parser.add_argument("--skills-root", type=Path, default=Path.home() / ".agents" / "skills")
    parsed = parser.parse_args(argv[1:])
    if parsed.action in {"enable", "disable", "status"}:
        print(update_guard(parsed.action, parsed.zshrc))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
