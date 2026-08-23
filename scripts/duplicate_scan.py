"""Read-only, deterministic overlap audit for Capability Profiles."""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

from _common import emit_json
from capability_parser import parse_capability_profile
from concept_normalizer import extract_concepts, specific_concepts
from decision_registry import DecisionRegistry
from inventory import discover_skills
from recommendation_policy import recommendation_for


WEIGHTS = {"capabilities": 0.60, "triggers": 0.25, "workflow": 0.15}
GENERIC_TERMS = {
    "a", "an", "and", "analyze", "by", "create", "design", "for", "from",
    "in", "of", "on", "or", "plan", "produce", "requirement", "requirements",
    "skill", "system", "the", "to", "use", "used", "using", "visual", "with",
}
TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
DOMAIN_TAGS = {
    "ui-interface": {
        "ui", "ux", "interface", "interfaces", "frontend", "component", "components",
        "layout", "layouts", "responsive",
    },
    "accessibility": {"accessibility", "accessible", "a11y"},
    "design-system": {
        "token", "tokens", "tailwind", "typography", "css", "variable", "variables",
    },
    "brand-identity": {"identity", "messaging", "voice", "guideline", "guidelines"},
    "marketing-creative": {"banner", "banners", "header", "headers", "campaign", "campaigns", "advertising"},
    "landing-redesign": {"landing", "portfolio", "portfolios", "redesign", "redesigns"},
    "presentations": {"presentation", "presentations", "slide", "slides"},
    "data-charts": {"chart", "charts"},
    "content-layout": {"wechat", "公众号", "article", "articles", "markdown"},
    "video-production": {"video", "videos", "broll", "editing"},
    "video-topic": {"topic", "topics"},
    "video-subtitle": {"subtitle", "subtitles", "srt", "transcription", "transcript", "字幕", "转写"},
    "orchestrator": {"director", "orchestrator", "pipeline", "routing"},
}
DOMAIN_LABELS = {
    "ui-interface": "UI / interface work",
    "accessibility": "Accessibility",
    "design-system": "Design system / tokens",
    "brand-identity": "Brand identity / messaging",
    "marketing-creative": "Marketing / banner creative",
    "landing-redesign": "Landing pages / redesign",
    "presentations": "Presentations / slides",
    "data-charts": "Data visualization / charts",
    "content-layout": "Article / WeChat layout",
    "video-production": "Video production",
    "video-topic": "Video topics / research",
    "video-subtitle": "Video subtitles / transcription",
    "orchestrator": "Workflow orchestration",
}
DEFAULT_CANDIDATE_THRESHOLD = 0.25
DEFAULT_MIN_CANDIDATES = 5
DEFAULT_MAX_CANDIDATES = 10


def _tokens(values: list[str]) -> set[str]:
    terms: set[str] = set()
    for value in values:
        for token in TOKEN_RE.findall(value.casefold()):
            if len(token) > 1 and token not in GENERIC_TERMS:
                terms.add(token)
    return terms


def _jaccard(a: set[str], b: set[str]) -> float | None:
    if not a and not b:
        return None
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _normalized_phrases(values: list[str]) -> dict[str, str]:
    return {" ".join(value.casefold().split()): value for value in values if value.strip()}


def _is_parent_child(a: dict, b: dict) -> bool:
    return a.get("parent_skill") == b.get("name") or b.get("parent_skill") == a.get("name")


def _profile_values(profile: dict, include_fallback: bool = True) -> list[str]:
    values = [profile.get("description", "")]
    primary = profile.get("primary_purpose", {})
    if isinstance(primary, dict) and (include_fallback or primary.get("source") != "body_fallback"):
        values.append(primary.get("value", ""))
    if include_fallback:
        for signal in profile.get("fallback_signals", []):
            if isinstance(signal, dict):
                values.append(signal.get("value", ""))
    for field in ("capabilities", "triggers", "workflow", "inputs", "outputs"):
        values.extend(profile.get(field, []))
    return [value for value in values if isinstance(value, str) and value]


def _primary_value(profile: dict) -> tuple[str, float]:
    primary = profile.get("primary_purpose", {})
    if isinstance(primary, dict) and primary.get("value"):
        return str(primary["value"]), float(primary.get("confidence", 0.0))
    return str(profile.get("description", "")), 0.85 if profile.get("description") else 0.0


