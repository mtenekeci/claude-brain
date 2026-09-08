"""Subagent briefing (SubagentStart) and the vault-notes reminder.

SubagentStop is gone: SMOKE.md check 10 showed its output never reaches the parent turn.
The two channels that DO reach the parent are PostToolUse on a foreground `Agent` call and
the `<task-notification>` prompt a background agent's completion submits.
"""
import json, os, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, write_config, payload, read_text
from brain import hooks, briefing

class AgentNotesTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")

    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_subagent_start_briefs_only_real_subagents(self):
        r = hooks.dispatch("SubagentStart", payload("SubagentStart", self.repo, agent_id="a1", agent_type="Explore"))
        ac = r.json["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ac.startswith(briefing.MARK)); self.assertIn("Never commit directly to `main`.", ac)
        self.assertLessEqual(ac.count("\n"), 13)
        self.assertIsNone(hooks.dispatch("SubagentStart", payload("SubagentStart", self.repo)).json)

    def test_foreground_agent_result_with_vault_notes_reminds(self):
        r = hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Agent", tool_input={"prompt": "x"},
                                                  tool_response={"content": "Done.\n\nVault notes:\n- all DB calls go through db.ts"}))
        self.assertIn("reported vault notes", r.stdout); self.assertIn("architecture.md", r.stdout)
        r2 = hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Agent", tool_input={"prompt": "x"},
                                                   tool_response={"content": "Done."}))
        self.assertEqual(r2.stdout, "")

    def test_background_task_notification_with_vault_notes_reminds(self):
        note = "<task-notification>\n<result>Done.\n\nVault notes:\n- auth is enforced in middleware</result>\n</task-notification>"
        r = hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt=note))
        self.assertIn("reported vault notes", r.stdout)
        self.assertEqual(hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo,
                                                                    prompt="<task-notification>Done.</task-notification>")).stdout, "")

    def test_task_notification_never_clears_the_turn_gate(self):
        """A completion notice is not a user turn: the reminder path must not reset the gate."""
        from brain import state
        s = state.SessionState.load("s1"); s.stop_blocks_this_turn = 1; s.save()
        note = "<task-notification>Vault notes:\n- x</task-notification>"
        hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt=note))
        self.assertEqual(state.SessionState.load("s1").stop_blocks_this_turn, 1)

    def test_briefing_is_delivered_exactly_once_across_both_events(self):
        # Models a real dispatch: PreToolUse(Agent) fires in the parent, then SubagentStart fires in the child.
        pre = hooks.dispatch("PreToolUse", payload("PreToolUse", self.repo, tool_name="Agent",
                                                   tool_input={"prompt": "Find the auth code"}, tool_use_id="t1"))
        start = hooks.dispatch("SubagentStart", payload("SubagentStart", self.repo, agent_id="a1", agent_type="Explore"))
        deliveries = [r for r in (pre, start) if r.json and briefing.MARK in str(r.json)]
        self.assertEqual(len(deliveries), 1)          # SubagentStart only; the Agent prompt is never rewritten

    def test_subagent_stop_is_not_registered(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(hooks.__file__)))
        data = json.loads(read_text(os.path.join(root, "hooks", "hooks.json")))
        self.assertNotIn("SubagentStop", data["hooks"]); self.assertNotIn("SubagentStop", hooks._HANDLERS)
        self.assertEqual(sorted(data["hooks"]), sorted(hooks._HANDLERS))
        self.assertEqual(data["hooks"]["PostToolUse"][0]["matcher"], "Bash|Read|Edit|Write|MultiEdit|Agent")


if __name__ == "__main__":
    unittest.main()
