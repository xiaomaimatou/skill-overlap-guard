from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path


SKILL_MANAGER = Path(__file__).resolve().parents[1]


class SkillManagerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skills_root = self.root / "skills"
        self.manager = self.skills_root / "skills-manager"
        self.skills_root.mkdir()
        shutil.copytree(SKILL_MANAGER / "scripts", self.manager / "scripts")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_skill(self, name: str, description: str = "Example skill") -> Path:
        skill_dir = self.skills_root / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
            encoding="utf-8",
        )
        return skill_dir

    def write_sources(self, skills: dict) -> None:
        (self.manager / "sources.json").write_text(
            json.dumps({"version": 1, "skills": skills}, indent=2) + "\n",
            encoding="utf-8",
        )

    def run_script(self, script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.manager / "scripts" / script), *args],
            cwd=str(self.manager),
            capture_output=True,
            text=True,
            check=check,
        )

    def make_remote_repo(self, skill_name: str = "git-skill") -> tuple[Path, str]:
        repo = self.root / "remote-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
        skill_dir = repo / "skills" / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: Remote skill\n---\n\n# Remote\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return repo, sha

    def test_inventory_marks_local_status_as_local(self) -> None:
        self.write_skill("private-skill")
        self.write_sources({"private-skill": {}})

        result = self.run_script("inventory.py", "--check-remote")
        rows = json.loads(result.stdout)

        self.assertEqual(rows[0]["type"], "local")
        self.assertEqual(rows[0]["update_status"], "local")
        self.assertNotIn("current_content_hash", rows[0])
        self.assertNotIn("modified_locally", rows[0])

    def _load_inventory_module(self):
        for cached in ("_common", "check_remote", "inventory_under_test"):
            sys.modules.pop(cached, None)
        sys.path.insert(0, str(self.manager / "scripts"))
        try:
            spec = importlib.util.spec_from_file_location(
                "inventory_under_test",
                self.manager / "scripts" / "inventory.py",
            )
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def _run_inventory_module(self, mod, argv: list[str]) -> dict | list:
        from io import StringIO
        cwd = os.getcwd()
        os.chdir(self.manager)
        original_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            mod.main(argv)
            return json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = original_stdout
            os.chdir(cwd)

    def test_inventory_audit_unclaimed_returns_envelope_with_audit_result(self) -> None:
        self.write_skill("unknown-skill")
        self.write_sources({})
        mod = self._load_inventory_module()

        def _fake_run_audit(dry_run: bool = False):
            self.assertFalse(dry_run)
            return {
                "summary": {
                    "auto_claimed": 1,
                    "needs_review": 0,
                    "no_match": 0,
                    "search_used": False,
                    "search_disabled_reason": "gh unavailable",
                },
                "reports": [{"name": "unknown-skill", "decision": "auto_claim"}],
                "inventory_after": [{
                    "name": "unknown-skill",
                    "path": str(self.skills_root / "unknown-skill"),
                    "has_skill_md": True,
                    "description": "Example skill",
                    "claimed": True,
                    "type": "remote",
                    "source": {"url": "https://github.com/example/unknown-skill"},
                    "update_status": "update_available",
                    "remote_revision": "abc123",
                    "check_error": None,
                }],
            }

        sys.modules["audit_unclaimed"] = types.SimpleNamespace(run_audit=_fake_run_audit)
        try:
            payload = self._run_inventory_module(
                mod, ["inventory.py", "--check-remote", "--audit-unclaimed"]
            )
        finally:
            sys.modules.pop("audit_unclaimed", None)

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["entries"][0]["type"], "remote")
        self.assertEqual(payload["audit"]["ran"], True)
        self.assertEqual(payload["audit"]["auto_claimed"], 1)
        self.assertEqual(payload["audit"]["needs_review"], 0)
        self.assertEqual(payload["audit"]["no_match"], 0)
        self.assertEqual(payload["audit"]["search_disabled_reason"], "gh unavailable")

    def test_inventory_audit_unclaimed_skips_audit_when_everything_is_claimed(self) -> None:
        self.write_skill("private-skill")
        self.write_sources({"private-skill": {}})
        mod = self._load_inventory_module()

        def _should_not_call(*_a, **_k):
            raise AssertionError("audit should not run when inventory has no unclaimed skills")

        sys.modules["audit_unclaimed"] = types.SimpleNamespace(run_audit=_should_not_call)
        try:
            payload = self._run_inventory_module(
                mod, ["inventory.py", "--check-remote", "--audit-unclaimed"]
            )
        finally:
            sys.modules.pop("audit_unclaimed", None)

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["entries"][0]["type"], "local")
        self.assertEqual(payload["audit"], {"ran": False})

    def test_claim_remote_does_not_write_installed_content_hash(self) -> None:
        self.write_skill("git-skill")
        self.write_sources({})

        result = self.run_script(
            "sources.py",
            "claim-remote",
            "git-skill",
            "--url",
            "https://example.com/repo.git",
            "--branch",
            "main",
            "--subpath",
            "skills/git-skill",
            "--no-resolve",
            "--assume-revision",
            "abc123",
        )
        payload = json.loads(result.stdout)
        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))

        self.assertNotIn("installed_content_hash", payload)
        self.assertNotIn("installed_content_hash", sources["skills"]["git-skill"])

    def test_update_skill_requires_revision_not_content_hash_and_removes_stale_hash(self) -> None:
        remote, sha = self.make_remote_repo("git-skill")
        self.write_skill("git-skill", "Old local copy")
        self.write_sources({
            "git-skill": {
                "url": str(remote),
                "branch": "main",
                "subpath": "skills/git-skill",
                "installed_revision": "old-sha",
                "installed_content_hash": "sha256:legacy",
            }
        })

        result = self.run_script("update_skill.py", "git-skill")
        payload = json.loads(result.stdout)
        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))

        self.assertTrue(payload["updated"])
        self.assertEqual(payload["new_revision"], sha)
        self.assertNotIn("new_content_hash", payload)
        self.assertNotIn("forced", payload)
        self.assertNotIn("installed_content_hash", sources["skills"]["git-skill"])

    def test_update_skill_accepts_missing_installed_revision(self) -> None:
        """A claimed-remote record without installed_revision means the
        previous claim recorded a content mismatch; update_skill must still
        run (overwriting the local copy with upstream HEAD) and write the
        revision after the swap. This is the self-healing path."""
        remote, sha = self.make_remote_repo("git-skill")
        self.write_skill("git-skill", "Old local copy")
        self.write_sources({
            "git-skill": {
                "url": str(remote),
                "branch": "main",
                "subpath": "skills/git-skill",
            }
        })

        result = self.run_script("update_skill.py", "git-skill")
        payload = json.loads(result.stdout)
        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))

        self.assertTrue(payload["updated"])
        self.assertIsNone(payload["old_revision"])
        self.assertEqual(payload["new_revision"], sha)
        self.assertEqual(sources["skills"]["git-skill"]["installed_revision"], sha)

    def test_common_no_longer_exposes_hash_directory(self) -> None:
        spec = importlib.util.spec_from_file_location("_common_under_test", self.manager / "scripts" / "_common.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertFalse(hasattr(module, "hash_directory"))


class VersionAlignmentTests(SkillManagerContractTests):
    """Cross-cutting tests for the 'installed_revision must reflect actual
    content alignment' contract. claim/audit only record a real SHA when
    local SKILL.md content matches upstream HEAD; otherwise they record null,
    and downstream tools (inventory, check_remote, update_skill) treat null
    as 'needs update'."""

    def test_claim_remote_records_revision_when_content_matches(self) -> None:
        upstream_text = "---\nname: aligned\ndescription: matches.\n---\n\n# Body\n"
        sd = self.write_skill("aligned")
        (sd / "SKILL.md").write_text(upstream_text, encoding="utf-8")
        remote, sha = self.make_remote_repo("aligned")
        # Overwrite the remote SKILL.md to match local exactly.
        rmd = remote / "skills" / "aligned" / "SKILL.md"
        rmd.write_text(upstream_text, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=remote, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "align"], cwd=remote, check=True, capture_output=True)
        new_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=remote, check=True,
                                  capture_output=True, text=True).stdout.strip()
        self.write_sources({})

        # We can't easily mock fetch_remote_skill_md through subprocess, so we
        # patch the sources module in-process. (raw.githubusercontent.com
        # obviously can't serve from a local file:// remote.)
        sys.modules.pop("_common", None)
        sys.path.insert(0, str(self.manager / "scripts"))
        try:
            import sources as sources_mod  # type: ignore
            import _common
            _common.fetch_remote_skill_md = lambda _u, _b, _s, timeout=15: (upstream_text, None)
            sources_mod.fetch_remote_skill_md = _common.fetch_remote_skill_md
            sources_mod.resolve_remote_revision = lambda _u, _b: new_sha
            from io import StringIO
            cwd = os.getcwd()
            os.chdir(self.manager)
            sys.stdout = StringIO()
            try:
                sources_mod.main([
                    "sources.py", "claim-remote", "aligned",
                    "--url", str(remote), "--branch", "main",
                    "--subpath", "skills/aligned",
                ])
                payload = json.loads(sys.stdout.getvalue())
            finally:
                sys.stdout = sys.__stdout__
                os.chdir(cwd)
        finally:
            sys.path.pop(0)
            for cached in ("sources", "_common"):
                sys.modules.pop(cached, None)

        self.assertEqual(payload["installed_revision"], new_sha)
        self.assertIn("matches", payload["verify_note"])

    def test_claim_remote_records_null_when_content_differs(self) -> None:
        local_text = "---\nname: drift\ndescription: local edited.\n---\n\n# Old body\n"
        upstream_text = "---\nname: drift\ndescription: upstream new.\n---\n\n# New body with many words different from local copy\n"
        sd = self.write_skill("drift")
        (sd / "SKILL.md").write_text(local_text, encoding="utf-8")
        self.write_sources({})

        sys.modules.pop("_common", None)
        sys.path.insert(0, str(self.manager / "scripts"))
        try:
            import sources as sources_mod  # type: ignore
            import _common
            _common.fetch_remote_skill_md = lambda _u, _b, _s, timeout=15: (upstream_text, None)
            sources_mod.fetch_remote_skill_md = _common.fetch_remote_skill_md
            sources_mod.resolve_remote_revision = lambda _u, _b: "deadbeef" * 5
            from io import StringIO
            cwd = os.getcwd()
            os.chdir(self.manager)
            sys.stdout = StringIO()
            try:
                sources_mod.main([
                    "sources.py", "claim-remote", "drift",
                    "--url", "https://github.com/x/y", "--branch", "main",
                    "--subpath", "skills/drift",
                ])
                payload = json.loads(sys.stdout.getvalue())
            finally:
                sys.stdout = sys.__stdout__
                os.chdir(cwd)
        finally:
            sys.path.pop(0)
            for cached in ("sources", "_common"):
                sys.modules.pop(cached, None)

        self.assertIsNone(payload["installed_revision"])
        self.assertIn("differs", payload["verify_note"])
        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        self.assertIsNone(sources["skills"]["drift"]["installed_revision"])

    def test_inventory_treats_null_revision_as_update_available(self) -> None:
        """Once a remote claim has null installed_revision, inventory must
        surface it as 'update_available' (not 'unknown'), so the user is
        prompted to re-align rather than thinking everything is fine."""
        self.write_skill("misaligned")
        remote, _sha = self.make_remote_repo("misaligned")
        self.write_sources({
            "misaligned": {
                "url": str(remote),
                "branch": "main",
                "subpath": "skills/misaligned",
                "installed_revision": None,
            }
        })

        result = self.run_script("inventory.py", "--check-remote")
        rows = json.loads(result.stdout)

        row = next(r for r in rows if r["name"] == "misaligned")
        self.assertEqual(row["update_status"], "update_available")


