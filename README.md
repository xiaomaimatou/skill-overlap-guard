# skills-manager

An agent-assisted source tracing skill that manages sibling skills installed
under the same skills root directory. Works with any agent that supports
`SKILL.md`:

- [Claude Code](https://code.claude.com/docs/en/skills)
- [Cursor](https://cursor.com/changelog/2-4) (2.4+)
- [Codex CLI](https://developers.openai.com/codex/skills)

## What it does

`skills-manager` scans its own parent directory, discovers sibling skill
folders (each containing a `SKILL.md`), and tracks where they came from via a
lightweight `sources.json` registry. It can:

- **List** all installed skills with update status
- **Check** whether remote (GitHub) skills are outdated
- **Install** new skills from GitHub URLs
- **Update** skills to the latest upstream commit
- **Delete** skills (with automatic backup)
- **Trace sources** for skills whose origin is unknown

## Installation model

Each `skills-manager` instance manages only the skills in its own parent
directory. It does **not** aggregate skills across agents.

If you use multiple agents and want independent inventories, install a separate
copy in each agent's skills root:

| Agent | Typical skills root |
|---|---|
| Claude Code | `~/.claude/skills/` or project `.claude/skills/` |
| Cursor | `~/.cursor/skills/` or project `.cursor/skills/` |
| Codex CLI | `~/.codex/skills/` or `~/.agents/skills/` |

### Install

Clone or copy this directory into your skills root:

```bash
cd ~/.claude/skills          # or your agent's skills root
git clone https://github.com/fan18817202997/skills-manager.git
```

The skill is ready immediately — no dependencies beyond Python 3.9+ and `git`.

## Quick start

List all skills and check for updates:

```powershell
python scripts/inventory.py --check-remote --audit-unclaimed
```

Install a skill from GitHub:

```powershell
python scripts/install_skill.py https://github.com/user/repo/tree/main/skills/my-skill
```

Update an outdated skill:

```powershell
python scripts/update_skill.py my-skill
```

## Commands

| Script | Purpose |
|---|---|
| `inventory.py [--check-remote] [--audit-unclaimed]` | Scan and classify all sibling skills |
| `check_remote.py <name>` | Check a single remote skill against upstream |
| `install_skill.py <url> [--name N] [--branch B]` | Clone, install atomically, and register source |
| `update_skill.py <name> [--dry-run]` | Pull latest upstream via clone + atomic swap |
| `audit_unclaimed.py [--dry-run]` | Batch-identify unclaimed skill origins |
| `sources.py list\|remove\|claim-local\|claim-remote` | Manage sources.json entries |
| `similarity.py <local.md> <remote.md>` | Compare two SKILL.md files for similarity |

All scripts output JSON to stdout. Errors go to stderr with structured exit
codes (2 = bad input, 3 = sources.json corrupt, 4 = remote failure, 5 =
filesystem failure).

## Status meanings

Each skill is classified into one of three types:

| Type | Meaning | Update-checkable? |
|---|---|---|
| **remote** | Has a registered GitHub source in `sources.json` | Yes |
| **local** | User-marked as private/self-authored | No (always current) |
| **unclaimed** | Origin unknown, not yet traced | No |

Status indicators returned by inventory:

| Status | Meaning |
|---|---|
| `up_to_date` | Local revision matches upstream HEAD |
| `update_available` | Upstream has newer commits |
| `unknown` | Cannot determine (unclaimed or network error) |

## Source tracing workflow

`skills-manager` uses a layered evidence approach to identify where skills
came from:

1. **Gate 1 — `.git/config`** (offline): If the skill directory is a git
   checkout, read its remote URL directly.
2. **Gate 2 — Embedded GitHub URL** (offline): If `SKILL.md` contains a GitHub
   URL, treat it as an explicit source hint and verify via similarity check.
3. **Gate 3 — Agent web search** (online): For unresolved skills, the script
   emits a `search_query_hint` that the hosting agent uses with its own web
   search capability.

Scripts handle only deterministic local evidence (Gates 1–2). Open-world search
(Gate 3) is delegated to the agent, which can evaluate context, distinguish
official sources from mirrors, and ask the user when ambiguous.

Once a source is identified, register it:

```powershell
# Remote skill from GitHub
python scripts/sources.py claim-remote my-skill --url https://github.com/owner/repo --branch main --subpath skills/my-skill

# Local/private skill
python scripts/sources.py claim-local my-skill
```

## Safety model

- **Non-destructive by default**: `audit_unclaimed.py` only writes to
  `sources.json` (not skill files). Install and update create backups under
  `.backup/` before any swap.
- **Atomic operations**: File replacements use rename-based swaps so partial
  failures don't leave broken state.
- **Reversible**: Every destructive action produces a timestamped backup in
  `.backup/<name>-<timestamp>-<uuid>/`. Undo by moving it back.
- **No telemetry**: No analytics, no network calls beyond `git ls-remote` and
  raw file fetches for verification.
- **Minimal scope**: Only manages sibling directories. Does not touch
  plugin-managed skills, Cursor built-in skills, or files outside the skills
  root.

### Limitations

- Only supports GitHub as a remote source (no GitLab, zip URLs, npm, etc.)
- Does not detect or merge local edits — updating replaces the directory
- Does not manage Cursor's built-in skills (`skills-cursor/`)
- Does not touch plugin-managed skills (`~/.claude/plugins/cache/...`)

## Development

### Prerequisites

- Python 3.9+
- `git` in PATH

### Running tests

```powershell
python -m unittest tests.test_contract
```

### Project structure

```
skills-manager/
├── SKILL.md            # Agent-facing skill instructions
├── sources.json        # Registry of known skill sources
├── scripts/
│   ├── _common.py      # Shared utilities
│   ├── inventory.py    # List and classify skills
│   ├── check_remote.py # Check single skill against upstream
│   ├── install_skill.py# Install from GitHub
│   ├── update_skill.py # Update to latest upstream
│   ├── audit_unclaimed.py # Batch source identification
│   ├── sources.py      # sources.json CRUD
│   └── similarity.py   # SKILL.md file comparison
├── tests/
│   └── test_contract.py
├── .backup/            # Auto-created backups (gitignored)
└── .tmp/               # Temporary files (gitignored)
```

## License

MIT
