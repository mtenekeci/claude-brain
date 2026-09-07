import os, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, payload
from brain import hooks, graph, retrieve, briefing, codemap

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
    def test_query_caps(self):
        self.assertLessEqual(graph.render_find(self.g, graph.find(self.g, "s")).count("\n"), 15)
        self.assertLessEqual(graph.render_near(self.g, "project:demo", depth=2).count("\n"), 40)
        self.assertLessEqual(graph.render_top(self.g, graph.top(self.g)).count("\n"), 12)
        self.assertLessEqual(retrieve.render(self.g, retrieve.select(self.g, ["auth", "session", "postgres"], set())).count("\n"), 20)
        self.assertLessEqual(briefing.text(type("C", (), {"project": type("P", (), {"slug": "demo"})(), "pdir": self.pdir, "context_path": os.path.join(self.pdir, "context.md")})()).count("\n"), 13)


if __name__ == "__main__":
    unittest.main()
