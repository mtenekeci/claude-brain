import io, json, os, shutil, stat, tempfile, unittest
from contextlib import redirect_stdout
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config
from brain import backends, cli, codemap, config, graph
from brain.backends import graphify


def graphify_fixture(repo):
    """A graphify-out/graph.json in the networkx node-link shape graphify really writes:
    `links` (not `edges`), `relation` (not `type`), most nodes carrying only label +
    source_file. Deliberately mixes in the tolerated key spellings (`path`/`file`, `kind`,
    `name`) and one absolute source_file."""
    nodes = [
        {"id": "src_auth_session", "label": "session.ts", "file_type": "code", "source_file": "src/auth/session.ts"},
        {"id": "src_auth_session_sessionstore", "label": "SessionStore", "type": "class", "source_file": "src/auth/session.ts"},
        {"id": "src_auth_session_refresh", "label": "refresh", "type": "function", "source_file": "src/auth/session.ts"},
        {"id": "foundation", "label": "Foundation", "type": "module", "source_file": "src/auth/session.ts"},
        {"id": "src_auth_verify", "label": "verify.ts", "file_type": "code", "source_file": "src/auth/verify.ts"},
        {"id": "src_auth_verify_verify", "label": "verify", "type": "function", "source_file": "src/auth/verify.ts"},
        {"id": "src_db", "label": "db.ts", "type": "file", "path": "src/db.ts"},
        {"id": "src_db_conn", "label": "Conn", "kind": "class", "file": "src/db.ts"},
        {"id": "lib_util", "name": "util.py", "type": "file", "source_file": os.path.join(repo, "lib", "util.py")},
        {"id": "lib_util_run", "label": "run", "type": "method", "source_file": "lib/util.py"},
        # A file only graphify knows about — it is not on disk, so the builtin layer can
        # never produce it. Every "did the backend really supply the layer?" assertion
        # keys off this node.
        {"id": "src_graphonly", "label": "graphonly.ts", "type": "file", "source_file": "./src/graphonly.ts"},
        # A doc corpus node and one of its headings: real graphify graphs mix these in, and a
        # code layer must not grow a README "file" with a "Overview" symbol.
        {"id": "readme", "label": "README.md", "file_type": "document", "source_file": "README.md"},
        {"id": "readme_overview", "label": "Overview", "file_type": "document", "source_file": "README.md"},
    ]
    links = [
        {"source": "src_auth_session", "target": "src_db", "relation": "imports", "confidence_score": 1.0},
        {"source": "src_auth_session_sessionstore", "target": "src_auth_verify_verify", "relation": "calls"},
        {"source": "src_db", "target": "lib_util", "relation": "contains"},
    ]
    out = os.path.join(repo, "graphify-out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"directed": True, "multigraph": True, "graph": {}, "nodes": nodes, "links": links}, f)
    with open(os.path.join(out, ".graphify_root"), "w", encoding="utf-8") as f:
        f.write(repo + "\n")
    return os.path.join(out, "graph.json")


def stub_graphify(tmp, body=None):
    """A `graphify` executable first on PATH. Echoes its argv joined, then one line per
    argument (so a question with spaces is visibly ONE argument), then 80 lines — the ask
    output cap has to bite on something."""
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir, exist_ok=True)
    path = os.path.join(bindir, "graphify")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body or '#!/bin/sh\necho "GRAPHIFY:$*"\nfor a in "$@"; do echo "ARG:$a"; done\ni=0\nwhile [ $i -lt 80 ]; do echo "line$i"; i=$((i+1)); done\n')
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
    return bindir


class BackendFixture(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ); self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "auto"}})
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo")
        codemap.ensure(self.repo, self.pdir)
        self.gj = graphify_fixture(self.repo)
        stub_graphify(self.tmp.name)

    def tearDown(self):
        os.chdir(self._cwd); self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def log_text(self):
        p = os.path.join(config.data_dir(), "brain.log")
        if not os.path.exists(p):
            return ""
        with open(p, encoding="utf-8") as f:
            return f.read()


