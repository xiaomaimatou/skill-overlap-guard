"""Conservative trigger and generalist/specialist conflict analysis."""
from __future__ import annotations

import re


def _tokens(values: list | str) -> set[str]:
    text = " ".join(map(str, values)) if isinstance(values, list) else str(values or "")
    return {token for token in re.findall(r"[a-z0-9_\u4e00-\u9fff]+", text.casefold()) if len(token) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _is_parent_child(a: dict, b: dict) -> bool:
    return a.get("parent_skill") == b.get("name") or b.get("parent_skill") == a.get("name")


def _unique_values(specialist: dict, generalist: dict) -> list[str]:
    general_tokens = _tokens(generalist.get("capabilities", []))
    return [value for value in specialist.get("capabilities", []) if not (_tokens(value) <= general_tokens)]


def classify_scope_relationship(candidate: dict, installed: dict) -> dict:
    if _is_parent_child(candidate, installed):
        return {"relationship": "parent-child", "specialist": "", "shared_scope": [], "specialist_unique_value": []}
    a = _tokens(candidate.get("capabilities", []))
    b = _tokens(installed.get("capabilities", []))
    if not a or not b:
        return {"relationship": "unknown", "specialist": "", "shared_scope": sorted(a & b), "specialist_unique_value": []}
    if a < b:
        specialist = candidate.get("name", "")
        return {"relationship": "generalist-specialist", "generalist": installed.get("name", ""), "specialist": specialist, "shared_scope": sorted(a), "specialist_unique_value": _unique_values(candidate, installed)}
    if b < a:
        specialist = installed.get("name", "")
        return {"relationship": "generalist-specialist", "generalist": candidate.get("name", ""), "specialist": specialist, "shared_scope": sorted(b), "specialist_unique_value": _unique_values(installed, candidate)}
    candidate_name = _tokens(candidate.get("name", ""))
    installed_name = _tokens(installed.get("name", ""))
    if (candidate_name & b) and len(a & b) >= 1:
        return {"relationship": "generalist-specialist", "generalist": installed.get("name", ""), "specialist": candidate.get("name", ""), "shared_scope": sorted(a & b), "specialist_unique_value": _unique_values(candidate, installed)}
    if (installed_name & a) and len(a & b) >= 1:
        return {"relationship": "generalist-specialist", "generalist": candidate.get("name", ""), "specialist": installed.get("name", ""), "shared_scope": sorted(a & b), "specialist_unique_value": _unique_values(installed, candidate)}
    return {"relationship": "peer", "specialist": "", "shared_scope": sorted(a & b), "specialist_unique_value": []}


def compare_trigger_conflict(candidate: dict, installed: dict) -> dict:
    candidate_triggers = _tokens(candidate.get("triggers", []))
    installed_triggers = _tokens(installed.get("triggers", []))
    candidate_description = _tokens(candidate.get("description", ""))
    installed_description = _tokens(installed.get("description", ""))
    shared = sorted(candidate_triggers & installed_triggers)
    description_similarity = _jaccard(candidate_description, installed_description)
    broad_text = " ".join(map(str, candidate.get("triggers", []))).casefold()
    broad = any(term in broad_text for term in ("any", "all", "everything", "anything", "任何", "所有"))
    scope = classify_scope_relationship(candidate, installed)
    if scope["relationship"] == "parent-child":
        level = "LOW"
    elif shared and (description_similarity >= 0.65 or broad):
        level = "HIGH"
    elif shared or description_similarity >= 0.45 or broad:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {
        "level": level,
        "conflicting_skills": [installed.get("name", "")] if level != "LOW" else [],
        "reason": "共享触发词或 description，可能争抢同一类请求" if level != "LOW" else "未发现明显触发冲突",
        "shared_triggers": shared,
        "description_similarity": round(description_similarity, 4),
        "scope_relationship": scope["relationship"],
        **scope,
    }
