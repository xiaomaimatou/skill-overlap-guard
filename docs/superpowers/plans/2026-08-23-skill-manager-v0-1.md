# Skill Manager V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the upstream Python skill manager with cross-root inventory, explainable duplicate auditing, pre-install dedup gating, and persisted user decisions without weakening its backup or atomic replacement guarantees.

**Architecture:** Keep existing source tracking and lifecycle scripts as the write-path authority. Add deterministic parsers and a candidate scorer for all skills; only a bounded semantic-review adapter receives the Top 5 candidate pairs and emits schema-validated judgments for an agent to resolve. Audit and check remain read-only; installation writes only after the gate completes.

**Tech Stack:** Python 3.9+, standard library (`argparse`, `dataclasses`, `hashlib`, `json`, `pathlib`, `difflib`, `unittest`), Git CLI.

## Global Constraints

- Scan `~/.agents/skills`, `~/.codex/skills`, and `<project>/.agents/skills`; exclude `.system`, `.backup`, `.tmp`, caches, and temporary download directories.
- Preserve the upstream `sources.json`, backup, and rename-based atomic replacement contracts.
- Do not call a model during all-pairs candidate generation; semantic review is bounded to the Top 5 candidates and is agent-mediated in V0.1.
- Audit and check are read-only. HIGH and DUPLICATE never delete, merge, replace, or install without explicit user confirmation.
- Parent-child pairs must be reported as related but must not be assigned `DUPLICATE` solely due to nesting.
- Use failing tests before each production-code change and run `python -m unittest` after each task.

---

## File Structure

- Modify: `scripts/_common.py` — shared paths, frontmatter/content helpers, atomic JSON persistence.
- Modify: `scripts/inventory.py` — multi-root discovery and normalized inventory records.
- Modify: `scripts/similarity.py` — retain existing two-file compatibility interface; add reusable deterministic primitives only.
- Modify: `scripts/install_skill.py` — delegate to the pre-install check and gate before any destination replacement.
- Create: `scripts/capability_parser.py` — deterministic `CapabilityProfile` parsing and content hashes.
- Create: `scripts/relationship_detector.py` — parent-child relation detection.
- Create: `scripts/duplicate_scan.py` — candidate score, levels, and audit JSON.
- Create: `scripts/semantic_review.py` — review-package construction and strict result-schema validation.
- Create: `scripts/overlap_report.py` — detailed comparison and ranked rendering payloads.
- Create: `scripts/decision_registry.py` — canonical pair keys and version-aware decisions.
- Create: `scripts/preinstall_check.py` — temporary candidate inspection and non-writing Dedup Gate state.
- Create: `tests/test_v0_1.py` — isolated fixture coverage for all V0.1 behavior.
- Modify: `tests/test_contract.py` — retain regression coverage for upstream lifecycle contracts.
- Modify: `SKILL.md`, `README.md`, `README.zh-CN.md` — agent command routing and user-facing contracts.

### Task 1: Build normalized multi-root inventory

**Files:**
- Test: `tests/test_v0_1.py`
- Modify: `scripts/_common.py`, `scripts/inventory.py`
- Create: `scripts/capability_parser.py`, `scripts/relationship_detector.py`

**Interfaces:**
- Produces `discover_skills(roots: list[Path]) -> list[dict]` with `name`, `path`, `scope`, `parent_skill`, `children`, `description`, and `content_hash`.
- Produces `parse_capability_profile(skill_dir: Path) -> dict` containing all fields in requirement §4.4 and §5.

- [ ] **Step 1: Write failing inventory and nesting tests**

```python
def test_inventory_recursively_discovers_parent_and_child_without_system_dirs(self):
    rows = discover_skills([self.agents_root, self.codex_root, self.project_root])
    self.assertEqual({row["name"] for row in rows}, {"creator-buddy", "space-xhs-writer"})
    child = next(row for row in rows if row["name"] == "space-xhs-writer")
    self.assertEqual(child["parent_skill"], "creator-buddy")
```

- [ ] **Step 2: Run the focused test and verify it fails because the new API is absent**

Run: `python -m unittest tests.test_v0_1.SkillManagerV01Tests.test_inventory_recursively_discovers_parent_and_child_without_system_dirs -v`

- [ ] **Step 3: Implement the smallest parser and recursive discovery path**

```python
def discover_skills(roots: list[Path]) -> list[dict]:
    # Find SKILL.md files below configured roots, excluding protected paths.
    # Normalize every result to a stable record and attach parent relationships.
```

- [ ] **Step 4: Run focused and full tests**

Run: `python -m unittest tests.test_v0_1 -v && python -m unittest -v`

### Task 2: Add deterministic duplicate candidates and relationship protection

**Files:**
- Test: `tests/test_v0_1.py`
- Modify: `scripts/similarity.py`
- Create: `scripts/duplicate_scan.py`

**Interfaces:**
- Produces `score_pair(a: dict, b: dict) -> dict` with `score`, `level`, `relationship`, and `candidate_reasons`.
- Produces `audit(records: list[dict], top: int = 10) -> dict` with ranked pairs and all HIGH/DUPLICATE pairs.

- [ ] **Step 1: Write failing tests for unrelated, partial-overlap, duplicate, and parent-child pairs**

