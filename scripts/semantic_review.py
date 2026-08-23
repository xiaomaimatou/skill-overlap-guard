"""Agent-mediated semantic review contracts for bounded Audit candidates.

This module deliberately does not call an LLM or write state. It packages the
real SKILL.md evidence for an Agent and validates the Agent's structured result.
"""
from __future__ import annotations

from pathlib import Path

from recommendation_policy import recommendation_for


ALLOWED_RELATIONSHIPS = {
    "duplicate", "high-overlap", "partial-overlap", "complementary",
    "parent-child", "unrelated", "uncertain",
}
ALLOWED_SCOPE_RELATIONSHIPS = {"peer", "generalist-specialist", "unknown"}
SEMANTIC_LEVELS = {
    "duplicate": "DUPLICATE",
    "high-overlap": "HIGH",
    "partial-overlap": "MEDIUM",
    "complementary": "LOW",
    "parent-child": "LOW",
    "unrelated": "LOW",
    "uncertain": "LOW",
}


def _read_skill_md(skill_dir: Path) -> str:
    for name in ("SKILL.md", "skill.md"):
        path = skill_dir / name
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"SKILL.md not found: {skill_dir}")


def build_review_package(candidate: dict, skill_paths: dict[str, Path]) -> dict:
    """Build an evidence-only package for one L0 candidate pair."""
    a_name, b_name = candidate["skill_a"], candidate["skill_b"]
    if a_name not in skill_paths or b_name not in skill_paths:
        raise ValueError("review package requires paths for both skills")
    return {
        "candidate_score": candidate.get("candidate_score", candidate.get("score")),
        "candidate_level": candidate.get("candidate_level", candidate.get("level")),
        "skill_a": {"name": a_name, "path": str(skill_paths[a_name]), "skill_md": _read_skill_md(skill_paths[a_name])},
        "skill_b": {"name": b_name, "path": str(skill_paths[b_name]), "skill_md": _read_skill_md(skill_paths[b_name])},
        "instructions": "Classify only evidence expressed in the two SKILL.md files. Preserve Chinese, English, or mixed-language evidence; separate primary purpose, core duties, incidental mentions, dependencies, and referenced tools. State scope_relationship as peer, generalist-specialist, or unknown; return uncertain when evidence is insufficient. High-overlap and duplicate require shared core capabilities, never incidental mentions alone.",
    }


def validate_semantic_result(result: dict) -> dict:
    """Validate an Agent result and derive its final semantic level."""
    required = {
        "primary_purpose", "core_capabilities", "incidental_mentions", "shared_core_capabilities",
        "skill_a_unique", "skill_b_unique", "relationship", "confidence", "reason", "evidence",
    }
    missing = required - result.keys()
    if missing:
        raise ValueError(f"semantic result missing fields: {', '.join(sorted(missing))}")
    relationship = result["relationship"]
    if relationship not in ALLOWED_RELATIONSHIPS:
        raise ValueError(f"invalid relationship: {relationship}")
    scope_relationship = result.get("scope_relationship", "unknown")
    if scope_relationship not in ALLOWED_SCOPE_RELATIONSHIPS:
        raise ValueError(f"invalid scope relationship: {scope_relationship}")
    confidence = result["confidence"]
    if not isinstance(confidence, (float, int)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be a number from 0 to 1")
    if not isinstance(result["evidence"], list) or not result["evidence"]:
        raise ValueError("semantic result requires at least one evidence item")
    for item in result["evidence"]:
        if not isinstance(item, dict) or not {"skill", "section", "text"} <= item.keys() or not item["text"]:
            raise ValueError("each evidence item requires skill, section, and text")
    if relationship in {"duplicate", "high-overlap"} and not result["shared_core_capabilities"]:
        raise ValueError("high overlap requires shared core capabilities, not incidental mentions alone")
    if relationship == "duplicate" and scope_relationship == "generalist-specialist":
        raise ValueError("a generalist-specialist scope relationship cannot be a duplicate")
    validated = dict(result)
    validated["scope_relationship"] = scope_relationship
    validated["confidence"] = float(confidence)
    validated["semantic_level"] = SEMANTIC_LEVELS[relationship]
    validated.update(recommendation_for(
        relationship,
        validated["primary_purpose"]["skill_a"],
        validated["primary_purpose"]["skill_b"],
        validated["shared_core_capabilities"],
        validated["skill_a_unique"],
        validated["skill_b_unique"],
    ))
    return validated


def apply_semantic_review(candidate: dict, result: dict) -> dict:
    """Combine a validated semantic result with its L0 candidate, without writes."""
    if candidate.get("relationship") == "parent-child":
        # Structural inventory evidence has precedence over an Agent's
        # functional guess.  Validate the same evidence under that protected
        # relation, so an unsupported duplicate claim cannot block reporting
        # the known hierarchy.
        protected_result = dict(result)
        protected_result["relationship"] = "parent-child"
        semantic = validate_semantic_result(protected_result)
        semantic["relationship"] = "parent-child"
        semantic["semantic_level"] = "LOW"
        semantic["reason"] = "Parent-child protection overrides semantic duplicate classification."
    else:
        semantic = validate_semantic_result(result)
    policy = recommendation_for(
        semantic["relationship"],
        semantic["primary_purpose"]["skill_a"],
        semantic["primary_purpose"]["skill_b"],
        semantic["shared_core_capabilities"],
        semantic["skill_a_unique"],
        semantic["skill_b_unique"],
    )
    return {
        **candidate,
        **semantic,
        "level": semantic["semantic_level"],
        **policy,
        "read_only": True,
    }
