import json, os, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, read_text
from brain import codemap, graph

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

    def test_add_node_real_then_stub_stays_real(self):
        g = graph.Graph()
        g.add_node(graph.Node("project:demo", "project", "demo", path="/v/projects/demo/context.md"))
        g.add_node(graph.Node("project:demo", "project", "demo", meta={"external": True}))
        self.assertNotIn("external", g.nodes["project:demo"].meta)
        self.assertIn("project:demo", [n.id for n in graph.top(g)])

    def test_add_edge_ignores_self_loops(self):
        g = graph.Graph(); g.add_node(graph.Node("project:demo", "project", "demo"))
        g.add_edge("project:demo", "project:demo", "links-to")
        self.assertEqual(g.edges, []); self.assertEqual(g.degree("project:demo"), 0); self.assertEqual(g.dangling, [])

    def test_dangling_is_deduped_and_single_shape(self):
        g = self._build("\n## Gaps\nsee:: [[concepts/missing-one|Missing]]\nAlso see:: [[concepts/missing-one|Missing]]\n")
        self.assertEqual(g.dangling.count(("section:demo/gaps", "concepts/missing-one")), 1)
        self.assertEqual(len(g.dangling), len(set(g.dangling)))
        self.assertTrue(all(len(x) == 2 and isinstance(x[1], str) for x in g.dangling))

    def test_decision_bullet_links_are_not_double_counted(self):
        """A link inside a Decisions/Open Questions bullet belongs to that bullet's node.
        Scanning the whole context.md for the project node too produced a second, misleading
        project→concept edge for every decision that cites a concept."""
        ctx = os.path.join(self.vault, "projects", "demo", "context.md")
        text = read_text(ctx).replace(
            "- **Use Postgres (2026-01-02)**: because.",
            "- **Use Postgres (2026-01-02)**: because. uses:: [[concepts/nextauth|NextAuth]]")
        with open(ctx, "w", encoding="utf-8") as f: f.write(text)
        g = graph.Graph(); graph.build_vault_layer(g, self.vault, "demo")
        # (the fixture's architecture.md ## Auth section links NextAuth too — that one is its own)
        edges = [e.src for e in g.edges if e.dst == "concept:nextauth" and e.type == "uses"
                 and not e.src.startswith("section:")]
        self.assertEqual(edges, ["decision:use-postgres-2026-01-02"])

    def test_mentions_ignore_inline_code_spans(self):
        with open(os.path.join(self.vault, "concepts", "test.md"), "w", encoding="utf-8") as f:
            f.write("---\nconcept: test\ntype: library\n---\n\n# test\n")
        g = self._build("\n## Commands\nRun `npm test` before pushing.\n")
        self.assertIn("concept:test", g.nodes)
        self.assertNotIn(("project:demo", "concept:test", "mentions"), {(e.src, e.dst, e.type) for e in g.edges})
        g2 = self._build("\n## Prose\nWe rely on test for everything.\n")
        self.assertIn(("project:demo", "concept:test", "mentions"), {(e.src, e.dst, e.type) for e in g2.edges})

    def test_unresolvable_wikilink_is_recorded_as_dangling(self):
        g = self._build("\n## Loose ends\nsee:: [[Name]] and [[_system/project-index|Index]]\n")
        self.assertIn(("section:demo/loose-ends", "Name"), g.dangling)
        # _system/ is vault infrastructure, deliberately not a graph node — not a broken link
        self.assertFalse([d for d in g.dangling if "_system" in d[1]])

    def test_wikilinks_inside_code_are_not_links(self):
        """A `[[X]]` in backticks or a fenced block is a syntax EXAMPLE. `graph lint` reported
        every one of them as a dangling link on this repo's own vault notes."""
        g = self._build("\n## Linking rules\nWrite `[[concepts/<slug>|<Name>]]`, never plain text.\n\n"
                        + "`" * 3 + "\nsee:: [[concepts/also-not-real]]\n" + "`" * 3 + "\n")
        self.assertEqual([d for d in g.dangling if "not-real" in d[1] or "<slug>" in d[1]], [])
        self.assertEqual(graph.parse_links("a `[[X]]` b"), [])
        self.assertEqual(graph.parse_links("`x` [[Y]]"), [("links-to", "Y")])

    def test_path_style_link_to_an_existing_vault_file_is_not_dangling(self):
        """`[[projects/demo/plans/2026-09-08-release]]` is a real note the graph does not model.
        Resolve it against the vault before calling the link broken."""
        pdir = os.path.join(self.vault, "projects", "demo", "plans")
        os.makedirs(pdir)
        with open(os.path.join(pdir, "2026-09-08-release.md"), "w", encoding="utf-8") as f:
            f.write("# Release plan\n")
        g = self._build("\n## Plans\nsee:: [[projects/demo/plans/2026-09-08-release|the plan]] "
                        "and [[projects/demo/plans/no-such-plan]]\n")
        self.assertEqual([d for d in g.dangling if "2026-09-08-release" in d[1]], [])
        self.assertIn(("section:demo/plans", "projects/demo/plans/no-such-plan"), g.dangling)

    def test_concept_ids_use_slugified_stem(self):
        with open(os.path.join(self.vault, "concepts", "Auth Flow.md"), "w", encoding="utf-8") as f:
            f.write("---\nconcept: Auth Flow\ntype: subsystem\n---\n\n# Auth Flow\n")
        g = self._build("\n## Wiring\nuses:: [[concepts/auth-flow|Auth Flow]]\n")
        self.assertIn("concept:auth-flow", g.nodes)
        self.assertEqual(g.nodes["concept:auth-flow"].name, "Auth Flow")
        self.assertIn(("section:demo/wiring", "concept:auth-flow", "uses"), {(e.src, e.dst, e.type) for e in g.edges})

class CodeLayerAndQueryTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo")
        codemap.ensure(self.repo, self.pdir)
        cm = os.path.join(self.pdir, "codemap.md")
        with open(cm, encoding="utf-8") as f: text = f.read()
        text = text.replace("|---|---|---|---|\n", "|---|---|---|---|\n| Auth flow | src/auth/ | Session cookies + refresh | uses:: [[concepts/nextauth|NextAuth]] |\n", 1)
        with open(cm, "w", encoding="utf-8") as f: f.write(text)
        self.g = graph.build(self.vault, "demo", self.repo)
    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_code_layer_nodes_and_edges(self):
        n = self.g.nodes
        self.assertEqual(n["file:src/auth/session.ts"].name, "session.ts")
        self.assertIn("symbol:src/auth/session.ts#SessionStore", n)
        self.assertEqual(n["module:auth-flow"].path, "src/auth/")
        types = {(e.src, e.dst, e.type) for e in self.g.edges}
        self.assertIn(("file:src/auth/session.ts", "symbol:src/auth/session.ts#SessionStore", "contains"), types)
        self.assertIn(("file:src/auth/session.ts", "file:src/db.ts", "imports"), types)
        self.assertIn(("module:auth-flow", "file:src/auth/session.ts", "contains"), types)
        self.assertIn(("module:auth-flow", "concept:nextauth", "uses"), types)
        self.assertIn(("project:demo", "module:auth-flow", "contains"), types)

    def test_build_tolerates_no_project_dir(self):
        g = graph.build(self.vault, "demo", None)
        self.assertIn("file:src/auth/session.ts", g.nodes); self.assertIn("module:auth-flow", g.nodes)

    def test_find_ranks_exact_then_prefix_then_substring(self):
        ids = [x.id for x in graph.find(self.g, "session")]
        self.assertEqual(ids[0], "file:src/auth/session.ts")                      # name exact match
        self.assertIn("symbol:src/auth/session.ts#SessionStore", ids)
        # A symbol borrows its FILE's basename only at the substring tier: TTL is not a "session"
        # match in any strong sense and must not tie with the file or outrank SessionStore.
        self.assertEqual(graph._score(self.g.nodes["file:src/auth/session.ts"], "session"), 3)
        self.assertEqual(graph._score(self.g.nodes["symbol:src/auth/session.ts#SessionStore"], "session"), 2)
        # …and at no tier at all: a symbol is matched on its OWN name, never on its file's.
        self.assertEqual(graph._score(self.g.nodes["symbol:src/auth/session.ts#TTL"], "session"), 0)
        self.assertNotIn("symbol:src/auth/session.ts#TTL", ids)
        self.assertNotIn("symbol:src/auth/session.ts#refresh", ids)
        self.assertEqual([x.id for x in graph.find(self.g, "pg")][0], "concept:postgresql")   # alias exact
        self.assertEqual(graph.find(self.g, "zzz"), [])
        self.assertTrue(all(x.type == "concept" for x in graph.find(self.g, "post", type="concept")))
        self.assertLessEqual(len(graph.find(self.g, "s")), 15)

    def test_path_and_top(self):
        p = graph.path(self.g, "symbol:src/auth/session.ts#SessionStore", "concept:nextauth")
        self.assertEqual(p[0], "symbol:src/auth/session.ts#SessionStore"); self.assertEqual(p[-1], "concept:nextauth"); self.assertLessEqual(len(p), 5)
        self.assertEqual(graph.path(self.g, "concept:nextauth", "concept:zzz"), [])
        top = graph.top(self.g, n=5)
        self.assertEqual(top[0].id, "project:demo"); self.assertTrue(all(x.type not in ("file", "symbol") for x in top)); self.assertLessEqual(len(top), 5)

    def test_renderers_respect_caps_and_shape(self):
        out = graph.render_find(self.g, graph.find(self.g, "auth"))
        self.assertLessEqual(out.count("\n"), 15); self.assertRegex(out.splitlines()[0], r"^\w+ \S+  \S+  — .+$")
        near = graph.render_near(self.g, "module:auth-flow", depth=1)
        self.assertLessEqual(near.count("\n"), 40); self.assertIn("contains →", near); self.assertIn("src/auth/session.ts", near); self.assertIn("uses → concept nextauth", near)
        near2 = graph.render_near(self.g, "section:demo/auth", depth=1); self.assertIn("architecture.md § Auth (line 8)", near2)
        self.assertEqual(graph.render_near(self.g, "nope:x"), "")
        self.assertIn("uses → concept nextauth  concepts/nextauth.md  — NextAuth", near)   # edge lines carry the name too
        self.assertIn(" → ", graph.render_path(self.g, graph.path(self.g, "project:demo", "concept:postgresql")))
        self.assertEqual(graph.render_path(self.g, ["project:demo", "concept:nope"]), "")   # total, never raises
        self.assertEqual(graph.render_path(self.g, []), "")
        topo = graph.render_top(self.g, graph.top(self.g, n=12)); self.assertLessEqual(topo.count("\n"), 12)
        big = graph.Graph(); big.add_node(graph.Node("project:p", "project", "p"))
        for i in range(100):
            big.add_node(graph.Node("concept:c%d" % i, "concept", "c%d" % i)); big.add_edge("project:p", "concept:c%d" % i, "uses")
        self.assertEqual(graph.render_near(big, "project:p").count("\n"), 40)

    def test_render_find_paths_are_vault_or_repo_relative(self):
        line = graph.render_find(self.g, [self.g.nodes["section:demo/auth"]]).strip()
        self.assertIn("projects/demo/architecture.md", line); self.assertNotIn(self.vault, line)
        self.assertIn("src/auth/session.ts", graph.render_find(self.g, [self.g.nodes["file:src/auth/session.ts"]]))

    def test_cache_ns_precision_and_unusable_shapes(self):
        graph.load(self.vault, "demo", self.repo)
        cache = os.path.join(self.pdir, ".brain", "graph.json")
        with open(cache, encoding="utf-8") as f: stamp = json.load(f)["built_at"]
        self.assertIsInstance(stamp, int)                    # integer nanoseconds, not float seconds
        arch = os.path.join(self.pdir, "architecture.md")
        with open(arch, "a", encoding="utf-8") as f: f.write("\n## Zzz\nlate section\n")
        os.utime(arch, ns=(stamp + 1, stamp + 1))            # exactly 1ns newer — float seconds round this away
        self.assertIn("section:demo/zzz", graph.load(self.vault, "demo", self.repo).nodes)
        # Valid JSON that is not a usable cache must fall back to a fresh build, not raise.
        for bad in ("[]", '{"built_at": 1e18, "graph": null}'):
            with open(cache, "w", encoding="utf-8") as f: f.write(bad)
            self.assertIn("section:demo/zzz", graph.load(self.vault, "demo", self.repo).nodes)

    def test_cache_invalidates_on_file_deletion(self):
        """Deleting an input leaves every surviving file's mtime untouched — only the vault
        project directory's own mtime moves, so it has to be an input too."""
        g1 = graph.load(self.vault, "demo", self.repo)
        self.assertIn("section:demo/auth", g1.nodes)
        os.remove(os.path.join(self.pdir, "architecture.md"))
        g2 = graph.load(self.vault, "demo", self.repo)
        self.assertNotIn("section:demo/auth", g2.nodes)
        self.assertNotIn("section:demo/storage", g2.nodes)

    def test_cache_roundtrip_and_invalidation(self):
        g1 = graph.load(self.vault, "demo", self.repo)
        cache = os.path.join(self.pdir, ".brain", "graph.json"); self.assertTrue(os.path.exists(cache))
        m1 = os.path.getmtime(cache)
        g2 = graph.load(self.vault, "demo", self.repo); self.assertEqual(os.path.getmtime(cache), m1); self.assertEqual(len(g2.nodes), len(g1.nodes))
        import time; time.sleep(0.01)
        with open(os.path.join(self.vault, "concepts", "redis.md"), "w") as f: f.write("---\nconcept: Redis\ntype: infra\n---\n# Redis\n\n## Used by\n- [[projects/demo/context|demo]] — cache\n")
        g3 = graph.load(self.vault, "demo", self.repo); self.assertIn("concept:redis", g3.nodes)
        with open(cache, "w") as f: f.write("{corrupt")
        g4 = graph.load(self.vault, "demo", self.repo); self.assertIn("concept:redis", g4.nodes)
        self.assertIn("concept:redis", graph.load(self.vault, "demo", self.repo, force=True).nodes)

if __name__ == "__main__":
    unittest.main()
