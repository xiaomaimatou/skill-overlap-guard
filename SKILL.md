---
name: skills-manager
description: >-
  Manage installed skills in the current sibling directory: list all skills with
  freshness status against their upstream GitHub repos, update outdated ones,
  delete unwanted ones, and claim unknown skills by tracing them back to their
  source on GitHub. Use this skill whenever the user mentions listing skills,
  checking skill updates, "which skills are outdated", updating or refreshing a
  skill, removing or deleting a skill, "I don't remember which skills I
  installed", "which skills do I have", or asks about the freshness/origin/source
  of an installed skill — even when they don't say the word "skills-manager"
  explicitly.
---

# Skills Manager

Manage the **sibling skills** of this directory. The skill scans only its own
parent directory (e.g. `~/.cursor/skills/*`) — never `~/.cursor/skills-cursor/`
(Cursor's built-in skills) or `~/.claude/skills/` (those need a separate
installation).

## Mental model

- Each skill is a sibling directory under `<skills_root>/` containing a
  `SKILL.md`.
- `sources.json` (in this directory) records where each remote skill came from.
  Without a record, a skill is **unclaimed** — we don't know its origin.
- A skill is one of three types:
  - **remote** — has a `url` in `sources.json`; can be checked / updated.
  - **local** — has an empty `{}` record; user marked it as private; skip checks.
  - **unclaimed** — no record at all; user hasn't told us where it came from.

## When to trigger (and what to run)

### Scenario A: list skills (and show update status)

Triggers: "list my skills", "what skills do I have", "show skills", "which
skills are outdated", "check for updates".

Run full inventory by default. This keeps the list command ergonomic: if the
first cheap scan finds unclaimed skills, inventory runs the source audit once,
writes high-confidence claims, and returns the final post-audit table data.

```powershell
python <skills-manager>/scripts/inventory.py --check-remote --audit-unclaimed
```

If the user explicitly says "preview only", "just list, don't write", or "no
audit", use the read-only command instead:

```powershell
python <skills-manager>/scripts/inventory.py --check-remote
```

Output shapes:
- Without `--audit-unclaimed`: JSON array of inventory entries.
- With `--audit-unclaimed`: JSON object `{ "entries": [...], "audit": {...} }`.

Parse `entries` (or the bare array for read-only output) and render as a Chinese
markdown table:

| Skill名称 | 类型 | 功能描述 | 状态 |
|---|---|---|---|
| brainstorming | Git | ... | 最新 / 过期 |
| my-private | 本地 | ... | 本地 |
| unknown-thing | 未知 | ... | 未知 |

Output contract: always render all four columns exactly: `Skill名称`, `类型`,
`功能描述`, `状态`. Do not omit `功能描述` to make the answer shorter, even on
repeat list requests, after source-audit follow-ups, or when every skill has a
known source. Use the inventory JSON `description` field for `功能描述`.

Display mappings:
- Type: `remote` → `Git`; `local` → `本地`; `unclaimed` → `未知`.
- Status: `up_to_date` → `最新`; `update_available` → `过期`;
  `local` → `本地`; `unclaimed` / `unknown` / `error` / `null` → `未知`.

After the table, summarize in Chinese: "共 X 个，最新 Y 个，过期 Z 个，本地
W 个，未知 V 个". If `audit.ran` is true, also summarize how many were
auto-claimed, need review, or had no match. Offer next steps: "要更新过期项吗？
要处理需确认/未识别的来源吗？"

If the user later asks something like "just show me the ones with updates",
re-filter the same JSON output — do **not** re-run inventory.

### Scenario B: update skill(s)

Triggers: "update X", "update all outdated", "refresh brainstorming", "pull
latest".

1. If user said "all outdated", first run inventory `--check-remote` to find
   them.
2. List the target skills back to the user for confirmation (destructive
   action).
3. For each, run:
   ```powershell
   python <skills-manager>/scripts/update_skill.py <name>
   ```
4. Each successful update writes a backup under `.backup/<name>-<ts>-<uuid>/`.
   Report the backup path in your summary so the user can roll back manually.

