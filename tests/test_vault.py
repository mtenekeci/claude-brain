import os, tempfile, unittest
from brain import vault

CTX = "---\nproject: demo\nupdated: 2026-01-01\n---\n\n## State\nA.\n\n## Active Work\nB.\n\n## Decisions\n- **X (d)**: y\n- plain\n"

class VaultTests(unittest.TestCase):
    def test_parse_and_set_frontmatter(self):
        fm, body = vault.parse_frontmatter(CTX)
        self.assertEqual(fm["project"], "demo")
        self.assertTrue(body.startswith("\n## State"))
        out = vault.set_frontmatter(CTX, "updated", "2026-09-07")
        self.assertIn("updated: 2026-09-07", out)
        out = vault.set_frontmatter(out, "branch", "feat/x")
        fm2, _ = vault.parse_frontmatter(out)
        self.assertEqual(fm2["branch"], "feat/x")
        self.assertEqual(list(fm2)[:2], ["project", "updated"])  # order preserved, new key appended

    def test_get_and_replace_section(self):
        self.assertEqual(vault.get_section(CTX, "State"), "A.")
        self.assertEqual(vault.get_section(CTX, "Nope"), "")
        out = vault.replace_section(CTX, "Active Work", "C.")
        self.assertEqual(vault.get_section(out, "Active Work"), "C.")
        self.assertEqual(vault.get_section(out, "State"), "A.")
        self.assertEqual(vault.bullets(vault.get_section(CTX, "Decisions")), ["**X (d)**: y", "plain"])

    def test_log_helpers(self):
        log = "← link\n\n## 2026-01-01 · Session 1\nCompleted: a\n\n## 2026-01-02 · Session 2 (auto-close)\nCompleted: b\nNext: —\n"
        self.assertEqual(vault.count_log_entries(log), 2)
        self.assertTrue(vault.last_log_entry(log).startswith("## 2026-01-02"))
        self.assertTrue(vault.last_entry_is_placeholder(log))
        self.assertFalse(vault.last_entry_is_placeholder(log.replace(" (auto-close)", "")))
        e = vault.format_log_entry("2026-09-07", 3, "did", "f.py", "none", "next", tag="pre-compact")
        self.assertEqual(e, "\n## 2026-09-07 · Session 3 (pre-compact)\nCompleted: did\nChanged: f.py\nDecided: none\nNext: next\n")

    def test_file_wrappers(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "x.md")
            self.assertEqual(vault.read(p), "")
            vault.write(p, "a"); vault.append(p, "b")
            self.assertEqual(vault.read(p), "ab")

    def test_headings_inside_code_fences_are_ignored(self):
        text = "## Notes\nSome text.\n```\n## Fake\n```\nmore.\n\n## Next\nN.\n"
        self.assertEqual(vault.get_section(text, "Notes"), "Some text.\n```\n## Fake\n```\nmore.")
        self.assertEqual(vault.get_section(text, "Next"), "N.")

    def test_log_helpers_ignore_fenced_headings(self):
        log = "## 2026-01-01 · Session 1\nCompleted: a\n\n## 2026-01-02 · Session 2\nSome text.\n```\n## bogus\n```\nmore.\nNext: —\n"
        self.assertEqual(vault.count_log_entries(log), 2)
        self.assertTrue(vault.last_log_entry(log).startswith("## 2026-01-02"))

    def test_get_section_requires_exact_heading(self):
        text = "## State of the Union\nX.\n\n## State\nY.\n"
        self.assertEqual(vault.get_section(text, "State"), "Y.")
        self.assertEqual(vault.get_section(text, "State of the Union"), "X.")
        self.assertEqual(vault.get_section("## Stateful\nZ.\n", "State"), "")

