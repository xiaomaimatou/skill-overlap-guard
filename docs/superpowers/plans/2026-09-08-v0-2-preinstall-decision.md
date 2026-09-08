# Skill Overlap Guard V0.2 Pre-install Decision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing read-only Skill Overlap Guard with deterministic health scoring, trigger-conflict analysis, security-precheck result normalization, and a unified pre-install decision report without implementing V0.3 installation transactions.

**Architecture:** Add focused pure-Python modules around the existing capability profile and dedup chain. `invocation_contract.py` remains the request router; `preinstall_report.py` composes health, trigger, security, overlap, and source evidence into a read-only report. The security layer exposes an adapter contract plus a conservative local static scanner that never executes candidate code.

**Tech Stack:** Python 3.9+, standard library only, `unittest`, existing profile parser and duplicate-scan modules.

## Global Constraints

- V0.2 remains read-only by default.
- Security risk has veto priority over overlap, trigger, health, and source recommendations.
- V0.2 must not automatically delete, merge, replace, disable, overwrite, install, or roll back Skills.
- Candidate code must never execute during scanning.
- Parent-child and generalist-specialist relationships must not be classified as duplicate by default.
- Existing V0.1 regression tests must continue to pass.
- Preserve compatibility with the legacy `skills-manager` trigger alias.

---

### Task 1: Add V0.2 failing tests and fixture coverage

**Files:**
- Create: `tests/test_v0_2.py`
- Test fixtures: inline temporary Skill directories created by the test helpers.

**Interfaces:**
- Tests define the required public functions for `health_score.py`, `trigger_conflict.py`, `security_precheck.py`, `decision_engine.py`, and `preinstall_report.py`.

- [ ] **Step 1: Write failing tests for health scoring, trigger conflicts, scope classification, security evidence, decision precedence, and report composition.**

- [ ] **Step 2: Run `python3 -m unittest tests.test_v0_2 -v` and verify failures are caused by missing V0.2 modules/functions.**

- [ ] **Step 3: Keep fixtures limited to safe text and inert script content; assert scanners report evidence but never execute files.**

### Task 2: Implement deterministic Skill Health Score

**Files:**
- Create: `scripts/health_score.py`
- Test: `tests/test_v0_2.py`

**Interfaces:**
- Produces `score_profile(profile: dict, source: dict | None = None, relationship: dict | None = None) -> dict`.
- The result contains `score` from 0 to 100, `strengths: list[str]`, `risks: list[str]`, and `factors: dict[str, int]`.

- [ ] **Step 1: Make the health-score tests pass for complete, incomplete, over-broad, and source-less profiles.**
- [ ] **Step 2: Implement bounded deterministic factors for metadata, structure, scope clarity, dependencies, source metadata, and relationship context.**
- [ ] **Step 3: Ensure health score is explanatory only and has no destructive action fields.**
- [ ] **Step 4: Run `python3 -m unittest tests.test_v0_2.HealthScoreTests -v`.**

### Task 3: Implement Trigger Conflict and Generalist/Specialist analysis

**Files:**
- Create: `scripts/trigger_conflict.py`
- Test: `tests/test_v0_2.py`

**Interfaces:**
- Produces `compare_trigger_conflict(candidate: dict, installed: dict) -> dict` with `level`, `conflicting_skills`, `reason`, `shared_triggers`, `description_similarity`, and `scope_relationship`.
- Produces `classify_scope_relationship(candidate: dict, installed: dict) -> dict` with `relationship`, `shared_scope`, and `specialist_unique_value`.

- [ ] **Step 1: Write/verify failing tests for identical descriptions, broad UI triggers, distinct same-domain skills, and generalist-specialist pairs.**
- [ ] **Step 2: Implement token normalization and conservative overlap thresholds using only profile evidence.**
- [ ] **Step 3: Protect parent-child and generalist-specialist pairs from duplicate-level trigger conclusions.**
- [ ] **Step 4: Run `python3 -m unittest tests.test_v0_2.TriggerConflictTests -v`.**

### Task 4: Implement the Security Scanner Adapter and safe static scanner

**Files:**
- Create: `scripts/security_precheck.py`
- Test: `tests/test_v0_2.py`

