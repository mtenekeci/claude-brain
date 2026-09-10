import os, subprocess, tempfile, unittest
from tests.helpers import make_vault, make_project, write_config, payload, stub_popen
from brain import hooks, state, vault

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
        write_config(self.tmp.name, self.vault, extra={"async_regen": True})
        calls = []
        orig_popen = stub_popen(calls)
        try:
            for i in range(3):
                self._post("Edit", file_path=os.path.join(self.repo, "src", "e%d.ts" % i), old_string="a", new_string="b")
        finally:
            hooks.subprocess.Popen = orig_popen
        self.assertEqual(len(calls), 1)
        s = state.SessionState.load("s1"); self.assertGreater(s.last_regen_spawn_at, 0)


class PostToolUseDeliveryTests(unittest.TestCase):
    """PostToolUse stdout is transcript-only in Claude Code — every reminder must ride
    hookSpecificOutput.additionalContext instead (SMOKE.md check 10)."""

    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")

    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def _commit(self, msg):
        import subprocess
        with open(os.path.join(self.repo, "a.py"), "a") as f: f.write("# x\n")
        subprocess.run(["git", "-C", self.repo, "commit", "-qam", msg], check=True)

    def test_reminders_are_delivered_as_additional_context(self):
        self._commit("feat: x")
        r = hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Bash",
                                                  tool_input={"command": "git commit -m x"}))
        self.assertIn("commit landed", r.stdout)              # handlers still compose plain text
        self.assertEqual(r.json["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(r.json["hookSpecificOutput"]["additionalContext"], r.stdout)

    def test_a_silent_result_stays_silent(self):
        r = hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Read",
                                                  tool_input={"file_path": os.path.join(self.repo, "notes.txt")}))
        self.assertEqual((r.stdout, r.json), ("", None))

    def test_only_post_tool_use_is_rewrapped(self):
        """SessionStart and UserPromptSubmit do inject stdout; they must keep using it."""
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertIn("Brain: vault context", r.stdout); self.assertIsNone(r.json)

    def test_entry_point_emits_the_json_once(self):
        import json as _json, subprocess, sys
        self._commit("feat: y")
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(hooks.__file__))),
                               "brain", "__main__.py")
        body = _json.dumps(payload("PostToolUse", self.repo, tool_name="Bash",
                                   tool_input={"command": "git commit -m y"}))
        r = subprocess.run([sys.executable, main_py, "hook", "PostToolUse"], input=body, text=True,
                           capture_output=True, env=dict(os.environ))
        out = _json.loads(r.stdout)                            # exactly one JSON document, no stray text
        self.assertIn("commit landed", out["hookSpecificOutput"]["additionalContext"])

class BashVaultWriteTests(unittest.TestCase):
    """A vault edit made through the shell (heredoc, `sed -i`, `{BRAIN} sync`) never passes
    through Edit/Write. Before mtime arbitration the Stop gate never saw it, so
    commits_since_vault_write stayed armed and the gate re-fired against a current vault."""
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")
        self.pdir = os.path.join(self.vault, "projects", "demo")
        self.context = os.path.join(self.pdir, "context.md")
    def tearDown(self):
        self.tmp.cleanup()
        os.environ.clear(); os.environ.update(self._env)

    def _post(self, tool, **tool_input):
        return hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name=tool,
                                                     tool_input=tool_input, tool_response={}))

    def _touch_later(self, path, body=None):
        """Write and stamp the mtime forward, so the test never depends on filesystem clock
        granularity to notice a change that happened milliseconds ago."""
        if body is not None:
            with open(path, "a") as f: f.write(body)
        t = os.stat(path).st_mtime + 10
        os.utime(path, (t, t))

    def _commit(self, msg):
        with open(os.path.join(self.repo, "c.py"), "a") as f: f.write("# %s\n" % msg)
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", msg], check=True)
        return self._post("Bash", command="git commit -m '%s'" % msg)

    def _armed(self):
        return state.SessionState.load("s1").commits_since_vault_write

    def test_first_bash_call_adopts_baseline_without_counting_a_write(self):
        self._post("Bash", command="ls")
        s = state.SessionState.load("s1")
        self.assertEqual(s.vault_writes, 0)
        self.assertGreater(s.vault_mtime_seen, 0.0)

    def test_shell_vault_write_clears_the_gate(self):
        hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self._commit("feat: thing")
        self.assertEqual(self._armed(), 1)
        self._touch_later(self.context, "\nupdated by a heredoc\n")
        self._post("Bash", command="cat >> %s <<'EOF'\nx\nEOF" % self.context)
        self.assertEqual(self._armed(), 0)
        self.assertEqual(state.SessionState.load("s1").vault_writes, 1)

    def test_plugin_frontmatter_write_does_not_clear_the_gate(self):
        """The commit handler rewrites context.md's `branch:` itself. That is the plugin's own
        bookkeeping, not the user's vault update, and must not disarm the commit it just armed."""
        hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "feat/beta"], check=True)
        self._commit("feat: thing")
        self.assertEqual(self._armed(), 1)
        self._post("Bash", command="ls")            # nothing touched the vault since
        self.assertEqual(self._armed(), 1)

    def test_brain_cache_writes_do_not_count(self):
        hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self._commit("feat: thing")
        cache = os.path.join(self.pdir, ".brain")
        os.makedirs(cache, exist_ok=True)
        with open(os.path.join(cache, "graph.json"), "w") as f: f.write("{}")
        self._touch_later(os.path.join(cache, "graph.json"))
        self._post("Bash", command="ls")
        self.assertEqual(self._armed(), 1)

    def test_tool_write_does_not_double_count_on_the_next_bash_call(self):
        self._post("Bash", command="ls")            # adopt baseline
        self._touch_later(self.context, "\nx\n")
        self._post("Edit", file_path=self.context)
        self._post("Bash", command="ls")
        self.assertEqual(state.SessionState.load("s1").vault_writes, 1)