class InstallSkillTests(SkillManagerContractTests):
    """End-to-end checks for install_skill.py."""

    def _load_install_module(self):
        for cached in ("_common", "install_skill_under_test"):
            sys.modules.pop(cached, None)
        sys.path.insert(0, str(self.manager / "scripts"))
        try:
            spec = importlib.util.spec_from_file_location(
                "install_skill_under_test",
                self.manager / "scripts" / "install_skill.py",
            )
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def test_parse_url_tree_form(self) -> None:
        mod = self._load_install_module()
        out = mod.parse_github_url("https://github.com/obra/superpowers/tree/main/skills/brainstorming")
        self.assertEqual(out, {
            "repo_url": "https://github.com/obra/superpowers",
            "branch": "main",
            "subpath": "skills/brainstorming",
        })

    def test_parse_url_blob_strips_skill_md(self) -> None:
        mod = self._load_install_module()
        out = mod.parse_github_url("https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md")
        self.assertEqual(out["subpath"], "skills/brainstorming")
        self.assertEqual(out["branch"], "main")

    def test_parse_url_raw_form(self) -> None:
        mod = self._load_install_module()
        out = mod.parse_github_url("https://raw.githubusercontent.com/obra/superpowers/main/skills/brainstorming/SKILL.md")
        self.assertEqual(out["repo_url"], "https://github.com/obra/superpowers")
        self.assertEqual(out["branch"], "main")
        self.assertEqual(out["subpath"], "skills/brainstorming")

    def test_parse_url_repo_only_defers_branch(self) -> None:
        mod = self._load_install_module()
        out = mod.parse_github_url("https://github.com/obra/superpowers.git")
        self.assertEqual(out, {
            "repo_url": "https://github.com/obra/superpowers",
            "branch": None,
            "subpath": "",
        })

    def test_parse_url_ssh_form(self) -> None:
        mod = self._load_install_module()
        out = mod.parse_github_url("git@github.com:obra/superpowers.git")
        self.assertEqual(out["repo_url"], "https://github.com/obra/superpowers")
        self.assertIsNone(out["branch"])

    def test_parse_url_rejects_unknown_host(self) -> None:
        mod = self._load_install_module()
        with self.assertRaises(SystemExit) as cm:
            mod.parse_github_url("https://gitlab.com/foo/bar")
        self.assertEqual(cm.exception.code, 2)

    def _run_install_inproc(self, repo_path: Path, subpath: str = "skills/git-skill",
                              extra_args: list[str] | None = None) -> dict:
        """Call install_skill.main() in-process, with parse_github_url stubbed
        to return a (repo_path, branch, subpath) record. This isolates the
        install/registration flow from the URL parser (which is unit-tested
        separately and only accepts real GitHub URLs)."""
        mod = self._load_install_module()
        original = mod.parse_github_url
        mod.parse_github_url = lambda _url: {
            "repo_url": str(repo_path),
            "branch": "main",
            "subpath": subpath,
        }
        argv = ["install_skill.py", "ignored://stubbed", *(extra_args or [])]
        captured: list[str] = []
        original_stdout = sys.stdout
        from io import StringIO
        sys.stdout = StringIO()
        try:
            mod.main(argv)
            captured.append(sys.stdout.getvalue())
        finally:
            sys.stdout = original_stdout
            mod.parse_github_url = original
        return json.loads(captured[0])

    def test_install_end_to_end_registers_sources(self) -> None:
        remote, sha = self.make_remote_repo("git-skill")
        self.write_sources({})

        cwd = os.getcwd()
        os.chdir(self.manager)
        try:
            payload = self._run_install_inproc(remote)
        finally:
            os.chdir(cwd)

        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["installed"], "git-skill")
        self.assertEqual(payload["installed_revision"], sha)
        self.assertIsNone(payload["backup"])

        rec = sources["skills"]["git-skill"]
        self.assertEqual(rec["branch"], "main")
        self.assertEqual(rec["subpath"], "skills/git-skill")
        self.assertEqual(rec["installed_revision"], sha)
        self.assertNotIn("installed_content_hash", rec)
        self.assertTrue((self.skills_root / "git-skill" / "SKILL.md").is_file())

    def test_install_backs_up_existing_skill(self) -> None:
        remote, _sha = self.make_remote_repo("git-skill")
        self.write_skill("git-skill", "old description")
        self.write_sources({})

        cwd = os.getcwd()
        os.chdir(self.manager)
        try:
            payload = self._run_install_inproc(remote)
        finally:
            os.chdir(cwd)

        self.assertIsNotNone(payload["backup"])
        backup = Path(payload["backup"])
        self.assertTrue(backup.is_dir())
        self.assertIn("old description", (backup / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("Remote skill", (self.skills_root / "git-skill" / "SKILL.md").read_text(encoding="utf-8"))


class AuditUnclaimedTests(SkillManagerContractTests):
    """Audit script: .git detection + whitelist + similarity."""

    def _load_audit_module(self):
        for cached in ("_common", "similarity", "check_remote", "gh_search", "inventory", "audit_under_test"):
            sys.modules.pop(cached, None)
        sys.path.insert(0, str(self.manager / "scripts"))
        try:
            spec = importlib.util.spec_from_file_location(
                "audit_under_test",
                self.manager / "scripts" / "audit_unclaimed.py",
            )
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def _run_audit(self, dry_run: bool = False) -> dict:
        from io import StringIO
        cwd = os.getcwd()
        os.chdir(self.manager)
        original_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            mod = self._load_audit_module()
            argv = ["audit_unclaimed.py"]
            if dry_run:
                argv.append("--dry-run")
            mod.main(argv)
            return json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = original_stdout
            os.chdir(cwd)

    def test_git_dir_detection_auto_claims(self) -> None:
        # The skill directory IS itself a fresh git checkout pointing at github.com.
        skill_dir = self.skills_root / "git-dir-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: git-dir-skill\ndescription: x\n---\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-b", "main"], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=skill_dir, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=skill_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/git-dir-skill.git"],
            cwd=skill_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=skill_dir, check=True, capture_output=True)
        self.write_sources({})

        payload = self._run_audit()

        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        rec = sources["skills"]["git-dir-skill"]

        self.assertEqual(rec["url"], "https://github.com/example/git-dir-skill")
        self.assertEqual(rec["branch"], "main")
        self.assertEqual(rec["subpath"], "")
        self.assertTrue(rec["installed_revision"])
        self.assertEqual(payload["summary"]["auto_claimed"], 1)

    def test_git_dir_with_ssh_remote_normalizes(self) -> None:
        skill_dir = self.skills_root / "ssh-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: ssh-skill\ndescription: x\n---\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=skill_dir, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=skill_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:example/ssh-skill.git"],
            cwd=skill_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=skill_dir, check=True, capture_output=True)
        self.write_sources({})

        self._run_audit()

        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(sources["skills"]["ssh-skill"]["url"], "https://github.com/example/ssh-skill")

    def test_git_dir_with_non_github_remote_is_unsupported(self) -> None:
        skill_dir = self.skills_root / "gitlab-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: gitlab-skill\ndescription: x\n---\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=skill_dir, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=skill_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://gitlab.com/example/gitlab-skill.git"],
            cwd=skill_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=skill_dir, check=True, capture_output=True)
        self.write_sources({})

        payload = self._run_audit()

        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        self.assertNotIn("gitlab-skill", sources["skills"])
        self.assertEqual(payload["summary"]["git_remote_unsupported"], 1)

    def test_embedded_github_url_auto_claims_before_whitelist(self) -> None:
        upstream_text = "---\nname: embedded\ndescription: traced from body\n---\n\n# Embedded\n\nbody body.\n"
        local_text = (
            upstream_text
            + "\nOriginal source: https://github.com/source/repo/blob/main/skills/embedded/SKILL.md\n"
        )
        sd = self.write_skill("embedded")
        (sd / "SKILL.md").write_text(local_text, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: False
        mod.fetch_remote_skill_md = lambda _u, _b, _s, timeout=15: (local_text, None)
        mod.fetch_remote_sha = lambda _u, _b: ("c0ffee" * 6, None)

        from io import StringIO
        cwd = os.getcwd()
        os.chdir(self.manager)
        sys.stdout = StringIO()
        try:
            mod.main(["audit_unclaimed.py"])
            payload = json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = sys.__stdout__
            os.chdir(cwd)

        rep = next(r for r in payload["reports"] if r["name"] == "embedded")
        self.assertEqual(rep["method"], "embedded_url")
        self.assertEqual(rep["decision"], "auto_claim")
        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        rec = sources["skills"]["embedded"]
        self.assertEqual(rec["url"], "https://github.com/source/repo")
        self.assertEqual(rec["branch"], "main")
        self.assertEqual(rec["subpath"], "skills/embedded")
        self.assertEqual(rec["installed_revision"], "c0ffee" * 6)

    def test_whitelist_high_confidence_auto_claims(self) -> None:
        # Identical SKILL.md text upstream + locally => similarity = 1.0 = "high".
        skill_text = "---\nname: faux-skill\ndescription: hello\n---\n\n# Faux\n\nbody body body.\n"
        skill_dir = self.write_skill("faux-skill", "hello")
        skill_dir.joinpath("SKILL.md").write_text(skill_text, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = [{
            "url": "https://github.com/fake/repo",
            "branch": "main",
            "subpath_template": "skills/{name}",
        }]
        mod.fetch_remote_skill_md = lambda _u, _b, _s, timeout=15: (skill_text, None)
        mod.fetch_remote_sha = lambda _u, _b: ("deadbeef" * 5, None)

        from io import StringIO
        cwd = os.getcwd()
        os.chdir(self.manager)
        sys.stdout = StringIO()
        try:
            mod.main(["audit_unclaimed.py"])
            payload = json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = sys.__stdout__
            os.chdir(cwd)

        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        rec = sources["skills"]["faux-skill"]
        self.assertEqual(rec["url"], "https://github.com/fake/repo")
        self.assertEqual(rec["subpath"], "skills/faux-skill")
        self.assertEqual(rec["installed_revision"], "deadbeef" * 5)
        self.assertEqual(payload["summary"]["auto_claimed"], 1)

    def test_whitelist_high_but_not_exact_records_null_revision(self) -> None:
        """similarity in [0.90, 1.0) is enough to auto-claim the source repo,
        but installed_revision must be null — local content is NOT the
        upstream HEAD bytes, so recording HEAD would lie."""
        local_text = "---\nname: drifted\ndescription: x\n---\n\n# Local\n\nbody body body body body body.\n"
        # Same structure but enough word-level difference to drop similarity
        # below 1.0 yet keep it >=0.90 ("high" confidence on the source).
        upstream_text = "---\nname: drifted\ndescription: x\n---\n\n# Local\n\nbody body body body body body extra.\n"
        sd = self.write_skill("drifted")
        (sd / "SKILL.md").write_text(local_text, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = [{
            "url": "https://github.com/fake/repo",
            "branch": "main",
            "subpath_template": "skills/{name}",
        }]
        mod.fetch_remote_skill_md = lambda _u, _b, _s, timeout=15: (upstream_text, None)
        # If we ever call fetch_remote_sha that means we'd record a HEAD SHA,
        # which is the bug we're guarding against. Fail loudly if called.
        def _should_not_resolve(*_a, **_k):
            raise AssertionError("fetch_remote_sha must not be called when content differs")
        mod.fetch_remote_sha = _should_not_resolve

        from io import StringIO
        cwd = os.getcwd()
        os.chdir(self.manager)
        sys.stdout = StringIO()
        try:
            mod.main(["audit_unclaimed.py"])
            payload = json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = sys.__stdout__
            os.chdir(cwd)

        rep = next(r for r in payload["reports"] if r["name"] == "drifted")
        self.assertEqual(rep["decision"], "auto_claim")
        self.assertIsNone(rep["claim_record"]["installed_revision"])
        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        self.assertIsNone(sources["skills"]["drifted"]["installed_revision"])

    def test_whitelist_no_match_does_not_claim(self) -> None:
        self.write_skill("homemade", "totally my own work")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = [{
            "url": "https://github.com/fake/repo",
            "branch": "main",
            "subpath_template": "skills/{name}",
        }]
        mod.fetch_remote_skill_md = lambda *_a, **_k: ("", "HTTP 404")
        from io import StringIO
        cwd = os.getcwd()
        os.chdir(self.manager)
        sys.stdout = StringIO()
        try:
            mod.main(["audit_unclaimed.py"])
            payload = json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = sys.__stdout__
            os.chdir(cwd)

        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        self.assertNotIn("homemade", sources["skills"])
        self.assertEqual(payload["summary"]["no_match"], 1)
        self.assertEqual(payload["summary"]["auto_claimed"], 0)

    def test_already_claimed_skills_are_skipped(self) -> None:
        self.write_skill("already-known")
        self.write_sources({"already-known": {}})

        payload = self._run_audit()

        self.assertEqual(payload["summary"]["total_unclaimed"], 0)

    def test_inventory_after_reflects_new_claims(self) -> None:
        """audit non-dry-run must attach a fresh inventory snapshot showing
        previously unclaimed skills as remote/local."""
        skill_dir = self.skills_root / "git-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: git-skill\ndescription: x\n---\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=skill_dir, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=skill_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/git-skill.git"],
            cwd=skill_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=skill_dir, check=True, capture_output=True)
        self.write_sources({})

        payload = self._run_audit()

        self.assertIsNotNone(payload["inventory_after"])
        entry = next(e for e in payload["inventory_after"] if e["name"] == "git-skill")
        self.assertEqual(entry["type"], "remote")

    def test_inventory_after_is_null_in_dry_run(self) -> None:
        """dry-run skips inventory because sources.json wasn't touched."""
        self.write_skill("some-skill")
        self.write_sources({})

        payload = self._run_audit(dry_run=True)

        self.assertIsNone(payload["inventory_after"])

    def test_dry_run_does_not_write_sources(self) -> None:
        skill_dir = self.skills_root / "git-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: git-skill\ndescription: x\n---\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=skill_dir, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=skill_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/git-skill.git"],
            cwd=skill_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=skill_dir, check=True, capture_output=True)
        self.write_sources({})

        payload = self._run_audit(dry_run=True)

        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        self.assertNotIn("git-skill", sources["skills"])
        self.assertTrue(payload["summary"]["dry_run"])
        self.assertEqual(payload["summary"]["auto_claimed"], 1)


