import os, tempfile, unittest
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, payload
from brain import lint, graph, codemap, vault, hooks

class LintTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo"); codemap.ensure(self.repo, self.pdir)
        # a concept that is only mentioned in prose (candidate), and one that claims this project but isn't referenced (stale)
        with open(os.path.join(self.vault, "concepts", "redis.md"), "w") as f:
            f.write("---\nconcept: Redis\ntype: infra\n---\n# Redis\n\n## Used by\n- [[projects/other/context|other]] — cache\n")
        with open(os.path.join(self.vault, "concepts", "kafka.md"), "w") as f:
            f.write("---\nconcept: Kafka\ntype: infra\n---\n# Kafka\n\n## Used by\n- [[projects/demo/context|demo]] — events\n")
        # a concept matching a manifest dep with NO typed link anywhere → gets both the uses:: line and the Used-by line
        with open(os.path.join(self.vault, "concepts", "jest.md"), "w") as f:
            f.write("---\nconcept: Jest\ntype: library\n---\n# Jest\n\n## Used by\n")
        arch = os.path.join(self.pdir, "architecture.md")
        with open(arch, "a") as f: f.write("\n## Cache\nWe put sessions in Redis with a 1h TTL.\n")
        self.g = graph.load(self.vault, "demo", self.repo, force=True)

    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_match_deps_to_concepts(self):
        m = lint.match_deps_to_concepts(["next-auth", "pg", "@scope/redis", "jest", "zzz"], self.g)
        self.assertEqual(m, {"next-auth": "concept:nextauth", "pg": "concept:postgresql", "@scope/redis": "concept:redis", "jest": "concept:jest"})

    def test_typed_targets_include_section_and_module_links(self):
        t = lint.typed_targets(self.g, "demo")
        self.assertIn("concept:nextauth", t)        # typed `uses::` from section:demo/auth counts for the project
        self.assertIn("concept:postgresql", t)      # typed from context.md
        self.assertNotIn("concept:kafka", t)        # only a Used-by claim
        self.assertNotIn("concept:redis", t)        # only a prose mention

    def test_run_classifies_and_auto_applies(self):
        res = lint.run(self.vault, "demo", self.repo, self.g)
        self.assertEqual(sorted(res["auto_applied"]), ["jest", "nextauth"])
        ctx = vault.read(os.path.join(self.pdir, "context.md")); arch_sec = vault.get_section(ctx, "Architecture")
        self.assertIn("uses:: [[concepts/jest|Jest]]", arch_sec)                      # no typed link anywhere → link added
        self.assertNotIn("uses:: [[concepts/nextauth|NextAuth]]", arch_sec)           # section already links it → no context.md line
        self.assertIn("[[projects/demo/context|demo]]", vault.read(os.path.join(self.vault, "concepts", "nextauth.md")))   # Used-by completed
        self.assertIn("[[projects/demo/context|demo]]", vault.read(os.path.join(self.vault, "concepts", "jest.md")))
        self.assertNotIn("postgresql", res["auto_applied"])                          # typed + Used-by already present
        self.assertEqual([c["slug"] for c in res["candidates"]], ["redis"])           # prose mention only
        self.assertEqual(res["stale"], ["kafka"])
        self.assertEqual(res["dangling"], [("project:demo", "concepts/missing-one")])
        res2 = lint.run(self.vault, "demo", self.repo, graph.load(self.vault, "demo", self.repo, force=True))
        self.assertEqual(res2["auto_applied"], [])                            # idempotent

    def test_dismiss_and_health_and_render(self):
        lint.dismiss(self.pdir, "redis")
        res = lint.run(self.vault, "demo", self.repo, self.g)
        self.assertEqual(res["candidates"], [])
        self.assertIn("1 stale", lint.health_line(res)); self.assertIn("1 dangling", lint.health_line(res))
        self.assertEqual(lint.health_line({"candidates": [], "stale": [], "dangling": [], "auto_applied": [], "duplicates": [], "projects": ["demo"]}), "")
        out = lint.render(res); self.assertIn("kafka", out); self.assertLessEqual(out.count("\n"), 40)

    def _concept(self, slug, name):
        with open(os.path.join(self.vault, "concepts", slug + ".md"), "w") as f:
            f.write("---\nconcept: %s\ntype: infra\n---\n# %s\n\n## Used by\n" % (name, name))

    def test_duplicates_by_alias_overlap_or_edit_distance(self):
        self._concept("postgres", "Postgres")
        g = graph.load(self.vault, "demo", self.repo, force=True)
        res = lint.run(self.vault, "demo", self.repo, g, want_duplicates=True)
        self.assertIn(("postgres", "postgresql"), res["duplicates"])

    def test_duplicates_are_lazy_and_render_fills_them_in(self):
        self._concept("postgres", "Postgres")
        g = graph.load(self.vault, "demo", self.repo, force=True)
        res = lint.run(self.vault, "demo", self.repo, g)                 # default: no O(n^2) scan
        self.assertEqual(res["duplicates"], [])
        self.assertIn(("postgres", "postgresql"), lint.duplicates(g))    # still available on demand
        self.assertIn("postgres ~ postgresql", lint.render(res))         # render pays for it itself
        self.assertEqual(lint.health_line(res), lint.health_line(dict(res, duplicates=[])))

    def test_near_duplicate_threshold_is_length_relative(self):
        self._concept("jwt", "JWT")                                      # jest/jwt: 2 edits, both short
        self._concept("mssql", "MSSQL"); self._concept("mysql", "MySQL")  # 5 chars, 1 edit
        self._concept("postgres", "Postgres")
        d = lint.duplicates(graph.load(self.vault, "demo", self.repo, force=True))
        self.assertNotIn(("jest", "jwt"), d)
        self.assertIn(("mssql", "mysql"), d)
        self.assertIn(("postgres", "postgresql"), d)

    def test_dismissed_concept_is_not_auto_applied(self):
        lint.dismiss(self.pdir, "jest")
        res = lint.run(self.vault, "demo", self.repo, self.g)
        self.assertNotIn("jest", res["auto_applied"])
        self.assertEqual(res["auto_applied"], ["nextauth"])               # other deps still applied
        ctx = vault.read(os.path.join(self.pdir, "context.md"))
        self.assertNotIn("concepts/jest", ctx)                            # no uses:: line
        self.assertNotIn("projects/demo/context", vault.get_section(      # shared note left alone
            vault.read(os.path.join(self.vault, "concepts", "jest.md")), "Used by"))

    def test_auto_apply_is_capped_and_the_remainder_is_reported(self):
        """Auto-apply edits shared concept notes. A manifest with dozens of matching concepts
        must not rewrite them all in one silent SessionStart pass."""
        deps = ["dep%d" % i for i in range(8)]
        with open(os.path.join(self.repo, "package.json"), "w") as f:
            f.write('{"name":"demo","dependencies":{%s}}' % ", ".join('"%s":"^1"' % d for d in deps))
        for d in deps:
            self._concept(d, d.upper())
        codemap.regenerate(self.repo, self.pdir, force=True)
        g = graph.load(self.vault, "demo", self.repo, force=True)
        res = lint.run(self.vault, "demo", self.repo, g)
        self.assertEqual(len(res["auto_applied"]), lint.AUTO_APPLY_LIMIT)
        self.assertEqual(res["auto_applied"], sorted(res["auto_applied"]))     # deterministic order
        self.assertEqual(res["auto_pending"], 3)                               # 8 deps − 5 applied
        line = lint.health_line(res)
        self.assertIn("5 concept links auto-applied", line)
        self.assertIn("3 pending", line)
        # the next run picks up where this one stopped
        res2 = lint.run(self.vault, "demo", self.repo, graph.load(self.vault, "demo", self.repo, force=True))
        self.assertEqual(len(res2["auto_applied"]), 3)
        self.assertEqual(res2["auto_pending"], 0)
        self.assertNotIn("pending", lint.health_line(res2))
        self.assertIn("3 concept links auto-applied", lint.health_line(res2))
        self.assertEqual(lint.health_line(dict(res2, auto_applied=["one"])).count("1 concept link auto-applied"), 1)

    def test_session_start_health_line(self):
        r = hooks.dispatch("SessionStart", payload("SessionStart", self.repo))
        self.assertIn("Brain: graph health —", r.stdout)


if __name__ == "__main__":
    unittest.main()
