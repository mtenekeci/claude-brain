"""Release-sweep behaviour changes that do not belong to one existing test module.

Symbol extraction, curated-table parsing, module binding, render truncation markers,
prompt-token noise, and the two CLI reporting fixes.
"""
import io, os, tempfile, unittest
from contextlib import redirect_stdout

from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config, read_text
from brain import cli, codemap, config, graph, lint, retrieve


class SymbolExtractionTests(unittest.TestCase):
    def test_export_abstract_class_is_a_symbol(self):
        ts = "export abstract class Repo {}\nexport default abstract class Base {}\nexport class Plain {}\n"
        self.assertEqual(codemap.extract_symbols(ts, ".ts"), ["Repo", "Base", "Plain"])

    def test_swift_declarations_may_be_indented(self):
        swift = (
            "extension Session {\n"
            "    public struct Token {}\n"
            "    func refresh() {}\n"
            "    private func secret() {}\n"
            "}\n"
            "final class Outer {}\n"
        )
        # `extension` is not a declaration keyword we extract; the point is that the two
        # INDENTED members are now found, and that `private` is still excluded at any indent.
        self.assertEqual(codemap.extract_symbols(swift, ".swift"), ["Token", "refresh", "Outer"])


class CuratedTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(env)))
        os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(self.tmp.name, "data")

    def test_unbalanced_wikilink_row_is_skipped_with_a_log_line(self):
        curated = ("## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n"
                   "| Broken | src/a/ | oops | [[concepts/x|X |\n"
                   "| Good | src/b/ | fine | — |\n")
        rows = codemap.parse_modules(curated)
        self.assertEqual([r["module"] for r in rows], ["Good"])
        log = read_text(os.path.join(config.data_dir(), "brain.log"))
        self.assertIn("unbalanced [[", log)
        self.assertIn("Broken", log)

    def test_header_row_is_dropped_without_a_log_line(self):
        codemap.parse_modules("## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n")
        self.assertFalse(os.path.exists(os.path.join(config.data_dir(), "brain.log")))

    def test_curated_template_names_the_project(self):
        text = codemap.curated_template("my-app")
        self.assertIn("my-app", text)
        self.assertNotIn("{slug}", text)


class VaultBackedTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ); self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo")
        codemap.ensure(self.repo, self.pdir)

    def tearDown(self):
        os.chdir(self._cwd); self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def _set_modules(self, rows):
        path = os.path.join(self.pdir, "codemap.md")
        text = read_text(path)
        head = "## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(head, head + rows))


class ModuleBindingTests(VaultBackedTests):
    def test_module_path_dot_binds_root_files(self):
        self._set_modules("| Root | . | top-level config | — |\n")
        g = graph.load(self.vault, "demo", self.repo, force=True)
        bound = {o for o, t, d in g.edges_of("module:root") if t == "contains" and d == "out"}
        # the generated layer holds source files only, so `a.py` is the repo's root file
        self.assertIn("file:a.py", bound)
        self.assertNotIn("file:src/db.ts", bound)      # not the whole tree
        self.assertNotIn("file:lib/util.py", bound)

    def test_module_path_prefix_still_binds_the_subtree(self):
        self._set_modules("| Auth | src/auth/ | sessions | — |\n")
        g = graph.load(self.vault, "demo", self.repo, force=True)
        bound = {o for o, t, d in g.edges_of("module:auth") if t == "contains" and d == "out"}
        self.assertIn("file:src/auth/session.ts", bound)
        self.assertNotIn("file:package.json", bound)


class ConceptBodyTests(VaultBackedTests):
    def test_sections_after_used_by_are_still_scanned_for_links(self):
        """`## Used by` used to truncate the note at that heading, losing every later section."""
        with open(os.path.join(self.vault, "concepts", "nextauth.md"), "w", encoding="utf-8") as f:
            f.write("---\nconcept: NextAuth\ntype: library\n---\n\n# NextAuth\n\n"
                    "## Used by\n- [[projects/other/context|other]] — sessions\n\n"
                    "## See also\nsee:: [[concepts/postgresql|PostgreSQL]]\n")
        g = graph.load(self.vault, "demo", self.repo, force=True)
        edges = {(e.src, e.dst, e.type) for e in g.edges}
        self.assertIn(("concept:nextauth", "concept:postgresql", "see"), edges)
        # the `## Used by` links are still provenance edges from the project, not the concept
        self.assertIn(("project:other", "concept:nextauth", "used-by"), edges)
        self.assertNotIn(("concept:nextauth", "project:other", "links-to"), edges)