class GhSearchPhraseTests(unittest.TestCase):
    """Pure-function tests for the query phrase extractor."""

    def _load_module(self):
        sys.modules.pop("gh_search", None)
        scripts = SKILL_MANAGER / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            import gh_search  # type: ignore
            return gh_search
        finally:
            sys.path.pop(0)

    def test_returns_distinctive_words_from_long_description(self) -> None:
        mod = self._load_module()
        desc = (
            "Manage installed skills in the current sibling directory: list all "
            "skills with freshness status against their upstream GitHub repos."
        )
        phrase = mod.extract_query_phrase(desc)
        self.assertIsNotNone(phrase)
        self.assertGreaterEqual(len(phrase.split()), 8)
        self.assertIn("installed skills in the current sibling directory", phrase)

    def test_search_skill_md_uses_gh_search_code_with_utf8_and_limit(self) -> None:
        mod = self._load_module()
        calls = []

        def _fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps([{
                "repository": {"nameWithOwner": "alice/kit", "defaultBranchRef": {"name": "trunk"}},
                "path": "skills/demo/SKILL.md",
                "url": "https://github.com/alice/kit/blob/trunk/skills/demo/SKILL.md",
            }]), stderr="")

        original_run = mod.subprocess.run
        mod.subprocess.run = _fake_run
        try:
            candidates, err = mod.search_skill_md("Karpathy Guidelines", max_results=50)
        finally:
            mod.subprocess.run = original_run

        self.assertIsNone(err)
        self.assertEqual(candidates[0]["owner"], "alice")
        self.assertEqual(candidates[0]["repo"], "kit")
        self.assertEqual(candidates[0]["branch"], "trunk")
        self.assertEqual(candidates[0]["subpath"], "skills/demo")
        args, kwargs = calls[0]
        self.assertEqual(args[:3], ["gh", "search", "code"])
        self.assertIn("--filename", args)
        self.assertIn("--limit", args)
        self.assertIn("50", args)
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")

    def test_gh_available_uses_utf8_decoding(self) -> None:
        mod = self._load_module()
        calls = []

        def _fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="✓ Logged in")

        original_run = mod.subprocess.run
        mod.subprocess.run = _fake_run
        try:
            self.assertTrue(mod.gh_available())
        finally:
            mod.subprocess.run = original_run
        self.assertEqual(calls[0][1]["encoding"], "utf-8")
        self.assertEqual(calls[0][1]["errors"], "replace")

    def test_returns_none_for_short_description(self) -> None:
        mod = self._load_module()
        self.assertIsNone(mod.extract_query_phrase("hello world"))
        self.assertIsNone(mod.extract_query_phrase(""))


