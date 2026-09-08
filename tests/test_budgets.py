import os, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, payload
from brain import hooks, graph, retrieve, briefing, codemap, vault

class BudgetTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo"); codemap.ensure(self.repo, self.pdir)
        self.g = graph.load(self.vault, "demo", self.repo, force=True)
    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_protocol_is_at_most_25_lines(self):
        with open(hooks.PROTOCOL_PATH, encoding="utf-8") as f: self.assertLessEqual(f.read().count("\n"), 25)
    def test_session_start_additions_at_most_45_lines(self):
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        after_log = r.stdout.split("(last entry only)")[-1].split("\n", 1)[-1]
        fixture_log_lines = 6
        self.assertLessEqual(after_log.count("\n") - fixture_log_lines, 45)
    def test_oversize_context_md_is_truncated_at_the_byte_cap(self):
        """Lines are a bad proxy for size: a real 81 KB context.md fit in 128 lines, passed the
        line cap, and buried every line the injection appends after it."""
        ctx_path = os.path.join(self.pdir, "context.md")
        with open(ctx_path, "a", encoding="utf-8") as f:
            f.write("\n## Filler\n")
            f.write("x" * 40000 + "\n")          # one very long line: 128-line file, ~40 KB
            f.write("\n## Trailer\nSENTINEL-BELOW-THE-CAP\n")
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertIn("Brain: context.md truncated at %d KB — trim it (/brain sync)" % (vault.INJECT_BYTE_CAP // 1024), r.stdout)
        self.assertIn("Brain: context.md oversize: ", r.stdout)
        self.assertNotIn("SENTINEL-BELOW-THE-CAP", r.stdout)
        self.assertIn("## State\nAlpha works.", r.stdout)                 # the top of the file survives
        # Everything the injection appends AFTER context.md still lands.
        self.assertIn("(last entry only)", r.stdout)

    def test_normal_context_md_is_injected_untouched(self):
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertNotIn("truncated at", r.stdout)
        self.assertNotIn("oversize", r.stdout)
        self.assertIn("## Hard Rules", r.stdout)

    def test_for_injection_cuts_on_a_section_boundary(self):
        text = "## A\n" + "a" * 20000 + "\n## B\nkeep out\n"
        shown, over = vault.for_injection(text, cap=64)
        self.assertTrue(over)
        self.assertNotIn("## B", shown)
        self.assertEqual(vault.for_injection("short\n", cap=64), ("short\n", 0))

    def test_query_caps(self):
        self.assertLessEqual(graph.render_find(self.g, graph.find(self.g, "s")).count("\n"), 15)
        self.assertLessEqual(graph.render_near(self.g, "project:demo", depth=2).count("\n"), 40)
        self.assertLessEqual(graph.render_top(self.g, graph.top(self.g)).count("\n"), 12)
        self.assertLessEqual(retrieve.render(self.g, retrieve.select(self.g, ["auth", "session", "postgres"], set())).count("\n"), 20)
        self.assertLessEqual(briefing.text(type("C", (), {"project": type("P", (), {"slug": "demo"})(), "pdir": self.pdir, "context_path": os.path.join(self.pdir, "context.md")})()).count("\n"), 13)


if __name__ == "__main__":
    unittest.main()
