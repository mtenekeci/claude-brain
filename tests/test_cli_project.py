import io, json, os, tempfile, time, unittest
from contextlib import redirect_stdout
from tests.helpers import make_graph_vault, make_project, make_source_tree, write_config
from brain import cli, config, project, vault


class ProjectCliTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ); self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_graph_vault(self.tmp.name, slug="demo")
        write_config(self.tmp.name, self.vault)
        os.environ["BRAIN_USER_SETTINGS"] = os.path.join(self.tmp.name, "user-settings.json")
        os.environ["HOME"] = self.tmp.name
        self.repo = make_project(self.tmp.name, slug="demo", vault=self.vault)
        make_source_tree(self.repo)
        self.pdir = os.path.join(self.vault, "projects", "demo")
        self.ctx_path = os.path.join(self.pdir, "context.md")
        # The fixture's context.md path: points at a placeholder — remove/disconnect need it to
        # resolve to the real fixture repo so the folder-side effects can be exercised.
        vault.write(self.ctx_path, vault.set_frontmatter(vault.read(self.ctx_path), "path", self.repo))
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self._cwd); self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def _run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.run(list(argv))
        return rc, buf.getvalue()

    def test_sync_prepare_and_finish(self):
        rc, out = self._run("sync-prepare"); self.assertEqual(rc, 0)
        for key in ("slug: demo", "context.md:", "last log entry:", "next session:", "today's commits:", "codemap:", "graph:", "lint:", "unannotated dirs:"):
            self.assertIn(key, out)
        rc, out = self._run("sync-finish"); self.assertEqual(rc, 0); self.assertIn("Brain synced: demo", out)
        fm, _ = vault.parse_frontmatter(vault.read(self.ctx_path)); self.assertEqual(fm["updated"], time.strftime("%Y-%m-%d"))
        self.assertIn("| %s |" % time.strftime("%Y-%m-%d"), vault.read(os.path.join(self.vault, "_system", "project-index.md")))
        self.assertTrue(os.path.exists(os.path.join(self.pdir, ".brain", "graph.json")))

    def test_sync_finish_warns_over_cap(self):
        vault.append(self.ctx_path, "\n".join("- filler %d" % i for i in range(150)) + "\n")
        rc, out = self._run("sync-finish"); self.assertIn("WARNING: over cap", out)

    def test_status_lists_health_and_orphans(self):
        orphan = os.path.join(self.tmp.name, ".claude", "brain-session-start.sh"); os.makedirs(os.path.dirname(orphan)); open(orphan, "w").close()
        rc, out = self._run("status"); self.assertEqual(rc, 0)
        for key in ("Brain status: demo (demo)", "Backend:", "Hooks: plugin-shipped (", "Codemap:", "Graph:", "Concept health:", "Orphan v1 hook scripts: brain-session-start.sh", "── State", "── Last Session"):
            self.assertIn(key, out)
        referenced = os.path.join(self.tmp.name, ".claude", "brain-precompact.sh"); open(referenced, "w").close()
        with open(os.path.join(self.repo, ".claude", "settings.json"), "w") as f:
            f.write(json.dumps({"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": referenced}]}]}}))
        rc, out = self._run("status", "--clean-orphans"); self.assertIn("removed: brain-session-start.sh", out); self.assertIn("kept (referenced): brain-precompact.sh", out)
        self.assertFalse(os.path.exists(orphan)); self.assertTrue(os.path.exists(referenced))
        os.chdir(self.tmp.name); rc, out = self._run("status"); self.assertEqual(rc, 2); self.assertIn("demo", out)

    def test_load_projects_and_concept_groups(self):
        rc, out = self._run("load", "demo", "nope"); self.assertEqual(rc, 0)
        self.assertIn("Not found: nope", out); self.assertIn("Loaded: demo", out); self.assertIn("=== demo context.md ===", out); self.assertIn("## State", out); self.assertIn("(last entry)", out)
        rc, out = self._run("load", "postgresql")
        self.assertIn("Via concept 'postgresql': demo", out); self.assertIn("stale link", out); self.assertIn("Relational store.", out)
        rc, out = self._run("load", "zzz"); self.assertEqual(rc, 1)

    def test_config_show_and_set(self):
        rc, out = self._run("config"); self.assertIn("vault:", out); self.assertIn("gate: all", out); self.assertIn("async_regen: off", out); self.assertIn("graph.backend: auto", out)
        rc, out = self._run("config", "set", "gate", "commits"); self.assertEqual(rc, 0); self.assertEqual(config.gate_mode(), "commits")
        rc, out = self._run("config", "set", "gate", "sometimes"); self.assertEqual(rc, 1)
        rc, out = self._run("config", "set", "async_regen", "on"); self.assertTrue(config.async_regen())
        rc, out = self._run("config", "set", "graph.backend", "graphify"); self.assertEqual(config.load_config()["graph"]["backend"], "graphify")
        rc, out = self._run("config", "set", "vault", "/nonexistent/dir"); self.assertEqual(rc, 1)

    def test_remove_requires_confirm_then_cleans(self):
        rc, out = self._run("remove", "demo"); self.assertEqual(rc, 1); self.assertIn("Type 'demo' to confirm", out)
        rc, out = self._run("remove", "demo", "--confirm", "demo"); self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self.pdir)); self.assertNotIn("demo", vault.read(os.path.join(self.vault, "_system", "project-index.md")))
        self.assertNotIn("brain:", vault.read(os.path.join(self.repo, "CLAUDE.md"))); self.assertIn("# Repo notes", vault.read(os.path.join(self.repo, "CLAUDE.md")))

    def test_remove_and_disconnect_refuse_a_folder_connected_to_another_slug(self):
        vault.write(os.path.join(self.repo, "CLAUDE.md"), "# Brain: other\n\nbrain: other\n---\n# notes\n")
        rc, out = self._run("disconnect", "demo"); self.assertEqual(rc, 1); self.assertIn("connected to 'other'", out)
        rc, out = self._run("remove", "demo", "--confirm", "demo"); self.assertEqual(rc, 0); self.assertIn("left untouched", out)
        self.assertIn("brain: other", vault.read(os.path.join(self.repo, "CLAUDE.md")))

    def test_disconnect_keeps_vault(self):
        rc, out = self._run("disconnect", "demo"); self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.pdir)); self.assertIsNone(project.resolve_project(self.repo))
        rc, out = self._run("disconnect", "demo"); self.assertEqual(rc, 1); self.assertIn("already be disconnected", out)

    def test_map_annotate(self):
        rc, out = self._run("map", "--annotate"); self.assertEqual(rc, 0); self.assertIn("src/", out)


if __name__ == "__main__":
    unittest.main()
