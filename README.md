# Skill Overlap Guard

Skill 防重助手

**Check before you install. Avoid redundant Agent Skills.**

安装前先查重，避免 Skill 越装越重复。

## Why

As your Skill collection grows, it becomes difficult to know whether a new
Skill duplicates capabilities you already have.

## What it does

- Pre-install capability overlap checks
- Overlap audits for installed Skills
- `HIGH` / `partial` / `complementary` judgments
- Chinese-English semantic matching
- Codex natural-language install checks
- Terminal `npx skills add` Guard
- Decision Registry for explicit user decisions

## Safety

- Does not automatically delete Skills
- Does not automatically merge Skills
- Does not automatically replace Skills
- Does not automatically disable Skills
- Changes to installed Skills require explicit user authorization

## Install

Clone the repository into an Agent Skills root:

```bash
git clone https://github.com/EfanWang/skill-overlap-guard.git
```

Runtime requirements: Python 3.9+ and `git`.

## Usage

Codex:

```text
$skill-overlap-guard 安装这个 skill https://github.com/owner/repo
```

Natural language:

```text
安装这个 skill https://github.com/xxx
```

Terminal:

```text
npx skills add owner/repo
```

Terminal Guard is disabled by default. It can be explicitly enabled for a
reversible dry-run check:

```bash
python scripts/terminal_guard.py enable
python scripts/terminal_guard.py status
python scripts/terminal_guard.py disable
```

## How it works

```text
Source
  → Inventory
  → Recall
  → Semantic Review
  → Overlap Warning
  → User Confirmation
```

The v0.1 workflow reports overlap and never installs a Skill before explicit
confirmation.

## Status

v0.1.0 MVP

## Known Limitations

- GitHub is the only supported remote source.
- The v0.1 workflow reports install decisions; it does not perform installs.
- Local edits are not merged automatically.
- Plugin-managed and Cursor built-in Skills are outside the scan scope.

## Credits

Based on / derived from [EfanWang/skills-manager](https://github.com/EfanWang/skills-manager).

This project retains the MIT License and the original author's copyright
notice. See [LICENSE](LICENSE).
