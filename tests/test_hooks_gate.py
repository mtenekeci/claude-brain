import json, os, tempfile, unittest
from tests.helpers import make_vault, make_project, write_config, payload
from brain import hooks, state

class GateTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")
    def tearDown(self):
        self.tmp.cleanup()
        os.environ.clear()
        os.environ.update(self._env)

    def _stop(self, msg="Done.", active=False, **extra):
        return hooks.dispatch("Stop", payload("Stop", self.repo, last_assistant_message=msg, stop_hook_active=active, **extra))

    def _commit(self):
        """Make a real commit, then report it through the hook (HEAD-verified since Task 7)."""
        import subprocess
        hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        with open(os.path.join(self.repo, "c.py"), "a") as f: f.write("# x\n")
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "x"], check=True)
        hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Bash", tool_input={"command": "git commit -m x"}, tool_response={}))

    def test_pure_decision_matrix(self):
        s = state.SessionState("x")
        self.assertIsNone(hooks.gate_decision(s, "all", False, None, "Done."))          # read-only turn
        s.note_commit("c")
        self.assertIn("1 commit", hooks.gate_decision(s, "all", False, None, "Done."))   # hard tier
        self.assertIsNone(hooks.gate_decision(s, "all", True, None, "Done."))            # loop guard
        self.assertIsNone(hooks.gate_decision(s, "all", False, "agent-1", "Done."))      # inside subagent
        self.assertIsNone(hooks.gate_decision(s, "off", False, None, "Done."))
        s = state.SessionState("y")
        for i in range(5): s.note_source_edit("/r/%d.py" % i)
        self.assertIn("5 uncommitted source edits", hooks.gate_decision(s, "all", False, None, "Done."))  # soft tier
        self.assertIsNone(hooks.gate_decision(s, "all", False, None, "Which option do you prefer?"))   # question suppresses
        self.assertIsNone(hooks.gate_decision(s, "commits", False, None, "Done."))                      # commits-only mode
        s2 = state.SessionState("z"); s2.note_source_edit("/r/a.py"); s2.note_source_edit("/r/b.py")
        self.assertIsNone(hooks.gate_decision(s2, "all", False, None, "Done."))                        # < 5 edits

    def test_blocks_once_per_turn_then_allows(self):
        self._commit()
        r1 = self._stop()
        self.assertEqual(r1.json["decision"], "block"); self.assertIn("context.md", r1.json["reason"])
        self.assertNotIn("hookSpecificOutput", r1.json)
        r2 = self._stop(active=True)
        self.assertIsNone(r2.json)
        r3 = self._stop()                       # same turn, already blocked once
        self.assertIsNone(r3.json)
        hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="continue"))
        r4 = self._stop()                       # new turn, still unsynced → blocks again
        self.assertEqual(r4.json["decision"], "block")

    def test_vault_write_releases_gate(self):
        self._commit()
        hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Edit", tool_input={"file_path": os.path.join(self.vault, "projects", "demo", "context.md"), "old_string": "a", "new_string": "b"}, tool_response={}))
        self.assertIsNone(self._stop().json)

    def test_soft_tier_resets_after_firing(self):
        for i in range(5):
            hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Edit", tool_input={"file_path": os.path.join(self.repo, "s%d.py" % i), "old_string": "a", "new_string": "b"}, tool_response={}))
        self.assertEqual(self._stop().json["decision"], "block")
        hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="go on"))
        self.assertIsNone(self._stop().json)     # counter reset by the block; needs 5 more edits
