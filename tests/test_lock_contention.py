"""Lock contention degrades to a logged skip, never to a hang.

Every event's `dispatch()` waits a bounded time for the session lock (`hooks._LOCK_WAIT`,
defaulting to `_LOCK_WAIT_DEFAULT`). An unbounded wait is indistinguishable from a hang:
Claude Code's own hook deadline would be the only thing ending it, and at that point the
output is discarded anyway — so waiting past the budget costs the whole event and buys
nothing. These tests hold the lock from the same process and assert the three properties
that make that safe: the wait ends, the event yields no output, and the skip is logged.
"""
import fcntl, os, tempfile, time, unittest
from tests.helpers import make_vault, make_project, write_config, payload
from brain import config, hooks, state


class LockContentionTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo")
        # Budgets are seconds in production; shrink them so the suite pays milliseconds.
        self._wait = dict(hooks._LOCK_WAIT), hooks._LOCK_WAIT_DEFAULT
        hooks._LOCK_WAIT = {k: 0.1 for k in hooks._LOCK_WAIT}
        hooks._LOCK_WAIT_DEFAULT = 0.1

    def tearDown(self):
        hooks._LOCK_WAIT, hooks._LOCK_WAIT_DEFAULT = self._wait
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def _hold(self):
        """Take the raw flock the way a peer hook process would. Returns a release callable."""
        holder = open(state.SessionState("s1").path + ".lock", "a")
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        def release():
            fcntl.flock(holder.fileno(), fcntl.LOCK_UN); holder.close()
        return release

    def _log(self):
        try:
            with open(os.path.join(config.data_dir(), "brain.log"), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def test_every_event_skips_instead_of_waiting_when_a_peer_holds_the_lock(self):
        """The parallel-tool case: many PostToolUse hooks land on one session id at once.
        Whichever loses the race must give up on its own budget, not on the hook deadline."""
        events = [("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="explain auth")),
                  ("PostToolUse", payload("PostToolUse", self.repo, tool_name="Read",
                                          tool_input={"file_path": "x.py"}, tool_response={})),
                  ("Stop", payload("Stop", self.repo)),
                  ("PreToolUse", payload("PreToolUse", self.repo, tool_name="Grep",
                                         tool_input={"pattern": "x"}, tool_use_id="t1")),
                  ("SessionStart", payload("SessionStart", self.repo, source="startup")),
                  ("PreCompact", payload("PreCompact", self.repo)),
                  ("SessionEnd", payload("SessionEnd", self.repo, reason="other"))]
        release = self._hold()
        try:
            for event, p in events:
                t0 = time.time()
                r = hooks.dispatch(event, p)
                elapsed = time.time() - t0
                self.assertLess(elapsed, 2.0, "%s waited %.2fs on a held lock" % (event, elapsed))
                self.assertEqual(r.stdout, "", "%s emitted output despite skipping" % event)
                self.assertIn("%s skipped: session lock busy" % event, self._log())
        finally:
            release()

    def test_stop_fails_open_rather_than_blocking_the_turn(self):
        """The gate needs state to decide. With none, fail-closed would block turn end on zero
        evidence — and the re-entry (`stop_hook_active`) would still find no state, so the block
        could repeat. Contention therefore lets the turn end."""
        release = self._hold()
        try:
            r = hooks.dispatch("Stop", payload("Stop", self.repo))
        finally:
            release()
        self.assertIsNone(r.json)
        self.assertEqual(r.exit_code, 0)

    def test_lock_released_by_the_peer_lets_the_next_event_through(self):
        """A skip is transient, not sticky: nothing about the busy path poisons later events."""
        release = self._hold()
        hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Edit",
                                              tool_input={"file_path": os.path.join(self.repo, "src", "x.ts"),
                                                          "old_string": "a", "new_string": "b"}, tool_response={}))
        release()
        self.assertEqual(state.SessionState.load("s1").source_edits, 0)     # the skipped edit is lost
        hooks.dispatch("PostToolUse", payload("PostToolUse", self.repo, tool_name="Edit",
                                              tool_input={"file_path": os.path.join(self.repo, "src", "x.ts"),
                                                          "old_string": "a", "new_string": "b"}, tool_response={}))
        self.assertEqual(state.SessionState.load("s1").source_edits, 1)     # the next one records


class LockBudgetTests(unittest.TestCase):
    """Each budget must leave the handler room inside its own hook deadline. Nothing enforces
    that the two stay in step when someone edits hooks/hooks.json, so this test does."""

    def test_every_registered_event_has_a_budget_below_its_hook_timeout(self):
        import json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "hooks", "hooks.json"), encoding="utf-8") as f:
            registered = json.load(f)["hooks"]
        for event, entries in registered.items():
            deadline = min(h["timeout"] for e in entries for h in e["hooks"])
            budget = hooks._LOCK_WAIT.get(event, hooks._LOCK_WAIT_DEFAULT)
            self.assertLess(budget, deadline,
                            "%s: lock budget %.1fs leaves no room inside its %ss deadline" % (event, budget, deadline))

    def test_no_budget_is_set_for_an_event_that_is_not_registered(self):
        import json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "hooks", "hooks.json"), encoding="utf-8") as f:
            registered = set(json.load(f)["hooks"])
        self.assertEqual(sorted(set(hooks._LOCK_WAIT) - registered), [])
