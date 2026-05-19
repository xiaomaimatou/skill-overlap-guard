# skills-manager

English | [简体中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB.svg)](https://www.python.org/)
[![GitHub](https://img.shields.io/badge/GitHub-EfanWang%2Fskills--manager-181717.svg)](https://github.com/EfanWang/skills-manager)

`skills-manager` is a simple, practical skill manager for the `SKILL.md` ecosystem. It scans sibling skills under the current skills root, records where each skill came from, and helps agents list skills, trace sources, check updates, update skills, install skills, and delete skills.

It works with any agent that supports `SKILL.md`:

| Agent | Support |
|---|---|
| [Claude Code](https://code.claude.com/docs/en/skills) | Supports skills directories |
| [Cursor](https://cursor.com/changelog/2-4) | Supports skills in 2.4+ |
| [Codex CLI](https://developers.openai.com/codex/skills) | Supports Codex skills |

## Why use it

Once you install multiple skills in the same environment, a few common questions appear quickly:

- Which skills are currently installed?
- Which GitHub repository did a skill come from?
- Are there upstream updates available?
- Will a manual update overwrite local files?
- How should an unknown-source skill be maintained?

`skills-manager` solves these problems with a lightweight `sources.json` registry. It manages only sibling skills under its own parent directory and does not aggregate inventories across Claude Code, Cursor, Codex CLI, or other tools. This keeps its behavior explicit and its scope controlled.

## Features

| Feature | Description |
|---|---|
| Skill inventory | Scan sibling skill directories and list name, type, description, and status |
| Source tracing | Analyze local evidence for unknown-source skills and hand unresolved cases to the agent for web search |
| Update checks | Check registered GitHub-backed skills against upstream |
| Skill updates | Pull the latest upstream version and create a backup before replacement |
| Skill installation | Clone a skill from a GitHub URL, place it atomically, and register its source |
| Skill deletion | Create an automatic backup before removal for manual recovery |

## Installation

Clone this repository into your skills root:

```bash
cd ~/.claude/skills          # or your agent's skills root
git clone https://github.com/EfanWang/skills-manager.git
```

Common skills roots:

| Agent | Typical skills root |
|---|---|
| Claude Code | `~/.claude/skills/` or project `.claude/skills/` |
| Cursor | `~/.cursor/skills/` or project `.cursor/skills/` |
| Codex CLI | `~/.codex/skills/` or `~/.agents/skills/` |

The skill is ready immediately. Runtime requirements:

- Python 3.9+
- `git` available in PATH

## Quick start

List all skills and check whether remote skills have updates:

```powershell
python scripts/inventory.py --check-remote --audit-unclaimed
```

Check a single remote skill against upstream:

```powershell
python scripts/check_remote.py my-skill
```

Update an outdated skill:

```powershell
python scripts/update_skill.py my-skill
```

Install a skill from GitHub:

```powershell
python scripts/install_skill.py https://github.com/user/repo/tree/main/skills/my-skill
```

## Runtime notes

The first full inventory and source audit may take longer because `skills-manager` traverses every sibling skill under the current skills root and attempts to create or complete source records in `sources.json`. After those records are established, later inventory scans and update checks are usually faster.

## Command reference

All scripts live in `scripts/` and output JSON to stdout. Errors go to stderr and use structured exit codes:

| Exit code | Meaning |
|---|---|
| 2 | Bad input |
| 3 | Corrupted `sources.json` |
| 4 | Remote operation failed |
| 5 | Filesystem replacement failed |

| Script | Purpose |
|---|---|
| `inventory.py [--check-remote] [--audit-unclaimed]` | Scan and classify all sibling skills |
| `audit_unclaimed.py [--dry-run]` | Batch-identify unclaimed skill sources |
| `check_remote.py <name>` | Check a single remote skill against upstream |
| `update_skill.py <name> [--dry-run]` | Pull the latest upstream version via clone and atomic swap |
| `install_skill.py <url> [--name N] [--branch B]` | Clone, install atomically, and register source |
| `sources.py list\|remove\|claim-local\|claim-remote` | Manage `sources.json` entries |
| `similarity.py <local.md> <remote.md>` | Compare two `SKILL.md` files for similarity |

## Status model

Each skill is classified into one of three types:

| Type | Meaning | Update-checkable |
|---|---|---|
| `remote` | Has a GitHub source registered in `sources.json` | Yes |
| `local` | Marked by the user as private or self-authored | No, always treated as current |
| `unclaimed` | Source is unknown and not yet traced | No |

Inventory statuses include:

| Status | Meaning |
|---|---|
| `up_to_date` | Local revision matches upstream HEAD |
| `update_available` | Upstream has newer commits |
| `unknown` | Cannot determine, usually because the skill is unclaimed or a network error occurred |

## Source tracing workflow

`skills-manager` uses layered evidence to determine where a skill came from:

1. **Read `.git/config`**: If the skill directory is itself a Git checkout, read its remote URL directly.
2. **Inspect GitHub URLs in `SKILL.md`**: If the file contains a GitHub link, treat it as an explicit source hint and verify it with a similarity check.
3. **Hand off to agent web search**: For unresolved skills, the script emits a `search_query_hint` so the agent can use web search to evaluate candidate sources. This step requires network access.

After identifying a source, register it manually:

```powershell
# Remote skill from GitHub
python scripts/sources.py claim-remote my-skill --url https://github.com/owner/repo --branch main --subpath skills/my-skill

# Local or private skill
python scripts/sources.py claim-local my-skill
```

## Safety design

- **Non-destructive by default**: `audit_unclaimed.py` only writes to `sources.json`; it does not modify skill files.
- **Automatic backups**: Install, update, delete, and other replacement operations create backups under `.backup/`.
- **Atomic replacement**: Directory replacement uses rename-based swaps to reduce the risk of broken partial state.
- **Manual recovery**: Backup paths look like `.backup/<name>-<timestamp>-<uuid>/` and can be moved back manually.
- **No telemetry**: No analytics and no telemetry. Network access is limited to `git ls-remote` and raw file fetches used for verification.
- **Minimal scope**: Only sibling skill directories are managed. Plugin caches, Cursor built-in skills, and files outside the skills root are untouched.

## Limitations

- Only GitHub is supported as a remote source; GitLab, zip URLs, npm, and other sources are not supported
- Local edits are not detected or merged; updates replace the directory with the upstream version after creating a backup
- Cursor's built-in `skills-cursor/` directory is not managed
- Plugin-managed skills such as `~/.claude/plugins/cache/...` are not managed

## Development

Run tests:

```powershell
python -m unittest tests.test_contract
```

Project structure:

```text
skills-manager/
|-- SKILL.md               # Agent-facing skill instructions
|-- sources.json           # Registry of known skill sources
|-- scripts/
|   |-- _common.py         # Shared utilities
|   |-- inventory.py       # List and classify skills
|   |-- audit_unclaimed.py # Batch source identification
|   |-- check_remote.py    # Check single skill against upstream
|   |-- update_skill.py    # Update to latest upstream
|   |-- install_skill.py   # Install from GitHub
|   |-- sources.py         # sources.json CRUD
|   `-- similarity.py      # SKILL.md file comparison
|-- tests/
|   `-- test_contract.py
|-- .backup/               # Auto-created backups, gitignored
`-- .tmp/                  # Temporary files, gitignored
```

## Getting help

If source identification is incorrect, an update fails, or script output is unexpected, open an issue at [EfanWang/skills-manager](https://github.com/EfanWang/skills-manager) with the relevant command, JSON output, and error message.

## License

MIT
