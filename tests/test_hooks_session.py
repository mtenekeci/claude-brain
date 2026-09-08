import json, os, tempfile, unittest
from tests.helpers import make_vault, make_project, write_config, payload, make_graph_vault, make_source_tree, stub_popen, read_text
from brain import hooks, state, vault

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
        self.assertNotIn("(expected:", r.stdout)          # fixture context.md declares no branch

    def test_compact_nudges_when_last_entry_is_a_placeholder_checkpoint(self):
        """No model turn runs between the PreCompact hook and the compaction, so the checkpoint's
        placeholder lines can only be filled in on the first post-compact turn — SessionStart
        `compact` is that turn and must say so. A real last entry gets no nudge."""
        log = os.path.join(self.vault, "projects", "demo", "log.md")
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo, source="compact"))
        self.assertNotIn("placeholder Completed/Decided", r.stdout)
        with open(log, "a") as f:
            f.write(vault.format_log_entry("2026-01-02", 2, "—", "a.py", "none", "—", tag="pre-compact"))
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo, session_id="s2", source="compact"))
        self.assertIn("Session 2 (pre-compact)", r.stdout)
        self.assertIn("placeholder Completed/Decided", r.stdout)
        self.assertIn("## State and ## Active Work in " + os.path.join(self.vault, "projects", "demo", "context.md"), r.stdout)
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo, session_id="s3", source="startup"))
        self.assertNotIn("placeholder Completed/Decided", r.stdout)   # a fresh session cannot recall the detail

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

    def test_payload_without_cwd_or_session_is_silent(self):
        """Malformed payloads must never fall back to the ambient cwd or a shared session id."""
        sessions = os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "sessions")
        for bad in ({}, {"cwd": self.repo}, {"session_id": "s9"}, {"cwd": "", "session_id": "s9"},
                    {"cwd": self.repo, "session_id": ""}, {"cwd": self.repo, "session_id": 5}, "not-a-dict"):
            r = hooks.dispatch("SessionStart", bad)
            self.assertEqual((r.stdout, r.json, r.exit_code), ("", None, 0), bad)
        self.assertFalse(os.path.isdir(sessions) and os.listdir(sessions))

    def test_hooks_json_registers_only_handled_events(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "hooks.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(set(data["hooks"]) <= set(hooks._HANDLERS), set(data["hooks"]) - set(hooks._HANDLERS))


class SessionStartGraphTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo")

    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_session_start_creates_codemap_and_injects_top(self):
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo, source="startup"))
        self.assertTrue(os.path.exists(os.path.join(self.pdir, "codemap.md")))
        self.assertTrue(os.path.exists(os.path.join(self.pdir, ".brain", "graph.json")))
        self.assertIn("Brain: most-connected nodes", r.stdout); self.assertIn("project demo", r.stdout)
        self.assertNotIn("src/auth/session.ts  (SessionStore", r.stdout)          # generated tree is NOT injected
        tail = r.stdout.split("(last entry only)")[-1]
        self.assertLessEqual(tail.count("\n"), 45 + 6)                             # +6 for the fixture log entry lines

    def test_large_repo_writes_a_stub_instead_of_building(self):
        """At LARGE_REPO_FILES the synchronous build is skipped entirely: the user gets the
        curated scaffold with an empty generated block, and the detached --force regen fills it."""
        write_config(self.tmp.name, self.vault, extra={"async_regen": True})
        calls, builds = [], []
        orig_lf, orig_build = hooks.codemap.list_files, hooks.codemap.build_layer
        hooks.codemap.list_files = lambda d: ["src/f%04d.ts" % i for i in range(4000)]
        hooks.codemap.build_layer = lambda *a, **k: builds.append(a) or orig_build(*a, **k)
        orig_popen = stub_popen(calls)
        try:
            hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            hooks.codemap.list_files, hooks.codemap.build_layer = orig_lf, orig_build
            hooks.subprocess.Popen = orig_popen
        self.assertEqual(builds, [])                                       # no synchronous full build
        self.assertEqual(len(calls), 1); self.assertIn("--regen", calls[0][0]); self.assertIn("--force", calls[0][0])
        self.assertTrue(state.SessionState.load("s1").codemap_stale)
        cm = read_text(os.path.join(self.pdir, "codemap.md"))
        sha, gen, curated = hooks.codemap.split_codemap(cm)
        self.assertEqual((sha, gen.strip()), ("", ""))                     # empty generated block
        self.assertIn("## Modules", curated)                               # curated template present

    def test_large_repo_with_async_off_builds_synchronously(self):
        """async_regen off means no background process will ever fill the stub in, so the
        foreground build is the only path left — a permanently empty code map is worse."""
        write_config(self.tmp.name, self.vault, extra={"async_regen": False})
        orig_lf = hooks.codemap.list_files
        real = orig_lf(self.repo)
        hooks.codemap.list_files = lambda d: real + ["pad/%d.ts" % i for i in range(3000)]
        try:
            hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            hooks.codemap.list_files = orig_lf
        text = read_text(os.path.join(self.pdir, "codemap.md"))
        self.assertIn("src/auth/session.ts", text)                                  # not a stub: built in the foreground
        self.assertFalse(state.SessionState.load("s1").codemap_stale)               # nothing was deferred

    def test_heavy_work_runs_before_the_lock(self):
        order = []
        orig_locked, orig_load = hooks.state.locked, hooks.graph.load
        def spy_locked(session_id, timeout=None):
            order.append("lock"); return orig_locked(session_id, timeout)
        def spy_load(*a, **k):
            order.append("graph"); return orig_load(*a, **k)
        hooks.state.locked, hooks.graph.load = spy_locked, spy_load
        try:
            hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            hooks.state.locked, hooks.graph.load = orig_locked, orig_load
        # The invariant is *every* graph build happens before the lock, not how many there are:
        # lint's auto-apply rewrites context.md and re-loads the graph to refresh the cache.
        self.assertEqual(order[0], "graph"); self.assertEqual(order[-1], "lock")
        self.assertEqual(order.count("lock"), 1); self.assertNotIn("graph", order[order.index("lock"):])


