"""Read-only recommendation policy, deliberately separate from relationship scoring."""
from __future__ import annotations

import re


def _normalized_purpose(value: str) -> str:
    return " ".join(re.findall(r"\w+", (value or "").casefold()))


def _merge_is_justified(primary_a: str, primary_b: str, shared: list[str],
                        unique_a: list[str], unique_b: list[str]) -> bool:
    normalized_a = _normalized_purpose(primary_a)
    normalized_b = _normalized_purpose(primary_b)
    total_a = len(shared) + len(unique_a)
    total_b = len(shared) + len(unique_b)
    if not normalized_a or not normalized_b or not total_a or not total_b:
        return False
    coverage_a = len(shared) / total_a
    coverage_b = len(shared) / total_b
    return (
        normalized_a == normalized_b
        and coverage_a >= 0.80
        and coverage_b >= 0.80
        and len(unique_a) <= 1
        and len(unique_b) <= 1
    )


def _decision_options(protected: bool) -> list[dict]:
    options = [
        {"action": "keep_skill_a", "label": "保留 Skill A"},
        {"action": "keep_skill_b", "label": "保留 Skill B"},
    ]
    if not protected:
        options.append({"action": "merge_candidate", "label": "两者合并（仅建议，需人工确认）"})
    return options


def recommendation_for(relationship: str, primary_a: str, primary_b: str,
                       shared_core: list[str], unique_a: list[str], unique_b: list[str]) -> dict:
    """Return a non-executing recommendation for one already-classified pair."""
    protected = relationship == "parent-child"
    merge_candidate = (
        relationship == "duplicate"
        and not protected
        and _merge_is_justified(primary_a, primary_b, shared_core, unique_a, unique_b)
    )
    if protected or relationship in {"complementary", "unrelated"}:
        recommendation = "keep_both"
    elif merge_candidate:
        recommendation = "merge_candidate"
    elif relationship == "duplicate":
        recommendation = "possible_duplicate"
    elif relationship == "partial-overlap":
        recommendation = "review_or_keep_both"
    else:
        recommendation = "manual_review"
    return {
        "recommendation": recommendation,
        "merge_candidate": merge_candidate,
        "protected_relationship": protected,
        "decision_options": _decision_options(protected),
    }


def best_skill_recommendation(relationship: str, candidate: dict, installed: dict,
                              candidate_health: dict | None = None,
                              installed_health: dict | None = None,
                              user_preference: str | None = None) -> str:
    """Return a non-destructive preference label for a classified Skill pair."""
    if user_preference in {"prefer_skill_a", "prefer_skill_b", "keep_both", "manual_review"}:
        return user_preference
    if relationship in {"parent-child", "complementary", "generalist-specialist", "unrelated"}:
        return "keep_both"
    if relationship not in {"duplicate", "high-overlap"}:
        return "manual_review"
    a_score = int((candidate_health or {}).get("score", 0))
    b_score = int((installed_health or {}).get("score", 0))
    if a_score and b_score and abs(a_score - b_score) >= 10:
        return "prefer_skill_a" if a_score > b_score else "prefer_skill_b"
    if candidate.get("primary_purpose") == installed.get("primary_purpose"):
        return "manual_review"
    return "keep_both"
