# Skill Overlap Guard

English · [简体中文](README.zh-CN.md)

> Add a semantic deduplication gate to Agent Skill installation: check whether a new Skill is already covered before deciding whether to proceed.

Skill Overlap Guard is a local tool for users of Codex, Claude Code, Cursor, and other Agent Skills runtimes. It inventories installed Skills, builds capability profiles, identifies duplicate or partial overlap, and records explicit user decisions.

## V0.2: Pre-install Decision Assistant

V0.2 automatically starts a read-only Pre-install Check when an Agent Skill installation intent is detected. The unified report keeps functional overlap, generalist/specialist scope, trigger conflicts, Health Score, source/commit evidence, and security signals independent. Security checks include prompt injection, dangerous commands, credential access, exfiltration, install hooks, obfuscation, traversal, and symlink escape.

The scanner only reads candidate files and never executes candidate Skill code. V0.2 does not automatically install, delete, merge, replace, disable, or overwrite Skills. Managed installation and recovery remain V0.3 scope.

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
| Pre-install Check | Compare a new Skill with the installed inventory before installation. |
| Dedup Gate | Warn and pause on `HIGH` / `DUPLICATE` relationships without deciding for the user. |
| Decision Registry | Store explicit decisions in `decisions.json`. |
| Terminal Guard | Optionally intercept `npx skills add` for a reversible dry-run check. |

## Installation

Clone the repository alongside the Skills root used by your Agent runtime:

```bash
git clone https://github.com/EfanWang/skill-overlap-guard.git
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
New Skill source
    ↓
Read SKILL.md / build capability profile
    ↓
Inventory installed Skills / recall candidates
    ↓
Semantic review with parent-child protection
    ↓
Overlap report
    ↓
User confirmation and decision record
```

V0.1 only analyzes, warns, and records decisions. It does not install a new Skill before explicit confirmation, and it never automatically deletes, merges, replaces, or disables an installed Skill.

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

- GitHub is the primary supported remote source in V0.1;
- the V0.1 installation flow reports analysis results rather than automatically installing after the check;
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
tests/        V0.1 behavior tests
decisions.json explicit user decisions
example*.png  usage examples
```

## Credits

Based on / derived from [EfanWang/skills-manager](https://github.com/EfanWang/skills-manager).

## License

MIT License. See [LICENSE](LICENSE).
