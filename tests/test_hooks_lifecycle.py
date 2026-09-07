import os, tempfile, time, unittest
from tests.helpers import make_vault, make_project, write_config, payload
from brain import hooks, state, vault

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")
        self.log = os.path.join(self.vault, "projects", "demo", "log.md")
    def tearDown(self):
        self.tmp.cleanup()
        os.environ.clear()
        os.environ.update(self._env)

    def _edit(self, path):
        hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Edit", tool_input={"file_path": path, "old_string": "a", "new_string": "b"}, tool_response={}))

    def test_precompact_writes_checkpoint_from_state(self):
        self._edit(os.path.join(self.repo, "src", "x.ts"))
        r = hooks.dispatch("PreCompact", payload("PreCompact", self.repo))
        text = vault.read(self.log)
        self.assertIn("Session 2 (pre-compact)", text)
        self.assertIn("Changed: ", text); self.assertIn("src/x.ts", text)
        self.assertIn("BRAIN SYNC", r.stdout)
        hooks.dispatch("PreCompact", payload("PreCompact", self.repo))     # second compact: no duplicate
        self.assertEqual(vault.count_log_entries(vault.read(self.log)), 2)

    def test_session_end_silent_when_idle(self):
        hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        hooks.dispatch("SessionEnd", payload("SessionEnd", self.repo, reason="other"))
        self.assertEqual(vault.count_log_entries(vault.read(self.log)), 1)
        self.assertFalse(os.path.exists(state.SessionState("s1").path))

    def _commit(self, msg="x"):
        import subprocess
        hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        with open(os.path.join(self.repo, "c.py"), "a") as f: f.write("# %s\n" % msg)
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", msg], check=True)
        hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Bash", tool_input={"command": "git commit -m x"}, tool_response={}))

    def test_session_end_writes_autoclose_from_state_fast(self):
        self._commit("feat: y")
        t0 = time.time()
        hooks.dispatch("SessionEnd", payload("SessionEnd", self.repo, reason="other"))
        self.assertLess(time.time() - t0, 1.0)
        text = vault.read(self.log)
        self.assertIn("Session 2 (auto-close)", text); self.assertIn("Completed: feat: y", text)

    def test_session_end_no_duplicate_after_manual_sync_entry(self):
        self._commit("feat: z")
        vault.append(self.log, vault.format_log_entry("2026-09-07", 2, "synced by /brain sync", "c.py", "none", "—"))
        hooks.dispatch("SessionEnd", payload("SessionEnd", self.repo, reason="other"))
        text = vault.read(self.log)
        self.assertEqual(vault.count_log_entries(text), 2); self.assertNotIn("(auto-close)", text)

    def test_session_end_skips_when_placeholder_exists(self):
        self._edit(os.path.join(self.repo, "src", "x.ts"))
        hooks.dispatch("PreCompact", payload("PreCompact", self.repo))
        hooks.dispatch("SessionEnd", payload("SessionEnd", self.repo, reason="other"))
        self.assertEqual(vault.count_log_entries(vault.read(self.log)), 2)

    def test_precompact_missing_log_reports_init(self):
        os.remove(self.log)
        r = hooks.dispatch("PreCompact", payload("PreCompact", self.repo))
        self.assertIn("run /brain init", r.stdout)
        self.assertNotIn("already exists", r.stdout)
        self.assertFalse(os.path.exists(self.log))

    def test_session_end_without_session_start_still_autocloses(self):
        import subprocess
        with open(os.path.join(self.repo, "c.py"), "a") as f: f.write("# feat: w\n")
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "feat: w"], check=True)
        hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Bash", tool_input={"command": "git commit -m x"}, tool_response={}))
        hooks.dispatch("SessionEnd", payload("SessionEnd", self.repo, reason="other"))
        text = vault.read(self.log)
        self.assertIn("(auto-close)", text)

    def test_session_end_gives_up_instead_of_hanging_on_a_held_lock(self):
        """SessionEnd runs against a 1 s hook timeout: it must never wait on the session lock."""
        import fcntl
        self._commit("feat: held")
        holder = open(state.SessionState("s1").path + ".lock", "a")
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        try:
            t0 = time.time()
            r = hooks.dispatch("SessionEnd", payload("SessionEnd", self.repo, reason="other"))
            self.assertLess(time.time() - t0, 1.0)
        finally:
            fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
            holder.close()
        self.assertEqual((r.stdout, r.json, r.exit_code), ("", None, 0))     # silent, not a crash
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "brain.log"), encoding="utf-8") as f:
            self.assertIn("lock busy", f.read())
        self.assertNotIn("(auto-close)", vault.read(self.log))

    def test_changed_line_truncates_at_a_space_never_mid_path(self):
        for i in range(40):
            self._edit(os.path.join(self.repo, "src", "a_very_long_directory_name_%02d" % i, "component.ts"))
        hooks.dispatch("PreCompact", payload("PreCompact", self.repo))
        changed = [l for l in vault.read(self.log).splitlines() if l.startswith("Changed: ")][-1][len("Changed: "):]
        self.assertLessEqual(len(changed), 200)
        self.assertGreater(len(changed), 150)                     # actually exercised the truncation
        for token in changed.split(" "):
            self.assertTrue(token.endswith("/component.ts"), token)

if __name__ == "__main__":
    unittest.main()
