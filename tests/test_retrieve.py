import os, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, payload
from brain import retrieve, graph, codemap, hooks, state

class TokenTests(unittest.TestCase):
    def test_tokens_prefer_spans_then_words(self):
        self.assertEqual(retrieve.tokens("How does `SessionStore` refresh the \"auth flow\" in src/auth?"), ["sessionstore", "auth flow", "refresh", "src/auth"])
        self.assertEqual(retrieve.tokens("the and for with"), [])
        self.assertLessEqual(len(retrieve.tokens(" ".join("word%d" % i for i in range(30)))), 12)
    def test_signals(self):
        self.assertTrue(retrieve.is_done_signal("thanks, ship it"))
        self.assertFalse(retrieve.is_done_signal("please fix the login"))
        self.assertTrue(retrieve.is_system_prompt("<task-notification>x")); self.assertTrue(retrieve.is_system_prompt("/brain status")); self.assertFalse(retrieve.is_system_prompt("hello"))

class RetrieveTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo"); codemap.ensure(self.repo, self.pdir)
        cm = os.path.join(self.pdir, "codemap.md")
        with open(cm, encoding="utf-8") as f: t = f.read()
        with open(cm, "w", encoding="utf-8") as f: f.write(t.replace("|---|---|---|---|\n", "|---|---|---|---|\n| Auth flow | src/auth/ | Session cookies + refresh | uses:: [[concepts/nextauth|NextAuth]] |\n", 1))
        self.g = graph.load(self.vault, "demo", self.repo)
    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_select_and_render_caps(self):
        nodes = retrieve.select(self.g, retrieve.tokens("where is the auth flow session handled?"), set())
        self.assertTrue(nodes); self.assertEqual(nodes[0].id, "module:auth-flow"); self.assertLessEqual(len(nodes), 3)
        out = retrieve.render(self.g, nodes)
        self.assertTrue(out.startswith('Brain: graph hits for')); self.assertIn("src/auth/", out); self.assertIn("nextauth", out); self.assertLessEqual(out.count("\n"), 20)
        self.assertEqual(retrieve.render(self.g, []), "")
        self.assertEqual(retrieve.select(self.g, ["zzzz"], set()), [])
        self.assertEqual(retrieve.select(self.g, retrieve.tokens("auth flow"), {"module:auth-flow"})[0].id != "module:auth-flow", True)

    def test_hook_injects_once_and_handles_signals(self):
        r1 = hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="explain the auth flow"))
        self.assertIn("Brain: graph hits", r1.stdout); self.assertIn("module:auth-flow", state.SessionState.load("s1").injected)
        r2 = hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="more about the auth flow"))
        self.assertNotIn("module auth-flow", r2.stdout)                                  # deduped this session
        r3 = hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="<task-notification>…"))
        self.assertEqual(r3.stdout, "")
        r4 = hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="what is the weather"))
        self.assertEqual(r4.stdout, "")
        s = state.SessionState.load("s1"); s.note_source_edit("/r/a.py"); s.save()
        r5 = hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="thanks, looks good"))
        self.assertIn("write the log entry", r5.stdout)
