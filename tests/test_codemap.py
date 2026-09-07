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