### Scenario D: install a new skill from GitHub

Triggers: "install X from <github url>", "add this skill: <url>", "下载这个
skill: <url>", or any time the user hands over a GitHub URL and asks you to set
it up locally.

**Always go through `install_skill.py`. Do not `git clone` manually** — the
script bundles cloning, atomic placement, and `sources.json` registration so
the skill is correctly tracked from day one.

```powershell
python <skills-manager>/scripts/install_skill.py <github-url> [--name <override>]
```

Accepted URL forms (the script normalizes all of these):
- `https://github.com/<owner>/<repo>` (only valid if SKILL.md is at the repo root)
- `https://github.com/<owner>/<repo>/tree/<branch>/<subpath>`
- `https://github.com/<owner>/<repo>/blob/<branch>/<subpath>/SKILL.md`
- `https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<subpath>/SKILL.md`
- `git@github.com:<owner>/<repo>.git`

Defaults and behavior worth knowing:
- Skill name defaults to `name` in the upstream SKILL.md frontmatter. Pass
  `--name` to override (useful when names collide).
- Branch defaults to the repo's default branch (auto-detected via
  `ls-remote --symref`). Pass `--branch` if the URL omits it AND the default
  is wrong, or if the branch name contains `/`.
- If a skill with the resolved name already exists, the existing copy is moved
  to `.backup/<name>-<ts>-<uuid>/` before installing. Report this path back to
  the user.
- On any failure after the swap, the script tries to roll back. If rollback
  also fails, it surfaces both error strings — pass them to the user verbatim.

Confirm with the user before installing (destructive if it overwrites an
existing skill). After success, summarize: name, source repo, installed
revision, backup path (if any).

### Scenario C: delete a skill

Triggers: "delete X", "remove X", "uninstall X".

This is destructive; do **not** automate it.

1. Confirm with the user: show the absolute path that will be moved.
2. Backup using PowerShell (same drive, atomic on Windows):
   ```powershell
   $ts = Get-Date -Format yyyyMMdd-HHmmss
   Move-Item <skills_root>/<name> <skills-manager>/.backup/<name>-$ts
   ```
3. Remove the sources.json record (only if it had one):
   ```powershell
   python <skills-manager>/scripts/sources.py remove <name>
   ```
4. Report success and the backup path.

Never edit `sources.json` directly. Always go through `sources.py`.

### Scenario E: audit unclaimed skills (batch)

Triggers: "figure out where all my skills came from", "batch claim unknown
skills", "auto-detect sources for installed skills", or proactively offer when
Scenario A surfaces several `unclaimed` rows.

This is an **agent-assisted source tracing** workflow. The scripts collect
mechanical evidence; the agent decides source identity; `sources.py` registers
confirmed sources. Open-world source search belongs to the agent because it can
use page, repository, owner, README, and search-result context to distinguish
official sources from mirrors, dotfiles, registries, and marketplace copies.

**Default invocation — DO NOT add `--dry-run` unless the user explicitly asks
for a preview.** Audit is not destructive: it only writes `sources.json` for
low-risk evidence (`.git/config` or embedded source URL).
No skill files are touched. Mistakes are reversible (`sources.py remove <name>`
and re-run). Treat audit like `update_skill.py`, not like `install_skill.py` or
delete — no confirmation needed beforehand, just report results afterwards.

```powershell
python <skills-manager>/scripts/audit_unclaimed.py            # collect evidence and auto-claim only trusted/explicit sources
python <skills-manager>/scripts/audit_unclaimed.py --dry-run  # ONLY when user says "先看看不要动" / "preview only"
```

If you (agent) reflexively add `--dry-run` "to be safe", you'll surprise the
user the same way they were surprised before this note was added: the script
will dutifully report high-similarity trusted hits but write nothing.

Per skill the workflow has three gates:

1. **`.git/config` inspection** (offline). If the skill directory is itself a
   git checkout pointing at github.com, claim it with the live branch +
   `rev-parse HEAD`.
