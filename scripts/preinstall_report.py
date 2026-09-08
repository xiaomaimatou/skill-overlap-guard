"""Compose the V0.2 read-only Pre-install Decision Report."""
from __future__ import annotations

from decision_engine import build_decision
from duplicate_scan import compare_profiles
from health_score import score_profile
from recommendation_policy import best_skill_recommendation
from security_precheck import scan_skill_tree
from manifest import build_manifest, scanner_cache_key
from source_metadata import normalize_source
from trigger_conflict import compare_trigger_conflict


def build_preinstall_report(request: dict, candidate: dict, installed: list[dict], *, security: dict | None = None, source: dict | None = None) -> dict:
    pairs = [compare_profiles(candidate, profile) for profile in installed]
    overlap = max(pairs, key=lambda item: item.get("candidate_score", item.get("score", 0)), default={
        "relationship": "unrelated", "level": "LOW", "skill_a": candidate.get("name", ""), "skill_b": "",
    })
    installed_match = next((profile for profile in installed if profile.get("name") == overlap.get("skill_b")), {})
    trigger = compare_trigger_conflict(candidate, installed_match) if installed_match else {"level": "LOW", "conflicting_skills": []}
    scope = {"scope_relationship": trigger.get("scope_relationship", "unknown")}
    health = score_profile(candidate, source, scope)
    if security is None and candidate.get("skill_dir"):
        security = scan_skill_tree(candidate["skill_dir"])
    decision = build_decision(overlap, trigger, health, security or {"risk_level": "INFO", "findings": []}, source)
    installed_health = score_profile(installed_match, source) if installed_match else {}
    preference = best_skill_recommendation(overlap.get("relationship", "unrelated"), candidate, installed_match, health, installed_health)
    source_info = normalize_source(source)
    manifest = build_manifest(candidate["skill_dir"]) if candidate.get("skill_dir") else None
    cache_key = None
    if manifest:
        cache_key = scanner_cache_key(source_info.get("commit"), manifest["content_hash"], security["scanner_version"] if security else "0.2.0", "0.2.0")
    return {
        **decision,
        "request": request,
        "candidate": {"name": candidate.get("name", ""), "description": candidate.get("description", "")},
        "sections": {
            "functional": decision["functional_risk"],
            "trigger": decision["trigger_risk"],
            "health": decision["health"],
            "security": decision["security_risk"],
        },
        "install_performed": False,
        "best_skill_recommendation": preference,
        "candidate_health": health,
        "installed_health": installed_health,
        "source_info": source_info,
        "manifest": manifest,
        "scanner_cache_key": cache_key,
    }
