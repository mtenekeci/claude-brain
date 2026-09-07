import os, subprocess, tempfile, unittest
from tests.helpers import make_vault, make_project, write_config, payload
from brain import hooks, state, vault

def stub_popen(calls):
    """Intercept only the detached `map --regen` spawn. subprocess.run() (gitinfo) resolves
    Popen through the same module global, so real git calls must still reach the real Popen."""
    orig = hooks.subprocess.Popen
    def fake(*a, **k):
        if a and "--regen" in list(a[0]):
            calls.append(a)
            return type("P", (), {"pid": 1})()
        return orig(*a, **k)
    hooks.subprocess.Popen = fake
    return orig


class PostToolUseTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")
    def tearDown(self):
        self.tmp.cleanup()
        os.environ.clear(); os.environ.update(self._env)

    def _post(self, tool, **tool_input):
        return hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name=tool,
                                                       tool_input=tool_input, tool_response={}))

    def test_helpers(self):
        self.assertTrue(hooks.is_source_path("/r/a.ts")); self.assertFalse(hooks.is_source_path("/r/README.md"))
        self.assertEqual(hooks.bash_read_targets("cat src/a.py | head; sed -n '1,20p' lib/b.go && ls"), ["src/a.py", "lib/b.go"])
        self.assertTrue(hooks.is_git_commit("git add . && git commit -m 'x'"))
        self.assertTrue(hooks.is_git_commit("git commit --dry-run"))          # HEAD check is the guard, not the regex
        self.assertFalse(hooks.is_git_commit("git committee")); self.assertFalse(hooks.is_git_commit("git log"))

    def _real_commit(self, msg):
        with open(os.path.join(self.repo, "c.py"), "a") as f: f.write("# %s\n" % msg)
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", msg], check=True)

    def test_commit_counts_only_when_head_moved(self):
        hooks.dispatch("SessionStart", payload("SessionStart", self.repo))        # records last_head_sha
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "feat/beta"], check=True)
        r = self._post("Bash", command="git commit -m 'nothing to commit'")       # no HEAD change
        self.assertEqual(r.stdout, "")
        self.assertEqual(state.SessionState.load("s1").commits, 0)
        self._real_commit("feat: thing")
        r = self._post("Bash", command="git add . && git commit -m 'feat: thing'")
        self.assertIn("Brain: commit landed", r.stdout)
        fm, _ = vault.parse_frontmatter(vault.read(os.path.join(self.vault, "projects", "demo", "context.md")))
        self.assertEqual(fm["branch"], "feat/beta")
        s = state.SessionState.load("s1")
        self.assertEqual((s.commits, s.commits_since_vault_write), (1, 1))
        self.assertEqual(s.commit_subjects, ["feat: thing"])
        r = self._post("Bash", command="git commit --amend --no-edit")             # HEAD unchanged again
        self.assertEqual(state.SessionState.load("s1").commits, 1)

    def test_commit_message_containing_dry_run_still_counts(self):
        self._real_commit("note: --dry-run is unsupported")
        self._post("Bash", command="git commit -m 'note: --dry-run is unsupported'")
        self.assertEqual(state.SessionState.load("s1").commits, 1)

    def test_reads_count_and_nudge_only_at_3_6_9(self):
        outs = []
        for i in range(10):
            outs.append(self._post("Read", file_path=os.path.join(self.repo, "f%d.ts" % i)).stdout)
        self.assertEqual([i + 1 for i, o in enumerate(outs) if "source files read" in o], [3, 6, 9])
        self.assertEqual(state.SessionState.load("s1").reads, 10)

    def test_multi_file_bash_read_crossing_threshold_still_nudges(self):
        self._post("Read", file_path=os.path.join(self.repo, "f1.ts"))
        self._post("Read", file_path=os.path.join(self.repo, "f2.ts"))
        r = self._post("Bash", command="cat %s/a.py %s/b.py" % (self.repo, self.repo))   # 2 → 4 skips exactly 3
        self.assertIn("4 source files read", r.stdout)

    def test_bash_read_counts_but_vault_and_md_do_not(self):
        self._post("Bash", command="cat %s/a.py" % self.repo)
        self._post("Read", file_path=os.path.join(self.vault, "projects", "demo", "architecture.md"))
        self._post("Read", file_path=os.path.join(self.repo, "notes.md"))
        self.assertEqual(state.SessionState.load("s1").reads, 1)

    def test_edits_classified(self):
        self._post("Edit", file_path=os.path.join(self.repo, "src", "x.ts"), old_string="a", new_string="b")
        self._post("Write", file_path=os.path.join(self.vault, "projects", "demo", "context.md"), content="x")
        s = state.SessionState.load("s1")
        self.assertEqual((s.source_edits, s.vault_writes, s.source_edits_since_vault_write), (1, 1, 0))
        self.assertTrue(s.codemap_stale)

    def test_read_nudge_suppressed_only_when_vault_written_since_last_nudge(self):
        for i in range(3): self._post("Read", file_path=os.path.join(self.repo, "f%d.ts" % i))   # nudge #1 at 3
        self._post("Edit", file_path=os.path.join(self.vault, "projects", "demo", "architecture.md"), old_string="a", new_string="b")
        for i in range(3, 6): r = self._post("Read", file_path=os.path.join(self.repo, "f%d.ts" % i))
        self.assertEqual(r.stdout, "")                                              # vault written since nudge #1 → 6 is silent
        for i in range(6, 9): r = self._post("Read", file_path=os.path.join(self.repo, "f%d.ts" % i))
        self.assertIn("9 source files read", r.stdout)                              # nothing written since → nudges again

    def test_prepare_runs_before_lock_and_supplies_git_facts(self):
        """Every git subprocess for PostToolUse runs in prepare(), outside the session lock."""
        seen = {}
        orig = state.locked
        def spy(session_id, timeout=None):
            seen["locked_after_prepare"] = "pre" in seen
            return orig(session_id, timeout)
        pre = hooks.on_post_tool_use.prepare
        def wrapped(c):
            r = pre(c); seen["pre"] = r; return r
        hooks.on_post_tool_use.prepare = wrapped
        state.locked = spy
        try:
            self._real_commit("feat: p")
            self._post("Bash", command="git commit -m 'feat: p'")
        finally:
            hooks.on_post_tool_use.prepare = pre; state.locked = orig
        self.assertTrue(seen["locked_after_prepare"])
        self.assertEqual(seen["pre"]["subject"], "feat: p"); self.assertEqual(len(seen["pre"]["sha"]), 40)

    def test_source_edit_spawns_regen_at_most_once_per_minute(self):
        calls = []
        orig_popen = stub_popen(calls)
        try:
            for i in range(3):
                self._post("Edit", file_path=os.path.join(self.repo, "src", "e%d.ts" % i), old_string="a", new_string="b")
        finally:
            hooks.subprocess.Popen = orig_popen
        self.assertEqual(len(calls), 1)
        s = state.SessionState.load("s1"); self.assertGreater(s.last_regen_spawn_at, 0)
