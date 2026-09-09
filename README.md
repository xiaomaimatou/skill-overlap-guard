# Skill Overlap Guard

English · [简体中文](README.zh-CN.md)

> Add a semantic deduplication gate to Agent Skill installation: check whether a new Skill is already covered before deciding whether to proceed.

**Current release: v0.2.0**

Skill Overlap Guard is a local tool for users of Codex, Claude Code, Cursor, and other Agent Skills runtimes. It inventories installed Skills, builds capability profiles, identifies duplicate or partial overlap, and records explicit user decisions.

## V0.2: Pre-install Decision Assistant

V0.2 automatically starts a read-only Pre-install Check when an Agent Skill installation intent is detected. Security Risk and Overlap are calculated independently, and Security Risk has the highest veto priority.

The scanner only reads candidate files and never executes candidate Skill code. V0.2 does not automatically delete, merge, replace, disable, or overwrite existing Skills. Managed Installation and rollback remain V0.3 scope.

## Contents

- [Why](#why)
- [Core capabilities](#core-capabilities)
- [Installation](#installation)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Scan scope](#scan-scope)
- [Safety boundaries](#safety-boundaries)
- [Known limitations](#known-limitations)
- [Development and tests](#development-and-tests)
- [License](#license)

## Why

Skill names do not reliably describe their real capabilities. Two differently named Skills may do the same job, while a parent Skill and one of its children may be related structurally without being duplicates.

Skill Overlap Guard turns installation checks into an explainable decision flow:

- inventory installed Skills;
- compare capabilities, triggers, workflows, inputs, and outputs instead of names alone;
- distinguish `HIGH`, `partial`, `complementary`, and `parent-child` relationships;
- pause by default when a new Skill has high overlap;
- retain explicit keep, ignore, or preference decisions for later reports.

## Core capabilities

| Capability | Description |
| --- | --- |
| Inventory | Recursively discover Skills, parent-child relationships, sources, and remote update status. |
| Capability Profile | Extract capabilities, triggers, workflows, inputs, outputs, tools, and dependencies from `SKILL.md`. |
| Overlap Audit | Recall candidate pairs and produce explainable semantic overlap reports. |
| Automatic Pre-install Check | Detect install intent and run a read-only pre-install analysis automatically. |
| Skill Health Score | Score responsibility clarity, structure, scope, dependencies, and source metadata. |
| Best Skill Recommendation | Recommend `prefer_skill_a`, `prefer_skill_b`, `keep_both`, or `manual_review` without destructive action. |
| Trigger / Description Conflict | Detect broad or competing descriptions and trigger scopes. |
| Generalist vs Specialist | Distinguish shared scope from specialist-specific value. |
| Security Precheck | Report prompt injection, dangerous commands, sensitive access, exfiltration, hooks, and path risks. |
| Unified Decision Report | Combine Functional, Trigger, Health, Security, and Source evidence. |
| Source / Commit Metadata | Surface repository, branch, commit, manifest, hashes, and scanner cache evidence. |
| Dedup Gate | Warn and pause on `HIGH` / `DUPLICATE` relationships without deciding for the user. |
| Decision Registry | Store explicit decisions in `decisions.json`. |
| Terminal Guard | Optionally intercept `npx skills add` for a reversible dry-run check. |

## Installation

Clone the repository alongside the Skills root used by your Agent runtime:

```bash
git clone https://github.com/xiaomaimatou/skill-overlap-guard.git
```

Requirements:

- Python 3.9+;
- `git` available on `PATH`;
- read access to the target Skills root;
- GitHub network access for remote source and version checks.

After installation in Codex, invoke it explicitly when needed:

```text
$skill-overlap-guard install this skill https://github.com/owner/repo
```

## Quick start

Inventory Skills and check remote status:

```bash
python scripts/inventory.py --check-remote --audit-unclaimed
```

Read-only preview:

```bash
python scripts/inventory.py --check-remote
```

Audit the installed inventory:

```bash
python scripts/duplicate_scan.py audit --top 10
```

Enable the optional Terminal Guard:

```bash
python scripts/terminal_guard.py enable
python scripts/terminal_guard.py status
python scripts/terminal_guard.py disable
```

Record an explicit decision:

```bash
python scripts/decision_registry.py set \
  skill-a skill-b keep_both \
  --relationship complementary \
  --reason "Different responsibilities; keep both"
```

The available decisions are `keep_both`, `ignore`, `preferred_a`, `preferred_b`, `manual_review`, and `pending`.

## How it works

```text
Install Intent
    ↓
Read-only candidate load
    ↓
Security / Overlap / Trigger / Health / Source checks
    ↓
Unified Decision Report
    ↓
User decision
```

Security Risk has the highest veto priority and cannot be reduced by a low-overlap result. The report remains advisory: it does not automatically delete, merge, replace, or disable an existing Skill.

## Scan scope

Default roots:

```text
~/.agents/skills/
~/.codex/skills/
<current project>/.agents/skills/
```

Excluded by default:

```text
~/.codex/skills/.system/
.backup/
.tmp/
cache and temporary download directories
```

Each Skill is a directory containing `SKILL.md`. Nested Skills are discovered recursively, with `parent_skill` and `children` metadata preserved.

## Safety boundaries

- Scanning and overlap analysis are local by default;
- Terminal Guard is opt-in and reversible;
- decision updates only write `decisions.json`;
- no automatic deletion, merge, replacement, or disabling;
- remote checks apply only to registered remote Skills;
- only use trusted Skill sources, especially when your Agent has logged-in access to external services.

## Known limitations

- V0.2 does not take over the final installation transaction;
- Managed Installation and rollback are planned for V0.3;
- security scanning can identify risk signals but cannot prove absolute safety;
- local edits are not merged automatically;
- plugin-managed and Cursor built-in Skills are outside the default scan scope;
- incomplete or very short `SKILL.md` files may produce `uncertain` results;
- one instance scans its own Skills root and does not automatically aggregate Claude Code, Cursor, and Codex roots.

## Development and tests

Run the test suite from this directory:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

```text
scripts/      inventory, overlap, source, decision, and Terminal Guard logic
tests/        144 tests passed; V0.1 regression and V0.2 tests included
decisions.json explicit user decisions
example*.png  usage examples
```

The V0.1 regression suite remains passing.

## Credits

Based on / derived from [EfanWang/skills-manager](https://github.com/EfanWang/skills-manager).

## License

MIT License. See [LICENSE](LICENSE).
