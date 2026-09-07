import io, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config
from brain import cli, codemap

class CliGraphTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ); self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo"); write_config(self.tmp.name, self.vault)
        self.repo = make_project(self.tmp.name, slug="demo"); make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo")
        os.chdir(self.repo)
    def tearDown(self):
        os.chdir(self._cwd); self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def _run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.run(list(argv))
        return rc, buf.getvalue()

    def test_map_regen_then_graph_find_near_path_top(self):
        rc, out = self._run("map", "--regen", "--quiet"); self.assertEqual((rc, out), (0, ""))
        self.assertTrue(os.path.exists(os.path.join(self.pdir, "codemap.md")))
        rc, out = self._run("graph", "find", "session"); self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("file src/auth/session.ts")); self.assertLessEqual(out.count("\n"), 15)
        rc, out = self._run("graph", "near", "file:src/auth/session.ts"); self.assertIn("imports →", out); self.assertLessEqual(out.count("\n"), 40)
        rc, out = self._run("graph", "near", "postgres"); self.assertTrue(out.startswith("concept postgresql"))   # term resolved via find
        rc, out = self._run("graph", "path", "project:demo", "concept:postgresql"); self.assertIn(" → ", out)
        rc, out = self._run("graph", "top", "--n", "3"); self.assertEqual(out.count("\n"), 3); self.assertTrue(out.startswith("project demo"))
        rc, out = self._run("graph", "rebuild"); self.assertEqual(rc, 0); self.assertIn("graph: ", out)
        rc, out = self._run("graph", "find", "zzz"); self.assertEqual((rc, out), (0, "no matches\n"))

    def test_map_without_regen_reports_freshness(self):
        rc, out = self._run("map"); self.assertEqual(rc, 0); self.assertIn("codemap:", out)

    def test_unresolvable_project_and_missing_config(self):
        os.chdir(self.tmp.name)
        rc, out = self._run("graph", "top"); self.assertEqual(rc, 2); self.assertIn("not a brain project", out)
        os.chdir(self.repo); os.environ["BRAIN_CONFIG"] = "/nonexistent"
        rc, out = self._run("graph", "top"); self.assertEqual(rc, 2); self.assertIn("not configured", out)

    def test_entrypoint_runs_cli(self):
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__))), "brain", "__main__.py")
        r = subprocess.run([sys.executable, main_py, "graph", "top", "--n", "1"], capture_output=True, text=True, cwd=self.repo, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr); self.assertTrue(r.stdout.startswith("project demo"))