2. **SKILL.md local GitHub URL hint**. A GitHub URL written inside the local
   skill is treated as explicit evidence, then verified via raw + similarity.
3. **WebSearch (agent side)**. For unresolved skills, the script emits a
   `search_query_hint`; the agent uses its own web search to find and judge the
   source, then registers confirmed results through `sources.py`.

Confidence rules:
- Trusted/explicit gates (`.git/config`, local GitHub URL hint):
  - `high` (both ratios ≥ 0.90) → auto-claim.
  - `installed_revision` is the upstream HEAD SHA **only when similarity is
    exactly 1.0**. Otherwise it is recorded as `null`, so inventory reports
    `update_available` and `update_skill.py` can re-align it.
- WebSearch:
  - The script does not run WebSearch itself.
  - Agent search results are evidence for source identity, not automatic claims.
  - Once source identity is clear, run `sources.py claim-remote` or
    `sources.py claim-local`.

When `installed_revision` is `null`, both `inventory --check-remote` and
`check_remote.py` surface the skill as `update_available` so the user/agent
is prompted to run `update_skill.py`, which overwrites the local copy with
upstream HEAD and writes the now-correct `installed_revision`. This is the
self-healing path: claim makes a conservative record, update aligns it.

**WebSearch handoff.** Every unresolved report carries a `search_query_hint`
when the local description is long enough. Search with combinations such as:

```text
<skill-name> SKILL.md GitHub
"<title or distinctive phrase>" "SKILL.md"
"<description phrase>" GitHub
```

When reviewing WebSearch results:
1. Prefer official or purpose-built source repos, standard `skills/<name>/`
   paths, and repos whose owner/name clearly match the skill family.
2. Treat dotfiles, `.agents/skills`, `.claude/skills`, registry, marketplace,
   mirror, awesome-list, and ordinary product repos as likely copies.
3. Compare the candidate `SKILL.md` name, description, and opening body against
   the local skill before registering it.
4. Once source identity is clear, run `sources.py claim-remote` with the
   candidate's url/branch/subpath. If multiple candidates still look plausible,
   ask the user instead of guessing.

Output is a JSON `{summary, reports, inventory_after}` payload. Render to the
user as:
- **"已自动登记 K 个"** — show each (name → repo+subpath, source: git_dir /
  embedded_url). These were trusted/explicit matches.
- **"未识别 M 个"** — for each, use `search_query_hint` to run WebSearch (or
  ask the user directly). Once you have a source, **agent runs
  `sources.py claim-remote`** (if from GitHub) or `sources.py claim-local`
  (if user-authored). Do not re-run audit expecting WebSearch to write records.
