import os, tempfile, unittest
from tests.helpers import make_vault, make_project, write_config, payload
from brain import hooks, state

class SessionStartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")
    def tearDown(self): self.tmp.cleanup()

    def test_injects_protocol_context_and_last_log(self):
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo, source="startup"))
        self.assertEqual(r.exit_code, 0); self.assertIsNone(r.json)
        self.assertIn('Brain: vault context for "demo"', r.stdout)
        self.assertIn("brain/__main__.py\" graph find", r.stdout)     # {BRAIN} substituted
        self.assertIn("## State\nAlpha works.", r.stdout)             # context.md verbatim
        self.assertIn("## 2026-01-01 · Session 1", r.stdout)          # last log entry
        self.assertNotIn("All DB calls go through", r.stdout)          # architecture.md NOT injected
        self.assertLessEqual(r.stdout.count("\n"), 25 + 60)            # protocol ≤ 25 + fixture context
        s = state.SessionState.load("s1")
        self.assertEqual((s.slug, s.vault, s.project_dir), ("demo", self.vault, self.repo))
        self.assertEqual(s.log_entries_at_start, 1)
        self.assertEqual(len(s.last_head_sha), 40)

    def test_compact_adds_branch_line(self):
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo, source="compact"))
        self.assertIn("Brain: context re-injected after compact; branch is main", r.stdout)

    def test_silent_outside_brain_project(self):
        with tempfile.TemporaryDirectory() as other:
            r = hooks.dispatch("SessionStart", payload("SessionStart", other))
            self.assertEqual((r.stdout, r.json, r.exit_code), ("", None, 0))

    def test_silent_without_config(self):
        os.environ["BRAIN_CONFIG"] = "/nonexistent"
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertEqual(r.stdout, "")

    def test_exception_is_swallowed_and_logged(self):
        os.environ["BRAIN_TEST_RAISE"] = "1"
        try:
            r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            del os.environ["BRAIN_TEST_RAISE"]
        self.assertEqual((r.stdout, r.exit_code), ("", 0))
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "brain.log")) as f:
            self.assertIn("SessionStart", f.read())

    def test_unknown_event_is_silent(self):
        r = hooks.dispatch("Bogus", payload("Bogus", self.repo))
        self.assertEqual(r.stdout, "")
