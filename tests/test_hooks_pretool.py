import json, os, subprocess, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, payload, read_text
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
        # a heredoc body is data, not commands — but real segments after the terminator still count
        self.assertEqual(pt("cat <<EOF\ngit push origin main\nEOF", "feat/x"), [])
        self.assertEqual(pt("cat <<'EOF'\ngit push origin main\nEOF\ngit push origin feat/x", "feat/x"), ["feat/x"])
        self.assertEqual(pt("cat <<-END\ngit push origin main\nEND", "feat/x"), [])
        # a '<<' with no matching terminator line is not a heredoc: nothing may be swallowed
        self.assertEqual(pt('echo "a << b"\ngit push origin main', "feat/x"), ["main"])

    def test_push_targets_sees_through_keywords_subshells_and_wrappers(self):
        """Each of these returned [] before — and on_pre_tool_use reads [] as "no push", so
        every one was a false ALLOW on a real `git push origin main`."""
        pt = hooks.push_targets
        self.assertEqual(pt("if true; then git push origin main; fi", "feat/x"), ["main"])
        self.assertEqual(pt("if false; then true; else git push origin main; fi", "feat/x"), ["main"])
        self.assertEqual(pt("for i in 1; do git push origin main; done", "feat/x"), ["main"])
        self.assertEqual(pt("while true; do git push origin main; done", "feat/x"), ["main"])
        self.assertEqual(pt("(git push origin main)", "feat/x"), ["main"])
        self.assertEqual(pt("{ git push origin main; }", "feat/x"), ["main"])
        self.assertEqual(pt("nohup git push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("time git push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("! git push origin main", "feat/x"), ["main"])
        # `timeout`/`xargs` take their own arguments before the command word
        self.assertEqual(pt("timeout 30 git push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("nohup timeout -k 5 30 git push origin main", "feat/x"), ["main"])
        # a wrapper skips its own arguments to the command word it runs; a wrapper with no
        # command word left at all is opaque, not "no push"
        self.assertEqual(pt("timeout 30 bash -c 'git push origin main'", "feat/x"), ["main"])
        self.assertEqual(pt("timeout 30 make build", "feat/x"), [])
        self.assertEqual(pt("xargs -n1 make 'git push origin main'", "feat/x"), [hooks.UNPARSED])
        # `bash -c` is parsed exactly one level deep, and never yields [] when it does push
        self.assertEqual(pt("bash -c 'git push origin main'", "feat/x"), ["main"])
        self.assertEqual(pt("sh -c 'git push origin main'", "feat/x"), ["main"])
        self.assertEqual(pt("sh -c 'echo hi'", "feat/x"), [])
        # a payload the nested parse cannot read, but which does push: the UNPARSED sentinel,
        # never [] and never the current branch (which both deny rules treat as permitted)
        self.assertEqual(pt("bash -c \"echo 'git push origin main'\"", "feat/x"), [hooks.UNPARSED])

    def test_push_targets_handles_keywords_in_command_position_and_arg_taking_wrappers(self):
        """The six shapes the re-review measured as false ALLOWs after round 1."""
        pt = hooks.push_targets
        self.assertEqual(pt("if git push origin main; then echo ok; fi", "feat/x"), ["main"])
        self.assertEqual(pt("while ! git push origin main; do sleep 1; done", "feat/x"), ["main"])
        self.assertEqual(pt("until git push origin main; do sleep 1; done", "feat/x"), ["main"])
        self.assertEqual(pt("eval 'git push origin main'", "feat/x"), ["main"])
        self.assertEqual(pt("eval git push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("sudo -u x git push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("timeout 30 bash -c 'git push origin main'", "feat/x"), ["main"])
        self.assertEqual(pt("env -i git push origin main", "feat/x"), ["main"])

    def test_segments_split_only_on_unquoted_separators(self):
        """A paren (or `;`, or `|`) inside a quoted argument is data, not a separator. Splitting
        there left a half-segment that no longer tokenised — turning a push the guard used to
        catch into one it could not read."""
        pt = hooks.push_targets
        self.assertEqual(pt('git push origin main --push-option="ref (x)"', "feat/x"), ["main"])
        # both are real refspecs to git, so both are reported; the point is that `main` survives
        self.assertEqual(pt('git push origin main "(note)"', "feat/x"), ["main", "(note)"])
        self.assertEqual(pt("git push origin main --push-option='a;b'", "feat/x"), ["main"])
        # …while an unquoted paren still opens a segment of its own
        self.assertEqual(pt("(git push origin main)", "feat/x"), ["main"])
        self.assertEqual(pt("x=$(git push origin main)", "feat/x"), ["main"])
        self.assertEqual(hooks.split_segments("a && b || c ; d | e & f\ng"),
                         ["a ", " b ", " c ", " d ", " e ", " f", "g"])
        self.assertEqual(hooks.split_segments("echo 'a;b(c)'"), ["echo 'a;b(c)'"])

    def test_push_targets_ignores_herestrings_redirections_and_tags(self):
        pt = hooks.push_targets
        # `<<<` is a herestring, not a heredoc opener: it must not swallow the following lines.
        self.assertEqual(pt("cat <<<main\ngit push origin main", "feat/x"), ["main"])
        self.assertEqual(pt("git push origin main <<<x", "feat/x"), ["main"])
        # An attached redirection token is shell syntax, never a refspec.
        self.assertEqual(pt("git push origin <<EOF\nbody\nEOF", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git push origin feat/x >out.log", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git push origin feat/x 2>err.log", "feat/x"), ["feat/x"])
        # A tag refspec targets no branch, so the branch-mismatch rule cannot apply to it.
        self.assertEqual(pt("git push origin refs/tags/v1.0.0", "feat/x"), [])
        self.assertEqual(pt("git push origin refs/tags/v1.0.0 refs/heads/feat/x", "feat/x"), ["feat/x"])
        self.assertEqual(pt("git push origin v1.0.0:refs/tags/v1.0.0", "feat/x"), [])

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

    def test_wrapped_pushes_to_main_deny_end_to_end(self):
        """The unit table proves the parse; this proves the DECISION. The re-review measured all
        of these as ALLOW in the standard configuration — branch `feat/x` checked out, matching
        `branch:` frontmatter, and a Hard Rule forbidding `main` — because the round-1 fallback
        returned the current branch, which is exactly the value both deny rules treat as fine."""
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "feat/x"], check=True)
        vault.write(self.ctx_path, vault.set_frontmatter(vault.read(self.ctx_path), "branch", "feat/x"))
        for cmd in ("if git push origin main; then echo ok; fi",
                    "while ! git push origin main; do sleep 1; done",
                    "until git push origin main; do sleep 1; done",
                    "eval 'git push origin main'",
                    "sudo -u x git push origin main",
                    "timeout 30 bash -c 'git push origin main'",
                    'git push origin main --push-option="ref (x)"',
                    "(git push origin main)",
                    "bash -c \"echo 'git push origin main'\""):        # opaque → the sentinel
            r = self._pre("Bash", command=cmd)
            self.assertIsNotNone(r.json, cmd)
            self.assertEqual(r.json["hookSpecificOutput"]["permissionDecision"], "deny", cmd)
        # the sentinel's own message names the fix, rather than blaming a branch it never read
        r = self._pre("Bash", command="bash -c \"echo 'git push origin main'\"")
        self.assertIn("could not parse the push target", r.json["hookSpecificOutput"]["permissionDecisionReason"])
        # …and none of this turns a legitimate push into a denial
        self.assertIsNone(self._pre("Bash", command="git push -u origin feat/x").json)
        self.assertIsNone(self._pre("Bash", command="timeout 30 git push origin feat/x").json)
        self.assertIsNone(self._pre("Bash", command="echo 'git push origin main'").json)

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
        data = json.loads(read_text(os.path.join(root, "hooks", "hooks.json")))
        self.assertEqual(data["hooks"]["PreToolUse"][0]["matcher"], "Bash|Grep|Glob")