```python
self.assertEqual(score_pair(video_subtitles, database_migration)["level"], "LOW")
self.assertEqual(score_pair(parent, child)["relationship"], "parent_child")
self.assertNotEqual(score_pair(parent, child)["level"], "DUPLICATE")
```

- [ ] **Step 2: Verify the tests fail with missing imports or incorrect result fields**

Run: `python -m unittest tests.test_v0_1 -v`

- [ ] **Step 3: Implement field-weighted scoring and stable level classification**

```python
LEVELS = ((85, "DUPLICATE"), (70, "HIGH"), (40, "MEDIUM"), (0, "LOW"))
```

- [ ] **Step 4: Run the focused and full suite**

Run: `python -m unittest tests.test_v0_1 -v && python -m unittest -v`

### Task 3: Add semantic-review and report contracts

**Files:**
- Test: `tests/test_v0_1.py`
- Create: `scripts/semantic_review.py`, `scripts/overlap_report.py`

**Interfaces:**
- Produces `build_review_package(candidate: dict) -> dict`.
- Produces `validate_review_result(payload: dict) -> dict`, rejecting invalid levels or relationships.
- Produces `render_comparison(pair: dict) -> dict` with common and unique capabilities plus a recommendation.

- [ ] **Step 1: Write a failing schema test**

```python
with self.assertRaises(ValueError):
    validate_review_result({"level": "CERTAIN", "relationship": "duplicate"})
```

- [ ] **Step 2: Run it and verify it fails before implementation**

Run: `python -m unittest tests.test_v0_1.SkillManagerV01Tests.test_semantic_review_rejects_unknown_level -v`

- [ ] **Step 3: Implement strict JSON normalization and report shaping**

```python
ALLOWED_RELATIONSHIPS = {"duplicate", "overlapping", "complementary", "unrelated", "parent_child"}
```

- [ ] **Step 4: Run all tests**

Run: `python -m unittest -v`

### Task 4: Persist decisions and suppress unchanged warnings

**Files:**
- Test: `tests/test_v0_1.py`
- Create: `scripts/decision_registry.py`

**Interfaces:**
- Produces `DecisionRegistry(path).record(pair, decision, ignore_future_warning)`.
- Produces `DecisionRegistry(path).should_suppress(pair) -> bool` only when both content hashes still match.

- [ ] **Step 1: Write failing tests for canonical ordering and invalidation on content change**

```python
registry.record(pair, "keep_both", ignore_future_warning=True)
self.assertTrue(registry.should_suppress(pair))
self.assertFalse(registry.should_suppress(changed_pair))
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m unittest tests.test_v0_1 -v`

- [ ] **Step 3: Implement atomic decisions.json storage**

```python
key = tuple(sorted((pair["skill_a"]["path"], pair["skill_b"]["path"])))
```

- [ ] **Step 4: Run all tests**

Run: `python -m unittest -v`

### Task 5: Add read-only pre-install check and gate states

**Files:**
- Test: `tests/test_v0_1.py`
- Create: `scripts/preinstall_check.py`
- Modify: `scripts/install_skill.py`

**Interfaces:**
- Produces `check_candidate(candidate_dir: Path, inventory: list[dict]) -> dict` without writes outside the candidate directory.
- Produces `gate_action(level: str, explicit_choice: str | None) -> str` returning `allow`, `confirm_required`, or `blocked`.

- [ ] **Step 1: Write failing tests that assert HIGH is paused and DUPLICATE needs explicit continuation**

```python
self.assertEqual(gate_action("HIGH", None), "confirm_required")
self.assertEqual(gate_action("DUPLICATE", None), "blocked")
self.assertEqual(gate_action("LOW", None), "allow")
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m unittest tests.test_v0_1.SkillManagerV01Tests.test_gate_requires_explicit_choice_for_high_overlap -v`

- [ ] **Step 3: Implement the check before `os.replace` in install_skill.py**

```python
# Build the candidate result after clone validation and before central = skills_root() / name.
# Abort or return a structured pending gate result before any backup or destination write.
```

- [ ] **Step 4: Run lifecycle regression tests and the full suite**

Run: `python -m unittest tests.test_contract -v && python -m unittest -v`

### Task 6: Expose commands and complete acceptance verification

**Files:**
- Test: `tests/test_v0_1.py`, `tests/test_contract.py`
- Modify: `SKILL.md`, `README.md`, `README.zh-CN.md`

**Interfaces:**
- `inventory.py` exposes configured roots.
- `duplicate_scan.py` exposes `audit`, `--level`, and `--top`.
- `preinstall_check.py` exposes `check`.
- `overlap_report.py` exposes `compare`.
- `decision_registry.py` exposes `decisions`.

- [ ] **Step 1: Write CLI contract tests for the six new command payloads**

```python
payload = json.loads(self.run_script("duplicate_scan.py", "audit", "--top", "10").stdout)
self.assertIn("top_pairs", payload)
```

- [ ] **Step 2: Run them and verify the missing command behavior fails**

Run: `python -m unittest tests.test_v0_1 -v`

- [ ] **Step 3: Add argparse commands and documentation without changing existing command output contracts**

```python
parser.add_argument("--top", type=int, default=10)
parser.add_argument("--level", choices=["low", "medium", "high", "duplicate"])
```

- [ ] **Step 4: Verify all acceptance cases and the complete suite**

Run: `python -m unittest -v`

Expected: all upstream contract tests and V0.1 tests pass; every case in requirements §18 has a named automated test.
