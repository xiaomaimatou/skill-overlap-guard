"""Compare two SKILL.md files. Used by the claim wizard.

Usage:
    python similarity.py <local.md> <remote.md>

Output (stdout, JSON):
    {
      "full_ratio": 0.92,
      "first_120_lines_ratio": 0.95,
      "confidence": "high"   // high (both >=0.90), mid (>=0.75), low (else)
    }
"""
from __future__ import annotations

import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from _common import die, emit_json


def normalize(text: str, strip_frontmatter: bool = True) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if strip_frontmatter:
        m = re.match(r"^\s*---\n.*?\n---\n", text, re.DOTALL)
        if m:
            text = text[m.end():]
    return text.strip()


def ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def first_n_lines(text: str, n: int) -> str:
    return "\n".join(text.split("\n")[:n])


def classify(full: float, head: float) -> str:
    if full >= 0.90 and head >= 0.90:
        return "high"
    if full >= 0.75 or head >= 0.75:
        return "mid"
    return "low"


def main(argv: list[str]) -> None:
    if len(argv) != 3:
        die("usage: similarity.py <local.md> <remote.md>", code=2)
    a_path = Path(argv[1])
    b_path = Path(argv[2])
    if not a_path.is_file():
        die(f"not a file: {a_path}", code=2)
    if not b_path.is_file():
        die(f"not a file: {b_path}", code=2)
    a = normalize(a_path.read_text(encoding="utf-8", errors="replace"))
    b = normalize(b_path.read_text(encoding="utf-8", errors="replace"))
    full = ratio(a, b)
    head = ratio(first_n_lines(a, 120), first_n_lines(b, 120))
    emit_json({
        "full_ratio": round(full, 4),
        "first_120_lines_ratio": round(head, 4),
        "confidence": classify(full, head),
    })


if __name__ == "__main__":
    main(sys.argv)