- Then re-render the Scenario A table from `inventory_after` so the user sees
  the new state in one shot — no need to invoke `inventory.py` separately.
  (`inventory_after` is `null` when `--dry-run` is used, because sources.json
  wasn't modified and a fresh inventory would just repeat the pre-audit state.)

See the "Claim wizard" section below for the exact `sources.py claim-remote
/ claim-local` parameter syntax — it's the single source of truth for those
commands.

**Important:** the script never auto `claim-local`. If a skill matched no
upstream, surface it to the user and ask if it's their own work.

## Claim wizard (handling unclaimed skills)

Triggers: "claim unknown skills", "I want to know where my skills came from",
"set up update tracking for all skills", or proactively offer it when the user
sees many `unclaimed` rows in scenario A.

For each unclaimed skill, in order:

1. **Read its SKILL.md** (first ~60 lines). Note name + description + style.

2. **Search GitHub**. Try in this order:
   - If `gh` CLI is installed:
     ```powershell
     gh api -X GET search/code -f q='filename:SKILL.md "<distinctive phrase from description>"'
     ```
   - Otherwise use `WebSearch` for `"<skill name>" SKILL.md github`.

3. **Compare**. For top 1–3 candidates, fetch the raw SKILL.md (use `WebFetch`
   or `curl`), save to `<skills-manager>/.tmp/<uuid>-candidate.md`, then:
   ```powershell
   python <skills-manager>/scripts/similarity.py <skills_root>/<skill>/SKILL.md <skills-manager>/.tmp/<uuid>-candidate.md
   ```

4. **Decide** based on `confidence`:
   - `high` → tell the user: "I'm confident this is from `<repo>/<subpath>`. OK
     to register?"
   - `mid` → present candidates with ratios, ask user to pick.
   - `low` → ask: "Is this skill written by you (not from GitHub)? Or do you
     remember the source URL?"

5. **Register**. Once user confirms:
   ```powershell
   # From GitHub
   python <skills-manager>/scripts/sources.py claim-remote <name> \
       --url <repo-url> --branch <branch> --subpath <subpath-in-repo>

   # User-authored / private
   python <skills-manager>/scripts/sources.py claim-local <name>
   ```

   `claim-remote` fetches upstream SKILL.md and compares it to local before
   recording `installed_revision`:
   - byte-equal → records the real HEAD SHA returned by `git ls-remote`
   - any difference → records `installed_revision = null` and emits a
     `verify_note` explaining the similarity ratio
   Pass `--no-resolve --assume-revision <sha>` to skip the verification
   (offline / scripted scenarios); the caller is then responsible for the
   honesty of the recorded SHA.

   A `null` revision is **not** an error: it's the honest "I know the source
   repo but not which commit your local copy corresponds to" state, which
   inventory surfaces as `update_available` and `update_skill.py` resolves by
   overwriting local with HEAD.

6. **Common upstreams seen in practice** (use as a hint, not a rule):
   - `obra/superpowers` — skills under `skills/<name>/` on `main` branch.
     Includes brainstorming, writing-plans, executing-plans,
     systematic-debugging, web-access, etc.
   - `thedotmack/claude-mem` plugin — skills already managed by the plugin
     mechanism; do **not** claim these as remote (let the plugin manage them).
   - Cursor official skills live in `skills-cursor/`, not `skills/`, so they
     never appear in our scans.

## Script contract reference

All scripts live in `scripts/`. All output JSON to stdout. Errors go to stderr
with non-zero exit codes (2 = bad input, 3 = sources.json corrupted, 4 = remote
failure, 5 = filesystem failure during swap).

| Script | Purpose |
|---|---|
| `inventory.py [--check-remote]` | Scan + classify all sibling skills. |
| `check_remote.py <name>` | ls-remote a single claimed-remote skill. |
| `install_skill.py <url> [--name N] [--branch B]` | Clone + atomic install + auto-register. |
| `update_skill.py <name> [--dry-run]` | Clone + atomic swap. |
| `audit_unclaimed.py [--dry-run]` | Batch identify unclaimed skills: `.git/` + local GitHub URL hints; unresolved items get WebSearch hints. |
| `sources.py list \| remove \| claim-local \| claim-remote` | Mutate sources.json safely. |
| `similarity.py <local.md> <remote.md>` | difflib-based file similarity for claim wizard. |

## Failure modes worth knowing

- **`sources.json` corrupt** → every script refuses to run. Show the parse
  error to the user; tell them to fix the file or restore from `.tmp/` backup.
- **`git ls-remote` fails** (network, private repo, dead URL) → status is shown
  as `未知` in the user-facing table, with the git stderr available in
  `check_error`. Don't retry blindly; tell the user when the error matters.
- **Clone succeeded but SKILL.md not at subpath** → `subpath` in sources.json
  is wrong. Re-run `sources.py claim-remote` with the correct subpath.
- **An update leaves the central directory missing** (very rare; likely
  disk/permission failure during rename) → check `.backup/<name>-<ts>-<uuid>/`
  and move it back manually.

## What this skill does NOT do

- Does not install non-GitHub sources (GitLab, raw zip URLs, npm, etc.) — only
  the URL forms listed under Scenario D.
- Does not manage Cursor's built-in skills (`skills-cursor/`).
- Does not touch plugin-managed skills (`~/.claude/plugins/cache/...`).
- Does not detect or auto-merge local edits in Git skills. Updating a Git skill
  replaces the current directory with the upstream copy after creating a backup.