def _fallback_concepts(profile: dict) -> set[str]:
    values = [signal.get("value", "") for signal in profile.get("fallback_signals", []) if isinstance(signal, dict)]
    return extract_concepts("\n".join(values))


def _recall_signals(a: dict, b: dict) -> tuple[set[str], list[str]]:
    """Derive explainable recall-only signals; none changes the L0 score."""
    # Keep body-fallback evidence separate from structured/description evidence
    # so one low-confidence paragraph cannot count as two independent signals.
    a_concepts = extract_concepts("\n".join(_profile_values(a, include_fallback=False)))
    b_concepts = extract_concepts("\n".join(_profile_values(b, include_fallback=False)))
    shared_specific = specific_concepts(a_concepts & b_concepts)
    signals = [f"normalized_concept_match:{concept}" for concept in sorted(shared_specific)]

    a_primary, a_confidence = _primary_value(a)
    b_primary, b_confidence = _primary_value(b)
    primary_shared = specific_concepts(extract_concepts(a_primary) & extract_concepts(b_primary))
    if primary_shared and min(a_confidence, b_confidence) >= 0.80:
        signals.extend(f"normalized_primary_purpose_match:{concept}" for concept in sorted(primary_shared))

    fallback_shared = specific_concepts(_fallback_concepts(a) & _fallback_concepts(b))
    if fallback_shared:
        signals.extend(f"fallback_concept_match:{concept}" for concept in sorted(fallback_shared))

    a_trigger = specific_concepts(extract_concepts("\n".join(a.get("triggers", []))))
    b_trigger = specific_concepts(extract_concepts("\n".join(b.get("triggers", []))))
    if a.get("category") and a.get("category") == b.get("category") and a_trigger & b_trigger:
        signals.append("category_and_trigger_match")

    a_specific = specific_concepts(a_concepts)
    b_specific = specific_concepts(b_concepts)
    if shared_specific and ((len(a_specific) >= 3 and len(b_specific) <= 1) or (len(b_specific) >= 3 and len(a_specific) <= 1)):
        signals.append("generalist_specialist_concept_scope")
    return shared_specific, signals


def _pair_key(pair: dict) -> tuple[str, str]:
    return tuple(sorted((pair["skill_a"], pair["skill_b"])))


def _normalize_pair_list(pairs: list[tuple[str, str]] | list[list[str]] | None) -> set[tuple[str, str]]:
    return {tuple(sorted((str(a), str(b)))) for a, b in (pairs or [])}


def _load_recall_benchmarks() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    path = Path(__file__).with_name("recall_benchmarks.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return (
        _normalize_pair_list(data.get("known_positive_pairs")),
        _normalize_pair_list(data.get("known_negative_pairs")),
    )


def _domain_tags(profile: dict) -> set[str]:
    values = [profile.get("description", "")]
    for field in WEIGHTS:
        values.extend(profile.get(field, []))
    terms = _tokens(values)
    return {tag for tag, evidence in DOMAIN_TAGS.items() if terms & evidence}


def _classification(score: float, explicit_score: float, a: dict, b: dict,
                    a_tags: set[str], b_tags: set[str]) -> tuple[str, str, str]:
    if _is_parent_child(a, b):
        return "LOW", "parent-child", "The skills are in a direct parent-child hierarchy; nesting is not duplicate evidence."
    if "orchestrator" in (a_tags ^ b_tags) and explicit_score < 0.25:
        return "LOW", "complementary", "One skill orchestrates a broader workflow; shared domain terms alone are not duplicate evidence."
    if score >= 0.90 and explicit_score >= 0.90:
        return "DUPLICATE", "duplicate", "Explicit capabilities, triggers, and workflow substantially match."
    if score >= 0.60:
        return "HIGH", "high-overlap", "Multiple explicit capability-profile fields overlap while each skill may retain distinct details."
    if score >= 0.25:
        return "MEDIUM", "partial-overlap", "The skills share some explicit work but retain meaningful distinct capabilities."
    if a.get("category") and a.get("category") == b.get("category"):
        return "LOW", "complementary", "The skills share a declared broad category but have distinct explicit capabilities."
    return "LOW", "complementary", "No material duplicate evidence was found; the skills may be used together or independently."


