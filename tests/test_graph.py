import os, tempfile, unittest
from tests.helpers import make_graph_vault, write_config
from brain import graph

class GraphModelTests(unittest.TestCase):
    def test_slugify_and_ids(self):
        self.assertEqual(graph.slugify("Use Postgres (2026-01-02)"), "use-postgres-2026-01-02")
        self.assertEqual(graph.slugify("  Auth  Flow!! "), "auth-flow")
        self.assertEqual(graph.node_id("concept", "pg"), "concept:pg")

    def test_add_merge_edges_dangling_neighbors(self):
        g = graph.Graph()
        g.add_node(graph.Node("concept:pg", "concept", "PostgreSQL", aliases=["Postgres"]))
        g.add_node(graph.Node("concept:pg", "concept", "PostgreSQL", aliases=["pg"]))
        self.assertEqual(sorted(g.nodes["concept:pg"].aliases), ["Postgres", "pg"])
        g.add_node(graph.Node("project:demo", "project", "demo")); g.add_node(graph.Node("module:auth", "module", "auth"))
        g.add_edge("project:demo", "concept:pg", "uses"); g.add_edge("project:demo", "concept:pg", "uses")
        g.add_edge("module:auth", "concept:pg", "uses"); g.add_edge("project:demo", "concept:nope", "see")
        self.assertEqual(len(g.edges), 2); self.assertEqual(g.dangling, [("project:demo", "concept:nope")])
        self.assertEqual(g.degree("concept:pg"), 2)
        self.assertEqual(g.neighbors("project:demo", depth=2), {"concept:pg": 1, "module:auth": 2})
        self.assertEqual(g.edges_of("concept:pg"), [("project:demo", "uses", "in"), ("module:auth", "uses", "in")])
        d = g.to_dict(); g2 = graph.Graph.from_dict(d)
        self.assertEqual(g2.to_dict(), d)

    def test_parse_links_and_resolve(self):
        text = "uses:: [[concepts/postgresql|PostgreSQL]] [[concepts/redis]]\nsee [[projects/demo/architecture#Auth|arch]] and [[projects/other/context|other]].\n- decided-by:: [[projects/demo/context#Decisions]]\n"
        self.assertEqual(graph.parse_links(text), [("uses", "concepts/postgresql"), ("uses", "concepts/redis"), ("links-to", "projects/demo/architecture#Auth"), ("links-to", "projects/other/context"), ("decided-by", "projects/demo/context#Decisions")])
        self.assertEqual(graph.resolve_link("concepts/postgresql", "demo"), "concept:postgresql")
        self.assertEqual(graph.resolve_link("projects/other/context", "demo"), "project:other")
        self.assertEqual(graph.resolve_link("projects/demo/architecture#Auth", "demo"), "section:demo/auth")
        self.assertEqual(graph.resolve_link("projects/other/architecture#Auth", "demo"), "section:other/auth")
        self.assertEqual(graph.resolve_link("projects/demo/architecture", "demo"), "project:demo")
        self.assertEqual(graph.resolve_link("projects/demo/context#Decisions", "demo"), "project:demo")
        self.assertIsNone(graph.resolve_link("_system/project-index", "demo"))
        self.assertEqual(graph.parse_aliases("[Postgres, pg]"), ["Postgres", "pg"]); self.assertEqual(graph.parse_aliases("a, b"), ["a", "b"]); self.assertEqual(graph.parse_aliases(""), [])
        fence = "`" * 3
        self.assertEqual(graph.strip_fences("a\n" + fence + "\n## x\n" + fence + "\nb"), "a\n\nb")

    def test_parse_links_document_order_with_repeated_target(self):
        # The same target appears twice: once plain, once typed. Order must follow the
        # document, so position has to come from each match, not from text.index().
        text = "[[concepts/pg]] then uses:: [[concepts/pg]]\n"
        self.assertEqual(graph.parse_links(text), [("links-to", "concepts/pg"), ("uses", "concepts/pg")])
        # A link with inner padding must not blow up (text.index of the stripped target would).
        self.assertEqual(graph.parse_links("[[ concepts/pg ]]"), [("links-to", "concepts/pg")])

class VaultLayerTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.g = graph.Graph(); graph.build_vault_layer(self.g, self.vault, "demo")
    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_nodes_from_vault(self):
        n = self.g.nodes
        self.assertEqual(n["project:demo"].type, "project")
        self.assertEqual(n["decision:use-postgres-2026-01-02"].name, "Use Postgres (2026-01-02)")
        self.assertEqual(n["question:should-we-cache"].type, "question")
        self.assertEqual(sorted(n["concept:postgresql"].aliases), ["Postgres", "pg"]); self.assertEqual(n["concept:postgresql"].meta["ctype"], "infra")
        self.assertEqual(n["section:demo/auth"].meta["line"], 8)   # frontmatter(4) + blank + "# Arch" + blank → "## Auth" is line 8
        self.assertEqual(n["section:demo/storage"].path.endswith("architecture.md"), True)
        self.assertIn("section:demo/migrations", n); self.assertNotIn("section:demo/not-a-heading", n)
        self.assertEqual(n["project:other"].meta.get("external"), True)

    def test_edges_from_vault(self):
        types = {(e.src, e.dst, e.type) for e in self.g.edges}
        self.assertIn(("project:demo", "concept:postgresql", "uses"), types)          # typed link in context.md
        self.assertIn(("project:demo", "concept:postgresql", "used-by"), types)       # claim in the concept note — separate provenance
        self.assertIn(("project:other", "concept:nextauth", "used-by"), types)
        self.assertNotIn(("project:other", "concept:nextauth", "uses"), types)
        self.assertIn(("section:demo/auth", "concept:nextauth", "uses"), types)
        self.assertIn(("section:demo/auth", "project:demo", "decided-by"), types)
        self.assertIn(("section:demo/storage", "concept:postgresql", "see"), types)
        self.assertIn(("project:demo", "decision:use-postgres-2026-01-02", "contains"), types)
        self.assertIn(("project:demo", "section:demo/auth", "contains"), types)
        self.assertNotIn(("project:demo", "concept:nextauth", "mentions"), types)    # only inside a wikilink alias → not a prose mention
        self.assertIn(("project:demo", "concept:postgresql", "mentions"), types)
        self.assertEqual(self.g.dangling, [("project:demo", "concepts/missing-one")])

class GraphCarryOverTests(unittest.TestCase):
    """Fixes carried over from Task 4's review: accumulated section bodies, stub upgrade,
    no self-loops, one deduped dangling shape, slugified concept ids."""
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.arch = os.path.join(self.vault, "projects", "demo", "architecture.md")
    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def _build(self, extra=""):
        if extra:
            with open(self.arch, "a", encoding="utf-8") as f: f.write(extra)
        g = graph.Graph(); graph.build_vault_layer(g, self.vault, "demo")
        return g

    def test_duplicate_heading_bodies_accumulate(self):
        g = self._build("\n## Notes\nsee:: [[concepts/postgresql|PostgreSQL]]\n\n## Notes\nuses:: [[concepts/nextauth|NextAuth]]\n")
        types = {(e.src, e.dst, e.type) for e in g.edges}
        self.assertIn(("section:demo/notes", "concept:postgresql", "see"), types)
        self.assertIn(("section:demo/notes", "concept:nextauth", "uses"), types)

    def test_add_node_upgrades_external_stub(self):
        g = graph.Graph()
        g.add_node(graph.Node("project:other", "project", "other", aliases=["o"], meta={"external": True}))
        g.add_node(graph.Node("project:other", "project", "Other Project", path="/v/projects/other/context.md", aliases=["op"]))
        n = g.nodes["project:other"]
        self.assertNotIn("external", n.meta)
        self.assertEqual(n.name, "Other Project"); self.assertEqual(n.path, "/v/projects/other/context.md")
        self.assertEqual(sorted(n.aliases), ["o", "op"])

    def test_add_edge_ignores_self_loops(self):
        g = graph.Graph(); g.add_node(graph.Node("project:demo", "project", "demo"))
        g.add_edge("project:demo", "project:demo", "links-to")
        self.assertEqual(g.edges, []); self.assertEqual(g.degree("project:demo"), 0); self.assertEqual(g.dangling, [])

    def test_dangling_is_deduped_and_single_shape(self):
        g = self._build("\n## Gaps\nsee:: [[concepts/missing-one|Missing]]\nAlso see:: [[concepts/missing-one|Missing]]\n")
        self.assertEqual(g.dangling.count(("section:demo/gaps", "concepts/missing-one")), 1)
        self.assertEqual(len(g.dangling), len(set(g.dangling)))
        self.assertTrue(all(len(x) == 2 and isinstance(x[1], str) for x in g.dangling))

    def test_concept_ids_use_slugified_stem(self):
        with open(os.path.join(self.vault, "concepts", "Auth Flow.md"), "w", encoding="utf-8") as f:
            f.write("---\nconcept: Auth Flow\ntype: subsystem\n---\n\n# Auth Flow\n")
        g = self._build("\n## Wiring\nuses:: [[concepts/auth-flow|Auth Flow]]\n")
        self.assertIn("concept:auth-flow", g.nodes)
        self.assertEqual(g.nodes["concept:auth-flow"].name, "Auth Flow")
        self.assertIn(("section:demo/wiring", "concept:auth-flow", "uses"), {(e.src, e.dst, e.type) for e in g.edges})

if __name__ == "__main__":
    unittest.main()
