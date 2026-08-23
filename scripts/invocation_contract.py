"""Read-only trigger and source-resolution contract for Skill Manager."""
from __future__ import annotations

import re

from decision_registry import DecisionRegistry
from duplicate_scan import attach_decision_status, compare_profiles, select_semantic_candidates


GITHUB_URL_RE = re.compile(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", re.IGNORECASE)
RAW_GITHUB_URL_RE = re.compile(
    r"https?://raw\.githubusercontent\.com/([^/\s]+)/([^/\s]+)/[^/\s]+/(?:[^\s]*/)?SKILL\.md", re.IGNORECASE,
)
SHORTHAND_RE = re.compile(r"(?<![\w/.-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?![\w/.-])")
LOCAL_PATH_RE = re.compile(r"(?<!\w)((?:~|\.)?/[\w./-]+)")


def dedup_status_for_relationship(relationship: str) -> str:
    """Map a completed semantic result to a report-only install-readiness state."""
    if relationship in {"duplicate", "high-overlap"}:
        return "blocked_pending_confirmation"
    if relationship == "partial-overlap":
        return "warning"
    if relationship in {"complementary", "unrelated", "parent-child"}:
        return "clear"
    return "not_started"


def build_dedup_context(
    request: dict, candidate_profile: dict, installed_profiles: list[dict], *,
    threshold: float = 0.25, min_candidates: int = 5, max_candidates: int = 10,
    known_positive_pairs: list[tuple[str, str]] | list[list[str]] | None = None,
    registry: DecisionRegistry | None = None,
) -> dict:
    """Join a classified install request to the existing read-only dedup chain.

    `candidate_profile` must come from an already-resolved source.  This helper
    deliberately does not download, install, or change either source or
    installed Skill.  It queues bounded L0 candidates for existing semantic
    review and exposes decision context for reporting only.
    """
    if request.get("intent") != "install_skill" or not request.get("dedup_required"):
        raise ValueError("dedup context requires an install_skill request")
    if not request.get("source", {}).get("source_type"):
        return {
            **request,
            "semantic_review_queue": [],
            "recommendation_status": "not_started",
            "decision_context": [],
            "install_performed": False,
        }

    pairs = [compare_profiles(candidate_profile, profile) for profile in installed_profiles]
    # Pre-install candidates must arise from generic parser/normalizer signals,
    # not previously memorized installed-pair benchmarks.
    candidates = select_semantic_candidates(
        pairs, threshold=threshold, min_candidates=min_candidates, max_candidates=max_candidates,
        known_positive_pairs=[] if known_positive_pairs is None else known_positive_pairs,
    )
    contextualized = attach_decision_status(candidates, registry or DecisionRegistry())
    return {
        **request,
        "semantic_review_queue": contextualized,
        "recommendation_status": "pending_semantic_review",
        "decision_context": [
            {
                "skill_a": pair["skill_a"], "skill_b": pair["skill_b"],
                "decision_status": pair["decision_status"], "decision": pair["decision"],
                "decision_stale": pair["decision_stale"],
            }
            for pair in contextualized
        ],
        "install_performed": False,
    }


def _source(prompt: str) -> dict:
    raw = RAW_GITHUB_URL_RE.search(prompt)
    if raw:
        repo = f"{raw.group(1)}/{raw.group(2)}"
        return {"source_type": "github", "source": raw.group(0), "repo": repo, "path": "", "requested_skill_name": raw.group(2)}
    github = GITHUB_URL_RE.search(prompt)
    if github:
        repo = f"{github.group(1)}/{github.group(2).removesuffix('.git')}"
        return {"source_type": "github", "source": github.group(0), "repo": repo, "path": "", "requested_skill_name": repo.split("/")[-1]}
    npx = re.search(r"\bnpx\s+skills\s+add\s+([^\s]+)", prompt, re.IGNORECASE)
    if npx:
        source = npx.group(1)
        if source.startswith(("/", "./", "../", "~/")):
            return {"source_type": "local_path", "source": source, "repo": "", "path": source, "requested_skill_name": source.rstrip("/").split("/")[-1]}
        match = SHORTHAND_RE.search(source)
        repo = match.group(1) if match else ""
        return {"source_type": "github_shorthand", "source": source, "repo": repo, "path": "", "requested_skill_name": repo.split("/")[-1] if repo else source}
    shorthand = SHORTHAND_RE.search(prompt)
    if shorthand:
        repo = shorthand.group(1)
        return {"source_type": "github_shorthand", "source": repo, "repo": repo, "path": "", "requested_skill_name": repo.split("/")[-1]}
    local_path = LOCAL_PATH_RE.search(prompt)
    if local_path:
        path = local_path.group(1)
        return {"source_type": "local_path", "source": path, "repo": "", "path": path, "requested_skill_name": path.rstrip("/").split("/")[-1]}
    named = re.search(r"(?:安装|install|add)\s+(?:这个\s+|this\s+)?(?:skill|技能)\s+([A-Za-z0-9][A-Za-z0-9_.-]*)", prompt, re.IGNORECASE)
    if named:
        name = named.group(1)
        return {"source_type": "skill_name", "source": name, "repo": "", "path": "", "requested_skill_name": name}
    return {"source_type": "", "source": "", "repo": "", "path": "", "requested_skill_name": ""}


def _skill_context(prompt: str) -> bool:
    lowered = prompt.casefold()
    return any(term in lowered for term in (
        "skill", "技能", "codex", "npx skills add", "install-skill-from-github.py",
    ))


def resolve_request(prompt: str) -> dict:
    """Classify a user request; return instructions only and never install anything."""
    text = str(prompt or "")
    lowered = text.casefold()
    explicit_new = "$skill-overlap-guard" in lowered
    explicit_legacy = "$skill-manager" in lowered
    explicit = explicit_new or explicit_legacy
    trigger_name = "skill-overlap-guard" if explicit_new else "skills-manager"
    source = _source(text)
    install_words = any(term in lowered for term in (
        "安装", "装一下", "装上", "添加", "加这个", "加到", "install", "add skill", "add this skill", "set up this skill",
        "npx skills add", "install-skill-from-github.py",
    ))
    analysis_words = any(term in lowered for term in ("分析", "比较", "重复", "做什么", "值得安装", "inspect", "compare", "duplication", "check"))
    skill_context = _skill_context(text) or bool(source["source_type"] and "github" in source["source_type"] and "skill" in lowered)

    base = {
        "trigger": trigger_name if explicit else None,
        "intent": None,
        "mode": None,
        "source": source,
        "dedup_required": False,
        "dedup_status": "not_started",
        "reason": "",
        "install_performed": False,
    }
    check_request = any(term in lowered for term in ("值得安装", "重复吗", "这个 skill 做什么", "what does this skill do"))
    if check_request and skill_context:
        base.update({"trigger": trigger_name, "intent": "analyze_skill", "mode": "check"})
        return base
    if (install_words and skill_context) or (explicit and install_words):
        base.update({"trigger": trigger_name, "intent": "install_skill", "mode": "install", "dedup_required": True})
        if source["source_type"]:
            base["dedup_status"] = "checking"
        else:
            base.update({"dedup_status": "blocked_pending_confirmation", "reason": "missing_source"})
        return base
    if (analysis_words and skill_context) or explicit:
        base.update({"trigger": trigger_name, "intent": "analyze_skill", "mode": "check" if "值得安装" in lowered else "analysis"})
    return base