class AuditWithSearchTests(SkillManagerContractTests):
    """audit_unclaimed.py third gate (GitHub Code Search) and whitelist growth."""

    def _load_audit_module(self):
        for cached in ("_common", "similarity", "check_remote", "gh_search", "inventory", "audit_under_test"):
            sys.modules.pop(cached, None)
        sys.path.insert(0, str(self.manager / "scripts"))
        try:
            spec = importlib.util.spec_from_file_location(
                "audit_under_test",
                self.manager / "scripts" / "audit_unclaimed.py",
            )
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def _run_in_manager(self, mod, argv: list[str]) -> dict:
        from io import StringIO
        cwd = os.getcwd()
        os.chdir(self.manager)
        sys.stdout = StringIO()
        try:
            mod.main(argv)
            return json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = sys.__stdout__
            os.chdir(cwd)

    def test_search_auto_claims_high_confidence(self) -> None:
        skill_text = (
            "---\nname: searched-skill\n"
            "description: A long enough description that we can extract distinctive search words from it without trouble at all.\n"
            "---\n\n# Body\n"
        )
        sd = self.write_skill("searched-skill")
        (sd / "SKILL.md").write_text(skill_text, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: True
        mod.gh_search.search_skill_md = lambda _phrase, max_results=3: ([{
            "owner": "alice",
            "repo": "kit",
            "branch": "main",
            "subpath": "skills/searched-skill",
            "path": "skills/searched-skill/SKILL.md",
        }], None)
        mod.fetch_remote_skill_md = lambda _u, _b, _s, timeout=15: (skill_text, None)
        mod.fetch_remote_sha = lambda _u, _b: ("c0ffee" * 6, None)

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        rec = sources["skills"]["searched-skill"]
        self.assertEqual(rec["url"], "https://github.com/alice/kit")
        self.assertEqual(rec["branch"], "main")
        self.assertEqual(rec["subpath"], "skills/searched-skill")
        self.assertEqual(rec["installed_revision"], "c0ffee" * 6)
        self.assertEqual(payload["summary"]["auto_claimed"], 1)
        self.assertTrue(payload["summary"]["search_used"])
        self.assertEqual(payload["reports"][0]["method"], "search")

    def test_search_tries_multiple_queries_and_larger_result_sets(self) -> None:
        skill_text = (
            "---\nname: karpathy-guidelines\n"
            "description: Behavioral guidelines to reduce common LLM coding mistakes when writing, reviewing, or refactoring code.\n"
            "---\n\n# Karpathy Guidelines\n\n"
            "Derived from Andrej Karpathy's observations about common coding mistakes.\n"
        )
        sd = self.write_skill("karpathy-guidelines")
        (sd / "SKILL.md").write_text(skill_text, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: True
        calls = []

        def _search(query, max_results=50):
            calls.append((query, max_results))
            if query == "Karpathy Guidelines":
                return ([{
                    "owner": "alice",
                    "repo": "kit",
                    "branch": "main",
                    "subpath": "skills/karpathy-guidelines",
                    "path": "skills/karpathy-guidelines/SKILL.md",
                }], None)
            return ([], None)

        mod.gh_search.search_skill_md = _search
        mod.fetch_remote_skill_md = lambda _u, _b, _s, timeout=15: (skill_text, None)
        mod.fetch_remote_sha = lambda _u, _b: ("c0ffee" * 6, None)

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        self.assertEqual(payload["summary"]["auto_claimed"], 1)
        self.assertIn(("karpathy-guidelines", 20), calls)
        self.assertIn(("Karpathy Guidelines", 20), calls)
        self.assertGreater(len(calls), 1)

    def test_search_limits_queries_results_and_verified_candidates(self) -> None:
        skill_text = (
            "---\nname: budgeted-skill\n"
            "description: Description with enough distinctive words to trigger several search queries during audit.\n"
            "---\n\n# Budgeted Skill\n\n"
            "Another distinctive sentence with enough words for a body query.\n"
        )
        sd = self.write_skill("budgeted-skill")
        (sd / "SKILL.md").write_text(skill_text, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: True
        calls = []

        def _search(query, max_results=50):
            calls.append((query, max_results))
            return ([{
                "owner": f"owner{len(calls)}",
                "repo": f"repo{i}",
                "branch": "main",
                "subpath": f"copies/{len(calls)}/{i}",
                "path": f"copies/{len(calls)}/{i}/SKILL.md",
            } for i in range(25)], None)

        fetched = []
        mod.gh_search.search_skill_md = _search
        mod.fetch_remote_skill_md = lambda _u, _b, subpath, timeout=15: (
            fetched.append(subpath) or f"not the same {subpath}", None
        )
        mod.fetch_remote_sha = lambda _u, _b: (_ for _ in ()).throw(
            AssertionError("low-confidence candidates must not resolve SHA")
        )

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        rep = next(r for r in payload["reports"] if r["name"] == "budgeted-skill")
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(max_results == 20 for _query, max_results in calls))
        self.assertEqual(len(fetched), 40)
        self.assertEqual(rep["verified_candidate_count"], 40)
        self.assertEqual(rep["skipped_candidate_count"], 35)
        self.assertEqual(rep["search_verify_budget"], 40)
        self.assertEqual(len(rep["search_queries"]), 3)
        self.assertEqual(len(rep["result_count_by_query"]), 3)
        self.assertIn("elapsed_ms", rep)

    def test_search_exact_strong_path_early_stops_and_resolves_sha_once(self) -> None:
        skill_text = "---\nname: winner\ndescription: enough words for searching this exact skill source.\n---\n\n# Winner\n"
        sd = self.write_skill("winner")
        (sd / "SKILL.md").write_text(skill_text, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: True
        calls = []

        def _search(query, max_results=50):
            calls.append(query)
            if len(calls) > 1:
                return ([], None)
            return ([
                {"owner": "mirror", "repo": "dotfiles", "branch": "main",
                 "subpath": ".agents/skills/winner", "path": ".agents/skills/winner/SKILL.md"},
                {"owner": "source", "repo": "skills", "branch": "main",
                 "subpath": "skills/winner", "path": "skills/winner/SKILL.md"},
                {"owner": "mirror2", "repo": "registry", "branch": "main",
                 "subpath": "registry/winner", "path": "registry/winner/SKILL.md"},
            ], None)

        fetched = []
        sha_calls = []
        mod.gh_search.search_skill_md = _search
        mod.fetch_remote_skill_md = lambda _u, _b, subpath, timeout=15: (
            fetched.append(subpath) or skill_text, None
        )
        mod.fetch_remote_sha = lambda url, branch: (
            sha_calls.append((url, branch)) or ("c0ffee" * 6, None)
        )

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        rep = next(r for r in payload["reports"] if r["name"] == "winner")
        self.assertEqual(rep["decision"], "auto_claim")
        self.assertEqual(rep["claim_record"]["url"], "https://github.com/source/skills")
        self.assertEqual(rep["claim_record"]["installed_revision"], "c0ffee" * 6)
        self.assertEqual(fetched, ["skills/winner"])
        self.assertEqual(sha_calls, [("https://github.com/source/skills", "main")])
        self.assertEqual(rep["verified_candidate_count"], 1)
        self.assertGreater(rep["skipped_candidate_count"], 0)

    def test_search_multiple_weak_exact_matches_need_review_without_sha(self) -> None:
        skill_text = "---\nname: copied\ndescription: enough words for searching copied exact matches.\n---\n\n# Copied\n"
        sd = self.write_skill("copied")
        (sd / "SKILL.md").write_text(skill_text, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: True
        mod.gh_search.search_skill_md = lambda _query, max_results=50: ([
            {"owner": "mirror", "repo": "dotfiles", "branch": "main",
             "subpath": ".agents/skills/copied", "path": ".agents/skills/copied/SKILL.md"},
            {"owner": "copy", "repo": "registry", "branch": "main",
             "subpath": "marketplace/copied", "path": "marketplace/copied/SKILL.md"},
        ], None)
        mod.fetch_remote_skill_md = lambda _u, _b, _s, timeout=15: (skill_text, None)
        mod.fetch_remote_sha = lambda _u, _b: (_ for _ in ()).throw(
            AssertionError("weak Code Search matches must not resolve SHA")
        )

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        rep = next(r for r in payload["reports"] if r["name"] == "copied")
        self.assertEqual(rep["decision"], "needs_review")
        self.assertIsNone(rep["claim_record"])
        self.assertEqual(payload["summary"]["auto_claimed"], 0)
        sources = json.loads((self.manager / "sources.json").read_text(encoding="utf-8"))
        self.assertNotIn("copied", sources["skills"])

    def test_search_skipped_when_gh_unavailable(self) -> None:
        sd = self.write_skill("alone-skill", "totally homemade thing here only mine.")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: False

        def _should_not_call(*_a, **_k):
            raise AssertionError("search_skill_md must not be called when gh is unavailable")

        mod.gh_search.search_skill_md = _should_not_call

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        self.assertFalse(payload["summary"]["search_used"])
        self.assertIn("gh", payload["summary"]["search_disabled_reason"])
        self.assertEqual(payload["summary"]["no_match"], 1)

    def test_search_circuit_breaker_trips_after_repeated_failures(self) -> None:
        for n in range(5):
            sd = self.write_skill(
                f"failing-skill-{n}",
                "Description with enough distinctive words to trigger a search query lookup."
            )
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: True
        call_count = {"n": 0}

        def _failing_search(_phrase, max_results=3):
            call_count["n"] += 1
            return ([], "API rate limit exceeded")

        mod.gh_search.search_skill_md = _failing_search

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        self.assertEqual(call_count["n"], mod.SEARCH_FAILURE_BUDGET)
        self.assertEqual(payload["summary"]["search_failures"], mod.SEARCH_FAILURE_BUDGET)
        self.assertIn("mid-run", payload["summary"]["search_disabled_reason"] or "")
        self.assertEqual(payload["summary"]["auto_claimed"], 0)

    def test_derive_whitelist_additions_groups_correctly(self) -> None:
        mod = self._load_audit_module()
        reports = [
            {"name": "foo", "method": "search", "decision": "auto_claim", "claim_record": {
                "url": "https://github.com/alice/kit", "branch": "main", "subpath": "skills/foo"}},
            {"name": "bar", "method": "search", "decision": "auto_claim", "claim_record": {
                "url": "https://github.com/alice/kit", "branch": "main", "subpath": "skills/bar"}},
            {"name": "solo", "method": "search", "decision": "auto_claim", "claim_record": {
                "url": "https://github.com/bob/other", "branch": "main", "subpath": "x/solo"}},
            {"name": "wl", "method": "whitelist", "decision": "auto_claim", "claim_record": {
                "url": "https://github.com/whitelist/repo", "branch": "main", "subpath": "skills/wl"}},
        ]
        additions = mod.derive_whitelist_additions(reports, [])
        self.assertEqual(additions, [{
            "url": "https://github.com/alice/kit",
            "branch": "main",
            "subpath_template": "skills/{name}",
        }])

    def test_derive_whitelist_skips_already_present(self) -> None:
        mod = self._load_audit_module()
        reports = [
            {"name": "foo", "method": "search", "decision": "auto_claim", "claim_record": {
                "url": "https://github.com/x/y", "branch": "main", "subpath": "s/foo"}},
            {"name": "bar", "method": "search", "decision": "auto_claim", "claim_record": {
                "url": "https://github.com/x/y", "branch": "main", "subpath": "s/bar"}},
        ]
        existing = [{
            "url": "https://github.com/x/y",
            "branch": "main",
            "subpath_template": "s/{name}",
        }]
        self.assertEqual(mod.derive_whitelist_additions(reports, existing), [])

    def test_no_match_report_carries_search_query_hint(self) -> None:
        """When a skill ends up no_match, the agent needs a phrase to feed
        into WebSearch as a fallback. Verify the hint is populated."""
        long_desc = (
            "Manage installed skills with freshness checks against their upstream "
            "GitHub repositories using a structured deterministic workflow."
        )
        sd = self.write_skill("homeless-skill", long_desc)
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: False

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        rep = next(r for r in payload["reports"] if r["name"] == "homeless-skill")
        self.assertEqual(rep["decision"], "no_match")
        self.assertIsInstance(rep.get("search_query_hint"), str)
        self.assertGreaterEqual(len(rep["search_query_hint"].split()), 8)

    def test_short_description_yields_null_hint(self) -> None:
        """Descriptions too short to form a distinctive phrase get null hint,
        rather than a useless 1-2 word query."""
        self.write_skill("tiny", "x")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: False

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        rep = next(r for r in payload["reports"] if r["name"] == "tiny")
        self.assertEqual(rep["decision"], "no_match")
        self.assertIsNone(rep.get("search_query_hint"))

    def test_auto_claim_report_has_no_hint(self) -> None:
        """Resolved skills don't need a fallback query."""
        skill_dir = self.skills_root / "git-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: git-skill\ndescription: x\n---\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=skill_dir, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=skill_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/git-skill.git"],
            cwd=skill_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=skill_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=skill_dir, check=True, capture_output=True)
        self.write_sources({})

        mod = self._load_audit_module()
        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        rep = next(r for r in payload["reports"] if r["name"] == "git-skill")
        self.assertEqual(rep["decision"], "auto_claim")
        self.assertNotIn("search_query_hint", rep)

    def test_audit_appends_to_whitelist_json(self) -> None:
        skill_text_a = (
            "---\nname: alpha\n"
            "description: A long enough description that we can extract distinctive search words from it without trouble at all.\n"
            "---\n\n# Body\n"
        )
        skill_text_b = (
            "---\nname: beta\n"
            "description: Another long description with plenty of distinctive lookup keywords waiting to be picked up.\n"
            "---\n\n# Body\n"
        )
        sd_a = self.write_skill("alpha")
        (sd_a / "SKILL.md").write_text(skill_text_a, encoding="utf-8")
        sd_b = self.write_skill("beta")
        (sd_b / "SKILL.md").write_text(skill_text_b, encoding="utf-8")
        self.write_sources({})

        mod = self._load_audit_module()
        mod.KNOWN_UPSTREAMS[:] = []
        mod.gh_search.gh_available = lambda: True

        def _search(phrase, max_results=3):
            if "alpha" in phrase or "Body" in phrase or True:
                # Return based on which skill we're searching for via current cwd context;
                # easier: inspect the phrase. Both descriptions are unique enough.
                if "Another" in phrase or "plenty" in phrase or "lookup" in phrase or "keywords" in phrase:
                    return ([{"owner": "alice", "repo": "kit", "branch": "main",
                              "subpath": "skills/beta", "path": "skills/beta/SKILL.md"}], None)
                return ([{"owner": "alice", "repo": "kit", "branch": "main",
                          "subpath": "skills/alpha", "path": "skills/alpha/SKILL.md"}], None)
            return ([], None)

        mod.gh_search.search_skill_md = _search

        def _fetch_raw(_url, _branch, subpath, timeout=15):
            if subpath.endswith("alpha"):
                return (skill_text_a, None)
            return (skill_text_b, None)

        mod.fetch_remote_skill_md = _fetch_raw
        mod.fetch_remote_sha = lambda _u, _b: ("a" * 40, None)

        payload = self._run_in_manager(mod, ["audit_unclaimed.py"])

        self.assertEqual(payload["summary"]["auto_claimed"], 2)
        self.assertEqual(len(payload["summary"]["whitelist_appended"]), 1)
        self.assertEqual(payload["summary"]["whitelist_appended"][0], {
            "url": "https://github.com/alice/kit",
            "branch": "main",
            "subpath_template": "skills/{name}",
        })

        wl_data = json.loads((self.manager / "whitelist.json").read_text(encoding="utf-8"))
        self.assertEqual(len(wl_data["entries"]), 1)
        self.assertEqual(wl_data["entries"][0]["url"], "https://github.com/alice/kit")


if __name__ == "__main__":
    unittest.main()
