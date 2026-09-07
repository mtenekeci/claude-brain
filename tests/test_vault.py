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