class SelectionTests(BackendFixture):
    def test_config_accessor_defaults_to_auto(self):
        write_config(self.tmp.name, self.vault)
        self.assertEqual(config.graph_backend(), "auto")
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "Builtin"}})
        self.assertEqual(config.graph_backend(), "builtin")
        write_config(self.tmp.name, self.vault, extra={"graph": "nonsense"})
        self.assertEqual(config.graph_backend(), "auto")

    def test_available_needs_graph_json_and_a_runnable_graphify(self):
        self.assertTrue(graphify.available(self.repo))
        os.environ["PATH"] = ""                                     # no binary, no interpreter recorded
        self.assertFalse(graphify.available(self.repo))
        interp = os.path.join(self.repo, "graphify-out", ".graphify_python")
        with open(interp, "w", encoding="utf-8") as f: f.write("/nonexistent/python\n")
        self.assertFalse(graphify.available(self.repo))             # recorded interpreter must exist
        with open(interp, "w", encoding="utf-8") as f: f.write("/usr/bin/python3\n")
        self.assertTrue(graphify.available(self.repo))
        os.remove(self.gj)
        self.assertFalse(graphify.available(self.repo))
        self.assertFalse(graphify.available(None))

    def test_explicit_graphify_without_a_graph_is_a_silent_builtin(self):
        """graph.backend is global, graphify graphs are per project: the projects that have no
        graph are the normal case and must not write a line per load into brain.log."""
        shutil.rmtree(os.path.join(self.repo, "graphify-out"))
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "graphify"}})
        self.assertEqual(backends.select(self.repo), "builtin")
        for _ in range(5):
            g = graph.load(self.vault, "demo", self.repo)
        self.assertEqual(g.nodes["project:demo"].meta["backend"], "builtin")
        self.assertEqual(self.log_text(), "")

    def test_select_honours_config_and_availability(self):
        self.assertEqual(backends.select(self.repo), "graphify")            # auto + available
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "builtin"}})
        self.assertEqual(backends.select(self.repo), "builtin")             # explicit builtin wins over availability
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "graphify"}})
        self.assertEqual(backends.select(self.repo), "graphify")
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "auto"}})
        os.remove(self.gj)
        self.assertEqual(backends.select(self.repo), "builtin")             # auto + nothing to read
        self.assertEqual(backends.select(None), "builtin")