def compare_profiles(a: dict, b: dict) -> dict:
    """Compare two profiles without changing them or their source files."""
    field_scores: dict[str, float] = {}
    weighted_total = 0.0
    weight_total = 0.0
    for field, weight in WEIGHTS.items():
        result = _jaccard(_tokens(a.get(field, [])), _tokens(b.get(field, [])))
        if result is not None:
            field_scores[field] = round(result, 4)
            weighted_total += result * weight
            weight_total += weight
    explicit_score = weighted_total / weight_total if weight_total else 0.0
    a_tags = _domain_tags(a)
    b_tags = _domain_tags(b)
    shared_tag_count = len(a_tags & b_tags)
    tag_score = _jaccard(a_tags, b_tags) or 0.0
    if shared_tag_count < 2:
        tag_score = min(tag_score, 0.45)
    score = max(explicit_score, (explicit_score * 0.15) + (tag_score * 0.85))
    if "orchestrator" in (a_tags ^ b_tags) and explicit_score < 0.25:
        score = min(score, 0.24)
    if _is_parent_child(a, b):
        score = min(score, 0.24)
    field_scores["evidence_tags"] = round(tag_score, 4)
    level, relationship, reason = _classification(score, explicit_score, a, b, a_tags, b_tags)

    a_capabilities = _normalized_phrases(a.get("capabilities", []))
    b_capabilities = _normalized_phrases(b.get("capabilities", []))
    shared_keys = sorted(a_capabilities.keys() & b_capabilities.keys())
    shared = [a_capabilities[key] for key in shared_keys]
    a_unique = [value for key, value in a_capabilities.items() if key not in b_capabilities]
    b_unique = [value for key, value in b_capabilities.items() if key not in a_capabilities]
    shared_tags = sorted(a_tags & b_tags)
    shared = [DOMAIN_LABELS[tag] for tag in shared_tags] + shared
    if not a_unique:
        a_unique = [DOMAIN_LABELS[tag] for tag in sorted(a_tags - b_tags)]
    if not b_unique:
        b_unique = [DOMAIN_LABELS[tag] for tag in sorted(b_tags - a_tags)]
    policy = recommendation_for(relationship, "", "", shared, a_unique, b_unique)
    shared_concepts, recall_signals = _recall_signals(a, b)
    return {
        "skill_a": a["name"],
        "skill_b": b["name"],
        "skill_a_hash": a.get("content_hash", ""),
        "skill_b_hash": b.get("content_hash", ""),
        "score": round(score, 4),
        "level": level,
        "candidate_score": round(score, 4),
        "candidate_level": level,
        "semantic_level": None,
        "relationship": relationship,
        "shared_capabilities": shared,
        "skill_a_unique": a_unique,
        "skill_b_unique": b_unique,
        "reason": reason,
        "normalized_concepts": {
            "shared": sorted(shared_concepts),
        },
        "recall_signals": recall_signals,
        **policy,
        "field_scores": field_scores,
    }


def attach_decision_status(pairs: list[dict], registry: DecisionRegistry) -> list[dict]:
    """Annotate every pair with decision state without filtering or modifying skills."""
    annotated = []
    for pair in pairs:
        status = registry.status_for(
            pair["skill_a"], pair["skill_b"],
            pair.get("skill_a_hash", ""), pair.get("skill_b_hash", ""),
        )
        annotated.append({**pair, **status})
    return annotated


def _candidate_score(pair: dict) -> float:
    return float(pair.get("candidate_score", pair.get("score", 0.0)))


def _semantic_confidence(pair: dict) -> float:
    value = pair.get("confidence")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else -1.0


def _rank_pairs(pairs: list[dict]) -> list[dict]:
    return sorted(pairs, key=lambda pair: (
        -_candidate_score(pair), -_semantic_confidence(pair), pair["skill_a"], pair["skill_b"]
    ))