**Interfaces:**
- Produces `scan_skill_tree(skill_dir: pathlib.Path, scanner: ScannerAdapter | None = None) -> dict`.
- Defines `ScannerAdapter.scan(skill_dir: pathlib.Path) -> dict` and `normalize_scan_result(raw: dict) -> dict`.
- Normalized output contains `risk_level`, `findings`, `commands`, `domains`, `sensitive_paths`, `scanner`, `scanner_version`, and `read_only`.

- [ ] **Step 1: Write/verify failing tests for prompt injection, dangerous shell, credential access, network exfiltration, install hooks, obfuscation, traversal/symlink, and documentation-only examples.**
- [ ] **Step 2: Implement a no-execution scanner that reads files as text, records file and line evidence, and skips documentation-only command mentions where possible.**
- [ ] **Step 3: Implement risk aggregation with `INFO < LOW < MEDIUM < HIGH < CRITICAL` and adapter result normalization.**
- [ ] **Step 4: Reject symlink escapes and flag suspicious hidden/binary files without following links outside the scan root.**
- [ ] **Step 5: Run `python3 -m unittest tests.test_v0_2.SecurityPrecheckTests -v`.**

### Task 5: Implement the unified decision engine

**Files:**
- Create: `scripts/decision_engine.py`
- Test: `tests/test_v0_2.py`

**Interfaces:**
- Produces `build_decision(overlap: dict, trigger: dict, health: dict, security: dict, source: dict | None = None) -> dict`.
- Result contains independent `functional_risk`, `trigger_risk`, `health`, `security_risk`, `source`, `recommendation`, `decision_options`, and `read_only` fields.

- [ ] **Step 1: Write/verify failing tests for CRITICAL-overlap-low yielding `block`, duplicate-safe yielding `keep_existing`, complementary yielding `keep_both`, and uncertain evidence yielding `manual_review`.**
- [ ] **Step 2: Implement security veto first, then overlap, trigger, health/source recommendation precedence.**
- [ ] **Step 3: Ensure allowed recommendations are only `install_candidate`, `keep_existing`, `keep_both`, `manual_review`, `possible_duplicate`, `security_warning`, and `block_recommended`.**
- [ ] **Step 4: Run `python3 -m unittest tests.test_v0_2.DecisionEngineTests -v`.**

### Task 6: Integrate the read-only Pre-install Decision Report

**Files:**
- Create: `scripts/preinstall_report.py`
- Modify: `scripts/invocation_contract.py`
- Modify: `scripts/terminal_guard.py`
- Test: `tests/test_v0_2.py`

**Interfaces:**
- Produces `build_preinstall_report(request: dict, candidate: dict, installed: list[dict], security: dict | None = None, source: dict | None = None) -> dict`.
- Extends `build_dedup_context(...)` with a `preinstall_report` field while preserving existing `semantic_review_queue`, `decision_context`, and `install_performed: False` behavior.
- Terminal dry-run returns the unified report and continues to guarantee `installer_called: False`.

- [ ] **Step 1: Write/verify failing integration tests for automatic install-intent routing, analysis-only non-routing, report sections, and terminal guard read-only behavior.**
- [ ] **Step 2: Implement report composition using the existing overlap candidate queue and new analyzers.**
- [ ] **Step 3: Preserve `$skill-manager` compatibility while making `skill-overlap-guard` the V0.2 explicit trigger name.**
- [ ] **Step 4: Run the focused integration tests.**

### Task 7: Add V0.2 documentation and regression verification

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Test: `tests/test_v0_2.py`

- [ ] **Step 1: Document automatic install-intent checking, unified report fields, security boundaries, and V0.2 non-goals.**
- [ ] **Step 2: Run `python3 -m unittest discover -s tests -p 'test_*.py'`.**
- [ ] **Step 3: Run a CLI smoke test for the read-only report with a temporary local candidate and installed Skill.**
- [ ] **Step 4: Review the diff for accidental installer, delete, merge, replace, disable, or overwrite behavior.**
- [ ] **Step 5: Commit the V0.2 implementation in focused commits and report the branch/commit state.**
