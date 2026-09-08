"""Read-only precedence rules for the V0.2 unified decision."""
from __future__ import annotations


def build_decision(overlap: dict, trigger: dict, health: dict, security: dict, source: dict | None = None) -> dict:
    overlap = dict(overlap or {})
    trigger = dict(trigger or {})
    health = dict(health or {})
    security = dict(security or {})
    security_level = str(security.get("risk_level", "INFO")).upper()
    relationship = overlap.get("relationship", "uncertain")
    if security_level == "CRITICAL":
        recommendation = "block_recommended"
        veto = True
    elif security_level == "HIGH":
        recommendation = "security_warning"
        veto = True
    elif relationship in {"duplicate", "DUPLICATE"}:
        recommendation = "keep_existing"
        veto = False
    elif not overlap.get("skill_b"):
        recommendation = "install_candidate"
        veto = False
    elif relationship in {"parent-child", "complementary", "unrelated", "generalist-specialist"}:
        recommendation = "keep_both"
        veto = False
    elif relationship in {"high-overlap", "HIGH", "partial-overlap", "MEDIUM"} or trigger.get("level") == "HIGH":
        recommendation = "manual_review"
        veto = False
    elif relationship in {"uncertain", ""}:
        recommendation = "manual_review"
        veto = False
    else:
        recommendation = "install_candidate"
        veto = False
    return {
        "functional_risk": overlap,
        "trigger_risk": trigger,
        "health": health,
        "security_risk": {**security, "veto": veto},
        "source": dict(source or {}),
        "recommendation": recommendation,
        "decision_options": ["block", "manual_review", "keep_existing", "keep_both", "install_candidate"],
        "read_only": True,
    }