class GraphifyLayerTests(BackendFixture):
    def test_layer_shape_matches_the_builtin_layer(self):
        layer = graphify.code_layer(self.repo)
        paths = [f["path"] for f in layer["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(set(paths), {"lib/util.py", "src/auth/session.ts", "src/auth/verify.ts", "src/db.ts", "src/graphonly.ts"})
        byp = dict((f["path"], f) for f in layer["files"])
        self.assertEqual(sorted(byp["src/auth/session.ts"]["symbols"]), ["Foundation", "SessionStore", "refresh"])
        self.assertEqual(byp["src/db.ts"]["symbols"], ["Conn"])
        self.assertEqual(byp["lib/util.py"]["symbols"], ["run"])            # absolute source_file relativised
        self.assertNotIn("README.md", byp)                                  # file_type document → not code
        self.assertNotIn("Overview", [s for f in layer["files"] for s in f["symbols"]])
        # imports: the `imports` edge plus the symbol→symbol `calls` edge lifted to its files.
        self.assertEqual(byp["src/auth/session.ts"]["imports"], ["src/auth/verify.ts", "src/db.ts"])
        self.assertEqual(byp["src/db.ts"]["imports"], [])                   # `contains` is not an import
        self.assertTrue(all(f["lines"] == 0 for f in layer["files"]))
        # the sha is backends.digest of graph.json: "<prefix><mtime_ns>-<size>", not a hash
        self.assertTrue(layer["sha"].startswith("graphify:"))
        self.assertEqual(layer["sha"], backends.source_key(self.repo, self.pdir)[1])
        self.assertIn("pg", layer["deps"])                                  # manifest deps still come from the repo

    def test_layer_caps_symbols_and_imports(self):
        nodes = [{"id": "f%d" % i, "label": "f%d.py" % i, "type": "file", "source_file": "f%d.py" % i} for i in range(9)]
        nodes += [{"id": "s%d" % i, "label": "sym%02d" % i, "type": "function", "source_file": "f0.py"} for i in range(12)]
        links = [{"source": "f0", "target": "f%d" % i, "relation": "imports"} for i in range(1, 9)]
        with open(self.gj, "w", encoding="utf-8") as f:
            json.dump({"nodes": nodes, "edges": links}, f)                  # `edges` spelling also accepted
        byp = dict((x["path"], x) for x in graphify.code_layer(self.repo)["files"])
        self.assertEqual(len(byp["f0.py"]["symbols"]), codemap.MAX_SYMBOLS)
        self.assertEqual(len(byp["f0.py"]["imports"]), 5)

    def test_corrupt_or_missing_graph_json_returns_none_and_logs(self):
        with open(self.gj, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(graphify.code_layer(self.repo))
        self.assertIn("graphify", self.log_text())
        with open(self.gj, "w", encoding="utf-8") as f:
            json.dump({"nodes": "not a list"}, f)
        self.assertIsNone(graphify.code_layer(self.repo))
        os.remove(self.gj)
        self.assertIsNone(graphify.code_layer(self.repo))

    def test_code_layer_dispatch_and_fallback(self):
        layer, name = backends.code_layer(self.repo, self.pdir)
        self.assertEqual(name, "graphify"); self.assertIn("src/graphonly.ts", [f["path"] for f in layer["files"]])
        with open(self.gj, "w", encoding="utf-8") as f:
            f.write("{not json")
        layer, name = backends.code_layer(self.repo, self.pdir)
        self.assertEqual(name, "builtin")
        self.assertEqual(layer["sha"], codemap.read_layer(self.pdir)["sha"])
        self.assertIn("graphify", self.log_text())
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "builtin"}})
        self.assertEqual(backends.code_layer(self.repo, self.pdir)[1], "builtin")

    def test_ask_runs_the_cli_and_caps_output(self):
        out = graphify.ask(self.repo, "how does auth work")
        self.assertTrue(out.startswith("GRAPHIFY:query how does auth work --budget 1500"))
        self.assertIn("ARG:how does auth work", out.splitlines())           # one argument, not four
        self.assertLessEqual(len(out.splitlines()), 60)
        self.assertEqual(graphify.ask(self.repo, "  "), "")
        os.environ["PATH"] = ""
        self.assertEqual(graphify.ask(self.repo, "anything"), "")

    def test_ask_never_triggers_a_build(self):
        # The only argv graphify is ever handed is a read-only query — one line per argument,
        # so a multi-word question proves it is passed as a single argv entry.
        argv = os.path.join(self.tmp.name, "argv.txt")
        with open(os.path.join(self.tmp.name, "bin", "graphify"), "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nfor a in "$@"; do echo "$a" >> %s; done\n' % argv)
        graphify.ask(self.repo, "how does auth work", budget=42)
        with open(argv, encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), ["query", "how does auth work", "--budget", "42"])


