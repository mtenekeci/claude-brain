import json, os, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, write_config, payload
from brain import hooks, briefing

class SubagentHookTests(unittest.TestCase):
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
        self.assertTrue(ac.startswith(briefing.MARK)); self.assertIn("Never commit directly to `main`.", ac); self.assertLessEqual(ac.count("\n"), 13)
        self.assertIsNone(hooks.dispatch("SubagentStart", payload("SubagentStart", self.repo)).json)

    def test_subagent_stop_reminds_only_with_vault_notes(self):
        r = hooks.dispatch("SubagentStop", payload("SubagentStop", self.repo, agent_id="a1", agent_type="Explore", last_assistant_message="Done.\n\nVault notes:\n- all DB calls go through db.ts"))
        self.assertIn("reported vault notes", r.json["hookSpecificOutput"]["additionalContext"]); self.assertIn("Explore", r.json["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(hooks.dispatch("SubagentStop", payload("SubagentStop", self.repo, agent_id="a1", agent_type="Explore", last_assistant_message="Done.")).json)

    def test_hooks_json_registers_both(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(hooks.__file__)))
        data = json.load(open(os.path.join(root, "hooks", "hooks.json"), encoding="utf-8"))
        self.assertIn("SubagentStart", data["hooks"]); self.assertIn("SubagentStop", data["hooks"])
        self.assertEqual(sorted(data["hooks"]), sorted(hooks._HANDLERS))               # Plan 2 restores full parity
