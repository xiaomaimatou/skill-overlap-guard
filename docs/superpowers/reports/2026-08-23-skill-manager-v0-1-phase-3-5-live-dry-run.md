# Skill Manager V0.1 — Phase 3.5 live dry-run validation

## Safety result

No Skill installation, deletion, merge, replacement, disable operation, or
managed-Skill write was executed. The initial and final discovered Skill count
was 40. The Terminal Guard was enabled only for live tests and was disabled
afterwards; no marker remains in `.zshrc`.

## Terminal Guard live test

The zsh wrapper was enabled with `terminal_guard.py enable`, then a new zsh
process ran:

```text
npx -y skills add /tmp/skill-manager-live-blind/data-analysis
```

It intercepted the command before `command npx` could run, resolved the local
source, parsed its `SKILL.md`, compared it with 40 installed Skills, produced a
five-pair semantic-review queue, and attached pending Decision Registry
context. Its report had `installer_called: false` and stated `Installation has
NOT been executed.` The guard then ran `disable` successfully.

`npx skills add owner/repo` was also intercepted. Its remote read was blocked
by this Python runtime's certificate trust failure; it stopped safely rather
than forwarding to npx or attempting an installation.

## Real held-out GitHub calibration

Five source files, none present in `recall_benchmarks.json` and with no Phase
3.5 alias changes, were read from GitHub and supplied as temporary parser
snapshots because this Python runtime cannot validate the remote TLS chain:

- JPeetz/agent-skills `data-analysis`
- 1EchA/academic-writing `academic-writing`
- rampstackco/claude-skills `content-and-copy`
- JetBrains/skills `frontend-design`
- drader/researcher_agent `research`

Each candidate was compared one-to-many against the same 40 installed Skills.
The manually reviewed positive was `frontend-design` ↔
`design-taste-frontend`: candidate rank 1, score 0.5667, semantic
relationship `high-overlap`, confidence 0.83, recommendation `manual_review`.
It therefore achieved Top-5 and Top-10 recall. The other four samples were not
claimed as HIGH/DUPLICATE: data analysis is complementary to presentation/UI
work; academic-writing, generic content-copy, and literature research require
further semantic differentiation. A notable L0 candidate-only false positive
was generic `content-and-copy` ↔ `space-video-cover`; it remains for semantic
review and must not be treated as a duplicate.

## Codex Runtime attempt

One isolated `codex exec --ephemeral --sandbox read-only` attempt was made with
a temporary `CODEX_HOME` containing only a symlink to this Skill Manager and
existing authentication. The runtime printed `failed to refresh available
models: timeout waiting for child process to exit` and returned no model/routing
response. Therefore no automatic or explicit Runtime Trigger case is counted
as passed, and this phase does not claim Codex Runtime Trigger readiness.
