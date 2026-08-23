"""Build deterministic, non-invented Capability Profiles from SKILL.md files."""
from __future__ import annotations

import re
from pathlib import Path

from _common import parse_frontmatter


SECTION_FIELDS = {
    "capabilities": ("capabilit", "feature", "功能", "能力"),
    "triggers": ("trigger", "when to", "触发", "适用场景"),
    "workflow": ("workflow", "process", "flow", "流程", "步骤"),
    "inputs": ("input", "输入"),
    "outputs": ("output", "输出"),
    "tools": ("tool", "工具"),
    "dependencies": ("dependenc", "requirement", "依赖"),
}

HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
FALLBACK_CONFIDENCE = 0.62
DESCRIPTION_CONFIDENCE = 0.85


def _skill_md_path(skill_dir: Path) -> Path | None:
    for filename in ("SKILL.md", "skill.md"):
        candidate = skill_dir / filename
        if candidate.is_file():
            return candidate
    return None


def _section_field(heading: str) -> str | None:
    normalized = heading.casefold()
    for field, keywords in SECTION_FIELDS.items():
        if any(keyword in normalized for keyword in keywords):
            return field
    return None


def _section_items(text: str) -> dict[str, list[str]]:
    fields = {field: [] for field in SECTION_FIELDS}
    current_field: str | None = None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = HEADING_RE.match(line)
        if heading:
            current_field = _section_field(heading.group(1))
            continue
        if current_field is None:
            continue
        item = LIST_ITEM_RE.match(line)
        if item:
            value = item.group(1).strip()
            if value and value not in fields[current_field]:
                fields[current_field].append(value)
    return fields


def _body_paragraphs(text: str, limit: int = 3) -> list[str]:
    """Extract original prose paragraphs without inferring fields or translating text."""
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if body.lstrip().startswith("---"):
        closing = body.find("\n---", body.find("---") + 3)
        if closing >= 0:
            body = body[closing + 4:]
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", body):
        lines = [line.strip() for line in paragraph.split("\n")]
        kept = [
            LIST_ITEM_RE.sub(r"\1", line) for line in lines
            if line and not HEADING_RE.match(line)
        ]
        value = " ".join(kept).strip()
        if value:
            paragraphs.append(value)
        if len(paragraphs) >= limit:
            break
    return paragraphs


def _fallback_metadata(text: str, description: str, sections: dict[str, list[str]]) -> tuple[dict, list[dict]]:
    """Return traceable lower-confidence prose signals when structured evidence is sparse."""
    structured_field_count = sum(bool(sections[field]) for field in ("capabilities", "triggers", "workflow"))
    if description:
        primary = {
            "value": description,
            "source": "frontmatter_description",
            "confidence": DESCRIPTION_CONFIDENCE,
        }
    else:
        primary = {"value": "", "source": "", "confidence": 0.0}
    if structured_field_count >= 2:
        return primary, []
    signals = [
        {"value": value, "source": "body_fallback", "confidence": FALLBACK_CONFIDENCE}
        for value in _body_paragraphs(text)
    ]
    if not description and signals:
        primary = dict(signals[0])
    return primary, signals


def parse_capability_profile(skill_dir: Path, parent_skill: str | None = None) -> dict:
    """Return the profile fields explicitly present in a skill's Markdown.

    A missing file, invalid frontmatter, prose-only section, or unrecognized
    heading produces an empty field rather than a guessed value.
    """
    skill_md = _skill_md_path(skill_dir)
    if skill_md is None:
        text = ""
        frontmatter: dict[str, str] = {}
    else:
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        frontmatter = parse_frontmatter(text)
    sections = _section_items(text)
    description = frontmatter.get("description", "").strip()
    primary_purpose, fallback_signals = _fallback_metadata(text, description, sections)
    return {
        "name": frontmatter.get("name", "").strip() or skill_dir.name,
        "description": description,
        "category": frontmatter.get("category", "").strip(),
        "capabilities": sections["capabilities"],
        "triggers": sections["triggers"],
        "workflow": sections["workflow"],
        "inputs": sections["inputs"],
        "outputs": sections["outputs"],
        "tools": sections["tools"],
        "dependencies": sections["dependencies"],
        "primary_purpose": primary_purpose,
        "fallback_signals": fallback_signals,
        "parent_skill": parent_skill,
    }
