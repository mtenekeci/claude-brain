import os, tempfile, unittest
from tests.helpers import make_vault, make_project, write_config, payload
from brain import hooks, state

class SessionStartTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)
        self.tmp.cleanup()

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

    def test_missing_context_md_points_at_init_and_still_resets_gate(self):
        os.remove(os.path.join(self.vault, "projects", "demo", "context.md"))
        with state.locked("s1") as s:
            s.stop_blocks_this_turn = 3
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertIn("has no context.md", r.stdout)
        self.assertEqual(state.SessionState.load("s1").stop_blocks_this_turn, 0)

    def test_handler_exception_is_swallowed_and_logged(self):
        def boom(ctx):
            raise RuntimeError("kaboom")
        original = hooks._HANDLERS["SessionStart"]
        hooks._HANDLERS["SessionStart"] = boom
        try:
            r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            hooks._HANDLERS["SessionStart"] = original
        self.assertEqual((r.stdout, r.json, r.exit_code), ("", None, 0))
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "brain.log")) as f:
            logged = f.read()
        self.assertIn("SessionStart", logged)
        self.assertIn("kaboom", logged)

    def test_locked_failure_is_swallowed(self):
        blocked = os.path.join(self.tmp.name, "blocked")
        os.makedirs(blocked)
        os.chmod(blocked, 0o500)
        try:
            target = os.path.join(blocked, "sub")
            try:
                os.makedirs(target)
            except OSError:
                pass                # expected: the data dir cannot be created
            else:
                self.skipTest("writes into a 0o500 directory succeed here (running as root?)")
            os.environ["CLAUDE_PLUGIN_DATA"] = target
            r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
            self.assertEqual((r.stdout, r.json, r.exit_code), ("", None, 0))
        finally:
            os.chmod(blocked, 0o700)

    def test_unknown_event_is_silent(self):
        r = hooks.dispatch("Bogus", payload("Bogus", self.repo))
        self.assertEqual(r.stdout, "")