class RenderTruncationTests(unittest.TestCase):
    def _hub(self, n):
        g = graph.Graph()
        g.add_node(graph.Node("project:demo", "project", "demo"))
        for i in range(n):
            fid = "file:f%03d.ts" % i
            g.add_node(graph.Node(fid, "file", "f%03d.ts" % i, path="f%03d.ts" % i))
            g.add_edge("project:demo", fid, "contains")
        return g

    def test_render_near_marks_what_it_cut(self):
        g = self._hub(60)
        out = graph.render_near(g, "project:demo", limit=10)
        lines = out.rstrip("\n").split("\n")
        self.assertEqual(len(lines), 10)
        self.assertIn("(+52 more", lines[-1])          # 1 header + 60 edges, 9 kept
        # under the cap there is no marker at all
        self.assertNotIn("more", graph.render_near(self._hub(3), "project:demo", limit=40))

    def test_lint_render_marks_capped_dangling_and_overall_length(self):
        res = {"projects": ["demo"], "auto_applied": [], "auto_pending": 0, "candidates": [],
               "stale": [], "duplicates": [],
               "dangling": [("project:demo", "missing-%d" % i) for i in range(20)]}
        out = lint.render(res)
        self.assertIn("… and %d more" % (20 - lint.DANGLING_RENDER_LIMIT), out)
        self.assertLessEqual(len(out.rstrip("\n").split("\n")), lint.RENDER_LINE_LIMIT)

    def test_every_section_of_a_full_report_stays_under_the_overall_cap(self):
        """Each section caps itself, so RENDER_LINE_LIMIT is a backstop, not the working limit."""
        res = {"projects": ["demo"], "auto_applied": [["demo", "x"]], "auto_pending": 2,
               "candidates": [{"project": "demo", "slug": "c%d" % i, "name": "C", "evidence": "e"} for i in range(50)],
               "stale": [["demo", "s"]], "duplicates": [("a%d" % i, "b%d" % i) for i in range(5)],
               "dangling": [("project:demo", "m%d" % i) for i in range(200)]}
        out = lint.render(res)
        lines = out.rstrip("\n").split("\n")
        self.assertLessEqual(len(lines), lint.RENDER_LINE_LIMIT)
        self.assertIn("  … and %d more" % (50 - lint.CANDIDATE_LIMIT), lines)
        self.assertIn("  … and %d more" % (200 - lint.DANGLING_RENDER_LIMIT), lines)


class LintAllProjectsTests(VaultBackedTests):
    def test_entries_carry_their_project_and_dangling_is_deduped(self):
        # A second project that dangles the SAME module id as the first.
        for slug in ("demo", "other"):
            pdir = os.path.join(self.vault, "projects", slug)
            os.makedirs(pdir, exist_ok=True)
            if slug != "demo":
                with open(os.path.join(pdir, "context.md"), "w", encoding="utf-8") as f:
                    f.write("---\nproject: other\ntype: code\n---\n\n## Architecture\n- x\n")
            with open(os.path.join(pdir, "codemap.md"), "w", encoding="utf-8") as f:
                f.write(codemap.gen_start("") + "\n" + codemap.GEN_END + "\n\n"
                        "## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n"
                        "| shared | src/ | s | [[concepts/ghost]] |\n\n## Where to look\n| question | path |\n|---|---|\n")
        g = graph.load(self.vault, "demo", self.repo, force=True)
        res = lint.run(self.vault, "demo", self.repo, g, all_projects=True)
        self.assertEqual(sorted(res["projects"]), ["demo", "other"])
        self.assertEqual(res["dangling"], list(dict.fromkeys(res["dangling"])))   # deduped
        self.assertEqual([d for d in res["dangling"] if d[0] == "module:shared"],
                         [("module:shared", "concepts/ghost")])
        # The DATA keeps bare slugs — `graph dismiss <slug>` is fed straight from here, and a
        # "other: foo" value is not a slug any more.
        for project, value in res["stale"] + res["auto_applied"]:
            self.assertIn(project, ("demo", "other")); self.assertNotIn(":", value)
        for c in res["candidates"]:
            self.assertIn(c["project"], ("demo", "other")); self.assertNotIn(":", c["slug"])
        # The PREFIX is applied by render, and only across projects.
        out = lint.render(res)
        self.assertRegex(out, r"(demo|other): ")

    def test_single_project_entries_are_not_labelled(self):
        g = graph.load(self.vault, "demo", self.repo, force=True)
        res = lint.run(self.vault, "demo", self.repo, g)
        self.assertEqual(res["projects"], ["demo"])
        # Single project: nothing is prefixed, because every line would carry the same slug.
        for line in lint.render(res).splitlines()[1:]:
            self.assertNotIn("demo: ", line)

    def test_result_is_plain_data_with_no_live_graph_handle(self):
        import json as _json
        g = graph.load(self.vault, "demo", self.repo, force=True)
        res = lint.run(self.vault, "demo", self.repo, g)
        self.assertNotIn("_graph", res)
        _json.dumps(res)                                      # serialisable: no Graph riding along
        self.assertIn("lint: projects demo", lint.render(res, g))


class TokenNoiseTests(unittest.TestCase):
    def test_urls_never_become_retrieval_terms(self):
        self.assertEqual(retrieve.tokens("see https://github.com/acme/app/issues/7 for the auth session"),
                         ["auth", "session"])
        self.assertEqual(retrieve.tokens("open www.example.com/docs then patch verify"), ["open", "patch", "verify"])
        self.assertEqual(retrieve.tokens("check `https://x.io/a` and the session store"), ["check", "session", "store"])

    def test_next_is_a_stop_word(self):
        self.assertNotIn("next", retrieve.tokens("what is next for the auth work"))
        self.assertIn("next-auth", retrieve.tokens("bump next-auth to v5"))


class CliReportingTests(VaultBackedTests):
    def _run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.run(list(argv))
        return rc, buf.getvalue()

    def test_bare_graph_prints_the_graph_subparser_usage(self):
        os.chdir(self.repo)
        rc, out = self._run("graph")
        self.assertEqual(rc, 1)
        self.assertIn("usage: brain graph", out)
        self.assertIn("find", out)          # the graph subcommands, not brain's top-level ones

    def test_status_reports_the_effective_backend(self):
        os.chdir(self.repo)
        rc, out = self._run("status")
        self.assertEqual(rc, 0)
        self.assertIn("Backend: builtin", out)      # `auto` with no graphify-out resolves to builtin

    def test_load_does_not_double_space_file_dumps(self):
        os.chdir(self.repo)
        rc, out = self._run("load", "demo")
        self.assertEqual(rc, 0)
        self.assertIn("## State\nAlpha works.", out)
        self.assertNotIn("\n\n\n\n", out)


if __name__ == "__main__":
    unittest.main()
