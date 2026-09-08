import json, os, tempfile, unittest
from tests.helpers import make_vault, make_project, make_source_tree, write_config
from brain import codemap

class CodemapExtractTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_list_files_respects_gitignore_and_sorts(self):
        files = codemap.list_files(self.repo)
        self.assertEqual(files, sorted(files))
        self.assertIn("src/auth/session.ts", files); self.assertIn("lib/util.py", files); self.assertIn("package.json", files)
        self.assertNotIn("node_modules/junk/index.js", files); self.assertNotIn("dist/out.js", files)

    def test_list_files_walk_fallback_without_git(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "node_modules", "x")); os.makedirs(os.path.join(t, "src"))
            open(os.path.join(t, "src", "a.ts"), "w").close(); open(os.path.join(t, "node_modules", "x", "b.ts"), "w").close()
            self.assertEqual(codemap.list_files(t), ["src/a.ts"])

    def test_extract_symbols_per_language(self):
        ts = open(os.path.join(self.repo, "src/auth/session.ts")).read()
        self.assertEqual(codemap.extract_symbols(ts, ".ts"), ["SessionStore", "refresh", "TTL"])
        self.assertEqual(codemap.extract_symbols("export default function main() {}\nexport function verify() {}", ".ts"), ["main", "verify"])
        py = open(os.path.join(self.repo, "lib/util.py")).read()
        self.assertEqual(codemap.extract_symbols(py, ".py"), ["Util", "run"])   # _private excluded
        self.assertEqual(codemap.extract_symbols("func (s *S) Do() {}\nfunc New() *S { return nil }\n", ".go"), ["Do", "New"])
        self.assertEqual(codemap.extract_symbols("pub fn go() {}\npub struct P;\nfn hidden() {}\n", ".rs"), ["go", "P"])
        self.assertEqual(codemap.extract_symbols("final class A {}\nstruct B {}\nprotocol C {}\nfunc d() {}\n", ".swift"), ["A", "B", "C", "d"])
        self.assertEqual(codemap.extract_symbols("public class K {}\ninternal interface I {}\nrecord R() {}\n", ".cs"), ["K", "I", "R"])
        self.assertEqual(len(codemap.extract_symbols("\n".join("export function f%d() {}" % i for i in range(20)), ".ts")), 8)

    def test_extract_imports_resolves_relative_only(self):
        files = set(codemap.list_files(self.repo))
        ts = open(os.path.join(self.repo, "src/auth/session.ts")).read()
        self.assertEqual(codemap.extract_imports("src/auth/session.ts", ts, files), ["src/auth/verify.ts", "src/db.ts"])
        py = open(os.path.join(self.repo, "lib/util.py")).read()
        self.assertEqual(codemap.extract_imports("lib/util.py", py, files), ["lib/helpers.py"])   # `import os` ignored
        # "../db" from "src/a.ts" (dirname "src") normalizes to root-level "db.ts", which isn't
        # in the fileset (only "src/db.ts" is) — so only the sibling import resolves.
        self.assertEqual(codemap.extract_imports("src/a.ts", "import './setup';\nimport \"../db\";\n", files | {"src/setup.ts"}), ["src/setup.ts"])
        gofiles = {"pkg/store/a.go", "pkg/store/b.go", "cmd/main.go"}
        self.assertEqual(codemap.extract_imports("cmd/main.go", 'import (\n\t"fmt"\n\t"example.com/m/pkg/store"\n)\n', gofiles, go_module="example.com/m"), ["pkg/store/a.go", "pkg/store/b.go"])
        self.assertEqual(codemap.go_module(self.repo), "")

    def test_manifest_deps(self):
        self.assertEqual(codemap.manifest_deps(self.repo), ["jest", "next-auth", "pg"])
        with open(os.path.join(self.repo, "requirements.txt"), "w") as f: f.write("psycopg2>=2\n# c\nredis\n")
        with open(os.path.join(self.repo, "go.mod"), "w") as f: f.write("module m\n\nrequire (\n\tgithub.com/lib/pq v1.0\n)\n")
        self.assertEqual(codemap.manifest_deps(self.repo), ["github.com/lib/pq", "jest", "next-auth", "pg", "psycopg2", "redis"])
        self.assertEqual(codemap.go_module(self.repo), "m")
        os.makedirs(os.path.join(self.repo, "svc", "Api"));
        with open(os.path.join(self.repo, "svc", "Api", "Api.csproj"), "w") as f: f.write('<Project><ItemGroup><PackageReference Include="Serilog" Version="3" /></ItemGroup></Project>')
        self.assertIn("Serilog", codemap.manifest_deps(self.repo))                     # recursive csproj scan

    def test_build_and_roundtrip_layer_is_deterministic(self):
        pdir = os.path.join(self.vault, "projects", "demo")
        a = codemap.build_layer(self.repo); b = codemap.build_layer(self.repo)
        for k in ("sha", "files", "deps"): self.assertEqual(a[k], b[k])
        self.assertEqual(len(a["sha"]), 49); self.assertEqual(a["sha"][40], ":")          # '<sha>:<8-hex status hash>'
        by = {f["path"]: f for f in a["files"]}
        self.assertEqual(by["src/auth/session.ts"]["symbols"], ["SessionStore", "refresh", "TTL"])
        self.assertEqual(by["src/auth/session.ts"]["imports"], ["src/auth/verify.ts", "src/db.ts"])
        self.assertEqual(by["lib/util.py"]["lines"], 11)  # 11 newline-terminated lines in the fixture body
        codemap.write_layer(pdir, a)
        self.assertTrue(os.path.exists(os.path.join(pdir, ".brain", "codelayer.json")))
        self.assertEqual(codemap.read_layer(pdir)["files"], a["files"])
        self.assertIsNone(codemap.read_layer(os.path.join(self.tmp.name, "nowhere")))

    def test_extract_imports_handles_multiline_ts_import(self):
        files = set(codemap.list_files(self.repo))
        text = "import {\n  a,\n  b,\n} from './verify';\n"
        self.assertEqual(codemap.extract_imports("src/auth/x.ts", text, files), ["src/auth/verify.ts"])

    def test_extract_symbols_swift_excludes_private_and_fileprivate(self):
        self.assertEqual(
            codemap.extract_symbols("private func hidden() {}\nfileprivate class H {}\nfunc visible() {}\n", ".swift"),
            ["visible"])

    def test_manifest_deps_go_mod_single_line_require(self):
        with open(os.path.join(self.repo, "go.mod"), "w") as f:
            f.write("module m\n\nrequire github.com/lib/pq v1.0.0\n")
        self.assertIn("github.com/lib/pq", codemap.manifest_deps(self.repo))

    def test_manifest_deps_poetry_tables(self):
        with open(os.path.join(self.repo, "pyproject.toml"), "w") as f:
            f.write('[tool.poetry.dependencies]\npython = "^3.9"\nrequests = "^2.0"\n\n'
                    '[tool.poetry.group.dev.dependencies]\npytest = "^8"\n')
        deps = codemap.manifest_deps(self.repo)
        self.assertIn("requests", deps); self.assertIn("pytest", deps); self.assertNotIn("python", deps)

class CodemapRenderTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo")
    def tearDown(self):
        self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def test_render_generated_tree_lists_symbols_and_deps(self):
        layer = codemap.build_layer(self.repo)
        out = codemap.render_generated(layer)
        self.assertIn("src/auth/session.ts  (SessionStore, refresh, TTL)", out)
        self.assertIn("deps: jest, next-auth, pg", out)
        self.assertLessEqual(out.count("\n"), 150)
        self.assertEqual(out, codemap.render_generated(layer))          # deterministic

    def test_render_generated_prunes_large_dirs_deterministically(self):
        files = [{"path": "big/f%03d.ts" % i, "lines": 1, "symbols": ["s"], "imports": []} for i in range(200)]
        files += [{"path": "small/a.ts", "lines": 1, "symbols": ["a"], "imports": []}]
        layer = {"sha": "x", "files": files, "deps": [], "generated_at": 0}
        out = codemap.render_generated(layer, cap=40)
        self.assertLessEqual(out.count("\n"), 40)
        self.assertIn("big/  (200 files, collapsed)", out)
        self.assertIn("small/a.ts  (a)", out)

    def _nested_layer(self, per_dir=50):
        files = [{"path": "src/%s/f%03d.ts" % (d, i), "lines": 1, "symbols": ["s"], "imports": []}
                 for d in ("auth", "db", "ui", "api") for i in range(per_dir)]
        files.append({"path": "package.json", "lines": 1, "symbols": [], "imports": []})
        return {"sha": "x", "files": files, "deps": [], "generated_at": 0}

    def test_render_generated_collapses_the_deepest_dirs_first(self):
        """Collapsing is iterative and depth-aware: the four leaf dirs go, not their parent —
        `src/` alone would throw away the whole structure when four lines already fit."""
        out = codemap.render_generated(self._nested_layer(), cap=40)
        lines = out.rstrip("\n").split("\n")
        self.assertLessEqual(len(lines), 40)
        for d in ("api", "auth", "db", "ui"):
            self.assertIn("src/%s/  (50 files, collapsed)" % d, lines)
        self.assertNotIn("src/  (200 files, collapsed)", lines)
        self.assertIn("package.json", lines)                      # root files never collapse

    def _assert_no_collapsed_dir_beside_its_descendants(self, out):
        body = [l for l in out.splitlines()[4:] if l]
        for c in [l for l in body if "collapsed" in l]:
            prefix = c.split("  ")[0]                       # "src/a/" — every descendant starts with it
            self.assertFalse(any(l != c and l.startswith(prefix) for l in body),
                             "collapsed dir rendered beside its descendants: %r in %r" % (c, body))

    def test_collapsed_dir_absorbs_all_descendants(self):
        files = [{"path": "src/%s/f%d.ts" % (d, i), "lines": 1, "symbols": [], "imports": []} for d in "abcdef" for i in range(4)]
        out = codemap.render_generated({"sha": "x", "files": files, "deps": [], "generated_at": 0}, cap=13)
        self._assert_no_collapsed_dir_beside_its_descendants(out)

    def test_collapsing_a_shallow_dir_absorbs_its_nested_subtree(self):
        """A dir wins on direct children while a deeper subtree is still expanded: collapsing it
        must take the whole subtree with it, never leave `src/` sitting above `src/deep/nest/*`."""
        files = [{"path": "src/f%d.ts" % i, "lines": 1, "symbols": [], "imports": []} for i in range(6)]
        files += [{"path": "src/deep/nest/g%d.ts" % i, "lines": 1, "symbols": [], "imports": []} for i in range(3)]
        out = codemap.render_generated({"sha": "x", "files": files, "deps": [], "generated_at": 0}, cap=10)
        self._assert_no_collapsed_dir_beside_its_descendants(out)
        self.assertIn("src/  (9 files, collapsed)", out)       # count covers the nested files too

    def test_render_generated_leaves_the_tree_expanded_when_it_fits(self):
        # 201 lines + 4 header lines + the trailer slot, so the cap has to clear ~206.
        out = codemap.render_generated(self._nested_layer(), cap=250)
        self.assertNotIn("collapsed", out)
        self.assertNotIn("not shown", out)
        self.assertIn("src/auth/f000.ts  (s)", out)
        self.assertIn("src/ui/f049.ts  (s)", out)

    def test_render_generated_caps_the_deps_line(self):
        layer = {"sha": "x", "files": [], "deps": ["dep%02d" % i for i in range(25)], "generated_at": 0}
        deps_line = [l for l in codemap.render_generated(layer).splitlines() if l.startswith("deps: ")][0]
        names = deps_line[len("deps: "):].split(", ")
        self.assertEqual(len(names), 21)
        self.assertEqual(names[:20], ["dep%02d" % i for i in range(20)])
        self.assertEqual(names[20], "… (+5 more)")

    def test_render_generated_reports_omitted_files(self):
        files = [{"path": "d%03d/a.ts" % i, "lines": 1, "symbols": ["a"], "imports": []} for i in range(200)]
        layer = {"sha": "x", "files": files, "deps": [], "generated_at": 0}
        cap = 40
        out = codemap.render_generated(layer, cap=cap)
        lines = out.rstrip("\n").split("\n")
        self.assertLessEqual(len(lines), cap)
        self.assertIn("more files not shown", lines[-1])
        header_len, budget = 4, cap - 4 - 1
        omitted = len(files) - (budget - 1)
        self.assertIn(str(omitted), lines[-1])

    def test_split_and_render_codemap_preserve_curated(self):
        curated = "## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n| auth | src/auth/ | sessions | [[concepts/nextauth]] |\n\n## Where to look\n| question | path |\n|---|---|\n| where are sessions? | src/auth/session.ts |\n"
        layer = codemap.build_layer(self.repo)
        text = codemap.render_codemap(layer, curated)
        sha, gen, cur = codemap.split_codemap(text)
        self.assertEqual(sha, layer["sha"]); self.assertIn("src/db.ts", gen); self.assertEqual(cur, curated)
        self.assertEqual(codemap.split_codemap("just curated\n"), ("", "", "just curated\n"))

    def test_parse_curated_tables(self):
        _, _, cur = codemap.split_codemap(codemap.render_codemap(codemap.build_layer(self.repo),
            "## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n| Auth flow | src/auth/ | Session cookies | uses:: [[concepts/nextauth|NextAuth]] |\n\n## Where to look\n| question | path |\n|---|---|\n| sessions? | src/auth/session.ts |\n"))
        mods = codemap.parse_modules(cur)
        self.assertEqual(mods, [{"module": "Auth flow", "path": "src/auth/", "responsibility": "Session cookies", "links": "uses:: [[concepts/nextauth|NextAuth]]"}])
        self.assertEqual(codemap.parse_where(cur), [{"question": "sessions?", "path": "src/auth/session.ts"}])
        self.assertEqual(codemap.parse_modules(codemap.curated_template("demo")), [])

    def test_ensure_then_regenerate_only_on_head_change(self):
        cm = os.path.join(self.pdir, "codemap.md")
        self.assertTrue(codemap.ensure(self.repo, self.pdir)); self.assertTrue(os.path.exists(cm))
        self.assertFalse(codemap.ensure(self.repo, self.pdir))
        with open(cm, encoding="utf-8") as f: before = f.read()
        self.assertFalse(codemap.regenerate(self.repo, self.pdir))          # same fingerprint → no rewrite
        with open(os.path.join(self.repo, "src", "dirty.ts"), "w") as f: f.write("export function dirty() {}\n")
        self.assertTrue(codemap.regenerate(self.repo, self.pdir))           # uncommitted edit changes the fingerprint
        self.assertIn("src/dirty.ts  (dirty)", open(cm, encoding="utf-8").read())
        self.assertFalse(codemap.regenerate(self.repo, self.pdir))
        with open(cm, "a", encoding="utf-8") as f: f.write("| auth | src/auth/ | sessions | |\n")
        import subprocess
        with open(os.path.join(self.repo, "src", "new.ts"), "w") as f: f.write("export function fresh() {}\n")
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True); subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "n"], check=True)
        self.assertTrue(codemap.regenerate(self.repo, self.pdir))
        with open(cm, encoding="utf-8") as f: after = f.read()
        self.assertIn("src/new.ts  (fresh)", after)
        self.assertTrue(after.endswith("| auth | src/auth/ | sessions | |\n"))   # curated block kept, incl. the appended row
        self.assertNotEqual(codemap.split_codemap(before)[0], codemap.split_codemap(after)[0])
        self.assertTrue(codemap.regenerate(self.repo, self.pdir, force=True))
        self.assertGreater(codemap.file_count(self.repo), 5)

    def test_non_git_tree_uses_a_content_freshness_key(self):
        """Without git, fingerprint() is empty and regenerate() would rebuild on every call."""
        with tempfile.TemporaryDirectory() as t:
            src = os.path.realpath(t)
            os.makedirs(os.path.join(src, "src"))
            with open(os.path.join(src, "src", "a.ts"), "w") as f: f.write("export function a() {}\n")
            pdir = os.path.join(self.vault, "projects", "nogit"); os.makedirs(pdir)
            self.assertEqual(codemap.fingerprint(src), "")
            key = codemap.freshness_key(src)
            self.assertTrue(key.startswith("nogit:")); self.assertEqual(len(key), len("nogit:") + 16)
            self.assertTrue(codemap.regenerate(src, pdir))          # first: builds
            self.assertFalse(codemap.regenerate(src, pdir))         # second: content unchanged
            self.assertFalse(codemap.regenerate(src, pdir))         # third: still unchanged
            with open(os.path.join(src, "src", "b.ts"), "w") as f: f.write("export function b() {}\n")
            self.assertTrue(codemap.regenerate(src, pdir))          # new file → new key → rebuild
            self.assertIn("src/b.ts", open(os.path.join(pdir, "codemap.md"), encoding="utf-8").read())
            self.assertEqual(codemap.freshness_key(os.path.join(src, "empty")), "")   # nothing to hash

    def test_ensure_stub_writes_an_empty_generated_block(self):
        pdir = os.path.join(self.vault, "projects", "stub"); os.makedirs(pdir)
        self.assertTrue(codemap.ensure_stub(self.repo, pdir))
        self.assertFalse(codemap.ensure_stub(self.repo, pdir))       # idempotent
        text = open(os.path.join(pdir, "codemap.md"), encoding="utf-8").read()
        sha, gen, curated = codemap.split_codemap(text)
        self.assertEqual((sha, gen.strip()), ("", ""))
        self.assertIn("## Modules", curated)
        self.assertTrue(codemap.regenerate(self.repo, pdir))         # empty sha never matches → fills in
        self.assertIn("src/auth/session.ts", open(os.path.join(pdir, "codemap.md"), encoding="utf-8").read())

    def test_regenerate_tolerates_missing_codemap(self):
        self.assertTrue(codemap.regenerate(self.repo, self.pdir, force=True))
        self.assertTrue(os.path.exists(os.path.join(self.pdir, "codemap.md")))

    def test_ensure_writes_atomically(self):
        calls = []
        real_replace = os.replace
        def fake_replace(src, dst):
            calls.append((src, dst)); real_replace(src, dst)
        os.replace = fake_replace
        try:
            self.assertTrue(codemap.ensure(self.repo, self.pdir))
        finally:
            os.replace = real_replace
        codemap_calls = [c for c in calls if c[0].endswith("codemap.md.tmp")]
        self.assertEqual(len(codemap_calls), 1)
