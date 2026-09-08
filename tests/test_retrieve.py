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

    def test_done_signal_is_word_bounded_and_negation_aware(self):
        self.assertFalse(retrieve.is_done_signal("this isn't done yet, keep going"))
        self.assertFalse(retrieve.is_done_signal("not done"))
        self.assertTrue(retrieve.is_done_signal("thanks, ship it"))
        self.assertTrue(retrieve.is_done_signal("done"))
        self.assertFalse(retrieve.is_done_signal("abandoned"))
        self.assertFalse(retrieve.is_done_signal("no thanks"))
        self.assertTrue(retrieve.is_done_signal("no problem, ship it"))
        # a trailing '?' makes it a question, not a sign-off
        self.assertFalse(retrieve.is_done_signal("is this done?"))
        self.assertFalse(retrieve.is_done_signal("looks good?  "))
        self.assertTrue(retrieve.is_done_signal("looks good"))

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

    def test_injected_list_is_capped(self):
        s = state.SessionState.load("s1")
        s.injected = ["dummy:%d" % i for i in range(300)]
        s.save()
        hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="explain the auth flow"))
        self.assertLessEqual(len(state.SessionState.load("s1").injected), 300)

    def test_injected_cap_preserves_order(self):
        ordered = ["dummy:%d" % i for i in range(300)]
        s = state.SessionState.load("s1")
        s.injected = list(ordered)
        s.save()
        hooks.dispatch("UserPromptSubmit", payload("UserPromptSubmit", self.repo, prompt="explain the auth flow"))
        result = state.SessionState.load("s1").injected
        self.assertEqual(len(result), 300)
        n_new = len(result) - len([i for i in result if i.startswith("dummy:")])
        # the oldest n_new dummy ids were dropped (order preserved), the survivors keep their
        # relative order, and the newly-injected ids land at the end in insertion order
        self.assertEqual(result[:300 - n_new], ordered[n_new:])
        self.assertNotIn("dummy:0", result)
        self.assertIn("module:auth-flow", result[300 - n_new:])

class DedupeTests(unittest.TestCase):
    """render_with_ids must report exactly the ids it rendered — not every node considered —
    so the hook's dedup set never starves a node the user never actually saw."""
    def _six_file_module_graph(self):
        g = graph.Graph()
        g.add_node(graph.Node("project:demo", "project", "demo"))
        g.add_node(graph.Node("module:auth-flow", "module", "Auth flow", path="src/auth/"))
        g.add_edge("project:demo", "module:auth-flow", "contains")
        names = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
        for name in names:
            fid = "file:src/auth/%s.ts" % name
            g.add_node(graph.Node(fid, "file", "%s.ts" % name, path="src/auth/%s.ts" % name))
            g.add_edge("module:auth-flow", fid, "contains")
        return g, names

    def test_dedupe_tracks_only_rendered_nodes(self):
        g, names = self._six_file_module_graph()
        module = g.nodes["module:auth-flow"]
        text, ids = retrieve.render_with_ids(g, [module])
        rendered = {"file:src/auth/%s.ts" % n for n in names[:3]}
        unrendered = {"file:src/auth/%s.ts" % n for n in names[3:]}
        self.assertTrue(rendered <= ids)
        self.assertFalse(ids & unrendered)
        # a later prompt naming an unrendered file must still retrieve it
        later = retrieve.select(g, retrieve.tokens("what about %s.ts" % names[3]), ids)
        self.assertTrue(later)
        self.assertEqual(later[0].id, "file:src/auth/%s.ts" % names[3])