def select_semantic_candidates(
    pairs: list[dict],
    threshold: float = DEFAULT_CANDIDATE_THRESHOLD,
    min_candidates: int = DEFAULT_MIN_CANDIDATES,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    known_positive_pairs: list[tuple[str, str]] | list[list[str]] | None = None,
) -> list[dict]:
    """Select a bounded, explainable review set without mutating pair scores."""
    if not 0 <= threshold <= 1:
        raise ValueError("candidate threshold must be from 0 to 1")
    if min_candidates < 0 or max_candidates < min_candidates:
        raise ValueError("candidate bounds must satisfy 0 <= min_candidates <= max_candidates")
    default_positive, _ = _load_recall_benchmarks()
    positive = default_positive if known_positive_pairs is None else _normalize_pair_list(known_positive_pairs)
    functional = _rank_pairs([pair for pair in pairs if pair.get("relationship") != "parent-child"])
    existing_keys = {_pair_key(pair) for pair in functional}
    mandatory = positive & existing_keys
    selected_keys: set[tuple[str, str]] = set()
    annotated: dict[tuple[str, str], dict] = {}

    for pair in functional:
        key = _pair_key(pair)
        reasons = []
        score_qualified = _candidate_score(pair) >= threshold
        if score_qualified:
            reasons.append("candidate_score_threshold")
        recall_reasons = list(pair.get("recall_signals", []))
        override = len(recall_reasons) >= 2 or key in mandatory
        if override:
            reasons.extend(recall_reasons)
            if key in mandatory and not recall_reasons:
                reasons.append("known_positive_benchmark")
        if score_qualified or override:
            annotated[key] = {
                **pair,
                "candidate_reasons": reasons,
                "candidate_override": bool(override and not score_qualified),
            }

    for pair in functional:
        key = _pair_key(pair)
        if key in mandatory and key not in annotated:
            annotated[key] = {
                **pair,
                "candidate_reasons": ["known_positive_benchmark"],
                "candidate_override": True,
            }

    for pair in functional:
        key = _pair_key(pair)
        if key in mandatory:
            selected_keys.add(key)
    for pair in functional:
        key = _pair_key(pair)
        if key in annotated and len(selected_keys) < max_candidates:
            selected_keys.add(key)
    for pair in functional:
        key = _pair_key(pair)
        if len(selected_keys) >= min_candidates or len(selected_keys) >= max_candidates:
            break
        if key not in selected_keys:
            selected_keys.add(key)
            annotated[key] = {
                **pair,
                "candidate_reasons": ["top_k_floor"],
                "candidate_override": False,
            }
    return _rank_pairs([annotated[key] for key in selected_keys])


def _candidate_recall_report(
    pairs: list[dict], candidates: list[dict], known_positive_pairs: set[tuple[str, str]],
    known_negative_pairs: set[tuple[str, str]],
) -> dict:
    available = {_pair_key(pair) for pair in pairs if pair.get("relationship") != "parent-child"}
    positives = known_positive_pairs & available
    candidate_keys = {_pair_key(pair) for pair in candidates}
    recalled = positives & candidate_keys
    missed = sorted(positives - candidate_keys)
    total_pairs = len(pairs)
    return {
        "known_positive_total": len(positives),
        "known_positive_recalled": len(recalled),
        "known_positive_missed": [list(pair) for pair in missed],
        "candidate_recall_rate": (len(recalled) / len(positives)) if positives else 1.0,
        "total_pairs": total_pairs,
        "semantic_candidates": len(candidates),
        "candidate_ratio": (len(candidates) / total_pairs) if total_pairs else 0.0,
        "known_negative_candidates": len((known_negative_pairs & available) & candidate_keys),
    }


def _candidate_selection_report(
    pairs: list[dict], candidates: list[dict], threshold: float,
    min_candidates: int, max_candidates: int,
) -> dict:
    functional = [pair for pair in pairs if pair.get("relationship") != "parent-child"]
    return {
        "threshold": threshold,
        "min_candidates": min_candidates,
        "max_candidates": max_candidates,
        "threshold_qualified": sum(_candidate_score(pair) >= threshold for pair in functional),
        "override_selected": sum(bool(pair.get("candidate_override")) for pair in candidates),
        "top_k_floor_selected": sum("top_k_floor" in pair.get("candidate_reasons", []) for pair in candidates),
    }


