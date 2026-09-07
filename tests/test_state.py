import os, tempfile, time, unittest
from brain import state

class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(self.tmp.name, "data")
    def tearDown(self): self.tmp.cleanup()

    def test_defaults_roundtrip(self):
        s = state.SessionState.load("abc")
        self.assertEqual((s.reads, s.commits, s.injected), (0, 0, []))
        s.slug = "demo"; s.note_read(); s.note_commit("fix: x"); s.note_source_edit("/r/a.py"); s.note_source_edit("/r/a.py")
        s.save()
        t = state.SessionState.load("abc")
        self.assertEqual((t.slug, t.reads, t.commits, t.commits_since_vault_write), ("demo", 1, 1, 1))
        self.assertEqual((t.source_edits, t.source_edits_since_vault_write, t.edited_files), (2, 2, ["/r/a.py"]))
        self.assertEqual(t.commit_subjects, ["fix: x"])
        self.assertGreater(t.last_work_at, 0)

    def test_vault_write_clears_counters(self):
        s = state.SessionState.load("s"); s.note_commit("c"); s.note_source_edit("/r/b.ts")
        s.note_vault_write()
        self.assertEqual((s.commits_since_vault_write, s.source_edits_since_vault_write), (0, 0))
        self.assertEqual((s.commits, s.source_edits, s.vault_writes), (1, 1, 1))
        self.assertGreaterEqual(s.last_vault_write, s.last_work_at)

    def test_isolated_per_session_and_prune(self):
        a = state.SessionState.load("a"); a.reads = 5; a.save()
        b = state.SessionState.load("b"); self.assertEqual(b.reads, 0)
        old = time.time() - 8 * 86400
        os.utime(a.path, (old, old))
        state.prune(days=7)
        self.assertFalse(os.path.exists(a.path))
        a.delete()  # no error when already gone

    def test_locked_serializes_concurrent_increments(self):
        import threading
        def work():
            for _ in range(50):
                with state.locked("c") as s:
                    s.reads += 1
        ts = [threading.Thread(target=work) for _ in range(4)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(state.SessionState.load("c").reads, 200)

    def test_locked_discard_skips_save(self):
        with state.locked("d") as s:
            s.reads = 9; s.discard = True
        self.assertEqual(state.SessionState.load("d").reads, 0)
