"""Held-out, read-only Candidate Recall validation for one incoming skill at a time."""
from __future__ import annotations

from duplicate_scan import compare_profiles, select_semantic_candidates


POSITIVE_RELATIONSHIPS = {"high-overlap", "duplicate"}


def run_blind_recall(
    cases: list[dict], installed_profiles: list[dict], *, threshold: float = 0.25,
    min_candidates: int = 5, max_candidates: int = 10,
) -> dict:
    """Validate held-out incoming skills without consulting known-positive benchmarks.

    Each case provides a real-shaped candidate profile plus a manually reviewed
    expected overlap and relationship. This function measures candidate recall;
    it does not infer or replace the semantic conclusion.
    """
    results: list[dict] = []
    for case in cases:
        candidate = case["candidate"]
        expected_skill = case["expected_overlap_skill"]
        expected_relationship = case["expected_relationship"]
        pairs = [compare_profiles(candidate, installed) for installed in installed_profiles]
        # Deliberately disable the project benchmark: these pairs are held out.
        selected = select_semantic_candidates(
            pairs, threshold=threshold, min_candidates=min_candidates,
            max_candidates=max_candidates, known_positive_pairs=[],
        )
        target_key = frozenset((candidate["name"], expected_skill))
        target = next(pair for pair in pairs if frozenset((pair["skill_a"], pair["skill_b"])) == target_key)
        selected_target = next(
            (pair for pair in selected if frozenset((pair["skill_a"], pair["skill_b"])) == target_key),
            None,
        )
        rank = next((index for index, pair in enumerate(selected, start=1) if pair is selected_target), None)
        results.append({
            "candidate_skill": candidate["name"],
            "installed_skill_count": len(installed_profiles),
            "semantic_candidate_count": len(selected),
            "candidate_ratio": len(selected) / len(installed_profiles) if installed_profiles else 0.0,
            "expected_overlap_skill": expected_skill,
            "expected_relationship": expected_relationship,
            "candidate_rank": rank,
            "candidate_score": target["candidate_score"],
            "candidate_override": bool(selected_target and selected_target.get("candidate_override")),
            "candidate_reasons": selected_target.get("candidate_reasons", []) if selected_target else [],
            "semantic_relationship": expected_relationship,
            "semantic_confidence": case.get("semantic_confidence"),
            "recalled": selected_target is not None,
        })

    positives = [result for result in results if result["expected_relationship"] in POSITIVE_RELATIONSHIPS]
    recalled = [result for result in positives if result["recalled"]]
    top_5 = [result for result in positives if result["candidate_rank"] is not None and result["candidate_rank"] <= 5]
    top_10 = [result for result in positives if result["candidate_rank"] is not None and result["candidate_rank"] <= 10]
    total_pairs = sum(result["installed_skill_count"] for result in results)
    semantic_candidate_count = sum(result["semantic_candidate_count"] for result in results)
    return {
        "benchmark_used": False,
        "held_out_total": len(results),
        "held_out_positive_total": len(positives),
        "held_out_positive_recalled": len(recalled),
        "held_out_positive_missed": [result["candidate_skill"] for result in positives if not result["recalled"]],
        "held_out_recall_rate": len(recalled) / len(positives) if positives else 1.0,
        "top_5_recall": len(top_5) / len(positives) if positives else 1.0,
        "top_10_recall": len(top_10) / len(positives) if positives else 1.0,
        "override_recalled_count": sum(result["candidate_override"] for result in recalled),
        "normal_score_recalled_count": sum(not result["candidate_override"] for result in recalled),
        "total_pairs": total_pairs,
        "semantic_candidate_count": semantic_candidate_count,
        "candidate_ratio": semantic_candidate_count / total_pairs if total_pairs else 0.0,
        "cases": results,
    }
