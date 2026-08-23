"""Small, deterministic cross-language concept alias normalizer for recall."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def alias_map() -> dict[str, dict]:
    path = Path(__file__).with_name("concept_aliases.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("concept aliases must be an object")
    return data


def extract_concepts(text: str) -> set[str]:
    """Return canonical concepts whose configured aliases occur in original text."""
    normalized = str(text or "").casefold()
    return {
        concept for concept, metadata in alias_map().items()
        if any(str(alias).casefold() in normalized for alias in metadata.get("aliases", []))
    }


def broad_concepts(concepts: set[str]) -> set[str]:
    aliases = alias_map()
    return {concept for concept in concepts if aliases.get(concept, {}).get("broad", False)}


def specific_concepts(concepts: set[str]) -> set[str]:
    return set(concepts) - broad_concepts(concepts)
