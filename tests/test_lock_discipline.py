"""Nothing slow may run while the per-session lock is held.

The lock serialises every hook of a session (and of concurrent sessions sharing a
session id). A git subprocess, a file-tree walk, a graph build or a lint pass inside
the locked body turns a 1 ms critical section into a multi-second one, so each handler
does that work in its `prepare(ctx)` phase, which `dispatch()` runs BEFORE `state.locked()`.

This test asserts the invariant directly: it flags the lock as held, then fails if any
of the four expensive entry points is reached while the flag is set.
"""
import os, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, payload
from brain import codemap, gitinfo, graph, hooks, lint, state


class LockDisciplineTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo")
        codemap.ensure(self.repo, self.pdir)
        cm = os.path.join(self.pdir, "codemap.md")
        with open(cm, encoding="utf-8") as f: text = f.read()
        with open(cm, "w", encoding="utf-8") as f:
            f.write(text.replace("|---|---|---|---|\n",
                                 "|---|---|---|---|\n| Auth flow | src/auth/ | Session cookies | uses:: [[concepts/nextauth|NextAuth]] |\n", 1))
        self.held = []            # non-empty while the lock is held
        self.violations = []

    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def _instrument(self):
        """Wrap state.locked + the four expensive entry points. Returns a restore callable."""
        originals = [(hooks.state, "locked", hooks.state.locked), (graph, "load", graph.load),
                     (gitinfo, "_git", gitinfo._git), (codemap, "list_files", codemap.list_files),
                     (lint, "run", lint.run)]

        def guard(name, fn):
            def wrapped(*a, **k):
                if self.held:
                    self.violations.append(name)
                return fn(*a, **k)
            return wrapped

        orig_locked = hooks.state.locked

        class _Locked(object):
            def __init__(inner, cm):
                inner.cm = cm
            def __enter__(inner):
                self.held.append(1)
                return inner.cm.__enter__()
            def __exit__(inner, *exc):
                try:
                    return inner.cm.__exit__(*exc)
                finally:
                    self.held.pop()

        hooks.state.locked = lambda sid, timeout=None: _Locked(orig_locked(sid, timeout))
        for mod, name, fn in originals[1:]:
            setattr(mod, name, guard("%s.%s" % (mod.__name__, name), fn))

        def restore():
            for mod, name, fn in originals:
                setattr(mod, name, fn)
        return restore

    def test_no_heavy_work_inside_the_lock(self):
        restore = self._instrument()
        try:
            hooks.dispatch("SessionStart", payload("SessionStart", self.repo, source="startup"))
            hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="explain the auth flow session handling"))
            hooks.dispatch("PreToolUse", payload("PreToolUse", self.repo, tool_name="Grep", tool_input={"pattern": "SessionStore"}, tool_use_id="t1"))
            hooks.dispatch("PreToolUse", payload("PreToolUse", self.repo, tool_name="Bash", tool_input={"command": "git push origin feat/x"}, tool_use_id="t2"))
            hooks.dispatch("PreCompact", payload("PreCompact", self.repo))
            hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Bash",
                                                  tool_input={"command": "git commit -m x"}, tool_response={}))
        finally:
            restore()
        self.assertEqual(self.violations, [], "ran inside the session lock: %s" % sorted(set(self.violations)))
        self.assertEqual(self.held, [])

    def test_prepare_exception_is_swallowed_and_logged(self):
        """A raising prepare() must cost the event, never the session."""
        def boom(ctx):
            raise RuntimeError("prepare-kaboom")
        original = hooks.on_session_start.prepare
        hooks.on_session_start.prepare = boom
        try:
            r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        finally:
            hooks.on_session_start.prepare = original
        self.assertEqual((r.stdout, r.json, r.exit_code), ("", None, 0))
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "brain.log"), encoding="utf-8") as f:
            logged = f.read()
        self.assertIn("SessionStart", logged); self.assertIn("prepare-kaboom", logged)


if __name__ == "__main__":
    unittest.main()