class VaultSweepTests(unittest.TestCase):
    """Release-sweep fixes: tilde fences, atomic writes, YAML block lists."""

    def test_tilde_fences_hide_headings_like_backtick_fences(self):
        log = "## Session 1\nCompleted: a\n\n## Session 2\n~~~\n## bogus\n~~~\nmore.\n"
        self.assertEqual(vault.count_log_entries(log), 2)
        self.assertTrue(vault.last_log_entry(log).startswith("## Session 2"))
        self.assertIn("more.", vault.get_section(log, "Session 2"))

    def test_write_is_atomic_and_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "sub", "context.md")
            vault.write(p, "hello\n")
            self.assertEqual(vault.read(p), "hello\n")
            self.assertFalse(os.path.exists(p + ".tmp"))
            # os.replace over a read-only *file* still succeeds; only losing the directory
            # stops the write — and then no .tmp may be left behind either.
            os.chmod(os.path.dirname(p), 0o555)
            try:
                if os.access(os.path.dirname(p), os.W_OK):
                    self.skipTest("filesystem ignores chmod; cannot force a write failure")
                with self.assertRaises(OSError):
                    vault.write(p, "replaced\n")
            finally:
                os.chmod(os.path.dirname(p), 0o755)
            self.assertFalse(os.path.exists(p + ".tmp"))
            self.assertEqual(vault.read(p), "hello\n")

    def test_block_list_frontmatter_folds_into_flow_form(self):
        text = "---\nconcept: PostgreSQL\naliases:\n  - Postgres\n  - \"pg\"\ntype: infra\n---\n\nbody\n"
        fm, body = vault.parse_frontmatter(text)
        self.assertEqual(fm["aliases"], "[Postgres, pg]")
        self.assertEqual((fm["concept"], fm["type"]), ("PostgreSQL", "infra"))
        self.assertEqual(body, "\nbody\n")
        from brain import graph
        self.assertEqual(graph.parse_aliases(fm["aliases"]), ["Postgres", "pg"])
        # The flow form still parses, and a bare `key:` with no block stays an empty string.
        fm2, _ = vault.parse_frontmatter("---\naliases: [A, B]\nempty:\nnext: x\n---\n")
        self.assertEqual((fm2["aliases"], fm2["empty"], fm2["next"]), ("[A, B]", "", "x"))


class AtomicWriteTests(unittest.TestCase):
    """`vault.atomic_write` is the single writer behind vault.write and every codemap write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sub", "context.md")

    def _strays(self):
        d = os.path.dirname(self.path)
        return [f for f in os.listdir(d) if f != os.path.basename(self.path)] if os.path.isdir(d) else []

    def test_temp_name_is_unique_per_call(self):
        """`path + '.tmp'` was shared by every writer of the same file; mkstemp is not."""
        seen = []
        real = os.replace
        def spy(src, dst):
            seen.append(src); real(src, dst)
        os.replace = spy
        try:
            vault.atomic_write(self.path, "one\n")
            vault.atomic_write(self.path, "two\n")
        finally:
            os.replace = real
        self.assertEqual(len(set(seen)), 2, seen)
        for src in seen:
            base = os.path.basename(src)
            self.assertTrue(base.startswith("context.md.") and base.endswith(".tmp"), base)
            self.assertEqual(os.path.dirname(src), os.path.dirname(self.path))   # same filesystem
        self.assertEqual(vault.read(self.path), "two\n")
        self.assertEqual(self._strays(), [])

    def test_interleaved_writers_both_succeed_and_leave_no_temp(self):
        """Deterministic stand-in for two processes: the inner write runs while the outer
        writer's temp file exists and is about to be replaced into place."""
        vault.atomic_write(self.path, "seed\n")
        real = os.replace
        inner_done = []
        def spy(src, dst):
            if not inner_done:
                inner_done.append(True)
                vault.atomic_write(self.path, "inner\n")     # a second writer, mid-flight
                self.assertTrue(os.path.exists(src), "the outer writer's temp was unlinked")
            real(src, dst)
        os.replace = spy
        try:
            vault.atomic_write(self.path, "outer\n")
        finally:
            os.replace = real
        self.assertEqual(vault.read(self.path), "outer\n")   # last replace wins, never a merge
        self.assertEqual(self._strays(), [])

    def test_mode_is_preserved_on_rewrite_and_defaulted_on_create(self):
        """mkstemp creates 0600; a rewrite must not quietly tighten an existing note."""
        import stat as _stat
        vault.atomic_write(self.path, "a\n")
        self.assertEqual(_stat.S_IMODE(os.stat(self.path).st_mode), vault.NEW_FILE_MODE)
        os.chmod(self.path, 0o664)
        vault.atomic_write(self.path, "b\n")
        self.assertEqual(_stat.S_IMODE(os.stat(self.path).st_mode), 0o664)

    def test_failure_removes_the_temp_and_reraises(self):
        vault.atomic_write(self.path, "keep\n")
        real = os.replace
        os.replace = lambda src, dst: (_ for _ in ()).throw(OSError("nope"))
        try:
            with self.assertRaises(OSError):
                vault.atomic_write(self.path, "lost\n")
        finally:
            os.replace = real
        self.assertEqual(vault.read(self.path), "keep\n")
        self.assertEqual(self._strays(), [])
