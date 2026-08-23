# Skill Manager V0.1 — Phase 3.4 validation

## Scope and safety

This phase adds read-only held-out recall validation and request-routing
contracts. It does not download, install, modify, disable, merge, replace, or
delete any managed Skill.

## Blind recall protocol

- Ten held-out incoming `SKILL.md` fixtures are parsed by the normal Capability
  Parser, then each incoming profile is compared with 40 parsed installed
  fixtures (400 one-to-many candidate pairs total).
- Five held-out positives cover title generation, frontend visual refinement,
  content search, subtitles, and video covers. They are Chinese, English, and
  mixed-language cases.
- The remaining cases cover partial overlap, complementary workflow, two
  unrelated work cases, and uncertain evidence.
- Held-out pairs are not in `recall_benchmarks.json`; the runner explicitly
  passes an empty known-positive set to candidate selection. No aliases or
  pair-specific rules were added for this phase.

Result: all five HIGH-overlap positives entered the bounded review set; their
Top-5 and Top-10 recall are both 100%. All five were admitted by generic,
explainable recall overrides, not benchmark injection. Candidate selection was
50/400 (12.5%), or five candidates per incoming profile, well below the cap of
ten. The unrelated and uncertain target pairs were not selected.

## Trigger and invocation contract

`scripts/invocation_contract.py` recognizes explicit `$skill-manager`, Agent
Skill installation intent, GitHub URLs, `owner/repo`, local paths, skill names,
and `npx skills add`. It rejects non-Skill package installations such as Python
and Homebrew. Inspection/comparison requests route to analysis/check mode and
never to install mode.

For install intent, `build_dedup_context` accepts a resolved Capability Profile
and installed profiles, then calls the existing candidate selector, exposes a
bounded semantic-review queue, supplies read-only Decision Registry context,
and marks recommendation as pending semantic review. It has no installer call.

Install request states are report-only:

- `not_started`
- `checking`
- `clear`
- `warning`
- `blocked_pending_confirmation`

Even `blocked_pending_confirmation` and a later `confirmed` result do not
authorize an installation in V0.1.
