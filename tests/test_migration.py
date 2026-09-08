import json, os, tempfile, unittest
from tests.helpers import make_vault, make_project, write_config, payload, read_text
from brain import migrate, project, hooks, vault

LEGACY_SETTINGS = {"permissions": {"allow": ["Read(~/x/**)", "café"]}, "hooks": {
    "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "/Users/old/.claude/brain-session-start.sh"}]}],
    "PostToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "/Users/old/.claude/brain-post-tool-use.sh"}, {"type": "command", "command": "/keep/me.sh"}]}],
    "PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": "/Users/old/.claude/brain-precompact.sh"}]}],
    "SessionEnd": [{"matcher": "", "hooks": [{"type": "command", "command": "/Users/old/.claude/brain-session-end.sh"}]}],
    "Notification": []}}

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
        original = vault.read(os.path.join(self.repo, "CLAUDE.md"))
        actions = migrate.migrate_project(proj, self.vault, self.repo)
        self.assertTrue(any("claude-md" in a for a in actions), actions)
        self.assertIn("hooks:4", actions); self.assertIn("path", actions)
        self.assertIn("codemap", actions)
        self.assertTrue(os.path.exists(os.path.join(self.vault, "projects", "old-app", "codemap.md")))
        backup = os.path.join(self.repo, "CLAUDE.md.brain-bak")          # backed up even with a separator
        self.assertTrue(os.path.exists(backup))
        with open(backup, encoding="utf-8") as f:
            self.assertEqual(f.read(), original)
        self.assertTrue(any("CLAUDE.md.brain-bak" in a for a in actions), actions)
        text = vault.read(os.path.join(self.repo, "CLAUDE.md"))
        self.assertIn("brain: old-app", text); self.assertNotIn("vault:", text)
        self.assertTrue(text.endswith("---\n# Repo notes\n"))            # content after separator preserved
        with open(self.settings, encoding="utf-8") as f: s = json.load(f)
        self.assertEqual(s["permissions"], LEGACY_SETTINGS["permissions"])
        self.assertEqual([h["command"] for h in s["hooks"]["PostToolUse"][0]["hooks"]], ["/keep/me.sh"])
        self.assertNotIn("SessionStart", s["hooks"]); self.assertNotIn("PreCompact", s["hooks"])
        self.assertIn("Notification", s["hooks"]); self.assertEqual(s["hooks"]["Notification"], [])  # untouched empty event survives
        with open(self.settings, encoding="utf-8") as f: raw = f.read()
        self.assertIn("café", raw)                                        # non-ascii preserved unescaped
        fm, _ = vault.parse_frontmatter(vault.read(os.path.join(self.vault, "projects", "old-app", "context.md")))
        self.assertEqual(fm["path"], self.repo)
        proj2 = project.resolve_project(self.repo)
        self.assertFalse(proj2.legacy); self.assertFalse(migrate.needs_migration(proj2, self.vault))
        self.assertEqual(migrate.migrate_project(proj2, self.vault, self.repo), [])   # idempotent

    def test_irregular_group_entries_are_preserved_not_crashed(self):
        data = {"hooks": {"PostToolUse": ["not-a-dict", {"hooks": "not-a-list"}, {"hooks": [{"type": "command", "command": "/Users/old/.claude/brain-post-tool-use.sh"}]}]}}
        with open(self.settings, "w") as f: json.dump(data, f)
        self.assertEqual(migrate.strip_legacy_hooks(self.settings), 1)
        with open(self.settings, encoding="utf-8") as f: s = json.load(f)
        self.assertEqual(s["hooks"]["PostToolUse"], ["not-a-dict", {"hooks": "not-a-list"}])

    def test_migration_failure_does_not_suppress_injection(self):
        # A read-only *directory*, not a read-only file: vault.write is atomic (tmp+replace),
        # and os.replace over a 0444 target succeeds — only losing write access to the
        # directory itself stops the backup/rewrite from landing.
        os.chmod(self.repo, 0o555)
        if os.access(self.repo, os.W_OK):
            self.skipTest("running as root or filesystem ignores chmod; cannot force a write failure")
        try:
            r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            os.chmod(self.repo, 0o755)
        self.assertIn("## State\nAlpha works.", r.stdout)
        self.assertNotIn("migrated", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "CLAUDE.md.tmp")))

    def test_settings_without_brain_hooks_untouched_bytewise(self):
        raw = '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/x.sh"}]}]}}'
        with open(self.settings, "w") as f: f.write(raw)
        self.assertEqual(migrate.strip_legacy_hooks(self.settings), 0)
        with open(self.settings, encoding="utf-8") as f: self.assertEqual(f.read(), raw)

    def test_session_start_runs_migration_and_reports_once(self):
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertIn("Brain: migrated old-app to v2 layout", r.stdout)
        r2 = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertNotIn("migrated", r2.stdout)

    def test_no_separator_backs_up_original(self):
        claude_md = os.path.join(self.repo, "CLAUDE.md")
        original = "# Brain: old-app\n\nvault: /Users/old/vault/projects/old-app\n\n## My notes\nDon't lose this.\n"
        with open(claude_md, "w", encoding="utf-8") as f:
            f.write(original)
        proj = project.resolve_project(self.repo)
        actions = migrate.migrate_project(proj, self.vault, self.repo)
        backup_path = claude_md + ".brain-bak"
        self.assertTrue(os.path.exists(backup_path))
        with open(backup_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), original)
        self.assertEqual(vault.read(claude_md), migrate.slim_block("old-app", "old-app"))
        self.assertTrue(any("backed up to CLAUDE.md.brain-bak — review it for your own notes" in a for a in actions), actions)

    def test_missing_context_md_still_reports_the_migration(self):
        os.remove(os.path.join(self.vault, "projects", "old-app", "context.md"))
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertIn("Brain: migrated old-app to v2 layout", r.stdout)
        self.assertIn("has no context.md", r.stdout)

    def test_existing_backup_is_not_clobbered(self):
        bak = os.path.join(self.repo, "CLAUDE.md.brain-bak")
        with open(bak, "w") as f: f.write("PRECIOUS")
        proj = project.resolve_project(self.repo)
        actions = migrate.migrate_project(proj, self.vault, self.repo)
        self.assertEqual(read_text(bak), "PRECIOUS")
        self.assertTrue(os.path.exists(bak + ".1"))
        self.assertTrue(any("brain-bak.1" in a for a in actions))

    def test_slim_block_matches_template(self):
        template_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "CLAUDE.md")
        with open(template_path, encoding="utf-8") as f:
            template = f.read()
        rendered = template.replace("{project-name}", "N").replace("{slug}", "S")
        self.assertEqual(rendered, migrate.slim_block("N", "S"))


if __name__ == "__main__":
    unittest.main()
