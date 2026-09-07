import json, os, subprocess, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, payload
from brain import hooks, briefing, vault, codemap

class PreToolUseTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo"); self.ctx_path = os.path.join(self.pdir, "context.md")
        codemap.ensure(self.repo, self.pdir)
    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)
    def _pre(self, tool, **ti):
        return hooks.dispatch("PreToolUse", payload("PreToolUse", self.repo, tool_name=tool, tool_input=ti, tool_use_id="t1"))

    def test_push_targets_parsing(self):
        pt = hooks.push_targets
        self.assertEqual(pt("git push", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git push -u origin feat/x", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git push origin HEAD:main", "feat/x"), ["main"])
        self.assertEqual(pt("git push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("git push --force-with-lease origin +feat/x:refs/heads/release", "feat/x"), ["release"])
        self.assertEqual(pt("git add . && git commit -m x && git push origin feat/x", "feat/x"), ["feat/x"])
        self.assertEqual(pt("echo 'git push origin main'", "feat/x"), [])
        self.assertEqual(pt("# git push origin main", "feat/x"), [])
        self.assertEqual(pt("git status | grep push", "feat/x"), [])
        self.assertEqual(pt("git push -o ci.skip origin feat/x", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git push origin feat/x 2>&1", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git push origin feat/x > log.txt 2>&1", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git push origin feat/x &> /dev/null", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git -C /x push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("git --no-pager -c core.x=1 push origin HEAD:main", "feat/x"), ["main"])
        self.assertEqual(pt("git --git-dir=/x/.git push", "feat/x"), ["feat/x"])
        # a newline is a segment separator just like ';' — a heredoc/multi-line Bash body
        # must not hide the push on its second line
        self.assertEqual(pt("echo hi\ngit push origin main", "feat/x"), ["main"])
        # bare '&' backgrounds the left segment; the right one is still a real command
        self.assertEqual(pt("true & git push origin main", "feat/x"), ["main"])
        # leading VAR=value assignments precede the command word
        self.assertEqual(pt("GIT_SSH=x git push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("A=1 B=2 env git push origin main", "feat/x"), ["main"])

    def test_push_guard_denies_mismatch_and_protected_main_by_target(self):
        # fixture Hard Rules contain "Never commit directly to `main`."; repo is on main
        r = self._pre("Bash", command="git push origin main")
        self.assertEqual(r.json["hookSpecificOutput"]["permissionDecision"], "deny"); self.assertIn("main", r.json["hookSpecificOutput"]["permissionDecisionReason"])
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "feat/x"], check=True)
        r = self._pre("Bash", command="git push origin HEAD:main")                          # from feat/x, targets main → deny
        self.assertEqual(r.json["hookSpecificOutput"]["permissionDecision"], "deny")
        vault.write(self.ctx_path, vault.set_frontmatter(vault.read(self.ctx_path), "branch", "feat/y"))
        r = self._pre("Bash", command="git push -u origin feat/x")
        self.assertEqual(r.json["hookSpecificOutput"]["permissionDecision"], "deny"); self.assertIn("feat/y", r.json["hookSpecificOutput"]["permissionDecisionReason"])
        vault.write(self.ctx_path, vault.set_frontmatter(vault.read(self.ctx_path), "branch", "feat/x"))
        self.assertIsNone(self._pre("Bash", command="git push -u origin feat/x").json)
        self.assertIsNone(self._pre("Bash", command="echo 'git push origin main'").json)
        self.assertIsNone(self._pre("Bash", command="git status").json)

    def test_grep_glob_hints_never_block(self):
        r = self._pre("Grep", pattern="Session(Store|Manager)", path=self.repo)
        ac = r.json["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Brain: graph already knows", ac); self.assertIn("src/auth/session.ts", ac); self.assertLessEqual(ac.count("\n"), 10)
        self.assertNotIn("permissionDecision", r.json["hookSpecificOutput"])
        self.assertIsNone(self._pre("Glob", pattern="**/*.zzz").json)
        self.assertIsNone(self._pre("Grep", pattern="a").json)

    def test_agent_tool_is_left_alone(self):
        self.assertIsNone(self._pre("Agent", prompt="Find the auth code", description="x", subagent_type="Explore").json)   # briefing arrives via SubagentStart (Task 10), never twice

    def test_briefing_text_shape(self):
        class C: pass
        c = C(); c.project = type("P", (), {"slug": "demo"})(); c.pdir = self.pdir; c.context_path = self.ctx_path
        t = briefing.text(c)
        self.assertTrue(t.startswith(briefing.MARK)); self.assertIn("Never commit directly to `main`.", t); self.assertIn("graph find", t); self.assertIn("Vault notes:", t)
        self.assertLessEqual(t.count("\n"), 13)

    def test_hooks_json_registers_pretooluse(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(hooks.__file__)))
        data = json.load(open(os.path.join(root, "hooks", "hooks.json"), encoding="utf-8"))
        self.assertEqual(data["hooks"]["PreToolUse"][0]["matcher"], "Bash|Grep|Glob")
