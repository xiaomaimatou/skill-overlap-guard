from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SKILL_MANAGER = Path(__file__).resolve().parents[1]


class SkillManagerV01Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scripts = self.root / "scripts"
        shutil.copytree(SKILL_MANAGER / "scripts", self.scripts)

        self.agents_root = self.root / "agents" / "skills"
        self.codex_root = self.root / "codex" / "skills"
        self.project_root = self.root / "project" / ".agents" / "skills"
        for root in (self.agents_root, self.codex_root, self.project_root):
            root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_skill(self, root: Path, relative_path: str, name: str, description: str) -> Path:
        skill_dir = root / relative_path
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
            encoding="utf-8",
        )
        return skill_dir

    def write_skill_markdown(self, root: Path, relative_path: str, text: str) -> Path:
        skill_dir = root / relative_path
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
        return skill_dir

    def load_inventory_module(self):
        return self.load_script_module("inventory.py", "inventory_v01_under_test")

    def load_script_module(self, filename: str, module_name: str):
        for cached in (
            "_common", "check_remote", "concept_normalizer", "capability_parser",
            "decision_registry", "duplicate_scan", "blind_recall", "invocation_contract",
            "source_loader", "terminal_guard", "health_score", "trigger_conflict",
            "security_precheck", "decision_engine", "preinstall_report", "manifest",
            "source_metadata", "recommendation_policy", module_name,
        ):
            sys.modules.pop(cached, None)
        sys.path.insert(0, str(self.scripts))
        spec = importlib.util.spec_from_file_location(
            module_name, self.scripts / filename
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def test_recursive_inventory_discovers_parent_child_and_excludes_system_skills(self) -> None:
        """Removing recursive discovery would hide nested skills from duplicate governance."""
        self.write_skill(self.agents_root, "creator-buddy", "creator-buddy", "Creator workflow")
        self.write_skill(
            self.agents_root,
            "creator-buddy/xhs-Skills/space-xhs-writer",
            "space-xhs-writer",
            "Write Xiaohongshu posts",
        )
        self.write_skill(self.codex_root, ".system/internal", "internal", "System-only skill")
        self.write_skill(self.project_root, "project-helper", "project-helper", "Project helper")

        inventory = self.load_inventory_module()
        rows = inventory.discover_skills(
            [self.agents_root, self.codex_root, self.project_root]
        )

        self.assertEqual(
            {row["name"] for row in rows},
            {"creator-buddy", "space-xhs-writer", "project-helper"},
        )
        child = next(row for row in rows if row["name"] == "space-xhs-writer")
        parent = next(row for row in rows if row["name"] == "creator-buddy")
        self.assertEqual(child["parent_skill"], "creator-buddy")
        self.assertEqual(parent["children"], ["space-xhs-writer"])
        self.assertEqual(child["scope"], "agents")
        self.assertEqual(
            next(row for row in rows if row["name"] == "project-helper")["scope"],
            "project",
        )

    def test_capability_profile_extracts_structured_sections_from_standard_skill_markdown(self) -> None:
        """Dropping heading extraction would reduce a profile to its description only."""
        skill_dir = self.write_skill_markdown(
            self.agents_root,
            "ui-helper",
            """---
name: ui-helper
description: Improve existing web interfaces.
category: frontend-design
---

# UI Helper

## Capabilities
- UI visual design
- Component styling

## Triggers
- improve frontend UI
- review visual quality

## Workflow
1. Analyze interface
2. Identify visual issues
3. Generate implementation

## Inputs
- existing frontend

## Outputs
- frontend code
- UI recommendations

## Tools
- Tailwind CSS

## Dependencies
- Node.js
""",
        )

        parser = self.load_script_module("capability_parser.py", "capability_parser_under_test")
        profile = parser.parse_capability_profile(skill_dir, parent_skill="creator-buddy")

        self.assertEqual(profile["name"], "ui-helper")
        self.assertEqual(profile["description"], "Improve existing web interfaces.")
        self.assertEqual(profile["category"], "frontend-design")
        self.assertEqual(profile["capabilities"], ["UI visual design", "Component styling"])
        self.assertEqual(profile["triggers"], ["improve frontend UI", "review visual quality"])
        self.assertEqual(profile["workflow"], ["Analyze interface", "Identify visual issues", "Generate implementation"])
        self.assertEqual(profile["inputs"], ["existing frontend"])
        self.assertEqual(profile["outputs"], ["frontend code", "UI recommendations"])
        self.assertEqual(profile["tools"], ["Tailwind CSS"])
        self.assertEqual(profile["dependencies"], ["Node.js"])
        self.assertEqual(profile["parent_skill"], "creator-buddy")

    def test_capability_profile_leaves_missing_or_malformed_fields_empty(self) -> None:
        """Inventing fields from malformed Markdown would contaminate similarity scoring."""
        skill_dir = self.write_skill_markdown(
            self.codex_root,
            "broken-skill",
            "---\nname: broken-skill\ndescription: >-\n  Still readable\n---\n\n## Capabilities\nnot a list\n",
        )

        parser = self.load_script_module("capability_parser.py", "capability_parser_under_test")
        profile = parser.parse_capability_profile(skill_dir)

        self.assertEqual(profile["name"], "broken-skill")
        self.assertEqual(profile["description"], "Still readable")
        self.assertEqual(profile["category"], "")
        self.assertEqual(profile["capabilities"], [])
        self.assertEqual(profile["triggers"], [])
        self.assertIsNone(profile["parent_skill"])

    def test_capability_profile_preserves_nested_skill_parent_and_non_design_terms(self) -> None:
        """Flattening nested or non-design skills would bias later audit input."""
        skill_dir = self.write_skill_markdown(
            self.agents_root,
            "creator-buddy/video-Skills/space-video-subtitle",
            """---
name: space-video-subtitle
description: Generate subtitles for spoken video.
---

## 功能
- 语音转写
- 生成 SRT 字幕

## 触发
- 上字幕
- 转写视频
""",
        )

        parser = self.load_script_module("capability_parser.py", "capability_parser_under_test")
        profile = parser.parse_capability_profile(skill_dir, parent_skill="creator-buddy")

        self.assertEqual(profile["capabilities"], ["语音转写", "生成 SRT 字幕"])
        self.assertEqual(profile["triggers"], ["上字幕", "转写视频"])
        self.assertEqual(profile["parent_skill"], "creator-buddy")

    def test_capability_profile_extracts_chinese_body_fallback_with_source_confidence(self) -> None:
        """Chinese prose-only skills need traceable recall signals without invented capabilities."""
        skill_dir = self.write_skill_markdown(
            self.agents_root,
            "prose-title",
            """---
name: prose-title
description:
---

这是一个标题生成器，输入主题后生成多个爆款标题并评分。
适用场景是公众号内容发布前的标题优化。
""",
        )

        parser = self.load_script_module("capability_parser.py", "capability_parser_under_test")
        profile = parser.parse_capability_profile(skill_dir)

        self.assertEqual(profile["capabilities"], [])
        self.assertEqual(profile["primary_purpose"]["source"], "body_fallback")
        self.assertEqual(profile["primary_purpose"]["confidence"], 0.62)
        self.assertIn("标题生成器", profile["primary_purpose"]["value"])
        self.assertTrue(all(signal["source"] == "body_fallback" for signal in profile["fallback_signals"]))

    def test_capability_profile_extracts_english_body_fallback(self) -> None:
        """English natural-language use guidance must become a lower-confidence candidate signal."""
        skill_dir = self.write_skill_markdown(
            self.codex_root,
            "prose-headline",
            """---
name: prose-headline
---

Use this skill when you need headline generation and headline scoring for an article.
It returns several title options for editorial review.
""",
        )

        parser = self.load_script_module("capability_parser.py", "capability_parser_under_test")
        profile = parser.parse_capability_profile(skill_dir)

        self.assertEqual(profile["primary_purpose"]["source"], "body_fallback")
        self.assertIn("headline generation", profile["fallback_signals"][0]["value"])

    def test_capability_profile_preserves_mixed_language_fallback_text(self) -> None:
        """Mixed-language prose must retain original text for later normalization, not translate or fabricate it."""
        skill_dir = self.write_skill_markdown(
            self.agents_root,
            "mixed-frontend",
            """---
name: mixed-frontend
---

适用场景：frontend visual refinement，优化现有界面的视觉层级。
""",
        )

        parser = self.load_script_module("capability_parser.py", "capability_parser_under_test")
        profile = parser.parse_capability_profile(skill_dir)

        self.assertIn("frontend visual refinement", profile["primary_purpose"]["value"])
        self.assertEqual(profile["fallback_signals"][0]["confidence"], 0.62)

    def test_concept_alias_normalizer_matches_chinese_and_english_without_replacing_text(self) -> None:
        """Alias matching must bridge title-generation wording while returning canonical concepts only as metadata."""
        normalizer = self.load_script_module("concept_normalizer.py", "concept_normalizer_under_test")

        chinese = normalizer.extract_concepts("这是一个爆款标题生成器")
        english = normalizer.extract_concepts("headline generation and title scoring")

        self.assertIn("title-generation", chinese)
        self.assertIn("title-generation", english)

    def test_dynamic_candidates_recall_low_score_known_positive_without_score_inflation(self) -> None:
        """A known title-generation positive with L0=0 must enter review by explainable concept signals."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        profiles = [
            {"name": "space-xhs-title", "description": "小红书爆款标题生成器，产出并评分标题。", "category": "", "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": []},
            {"name": "baokuan-title-generator", "description": "公众号爆款标题生成器，生成候选标题并评分。", "category": "", "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": []},
            {"name": "agent-reach", "description": "Search the internet for public sources.", "category": "", "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": []},
            {"name": "space-video", "description": "视频创作总控，编辑和导出视频。", "category": "", "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": []},
        ]

        report = scan.audit_profiles(
            profiles, threshold=0.90, min_candidates=1, max_candidates=3,
            known_positive_pairs=[("space-xhs-title", "baokuan-title-generator")],
            known_negative_pairs=[("agent-reach", "space-video")],
        )
        title_pair = next(
            pair for pair in report["semantic_candidates"]
            if {pair["skill_a"], pair["skill_b"]} == {"space-xhs-title", "baokuan-title-generator"}
        )

        self.assertEqual(title_pair["candidate_score"], 0.0)
        self.assertTrue(title_pair["candidate_override"])
        self.assertIn("normalized_concept_match:title-generation", title_pair["candidate_reasons"])
        self.assertEqual(report["candidate_recall_report"]["candidate_recall_rate"], 1.0)
        self.assertEqual(report["candidate_recall_report"]["known_negative_candidates"], 0)
        self.assertEqual(report["candidate_selection"]["threshold_qualified"], 0)
        self.assertEqual(report["candidate_selection"]["override_selected"], 1)

    def test_dynamic_candidates_apply_threshold_top_k_and_parent_child_guardrails(self) -> None:
        """Threshold, Top-K floor, and structural exclusion must control review cost independently of recall overrides."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        pairs = [
            {"skill_a": "a", "skill_b": "b", "candidate_score": 0.80, "score": 0.80, "relationship": "partial-overlap", "recall_signals": []},
            {"skill_a": "c", "skill_b": "d", "candidate_score": 0.60, "score": 0.60, "relationship": "partial-overlap", "recall_signals": []},
            {"skill_a": "e", "skill_b": "f", "candidate_score": 0.20, "score": 0.20, "relationship": "complementary", "recall_signals": []},
            {"skill_a": "parent", "skill_b": "child", "candidate_score": 0.99, "score": 0.99, "relationship": "parent-child", "recall_signals": ["normalized_concept_match:title-generation"]},
        ]

        selected = scan.select_semantic_candidates(pairs, threshold=0.50, min_candidates=3, max_candidates=3)

        self.assertEqual([(pair["skill_a"], pair["skill_b"]) for pair in selected], [("a", "b"), ("c", "d"), ("e", "f")])
        self.assertIn("top_k_floor", selected[-1]["candidate_reasons"])
        self.assertNotIn("parent", [pair["skill_a"] for pair in selected])

    def test_known_positive_recall_has_priority_over_max_candidate_cap(self) -> None:
        """A cost cap may trim ordinary candidates but must never drop a known HIGH/DUPLICATE benchmark."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        pairs = [
            {"skill_a": "positive-a", "skill_b": "positive-b", "candidate_score": 0.0, "score": 0.0, "relationship": "complementary", "recall_signals": []},
            {"skill_a": "positive-c", "skill_b": "positive-d", "candidate_score": 0.0, "score": 0.0, "relationship": "complementary", "recall_signals": []},
        ]

        selected = scan.select_semantic_candidates(
            pairs, threshold=0.99, min_candidates=0, max_candidates=1,
            known_positive_pairs=[("positive-a", "positive-b"), ("positive-c", "positive-d")],
        )

        self.assertEqual(len(selected), 2)

    def test_single_broad_concept_does_not_override_candidate_guardrail(self) -> None:
        """One generic concept such as design must not send an otherwise unrelated pair to semantic review."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        profiles = [
            {"name": "design-a", "description": "design", "category": "", "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": []},
            {"name": "design-b", "description": "design", "category": "", "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": []},
        ]

        report = scan.audit_profiles(profiles, threshold=0.99, min_candidates=0, max_candidates=5)

        self.assertEqual(report["semantic_candidates"], [])

    def test_single_low_confidence_fallback_concept_does_not_count_as_two_signals(self) -> None:
        """Primary text copied from one fallback paragraph must not bypass the two-signal guardrail."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        fallback_signal = [{"value": "标题生成", "source": "body_fallback", "confidence": 0.62}]
        profiles = [
            {"name": "a", "description": "", "category": "", "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [], "primary_purpose": dict(fallback_signal[0]), "fallback_signals": fallback_signal},
            {"name": "b", "description": "", "category": "", "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [], "primary_purpose": dict(fallback_signal[0]), "fallback_signals": fallback_signal},
        ]

        report = scan.audit_profiles(profiles, threshold=0.99, min_candidates=0, max_candidates=5, known_positive_pairs=[])

        self.assertEqual(report["semantic_candidates"], [])

    def test_blind_recall_reaches_five_held_out_high_pairs_without_benchmark(self) -> None:
        """Held-out cross-language positives must be selected without being added to recall_benchmarks.json."""
        blind = self.load_script_module("blind_recall.py", "blind_recall_under_test")
        parser = self.load_script_module("capability_parser.py", "capability_parser_blind_under_test")
        fixture_root = self.root / "blind-skill-fixtures"

        def profile(name: str, description: str) -> dict:
            # These are real-shaped SKILL.md fixtures, parsed through the same
            # source-facing parser used by the candidate pipeline.
            skill_dir = self.write_skill_markdown(
                fixture_root, name,
                f"---\nname: {name}\ndescription: {description}\n---\n\n"
                f"# {name}\n\nUse this skill when {description}\n",
            )
            return parser.parse_capability_profile(skill_dir)

        installed = [
            profile("space-xhs-title", "小红书爆款标题生成器，生成并评分标题。"),
            profile("ui-styling", "frontend visual refinement for responsive interfaces"),
            profile("global-content-search", "content search and content retrieval"),
            profile("space-video-subtitle", "subtitle production and transcription"),
            profile("space-video-cover", "video cover and thumbnail design"),
            profile("brand", "brand identity and messaging"),
            profile("space-video", "video production workflow director"),
        ]
        # A Gate compares one incoming Skill with the whole installed set, not only
        # with the known target.  These realistic, unrelated operational Skills are
        # distractors; they deliberately use none of the tested concept aliases.
        installed.extend(
            profile(
                f"held-out-installed-{index:02d}",
                "Use this skill when a project needs a bounded operations task. "
                "It receives local context, performs a focused check, and returns a concise report.",
            )
            for index in range(1, 34)
        )
        cases = [
            {"candidate": profile("held-headline", "headline generation and title scoring"), "expected_overlap_skill": "space-xhs-title", "expected_relationship": "high-overlap"},
            {"candidate": profile("held-frontend", "前端视觉优化和界面 refinement"), "expected_overlap_skill": "ui-styling", "expected_relationship": "high-overlap"},
            {"candidate": profile("held-search", "内容检索与内容搜索"), "expected_overlap_skill": "global-content-search", "expected_relationship": "high-overlap"},
            {"candidate": profile("held-subtitle", "字幕转写与字幕生成"), "expected_overlap_skill": "space-video-subtitle", "expected_relationship": "high-overlap"},
            {"candidate": profile("held-cover", "视频封面和缩略图设计"), "expected_overlap_skill": "space-video-cover", "expected_relationship": "high-overlap"},
            {"candidate": profile("held-brand-assets", "brand asset templates"), "expected_overlap_skill": "brand", "expected_relationship": "partial-overlap"},
            {"candidate": profile("held-video-plan", "video research planning"), "expected_overlap_skill": "space-video", "expected_relationship": "complementary"},
            {"candidate": profile("held-database", "database schema migration"), "expected_overlap_skill": "held-out-installed-33", "expected_relationship": "unrelated"},
            {"candidate": profile("held-spreadsheet", "spreadsheet budget reconciliation"), "expected_overlap_skill": "held-out-installed-31", "expected_relationship": "unrelated"},
            {"candidate": profile("held-context", "remember task context"), "expected_overlap_skill": "held-out-installed-32", "expected_relationship": "uncertain"},
        ]

        report = blind.run_blind_recall(cases, installed, threshold=0.25, min_candidates=5, max_candidates=10)

        self.assertEqual(report["held_out_positive_total"], 5)
        self.assertTrue(all(case["installed_skill_count"] == 40 for case in report["cases"]))
        self.assertEqual(report["held_out_positive_recalled"], 5)
        self.assertEqual(report["held_out_recall_rate"], 1.0)
        self.assertEqual(report["top_5_recall"], 1.0)
        self.assertEqual(report["top_10_recall"], 1.0)
        self.assertEqual(report["override_recalled_count"], 5)
        self.assertEqual(report["normal_score_recalled_count"], 0)
        self.assertEqual(report["total_pairs"], 400)
        self.assertEqual(report["semantic_candidate_count"], 50)
        self.assertEqual(report["candidate_ratio"], 0.125)
        self.assertTrue(all(case["semantic_candidate_count"] <= 10 for case in report["cases"]))
        case_by_name = {case["candidate_skill"]: case for case in report["cases"]}
        self.assertFalse(case_by_name["held-database"]["recalled"])
        self.assertFalse(case_by_name["held-spreadsheet"]["recalled"])
        self.assertFalse(case_by_name["held-context"]["recalled"])
        self.assertFalse(any("known_positive_benchmark" in case["candidate_reasons"] for case in report["cases"]))

    def test_install_intent_routes_chinese_english_and_commands_to_analysis_first(self) -> None:
        """Agent-skill installation expressions must require dedup analysis before any installer action."""
        contract = self.load_script_module("invocation_contract.py", "invocation_contract_under_test")

        chinese = contract.resolve_request("安装这个skill https://github.com/acme/example-skill")
        english = contract.resolve_request("add this skill https://github.com/acme/example-skill")
        english_short = contract.resolve_request("add skill acme/example-skill")
        command = contract.resolve_request("npx skills add acme/example-skill")
        codex = contract.resolve_request("把这个 skill 加到 Codex")
        chinese_without_source = contract.resolve_request("帮我装一下这个 GitHub Skill")

        for result in (chinese, english, english_short, command, codex, chinese_without_source):
            self.assertEqual(result["trigger"], "skills-manager")
            self.assertEqual(result["intent"], "install_skill")
            self.assertTrue(result["dedup_required"])
            self.assertFalse(result["install_performed"])
        self.assertEqual(chinese["source"]["source_type"], "github")
        self.assertEqual(command["source"]["source_type"], "github_shorthand")
        self.assertEqual(codex["dedup_status"], "blocked_pending_confirmation")
        self.assertEqual(codex["reason"], "missing_source")
        self.assertEqual(chinese_without_source["reason"], "missing_source")

    def test_invocation_contract_rejects_non_skill_installs_and_separates_analysis(self) -> None:
        """Package installs must not hijack routing, while Skill inspection remains non-install analysis."""
        contract = self.load_script_module("invocation_contract.py", "invocation_contract_under_test")

        python_install = contract.resolve_request("安装 Python")
        homebrew_install = contract.resolve_request("install Homebrew")
        repos = contract.resolve_request("比较两个 GitHub repo")
        analysis = contract.resolve_request("分析这个 Skill")
        check = contract.resolve_request("这个 Skill 值得安装吗")
        explicit = contract.resolve_request("$skill-manager 安装这个 skill owner/repo")

        self.assertIsNone(python_install["trigger"])
        self.assertIsNone(homebrew_install["trigger"])
        self.assertIsNone(repos["intent"])
        self.assertEqual(analysis["mode"], "analysis")
        self.assertFalse(analysis["dedup_required"])
        self.assertEqual(check["mode"], "check")
        self.assertFalse(check["dedup_required"])
        self.assertEqual(explicit["trigger"], "skills-manager")
        self.assertEqual(explicit["source"]["repo"], "owner/repo")

    def test_source_resolver_handles_local_path_name_and_github_command(self) -> None:
        """Install analysis must preserve explicit sources and never invent a missing repository."""
        contract = self.load_script_module("invocation_contract.py", "invocation_contract_under_test")

        local = contract.resolve_request("安装这个 skill /tmp/example-skill")
        nested_local = contract.resolve_request("安装这个 skill /tmp/fixtures/example-skill")
        named = contract.resolve_request("安装 skill example-skill")
        command = contract.resolve_request("install-skill-from-github.py owner/repo")
        npx_local = contract.resolve_request("npx skills add /tmp/fixtures/example-skill")
        raw = contract.resolve_request("install this skill https://raw.githubusercontent.com/acme/example/main/SKILL.md")

        self.assertEqual(local["source"]["source_type"], "local_path")
        self.assertEqual(nested_local["source"]["source_type"], "local_path")
        self.assertEqual(named["source"]["source_type"], "skill_name")
        self.assertEqual(named["source"]["requested_skill_name"], "example-skill")
        self.assertEqual(command["source"]["source_type"], "github_shorthand")
        self.assertEqual(npx_local["source"]["source_type"], "local_path")
        self.assertEqual(raw["source"]["source_type"], "github")
        self.assertEqual(raw["source"]["repo"], "acme/example")

    def test_dedup_status_maps_semantic_relationship_without_installing(self) -> None:
        """Semantic outcomes must communicate review state only, never turn into installer authorization."""
        contract = self.load_script_module("invocation_contract.py", "invocation_contract_under_test")

        self.assertEqual(contract.dedup_status_for_relationship("duplicate"), "blocked_pending_confirmation")
        self.assertEqual(contract.dedup_status_for_relationship("high-overlap"), "blocked_pending_confirmation")
        self.assertEqual(contract.dedup_status_for_relationship("partial-overlap"), "warning")
        self.assertEqual(contract.dedup_status_for_relationship("complementary"), "clear")
        self.assertEqual(contract.dedup_status_for_relationship("unrelated"), "clear")

    def test_install_trigger_connects_to_existing_bounded_candidate_chain(self) -> None:
        """An install intent must hand its parsed profile to recall, review, recommendation, and decision context."""
        contract = self.load_script_module("invocation_contract.py", "invocation_contract_under_test")
        request = contract.resolve_request("install this skill https://github.com/acme/example-skill")
        candidate = {
            "name": "incoming-title", "description": "headline generation and title scoring",
            "category": "", "parent_skill": None, "capabilities": [], "triggers": [],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }
        installed = [{
            "name": "space-xhs-title", "description": "小红书爆款标题生成器，生成并评分标题。",
            "category": "", "parent_skill": None, "capabilities": [], "triggers": [],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }]

        context = contract.build_dedup_context(
            request, candidate, installed, threshold=0.25, min_candidates=1, max_candidates=3,
            known_positive_pairs=[],
        )

        self.assertEqual(context["dedup_status"], "checking")
        self.assertEqual(len(context["semantic_review_queue"]), 1)
        self.assertTrue(context["semantic_review_queue"][0]["candidate_override"])
        self.assertEqual(context["recommendation_status"], "pending_semantic_review")
        self.assertEqual(context["decision_context"][0]["decision_status"], "pending")
        self.assertFalse(context["install_performed"])

    def test_terminal_guard_detects_all_supported_npx_skills_add_forms(self) -> None:
        """The shell guard must recognize skills add regardless of safe npx or CLI options."""
        guard = self.load_script_module("terminal_guard.py", "terminal_guard_under_test")

        forms = [
            ["skills", "add", "owner/repo"],
            ["skills", "add", "https://github.com/owner/repo"],
            ["-y", "skills", "add", "owner/repo"],
            ["skills", "add", "owner/repo", "-g"],
            ["skills", "add", "owner/repo", "-a", "codex"],
        ]

        for args in forms:
            detected = guard.detect_skills_add(args)
            self.assertTrue(detected["intercept"])
            self.assertEqual(detected["source"], args[args.index("add") + 1])
        self.assertFalse(guard.detect_skills_add(["vite"])["intercept"])
        self.assertFalse(guard.detect_skills_add(["prettier", "."])["intercept"])
        self.assertFalse(guard.detect_skills_add(["create-next-app"])["intercept"])

    def test_terminal_guard_zshrc_block_is_idempotent_and_removable(self) -> None:
        """Enabling then removing the guard must preserve all unrelated zsh configuration."""
        guard = self.load_script_module("terminal_guard.py", "terminal_guard_under_test")
        zshrc = self.root / ".zshrc"
        zshrc.write_text("export EXISTING=value\n", encoding="utf-8")

        self.assertEqual(guard.update_guard("enable", zshrc), "enabled")
        self.assertEqual(guard.update_guard("enable", zshrc), "already_enabled")
        enabled = zshrc.read_text(encoding="utf-8")
        self.assertEqual(enabled.count(guard.BEGIN_MARKER), 1)
        self.assertIn("command npx \"$@\"", enabled)
        self.assertIn("export EXISTING=value", enabled)
        self.assertEqual(guard.update_guard("status", zshrc), "enabled")
        self.assertEqual(guard.update_guard("disable", zshrc), "disabled")
        self.assertEqual(guard.update_guard("status", zshrc), "disabled")
        self.assertEqual(zshrc.read_text(encoding="utf-8"), "export EXISTING=value\n")

    def test_terminal_guard_dry_run_reuses_invocation_and_candidate_chain_without_install(self) -> None:
        """A terminal intercept must use the shared candidate engine and return before command npx."""
        guard = self.load_script_module("terminal_guard.py", "terminal_guard_under_test")
        candidate = {
            "name": "incoming-title", "description": "headline generation and title scoring",
            "category": "", "parent_skill": None, "capabilities": [], "triggers": [],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }
        installed = [{
            "name": "space-xhs-title", "description": "小红书爆款标题生成器，生成并评分标题。",
            "category": "", "parent_skill": None, "capabilities": [], "triggers": [],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }]

        report = guard.run_dry_run(
            ["-y", "skills", "add", "owner/repo"], candidate, installed,
            threshold=0.25, min_candidates=1, max_candidates=3,
        )

        self.assertTrue(report["intercepted"])
        self.assertTrue(report["dedup_started"])
        self.assertEqual(len(report["semantic_review_queue"]), 1)
        self.assertFalse(report["installer_called"])
        self.assertIn("Installation has NOT been executed.", report["message"])

    def test_terminal_guard_cli_preserves_leading_npx_flags(self) -> None:
        """The wrapper passes -y through as intercepted npx input, not as a Python option."""
        guard = self.load_script_module("terminal_guard.py", "terminal_guard_under_test")
        guard._live_dry_run = lambda args, root: {
            "intercepted": True, "source": args[3], "installer_called": False,
        }

        output = io.StringIO()
        with redirect_stdout(output):
            code = guard.main(["terminal_guard.py", "intercept", "-y", "skills", "add", "owner/repo"])

        self.assertEqual(code, guard.INTERCEPTED_EXIT)
        self.assertIn("owner/repo", output.getvalue())

    def test_skill_manager_documents_explicit_reversible_terminal_guard(self) -> None:
        """Terminal interception must be opt-in, removable, and never authorize installation."""
        text = (SKILL_MANAGER / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("terminal_guard.py enable", text)
        self.assertIn("terminal_guard.py disable", text)
        self.assertIn("Installation has NOT been executed", text)

    def test_source_loader_parses_a_remote_skill_snapshot_without_installing(self) -> None:
        """A fetched remote SKILL.md must enter the regular parser, never an installation directory."""
        loader = self.load_script_module("source_loader.py", "source_loader_under_test")
        source = {
            "source_type": "github", "source": "https://github.com/acme/example",
            "repo": "acme/example", "path": "", "requested_skill_name": "example",
        }
        markdown = "---\nname: remote-example\ndescription: analyze data tables and create charts\n---\n\n# Remote\n\nUse this skill when analyzing data tables.\n"

        profile = loader.load_candidate_profile(source, fetch_text=lambda _: markdown)

        self.assertEqual(profile["name"], "remote-example")
        self.assertEqual(profile["source_type"], "github")
        self.assertIn("raw.githubusercontent.com/acme/example/main/SKILL.md", profile["source_url"])

    def test_audit_distinguishes_duplicate_partial_complementary_and_parent_child(self) -> None:
        """Collapsing relationship types would turn useful audit findings into unsafe deletion advice."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        profiles = [
            {
                "name": "ui-review-a", "description": "", "category": "", "parent_skill": None,
                "capabilities": ["UI accessibility review", "responsive layout review"],
                "triggers": ["review interface accessibility"], "workflow": ["inspect UI", "report issues"],
                "inputs": [], "outputs": [], "tools": [], "dependencies": [],
            },
            {
                "name": "ui-review-b", "description": "", "category": "", "parent_skill": None,
                "capabilities": ["UI accessibility review", "responsive layout review"],
                "triggers": ["review interface accessibility"], "workflow": ["inspect UI", "report issues"],
                "inputs": [], "outputs": [], "tools": [], "dependencies": [],
            },
            {
                "name": "brand", "description": "", "category": "design", "parent_skill": None,
                "capabilities": ["brand voice", "visual identity", "messaging framework"],
                "triggers": ["create brand guidelines"], "workflow": ["define brand principles"],
                "inputs": [], "outputs": [], "tools": [], "dependencies": [],
            },
            {
                "name": "design-system", "description": "", "category": "design", "parent_skill": None,
                "capabilities": ["design tokens", "component specifications", "CSS variables"],
                "triggers": ["create design tokens"], "workflow": ["define token layers"],
                "inputs": [], "outputs": [], "tools": [], "dependencies": [],
            },
            {
                "name": "creator-buddy", "description": "", "category": "", "parent_skill": None,
                "capabilities": ["content workflow routing"], "triggers": ["create content"],
                "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
            },
            {
                "name": "space-xhs-writer", "description": "", "category": "", "parent_skill": "creator-buddy",
                "capabilities": ["write Xiaohongshu posts"], "triggers": ["write Xiaohongshu"],
                "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
            },
        ]

        report = scan.audit_profiles(profiles)
        pairs = {(item["skill_a"], item["skill_b"]): item for item in report["pairs"]}

        self.assertEqual(pairs[("ui-review-a", "ui-review-b")]["relationship"], "duplicate")
        self.assertEqual(pairs[("ui-review-a", "ui-review-b")]["level"], "DUPLICATE")
        self.assertIn(
            pairs[("brand", "design-system")]["relationship"], {"complementary", "partial-overlap"}
        )
        self.assertNotIn(pairs[("brand", "design-system")]["level"], {"HIGH", "DUPLICATE"})
        self.assertEqual(pairs[("creator-buddy", "space-xhs-writer")]["relationship"], "parent-child")
        self.assertNotEqual(pairs[("creator-buddy", "space-xhs-writer")]["level"], "DUPLICATE")

    def test_audit_does_not_promote_shared_keyword_category_or_workflow_to_duplicate(self) -> None:
        """A keyword-only scorer would falsely remove distinct skills in the same broad domain."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        visual_database = {
            "name": "database-dashboard", "description": "", "category": "design", "parent_skill": None,
            "capabilities": ["database migration planning"], "triggers": ["plan database migration"],
            "workflow": ["analyze requirements", "produce plan"], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }
        visual_brand = {
            "name": "brand-guide", "description": "", "category": "design", "parent_skill": None,
            "capabilities": ["visual brand identity"], "triggers": ["create visual guidelines"],
            "workflow": ["analyze requirements", "produce plan"], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }

        pair = scan.compare_profiles(visual_database, visual_brand)

        self.assertNotEqual(pair["relationship"], "duplicate")
        self.assertNotIn(pair["level"], {"HIGH", "DUPLICATE"})
        self.assertLess(pair["score"], 0.40)

    def test_audit_marks_overlapping_capabilities_high_without_claiming_duplicate(self) -> None:
        """A high overlap with distinct capabilities must remain reviewable rather than collapse to duplicate."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        a = {
            "name": "frontend-design", "description": "", "category": "", "parent_skill": None,
            "capabilities": ["UI styling", "responsive layout", "component accessibility"],
            "triggers": ["improve frontend UI"], "workflow": ["review interface", "implement styles"],
            "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }
        b = {
            "name": "ui-quality", "description": "", "category": "", "parent_skill": None,
            "capabilities": ["UI styling", "responsive layout", "visual quality review"],
            "triggers": ["improve frontend UI"], "workflow": ["review interface", "recommend changes"],
            "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }

        pair = scan.compare_profiles(a, b)

        self.assertEqual(pair["relationship"], "high-overlap")
        self.assertEqual(pair["level"], "HIGH")
        self.assertIn("UI styling", pair["shared_capabilities"])
        self.assertIn("component accessibility", pair["skill_a_unique"])
        self.assertIn("visual quality review", pair["skill_b_unique"])

    def test_audit_skill_roots_uses_inventory_profiles_without_writing_skill_files(self) -> None:
        """An audit that mutates an installed SKILL.md would violate its read-only contract."""
        first = self.write_skill_markdown(
            self.agents_root,
            "first-ui-review",
            """---
name: first-ui-review
description: UI review.
---
## Capabilities
- UI accessibility review
## Triggers
- review interface accessibility
""",
        )
        self.write_skill_markdown(
            self.agents_root,
            "second-ui-review",
            """---
name: second-ui-review
description: UI review.
---
## Capabilities
- UI accessibility review
## Triggers
- review interface accessibility
""",
        )
        before = (first / "SKILL.md").read_bytes()
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")

        report = scan.audit_skill_roots([self.agents_root])

        self.assertTrue(report["read_only"])
        self.assertEqual(report["top_pairs"][0]["relationship"], "duplicate")
        self.assertEqual((first / "SKILL.md").read_bytes(), before)

    def test_audit_uses_explicit_ui_evidence_for_high_overlap_but_not_duplicate(self) -> None:
        """Ignoring real descriptions and use-case sections would create false negatives for UI skills."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        a = {
            "name": "ui-intelligence", "description": "UI UX design systems accessibility responsive layout", "category": "",
            "parent_skill": None, "capabilities": [], "triggers": ["review interface quality"],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }
        b = {
            "name": "ui-styling", "description": "accessible user interfaces design systems responsive layouts", "category": "",
            "parent_skill": None, "capabilities": [], "triggers": ["build UI components"],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }

        pair = scan.compare_profiles(a, b)

        self.assertEqual(pair["relationship"], "high-overlap")
        self.assertEqual(pair["level"], "HIGH")
        self.assertIn("UI / interface work", pair["shared_capabilities"])

    def test_audit_keeps_brand_and_design_system_below_high_when_their_evidence_differs(self) -> None:
        """Broad design vocabulary must not erase the distinct brand and token-system roles."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        brand = {
            "name": "brand", "description": "brand identity messaging voice visual guidelines", "category": "",
            "parent_skill": None, "capabilities": [], "triggers": ["define brand standards"],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }
        system = {
            "name": "design-system", "description": "design tokens CSS variables component specifications typography", "category": "",
            "parent_skill": None, "capabilities": [], "triggers": ["create design tokens"],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }

        pair = scan.compare_profiles(brand, system)

        self.assertIn(pair["relationship"], {"complementary", "partial-overlap"})
        self.assertNotIn(pair["level"], {"HIGH", "DUPLICATE"})

    def test_audit_does_not_mark_single_shared_domain_tag_as_high_overlap(self) -> None:
        """One broad domain tag, such as subtitles, cannot prove two workflows are redundant."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        editor = {
            "name": "video-edit", "description": "subtitle editing workflow", "category": "",
            "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [],
            "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }
        researcher = {
            "name": "video-topic", "description": "subtitle topic research workflow", "category": "",
            "parent_skill": None, "capabilities": [], "triggers": [], "workflow": [],
            "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }

        pair = scan.compare_profiles(editor, researcher)

        self.assertNotIn(pair["level"], {"HIGH", "DUPLICATE"})
        self.assertIn(pair["relationship"], {"complementary", "partial-overlap"})

    def test_l0_candidate_score_is_separate_from_unset_semantic_level_and_has_safe_options(self) -> None:
        """Treating a lexical candidate level as a semantic verdict would make the Gate unsafe."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        a = {
            "name": "a", "description": "", "category": "", "parent_skill": None,
            "capabilities": ["UI styling", "responsive layout"], "triggers": ["improve UI"],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }
        b = {
            "name": "b", "description": "", "category": "", "parent_skill": None,
            "capabilities": ["UI styling", "responsive layout"], "triggers": ["improve UI"],
            "workflow": [], "inputs": [], "outputs": [], "tools": [], "dependencies": [],
        }

        pair = scan.compare_profiles(a, b)

        self.assertEqual(pair["candidate_score"], pair["score"])
        self.assertEqual(pair["candidate_level"], "DUPLICATE")
        self.assertIsNone(pair["semantic_level"])
        self.assertEqual(pair["recommendation"], "possible_duplicate")
        self.assertTrue(pair["merge_candidate"] is False)
        self.assertFalse(pair["protected_relationship"])
        self.assertEqual(
            [option["action"] for option in pair["decision_options"]],
            ["keep_skill_a", "keep_skill_b", "merge_candidate"],
        )

    def test_semantic_review_builds_evidence_package_and_validates_final_result(self) -> None:
        """A semantic judgment without original Markdown evidence must not be accepted."""
        first = self.write_skill_markdown(
            self.agents_root, "first", "---\nname: first\ndescription: UI reviews\n---\n\n## When to Use\n- Review interfaces\n"
        )
        second = self.write_skill_markdown(
            self.agents_root, "second", "---\nname: second\ndescription: UI styling\n---\n\n## When to Use\n- Style interfaces\n"
        )
        semantic = self.load_script_module("semantic_review.py", "semantic_review_under_test")
        candidate = {"skill_a": "first", "skill_b": "second", "candidate_score": 0.68, "candidate_level": "HIGH"}

        package = semantic.build_review_package(candidate, {"first": first, "second": second})
        final = semantic.validate_semantic_result({
            "primary_purpose": {"skill_a": "Review UI quality", "skill_b": "Implement UI styling"},
            "core_capabilities": {"skill_a": ["UI review"], "skill_b": ["UI styling"]},
            "incidental_mentions": {"skill_a": [], "skill_b": []},
            "shared_core_capabilities": ["Interface quality"],
            "skill_a_unique": ["Review"], "skill_b_unique": ["Implementation"],
            "relationship": "partial-overlap", "confidence": 0.72,
            "reason": "Both address interfaces but have different primary work.",
            "evidence": [
                {"skill": "first", "section": "When to Use", "text": "Review interfaces"},
                {"skill": "second", "section": "When to Use", "text": "Style interfaces"}
            ],
        })

        self.assertIn("## When to Use", package["skill_a"]["skill_md"])
        self.assertEqual(final["semantic_level"], "MEDIUM")
        self.assertEqual(final["recommendation"], "review_or_keep_both")
        self.assertFalse(final["merge_candidate"])

    def test_semantic_review_keeps_parent_child_out_of_duplicate_resolution(self) -> None:
        """A model result must not override the structural parent-child safety rule."""
        semantic = self.load_script_module("semantic_review.py", "semantic_review_under_test")
        candidate = {
            "skill_a": "creator-buddy", "skill_b": "space-xhs-writer",
            "candidate_score": 0.9, "candidate_level": "DUPLICATE", "relationship": "parent-child",
        }
        result = {
            "primary_purpose": {"skill_a": "Router", "skill_b": "Writer"},
            "core_capabilities": {"skill_a": ["Route"], "skill_b": ["Write"]},
            "incidental_mentions": {"skill_a": [], "skill_b": []}, "shared_core_capabilities": [],
            "skill_a_unique": ["Route"], "skill_b_unique": ["Write"],
            "relationship": "duplicate", "confidence": 0.99, "reason": "bad model result",
            "evidence": [{"skill": "creator-buddy", "section": "Overview", "text": "routes"}],
        }

        final = semantic.apply_semantic_review(candidate, result)

        self.assertEqual(final["relationship"], "parent-child")
        self.assertEqual(final["semantic_level"], "LOW")
        self.assertEqual(final["recommendation"], "keep_both")
        self.assertTrue(final["protected_relationship"])
        self.assertFalse(final["merge_candidate"])

    def test_recommendation_policy_keeps_partial_and_high_pairs_out_of_default_merge(self) -> None:
        """Overlap alone must not turn a pair into a merge recommendation."""
        policy = self.load_script_module("recommendation_policy.py", "recommendation_policy_under_test")

        partial = policy.recommendation_for(
            "partial-overlap", "landing page design", "component implementation",
            ["UI styling"], ["art direction"], ["shadcn components"],
        )
        high = policy.recommendation_for(
            "high-overlap", "UI review", "UI implementation",
            ["UI quality", "accessibility"], ["audit checklist"], ["Tailwind delivery"],
        )

        self.assertEqual(partial["recommendation"], "review_or_keep_both")
        self.assertFalse(partial["merge_candidate"])
        self.assertEqual(high["recommendation"], "manual_review")
        self.assertFalse(high["merge_candidate"])

    def test_recommendation_policy_protects_parent_child_and_keeps_complementary_pairs(self) -> None:
        """Structural and complementary relationships must never emit destructive advice."""
        policy = self.load_script_module("recommendation_policy.py", "recommendation_policy_under_test")

        parent = policy.recommendation_for("parent-child", "router", "writer", [], ["route"], ["write"])
        complementary = policy.recommendation_for("complementary", "brand identity", "design tokens", [], ["voice"], ["CSS"])
        unrelated = policy.recommendation_for("unrelated", "web research", "video production", [], ["search"], ["edit"])

        self.assertEqual(parent["recommendation"], "keep_both")
        self.assertTrue(parent["protected_relationship"])
        self.assertEqual(complementary["recommendation"], "keep_both")
        self.assertEqual(unrelated["recommendation"], "keep_both")

    def test_recommendation_policy_only_marks_merge_candidate_for_nearly_identical_purposes(self) -> None:
        """Merge requires high bilateral core coverage and almost no unique work."""
        policy = self.load_script_module("recommendation_policy.py", "recommendation_policy_under_test")

        decision = policy.recommendation_for(
            "duplicate", "UI accessibility review", "UI accessibility review",
            ["UI review", "accessibility"], [], [],
        )

        self.assertEqual(decision["recommendation"], "merge_candidate")
        self.assertTrue(decision["merge_candidate"])

    def test_functional_report_sorts_by_candidate_then_confidence_and_excludes_parent_child(self) -> None:
        """Structural relations must not consume functional-overlap ranking slots."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        pairs = [
            {"skill_a": "low", "skill_b": "x", "candidate_score": 0.17, "score": 0.17, "relationship": "complementary", "confidence": 0.99},
            {"skill_a": "high", "skill_b": "x", "candidate_score": 0.68, "score": 0.68, "relationship": "partial-overlap", "confidence": 0.10},
            {"skill_a": "middle", "skill_b": "x", "candidate_score": 0.43, "score": 0.43, "relationship": "high-overlap", "confidence": 0.88},
            {"skill_a": "tie-low-confidence", "skill_b": "x", "candidate_score": 0.64, "score": 0.64, "relationship": "partial-overlap", "confidence": 0.20},
            {"skill_a": "tie-high-confidence", "skill_b": "x", "candidate_score": 0.64, "score": 0.64, "relationship": "unrelated", "confidence": 0.90},
            {"skill_a": "creator-buddy", "skill_b": "space-video", "candidate_score": 0.99, "score": 0.99, "relationship": "parent-child", "confidence": 1.0, "protected_relationship": True, "recommendation": "keep_both"},
        ]

        report = scan.build_audit_report(pairs, top=5)

        self.assertEqual(
            [pair["candidate_score"] for pair in report["top_functional_overlap"]],
            [0.68, 0.64, 0.64, 0.43, 0.17],
        )
        self.assertEqual(
            [pair["skill_a"] for pair in report["top_functional_overlap"][:3]],
            ["high", "tie-high-confidence", "tie-low-confidence"],
        )
        self.assertEqual(report["structural_relationships"][0]["skill_a"], "creator-buddy")
        self.assertTrue(report["structural_relationships"][0]["protected_relationship"])
        self.assertEqual(report["structural_relationships"][0]["recommendation"], "keep_both")
        self.assertNotIn("creator-buddy", [pair["skill_a"] for pair in report["top_functional_overlap"]])

    def test_semantic_level_does_not_reorder_functional_candidates(self) -> None:
        """Semantic conclusions explain a candidate; they do not replace ranking evidence."""
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        pairs = [
            {"skill_a": "a", "skill_b": "b", "candidate_score": 0.68, "score": 0.68, "relationship": "partial-overlap", "semantic_level": "MEDIUM", "confidence": 0.1},
            {"skill_a": "c", "skill_b": "d", "candidate_score": 0.43, "score": 0.43, "relationship": "high-overlap", "semantic_level": "HIGH", "confidence": 0.99},
        ]

        report = scan.build_audit_report(pairs)

        self.assertEqual([pair["skill_a"] for pair in report["top_functional_overlap"]], ["a", "c"])

    def test_decision_registry_normalizes_pair_and_supports_crud(self) -> None:
        """Reversed skill order must update one decision, not create conflicting records."""
        registry_module = self.load_script_module("decision_registry.py", "decision_registry_under_test")
        registry = registry_module.DecisionRegistry(self.root / "decisions.json")

        created = registry.set(
            "z-skill", "a-skill", "hash-z", "hash-a", "complementary", "keep_both",
            "Distinct responsibilities", ignore_future_warning=True,
        )
        updated = registry.set(
            "a-skill", "z-skill", "hash-a", "hash-z", "complementary", "ignore",
            "User confirmed", ignore_future_warning=True,
        )

        self.assertEqual(created["skill_a"], "a-skill")
        self.assertEqual(updated["decision"], "ignore")
        self.assertEqual(len(registry.list()), 1)
        self.assertTrue(registry.remove("z-skill", "a-skill"))
        self.assertEqual(registry.list(), [])

    def test_decision_registry_marks_hash_change_stale_without_authorizing_execution(self) -> None:
        """A preference must expire after content changes and never become a delete authority."""
        registry_module = self.load_script_module("decision_registry.py", "decision_registry_under_test")
        registry = registry_module.DecisionRegistry(self.root / "decisions.json")
        registry.set("brand", "design-system", "hash-brand", "hash-system", "complementary", "keep_both", "", True)

        confirmed = registry.status_for("brand", "design-system", "hash-brand", "hash-system")
        stale = registry.status_for("brand", "design-system", "hash-brand", "changed-system")

        self.assertEqual(confirmed["decision_status"], "confirmed")
        self.assertTrue(confirmed["warning_suppressed"])
        self.assertEqual(stale["decision_status"], "stale")
        self.assertTrue(stale["decision_stale"])
        self.assertFalse(stale["warning_suppressed"])
        self.assertNotIn("execution", stale)

    def test_decision_registry_keeps_preferred_skill_when_pair_is_reversed(self) -> None:
        """Canonical sorting must not silently reverse a user's preferred skill."""
        registry_module = self.load_script_module("decision_registry.py", "decision_registry_under_test")
        registry = registry_module.DecisionRegistry(self.root / "decisions.json")

        record = registry.set(
            "z-skill", "a-skill", "hash-z", "hash-a", "partial-overlap", "preferred_a", "",
        )

        self.assertEqual(record["skill_a"], "a-skill")
        self.assertEqual(record["decision"], "preferred_b")

    def test_audit_attaches_confirmed_and_stale_decision_status_without_hiding_pairs(self) -> None:
        """Ignoring a warning must preserve the pair in the complete read-only report."""
        registry_module = self.load_script_module("decision_registry.py", "decision_registry_under_test")
        registry = registry_module.DecisionRegistry(self.root / "decisions.json")
        registry.set("brand", "design-system", "hash-brand", "hash-system", "complementary", "keep_both", "", True)
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        pair = {"skill_a": "brand", "skill_b": "design-system", "skill_a_hash": "hash-brand", "skill_b_hash": "hash-system", "relationship": "complementary", "candidate_score": 0.2, "score": 0.2}

        annotated = scan.attach_decision_status([pair], registry)[0]

        self.assertEqual(annotated["decision"], "keep_both")
        self.assertEqual(annotated["decision_status"], "confirmed")
        self.assertTrue(annotated["warning_suppressed"])

    def test_confirmed_ignore_decision_suppresses_warning_but_keeps_complete_pair(self) -> None:
        """A confirmed keep-both choice leaves evidence visible but removes repeat review noise."""
        registry_module = self.load_script_module("decision_registry.py", "decision_registry_under_test")
        registry = registry_module.DecisionRegistry(self.root / "decisions.json")
        registry.set("a", "b", "hash-a", "hash-b", "high-overlap", "keep_both", "", True)
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")
        pair = {
            "skill_a": "a", "skill_b": "b", "skill_a_hash": "hash-a", "skill_b_hash": "hash-b",
            "candidate_score": 0.8, "score": 0.8, "relationship": "high-overlap",
        }

        report = scan.build_audit_report(scan.attach_decision_status([pair], registry))

        self.assertEqual(len(report["pairs"]), 1)
        self.assertTrue(report["pairs"][0]["warning_suppressed"])
        self.assertEqual(report["high_or_duplicate_review"], [])

    def test_audit_without_decisions_marks_pairs_pending_without_creating_registry(self) -> None:
        """A normal audit must remain read-only even when no registry exists yet."""
        self.write_skill(self.agents_root, "alpha", "alpha", "Write product copy")
        self.write_skill(self.agents_root, "beta", "beta", "Generate product headlines")
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")

        report = scan.audit_skill_roots([self.agents_root])

        self.assertEqual(len(report["pairs"]), 1)
        self.assertEqual(report["pairs"][0]["decision_status"], "pending")
        self.assertFalse((self.root / "decisions.json").exists())

    def test_audit_binds_decision_status_to_inventory_content_hashes(self) -> None:
        """Changing an installed SKILL.md must stale its previously confirmed audit decision."""
        first = self.write_skill(self.agents_root, "alpha", "alpha", "Write product copy")
        second = self.write_skill(self.agents_root, "beta", "beta", "Generate product headlines")
        inventory = self.load_inventory_module()
        parser = self.load_script_module("capability_parser.py", "capability_parser_under_test")
        registry_module = self.load_script_module("decision_registry.py", "decision_registry_under_test")
        scan = self.load_script_module("duplicate_scan.py", "duplicate_scan_under_test")

        def profiles_with_hashes():
            records = inventory.discover_skills([self.agents_root])
            profiles = []
            for record in records:
                profile = parser.parse_capability_profile(Path(record["path"]), record["parent_skill"])
                profile["content_hash"] = record["content_hash"]
                profiles.append(profile)
            return profiles

        original = profiles_with_hashes()
        hashes = {profile["name"]: profile["content_hash"] for profile in original}
        registry = registry_module.DecisionRegistry(self.root / "decisions.json")
        registry.set("alpha", "beta", hashes["alpha"], hashes["beta"], "complementary", "keep_both", "", True)

        confirmed = scan.audit_profiles(original, registry=registry)["pairs"][0]
        second.joinpath("SKILL.md").write_text("---\nname: beta\ndescription: Changed scope\n---\n", encoding="utf-8")
        stale = scan.audit_profiles(profiles_with_hashes(), registry=registry)["pairs"][0]

        self.assertEqual(confirmed["decision_status"], "confirmed")
        self.assertEqual(stale["decision_status"], "stale")
        self.assertTrue(stale["decision_stale"])

    def test_semantic_review_accepts_cross_language_evidence_and_uncertain_fallback(self) -> None:
        """Language differences must not block an evidence-backed high overlap or an uncertain result."""
        semantic = self.load_script_module("semantic_review.py", "semantic_review_under_test")
        cross_language = semantic.validate_semantic_result({
            "primary_purpose": {"skill_a": "前端视觉优化", "skill_b": "frontend visual refinement"},
            "core_capabilities": {"skill_a": ["界面视觉优化"], "skill_b": ["frontend visual refinement"]},
            "incidental_mentions": {"skill_a": [], "skill_b": []}, "shared_core_capabilities": ["frontend visual refinement"],
            "skill_a_unique": [], "skill_b_unique": [], "relationship": "high-overlap", "confidence": 0.84,
            "reason": "Same primary responsibility in Chinese and English.",
            "evidence": [{"skill": "a", "section": "功能", "text": "前端视觉优化"}, {"skill": "b", "section": "Capabilities", "text": "frontend visual refinement"}],
        })
        uncertain = semantic.validate_semantic_result({
            "primary_purpose": {"skill_a": "mixed", "skill_b": "mixed"}, "core_capabilities": {"skill_a": [], "skill_b": []},
            "incidental_mentions": {"skill_a": ["video"], "skill_b": ["video"]}, "shared_core_capabilities": [],
            "skill_a_unique": [], "skill_b_unique": [], "relationship": "uncertain", "confidence": 0.30,
            "reason": "Only incidental evidence is available.", "evidence": [{"skill": "a", "section": "References", "text": "video"}],
        })
        shared_keyword_different_work = semantic.validate_semantic_result({
            "primary_purpose": {"skill_a": "discover installable skills", "skill_b": "search public content"},
            "core_capabilities": {"skill_a": ["find agent capabilities"], "skill_b": ["retrieve platform posts"]},
            "incidental_mentions": {"skill_a": [], "skill_b": []}, "shared_core_capabilities": [],
            "skill_a_unique": ["skill installation"], "skill_b_unique": ["content retrieval"],
            "relationship": "unrelated", "confidence": 0.88,
            "reason": "Both say search, but their outputs and primary work differ.",
            "evidence": [{"skill": "a", "section": "Triggers", "text": "find a skill"}, {"skill": "b", "section": "功能", "text": "内容搜索"}],
        })
        mixed_language = semantic.validate_semantic_result({
            "primary_purpose": {"skill_a": "前端 visual refinement", "skill_b": "frontend UI implementation"},
            "core_capabilities": {"skill_a": ["视觉审查"], "skill_b": ["component styling"]},
            "incidental_mentions": {"skill_a": [], "skill_b": []}, "shared_core_capabilities": ["frontend visual work"],
            "skill_a_unique": ["art direction"], "skill_b_unique": ["shadcn components"],
            "relationship": "partial-overlap", "confidence": 0.76,
            "reason": "Mixed-language evidence identifies overlapping frontend work with distinct implementation scope.",
            "evidence": [{"skill": "a", "section": "功能", "text": "前端 visual refinement"}, {"skill": "b", "section": "Capabilities", "text": "frontend UI implementation"}],
        })

        self.assertEqual(cross_language["semantic_level"], "HIGH")
        self.assertEqual(uncertain["recommendation"], "manual_review")
        self.assertEqual(shared_keyword_different_work["relationship"], "unrelated")
        self.assertEqual(shared_keyword_different_work["recommendation"], "keep_both")
        self.assertEqual(mixed_language["relationship"], "partial-overlap")

    def test_semantic_review_rejects_high_overlap_based_only_on_incidental_mentions(self) -> None:
        """A shared referenced tool or keyword is not enough evidence for HIGH overlap."""
        semantic = self.load_script_module("semantic_review.py", "semantic_review_under_test")
        result = {
            "primary_purpose": {"skill_a": "web research", "skill_b": "video production"},
            "core_capabilities": {"skill_a": ["search sources"], "skill_b": ["edit footage"]},
            "incidental_mentions": {"skill_a": ["video"], "skill_b": ["video"]},
            "shared_core_capabilities": [], "skill_a_unique": ["search"], "skill_b_unique": ["edit"],
            "relationship": "high-overlap", "confidence": 0.75,
            "reason": "Both documents mention video.",
            "evidence": [{"skill": "a", "section": "References", "text": "YouTube video search"}],
        }

        with self.assertRaisesRegex(ValueError, "shared core capabilities"):
            semantic.validate_semantic_result(result)

    def test_semantic_review_validates_generalist_specialist_scope(self) -> None:
        """A broad coordinator and a specialist need an explicit, bounded scope relation."""
        semantic = self.load_script_module("semantic_review.py", "semantic_review_under_test")
        result = {
            "primary_purpose": {"skill_a": "comprehensive design coordination", "skill_b": "banner production"},
            "core_capabilities": {"skill_a": ["coordinate design"], "skill_b": ["create banners"]},
            "incidental_mentions": {"skill_a": [], "skill_b": []},
            "shared_core_capabilities": ["visual design"], "skill_a_unique": ["brand", "slides"],
            "skill_b_unique": ["ad formats"], "relationship": "partial-overlap", "confidence": 0.79,
            "reason": "The generalist routes a wider surface than the specialist executes.",
            "evidence": [{"skill": "a", "section": "Description", "text": "brand and banners"}],
            "scope_relationship": "not-a-scope",
        }

        with self.assertRaisesRegex(ValueError, "scope relationship"):
            semantic.validate_semantic_result(result)


if __name__ == "__main__":
    unittest.main()