class GraphIntegrationTests(BackendFixture):
    def test_load_uses_the_backend_layer_and_records_it(self):
        g = graph.load(self.vault, "demo", self.repo)
        self.assertIn("file:src/graphonly.ts", g.nodes)
        self.assertIn("symbol:src/auth/session.ts#SessionStore", g.nodes)
        self.assertEqual(g.nodes["project:demo"].meta["backend"], "graphify")
        types = {(e.src, e.dst, e.type) for e in g.edges}
        self.assertIn(("file:src/auth/session.ts", "file:src/db.ts", "imports"), types)

    def test_cache_survives_a_repeat_load_but_not_a_backend_switch(self):
        cache = os.path.join(self.pdir, ".brain", "graph.json")
        graph.load(self.vault, "demo", self.repo)
        m1 = os.path.getmtime(cache)
        graph.load(self.vault, "demo", self.repo)
        self.assertEqual(os.path.getmtime(cache), m1)                       # same backend, same source → cache hit
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d["backend"], "graphify"); self.assertTrue(d["source"].startswith("graphify:"))
        # No vault file moves: only the config changes, and the cache must still rebuild.
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "builtin"}})
        g = graph.load(self.vault, "demo", self.repo)
        self.assertNotIn("file:src/graphonly.ts", g.nodes)
        self.assertEqual(g.nodes["project:demo"].meta["backend"], "builtin")
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "auto"}})
        g = graph.load(self.vault, "demo", self.repo)
        self.assertIn("file:src/graphonly.ts", g.nodes)
        self.assertEqual(g.nodes["project:demo"].meta["backend"], "graphify")

    def test_cache_hit_never_parses_the_graph(self):
        """The cache check compares a streamed md5, so a cache hit must not touch the parser —
        parsing a 6k-node graph.json on every hook load is exactly what the cache is for."""
        graph.load(self.vault, "demo", self.repo)
        orig = graphify.parse_graph

        def boom(*a, **k):
            raise AssertionError("parse_graph called on a cache hit")

        graphify.parse_graph = boom
        try:
            g = graph.load(self.vault, "demo", self.repo)
        finally:
            graphify.parse_graph = orig
        self.assertIn("file:src/graphonly.ts", g.nodes)

    def test_regenerated_graph_json_invalidates_the_cache(self):
        graph.load(self.vault, "demo", self.repo)
        stamp = graph.inputs_mtime(self.vault, "demo", self.repo)
        with open(self.gj, encoding="utf-8") as f:
            d = json.load(f)
        d["nodes"].append({"id": "src_fresh", "label": "fresh.ts", "type": "file", "source_file": "src/fresh.ts"})
        with open(self.gj, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.utime(self.gj, ns=(stamp + 10 ** 9, stamp + 10 ** 9))
        # graphify's own output is an input: a rebuild there must stale the cache even though
        # nothing in the vault moved.
        self.assertGreater(graph.inputs_mtime(self.vault, "demo", self.repo), stamp)
        self.assertIn("file:src/fresh.ts", graph.load(self.vault, "demo", self.repo).nodes)

    def test_corrupt_graph_json_falls_back_to_the_builtin_layer(self):
        with open(self.gj, "w", encoding="utf-8") as f:
            f.write("{not json")
        g = graph.load(self.vault, "demo", self.repo)
        self.assertEqual(g.nodes["project:demo"].meta["backend"], "builtin")
        self.assertIn("file:src/auth/session.ts", g.nodes)                  # builtin layer still there
        self.assertNotIn("file:src/graphonly.ts", g.nodes)
        self.assertIn("graphify", self.log_text())


class AskCliTests(BackendFixture):
    def setUp(self):
        BackendFixture.setUp(self); os.chdir(self.repo)

    def _run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.run(list(argv))
        return rc, buf.getvalue()

    def test_ask_passes_through_when_the_backend_is_active(self):
        rc, out = self._run("graph", "ask", "how does auth work")
        self.assertEqual(rc, 0)
        self.assertIn("GRAPHIFY:query how does auth work --budget 1500", out)
        rc, out = self._run("graph", "ask", "x", "--budget", "300")
        self.assertIn("--budget 300", out)

    def test_ask_reports_an_empty_query_differently_from_an_inactive_backend(self):
        with open(os.path.join(self.tmp.name, "bin", "graphify"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        rc, out = self._run("graph", "ask", "session")
        self.assertEqual(rc, 0)
        self.assertIn("graphify query returned nothing", out)
        self.assertNotIn("backend not active", out)
        self.assertIn("file src/auth/session.ts", out)                      # still falls back

    def test_ask_without_the_backend_explains_and_falls_back(self):
        write_config(self.tmp.name, self.vault, extra={"graph": {"backend": "builtin"}})
        rc, out = self._run("graph", "ask", "session")
        self.assertEqual(rc, 0)
        self.assertIn("graphify backend not active", out)
        self.assertIn("file src/auth/session.ts", out)                      # render_near of the best find hit
        rc, out = self._run("graph", "ask", "zzz-nothing-matches")
        self.assertIn("graphify backend not active", out); self.assertIn("no matches", out)


if __name__ == "__main__":
    unittest.main()
