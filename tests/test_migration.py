import json, os, tempfile, unittest
from tests.helpers import make_vault, make_project, write_config, payload
from brain import migrate, project, hooks, vault

LEGACY_SETTINGS = {"permissions": {"allow": ["Read(~/x/**)"]}, "hooks": {
    "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "/Users/old/.claude/brain-session-start.sh"}]}],
    "PostToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "/Users/old/.claude/brain-post-tool-use.sh"}, {"type": "command", "command": "/keep/me.sh"}]}],
    "PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": "/Users/old/.claude/brain-precompact.sh"}]}],
    "SessionEnd": [{"matcher": "", "hooks": [{"type": "command", "command": "/Users/old/.claude/brain-session-end.sh"}]}]}}

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="old-app")
        write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="old-app", legacy=True, vault="/Users/old/vault")
        self.settings = os.path.join(self.repo, ".claude", "settings.json")
        with open(self.settings, "w") as f: json.dump(LEGACY_SETTINGS, f, indent=2)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.clear()
        os.environ.update(self._env)

    def test_migrates_claude_md_settings_and_path(self):
        proj = project.resolve_project(self.repo)
        self.assertTrue(migrate.needs_migration(proj, self.vault))
        actions = migrate.migrate_project(proj, self.vault, self.repo)
        self.assertIn("claude-md", actions); self.assertIn("hooks:4", actions); self.assertIn("path", actions)
        text = vault.read(os.path.join(self.repo, "CLAUDE.md"))
        self.assertIn("brain: old-app", text); self.assertNotIn("vault:", text)
        self.assertTrue(text.endswith("---\n# Repo notes\n"))            # content after separator preserved
        s = json.load(open(self.settings))
        self.assertEqual(s["permissions"], LEGACY_SETTINGS["permissions"])
        self.assertEqual([h["command"] for h in s["hooks"]["PostToolUse"][0]["hooks"]], ["/keep/me.sh"])
        self.assertNotIn("SessionStart", s["hooks"]); self.assertNotIn("PreCompact", s["hooks"])
        fm, _ = vault.parse_frontmatter(vault.read(os.path.join(self.vault, "projects", "old-app", "context.md")))
        self.assertEqual(fm["path"], self.repo)
        proj2 = project.resolve_project(self.repo)
        self.assertFalse(proj2.legacy); self.assertFalse(migrate.needs_migration(proj2, self.vault))
        self.assertEqual(migrate.migrate_project(proj2, self.vault, self.repo), [])   # idempotent

    def test_irregular_group_entries_are_preserved_not_crashed(self):
        data = {"hooks": {"PostToolUse": ["not-a-dict", {"hooks": "not-a-list"}, {"hooks": [{"type": "command", "command": "/Users/old/.claude/brain-post-tool-use.sh"}]}]}}
        with open(self.settings, "w") as f: json.dump(data, f)
        self.assertEqual(migrate.strip_legacy_hooks(self.settings), 1)
        s = json.load(open(self.settings))
        self.assertEqual(s["hooks"]["PostToolUse"], ["not-a-dict", {"hooks": "not-a-list"}])

    def test_migration_failure_does_not_suppress_injection(self):
        os.chmod(os.path.join(self.repo, "CLAUDE.md"), 0o444)     # rewrite of CLAUDE.md will fail
        if os.access(os.path.join(self.repo, "CLAUDE.md"), os.W_OK):
            self.skipTest("running as root or filesystem ignores chmod; cannot force a write failure")
        try:
            r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            os.chmod(os.path.join(self.repo, "CLAUDE.md"), 0o644)
        self.assertIn("## State\nAlpha works.", r.stdout)
        self.assertNotIn("migrated", r.stdout)

    def test_settings_without_brain_hooks_untouched_bytewise(self):
        raw = '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/x.sh"}]}]}}'
        with open(self.settings, "w") as f: f.write(raw)
        self.assertEqual(migrate.strip_legacy_hooks(self.settings), 0)
        self.assertEqual(open(self.settings).read(), raw)

    def test_session_start_runs_migration_and_reports_once(self):
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertIn("Brain: migrated old-app to v2 layout", r.stdout)
        r2 = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertNotIn("migrated", r2.stdout)


if __name__ == "__main__":
    unittest.main()