if __name__ == "__main__":
    unittest.main()


class LargeRepoDeferralTests(unittest.TestCase):
    """SessionStart's bounded code-map path: the stub, the injected notice, and the fact that
    `compact`/`resume` re-firing SessionStart spawns at most one background build."""

    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault, extra={"async_regen": True})
        self.repo = make_project(self.tmp.name, slug="demo")
        self.pdir = os.path.join(self.vault, "projects", "demo")
        self._orig_lf = hooks.codemap.list_files
        hooks.codemap.list_files = lambda d: ["src/f%04d.ts" % i for i in range(4000)]

    def tearDown(self):
        hooks.codemap.list_files = self._orig_lf
        os.environ.clear(); os.environ.update(self._env)
        self.tmp.cleanup()

    def _session_starts(self, *sources):
        calls = []
        orig_popen = stub_popen(calls)
        outs = []
        try:
            for src in sources:
                outs.append(hooks.dispatch("SessionStart", payload("SessionStart", self.repo, source=src)).stdout)
        finally:
            hooks.subprocess.Popen = orig_popen
        return outs, calls

    def test_deferred_code_map_is_announced_in_the_injection(self):
        (out,), calls = self._session_starts("startup")
        self.assertIn("Brain: code map deferred", out)
        self.assertIn("holds only the curated block", out)
        self.assertIn("map --regen", out)
        self.assertEqual(len(calls), 1)
        self.assertTrue(state.SessionState.load("s1").codemap_stale)

    def test_a_stale_but_complete_code_map_is_not_described_as_empty(self):
        """Deferral fires for both an empty stub and a generated block that predates the tree.
        Telling the user the file 'holds only the curated block' is false in the second case."""
        self._session_starts("startup")                     # writes the stub codemap.md
        cm = os.path.join(self.pdir, "codemap.md")
        _, _, curated = hooks.codemap.split_codemap(read_text(cm))
        with open(cm, "w", encoding="utf-8") as f:
            f.write(hooks.codemap.gen_start("an-older-commit") + "\nsrc/f0000.ts\n" + hooks.codemap.GEN_END + "\n\n" + curated)
        calls = []
        orig_popen = stub_popen(calls)                      # a fresh session id would spawn for real
        try:
            out = hooks.dispatch("SessionStart", payload("SessionStart", self.repo, session_id="s2")).stdout
        finally:
            hooks.subprocess.Popen = orig_popen
        self.assertIn("Brain: code map deferred", out)
        self.assertIn("codemap.md is stale", out)
        self.assertNotIn("holds only the curated block", out)

    def test_compact_and_resume_do_not_each_spawn_a_build(self):
        outs, calls = self._session_starts("startup", "compact", "resume")
        self.assertEqual(len(calls), 1, "one detached build per session, not one per SessionStart")
        self.assertTrue(all("code map deferred" in o for o in outs))
        # a moved tree earns a fresh build
        s = state.SessionState.load("s1"); self.assertTrue(s.regen_spawned_for)
        s.regen_spawned_for = "different-key"; s.save()
        _, more = self._session_starts("resume")
        self.assertEqual(len(more), 1)

    def test_a_failed_codemap_refresh_leaves_the_map_marked_stale(self):
        """`codemap_stale` must not read 'fresh' just because the refresh blew up."""
        hooks.codemap.list_files = self._orig_lf                    # small repo: the normal path
        orig = hooks.codemap.ensure
        hooks.codemap.ensure = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
        try:
            hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            hooks.codemap.ensure = orig
        self.assertTrue(state.SessionState.load("s1").codemap_stale)

    def test_a_fresh_code_map_is_not_reported_as_deferred(self):
        """`large` is a size test. Once the detached build has filled codemap.md in, a later
        compact/resume must neither claim the map is deferred nor re-spawn a build."""
        # First SessionStart: stub written, one build spawned.
        outs, calls = self._session_starts("startup")
        self.assertIn("code map deferred", outs[0])
        self.assertEqual(len(calls), 1)
        # Simulate that detached build completing: a real generated block stamped with the
        # current freshness key.
        key = hooks.codemap.freshness_key(self.repo, hooks.codemap.list_files(self.repo))
        cm = os.path.join(self.pdir, "codemap.md")
        _, _, curated = hooks.codemap.split_codemap(read_text(cm))
        with open(cm, "w", encoding="utf-8") as f:
            f.write(hooks.codemap.gen_start(key) + "\nsrc/f0000.ts\n" + hooks.codemap.GEN_END + "\n\n" + curated)
        # A fresh session id, so the spawn claim from the first run cannot be what suppresses it.
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo, session_id="s2", source="resume"))
        self.assertNotIn("code map deferred", r.stdout)
        self.assertFalse(state.SessionState.load("s2").codemap_stale)
        calls2 = []
        orig = stub_popen(calls2)
        try:
            hooks.dispatch("SessionStart", payload("SessionStart", self.repo, session_id="s3", source="resume"))
        finally:
            hooks.subprocess.Popen = orig
        self.assertEqual(calls2, [], "a current code map must not be force-rebuilt")

    def test_a_failed_spawn_is_not_remembered_as_one(self):
        """The claim is optimistic, so a Popen that never started has to release it — otherwise
        compact/resume see `regen_spawned_for` set and never retry the build."""
        def exploding(*a, **k):
            if a and "--regen" in list(a[0]):
                raise OSError("no fork for you")
            return orig(*a, **k)
        orig = hooks.subprocess.Popen
        hooks.subprocess.Popen = exploding
        try:
            r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            hooks.subprocess.Popen = orig
        self.assertIn("code map deferred", r.stdout)          # the event itself still succeeds
        s = state.SessionState.load("s1")
        self.assertEqual(s.regen_spawned_for, "")
        self.assertEqual(s.last_regen_spawn_at, 0.0)
        # ...and the next SessionStart therefore does try again.
        _, calls = self._session_starts("resume")
        self.assertEqual(len(calls), 1)
