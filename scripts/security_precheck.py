"""Read-only security scanner adapter and conservative local fallback scanner."""
from __future__ import annotations

import re
from pathlib import Path


RANK = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


class ScannerAdapter:
    scanner = "external"
    scanner_version = "unknown"

    def scan(self, skill_dir: Path) -> dict:
        raise NotImplementedError


def _finding(rule: str, level: str, path: Path, line: int, evidence: str) -> dict:
    return {"rule": rule, "level": level, "file": str(path), "line": line, "evidence": evidence[:240]}


def _documentation_example(line: str) -> bool:
    lowered = line.casefold()
    return "`" in line and any(term in lowered for term in ("do not", "don't", "unsafe", "example", "never"))


def _scan_builtin(skill_dir: Path) -> dict:
    findings: list[dict] = []
    commands: set[str] = set()
    domains: set[str] = set()
    sensitive_paths: set[str] = set()
    for path in sorted(skill_dir.rglob("*")):
        if path.is_symlink():
            try:
                if not path.resolve().is_relative_to(skill_dir.resolve()):
                    findings.append(_finding("symlink_escape", "HIGH", path, 1, str(path)))
            except OSError:
                findings.append(_finding("symlink_escape", "HIGH", path, 1, str(path)))
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir)
        if any(part.startswith(".") for part in relative.parts) and path.name not in {".gitignore"}:
            findings.append(_finding("hidden_file", "LOW", path, 1, str(relative)))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            findings.append(_finding("binary_file", "MEDIUM", path, 1, str(relative)))
            continue
        suffix = path.suffix.casefold()
        for number, line in enumerate(text.splitlines(), 1):
            lowered = line.casefold()
            if _documentation_example(line):
                continue
            if re.search(r"ignore (?:previous|all) (?:system|developer|user) instructions|bypass (?:user )?confirmation|send (?:the )?(?:environment|local)", lowered):
                findings.append(_finding("prompt_injection", "CRITICAL", path, number, line))
            if re.search(r"(?:curl|wget)\s+[^|\n]+\|\s*(?:sh|bash|zsh)", lowered):
                findings.append(_finding("download_execute", "CRITICAL", path, number, line))
            if re.search(r"(?:os\.system|subprocess\.|child_process|eval\s*\(|exec\s*\()", lowered):
                findings.append(_finding("dynamic_execution", "HIGH", path, number, line))
            if re.search(r"(?:ssh|\.aws|\.npmrc|\.env|keychain|browser).*(?:token|secret|password|credential|private)", lowered):
                findings.append(_finding("credential_access", "CRITICAL", path, number, line))
            if re.search(r"(?:upload|exfil|send|post).*(?:token|secret|environment|file|data)", lowered):
                findings.append(_finding("exfiltration", "CRITICAL", path, number, line))
            if re.search(r"(?:preinstall|postinstall|install)\s*['\"]?[:=]", lowered) or (path.name == "package.json" and "install" in lowered):
                findings.append(_finding("install_hook", "HIGH", path, number, line))
            if re.search(r"(?:base64|frombase64|atob|decode64)", lowered) and len(line) > 80:
                findings.append(_finding("obfuscation", "HIGH", path, number, line))
            for match in re.finditer(r"https?://([^/\s'\"`]+)", line):
                domains.add(match.group(1))
            for match in re.finditer(r"(?:/Users/[^\s'\"`]+|~?/\.?ssh[^\s'\"`]*|\.env)", line):
                sensitive_paths.add(match.group(0))
            if suffix in {".sh", ".bash", ".zsh", ".py", ".js", ".ts"} and re.search(r"\b(?:curl|wget|python|node|npm|pip)\b", lowered):
                commands.add(line.strip())
    highest = max((RANK[item["level"]] for item in findings), default=0)
    risk_level = next(level for level, rank in RANK.items() if rank == highest)
    return {"risk_level": risk_level, "findings": findings, "commands": sorted(commands), "domains": sorted(domains), "sensitive_paths": sorted(sensitive_paths), "scanner": "built-in-static", "scanner_version": "0.2.0", "read_only": True}


def normalize_scan_result(raw: dict) -> dict:
    result = dict(raw or {})
    level = str(result.get("risk_level", "INFO")).upper()
    if level not in RANK:
        level = "INFO"
    return {
        "risk_level": level,
        "findings": list(result.get("findings", [])),
        "commands": sorted(set(result.get("commands", []))),
        "domains": sorted(set(result.get("domains", []))),
        "sensitive_paths": sorted(set(result.get("sensitive_paths", []))),
        "scanner": result.get("scanner", "external"),
        "scanner_version": result.get("scanner_version", "unknown"),
        "read_only": True,
    }


def scan_skill_tree(skill_dir: Path, scanner: ScannerAdapter | None = None) -> dict:
    path = Path(skill_dir).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"skill directory not found: {skill_dir}")
    return normalize_scan_result((scanner or _BuiltinAdapter()).scan(path))


class _BuiltinAdapter(ScannerAdapter):
    scanner = "built-in-static"
    scanner_version = "0.2.0"

    def scan(self, skill_dir: Path) -> dict:
        return _scan_builtin(skill_dir)