def build_audit_report(
    pairs: list[dict], top: int = 10, threshold: float = DEFAULT_CANDIDATE_THRESHOLD,
    min_candidates: int = DEFAULT_MIN_CANDIDATES, max_candidates: int = DEFAULT_MAX_CANDIDATES,
    known_positive_pairs: list[tuple[str, str]] | list[list[str]] | None = None,
    known_negative_pairs: list[tuple[str, str]] | list[list[str]] | None = None,
) -> dict:
    """Partition structural links from functional candidates and rank only candidates.

    Candidate score is the sole primary ordering signal. Semantic confidence is
    a tie breaker; a semantic conclusion never changes candidate ordering.
    """
    structural = [pair for pair in pairs if pair.get("relationship") == "parent-child"]
    functional = [pair for pair in pairs if pair.get("relationship") != "parent-child"]
    functional = _rank_pairs(functional)
    structural.sort(key=lambda pair: (pair["skill_a"], pair["skill_b"]))
    high_or_duplicate = [
        pair for pair in functional
        if pair.get("relationship") in {"high-overlap", "duplicate"}
        and not pair.get("warning_suppressed", False)
    ]
    default_positive, default_negative = _load_recall_benchmarks()
    positives = default_positive if known_positive_pairs is None else _normalize_pair_list(known_positive_pairs)
    negatives = default_negative if known_negative_pairs is None else _normalize_pair_list(known_negative_pairs)
    semantic_candidates = select_semantic_candidates(
        pairs, threshold=threshold, min_candidates=min_candidates, max_candidates=max_candidates,
        known_positive_pairs=list(positives),
    )
    return {
        "pairs": functional + structural,
        "top_functional_overlap": functional[:max(0, top)],
        "top_pairs": functional[:max(0, top)],
        "high_or_duplicate_review": high_or_duplicate,
        "high_or_duplicate": high_or_duplicate,
        "structural_relationships": structural,
        "semantic_candidates": semantic_candidates,
        "candidate_recall_report": _candidate_recall_report(pairs, semantic_candidates, positives, negatives),
        "candidate_selection": _candidate_selection_report(
            pairs, semantic_candidates, threshold, min_candidates, max_candidates,
        ),
        "read_only": True,
    }


def audit_profiles(
    profiles: list[dict], top: int = 10, registry: DecisionRegistry | None = None,
    threshold: float = DEFAULT_CANDIDATE_THRESHOLD, min_candidates: int = DEFAULT_MIN_CANDIDATES,
    max_candidates: int = DEFAULT_MAX_CANDIDATES, known_positive_pairs: list[tuple[str, str]] | list[list[str]] | None = None,
    known_negative_pairs: list[tuple[str, str]] | list[list[str]] | None = None,
) -> dict:
    """Produce a read-only report of functional and structural relationships."""
    pairs = [compare_profiles(a, b) for a, b in itertools.combinations(profiles, 2)]
    return build_audit_report(
        attach_decision_status(pairs, registry or DecisionRegistry()), top=top,
        threshold=threshold, min_candidates=min_candidates, max_candidates=max_candidates,
        known_positive_pairs=known_positive_pairs, known_negative_pairs=known_negative_pairs,
    )


def audit_skill_roots(
    roots: list[Path], top: int = 10, threshold: float = DEFAULT_CANDIDATE_THRESHOLD,
    min_candidates: int = DEFAULT_MIN_CANDIDATES, max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> dict:
    """Build profiles from discovered skills and return a read-only audit report."""
    records = discover_skills(roots)
    profiles = []
    for record in records:
        profile = parse_capability_profile(
            Path(record["path"]), parent_skill=record["parent_skill"]
        )
        profile["path"] = record["path"]
        profile["scope"] = record["scope"]
        profile["content_hash"] = record["content_hash"]
        profiles.append(profile)
    report = audit_profiles(
        profiles, top=top, threshold=threshold, min_candidates=min_candidates, max_candidates=max_candidates,
    )
    report["skills_scanned"] = len(profiles)
    return report


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="duplicate_scan.py")
    parser.add_argument("command", choices=["audit"])
    parser.add_argument(
        "--root", action="append", required=True,
        help="Skills root to scan; repeat for every root to include.",
    )
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--candidate-threshold", type=float, default=DEFAULT_CANDIDATE_THRESHOLD)
    parser.add_argument("--min-candidates", type=int, default=DEFAULT_MIN_CANDIDATES)
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    args = parser.parse_args(argv[1:])
    emit_json(audit_skill_roots(
        [Path(root).expanduser() for root in args.root], top=args.top,
        threshold=args.candidate_threshold, min_candidates=args.min_candidates,
        max_candidates=args.max_candidates,
    ))


if __name__ == "__main__":
    main(sys.argv)
