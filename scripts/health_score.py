"""Deterministic, explanatory health scoring for Skill capability profiles."""
from __future__ import annotations

import re


def _text(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("value", ""))
    return str(value or "")


def score_profile(profile: dict, source: dict | None = None, relationship: dict | None = None) -> dict:
    factors: dict[str, int] = {}
    strengths: list[str] = []
    risks: list[str] = []

    name = _text(profile.get("name")).strip()
    description = _text(profile.get("description")).strip()
    factors["metadata"] = (8 if name else 0) + (7 if description else 0)
    if name and description:
        strengths.append("核心职责明确")
    else:
        risks.append("name / description 信息缺失")

    fields = ("capabilities", "triggers", "workflow", "inputs", "outputs")
    present = sum(bool(profile.get(field)) for field in fields)
    factors["structure"] = min(30, present * 6)
    if present >= 4:
        strengths.append("SKILL.md 结构完整")
    else:
        risks.append("SKILL.md 结构字段缺失")

    words = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", description.casefold())
    broad_terms = ("any", "all", "everything", "anything", "any task", "所有", "任何")
    broad = any(term in description.casefold() for term in broad_terms)
    factors["clarity"] = 20 if 3 <= len(words) <= 30 else 10 if description else 0
    if broad or any(term in " ".join(map(str, profile.get("triggers", []))).casefold() for term in broad_terms):
        factors["clarity"] = max(0, factors["clarity"] - 12)
        risks.append("触发范围过宽")
    elif description:
        strengths.append("使用场景清晰")

    factors["dependencies"] = 8 if profile.get("dependencies") is not None else 0
    if profile.get("dependencies"):
        strengths.append("依赖信息已声明")
    else:
        risks.append("未声明依赖信息")

    source = source or {}
    factors["source"] = min(15, (8 if source.get("url") or source.get("source_url") else 0) +
                              (7 if source.get("installed_revision") or source.get("revision") else 0))
    if factors["source"] == 15:
        strengths.append("来源与版本信息清晰")
    else:
        risks.append("来源或版本信息不完整")

    relationship = relationship or {}
    factors["relationship"] = 4 if relationship.get("scope_relationship") in {"peer", "generalist-specialist"} else 0
    if relationship.get("scope_relationship") == "generalist-specialist":
        strengths.append("通用 / 专项边界可解释")

    score = max(0, min(100, sum(factors.values())))
    return {"score": score, "strengths": strengths, "risks": risks, "factors": factors}
