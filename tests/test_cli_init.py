import io, json, os, subprocess, tempfile, unittest
from contextlib import redirect_stdout
from tests.helpers import make_source_tree, write_config
from brain import cli, config, initproj, vault, project

class InitTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ); self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        # realpath: brain canonicalises every path it stores, and macOS tmpdirs are symlinked.
        self.vault = os.path.realpath(os.path.join(self.tmp.name, "vault")); os.makedirs(self.vault)
        write_config(self.tmp.name, self.vault)
        os.environ["BRAIN_USER_SETTINGS"] = os.path.join(self.tmp.name, "user-settings.json")
        os.environ["HOME"] = self.tmp.name
        self.repo = os.path.join(self.tmp.name, "repo"); os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.email", "t@t"], check=True); subprocess.run(["git", "-C", self.repo, "config", "user.name", "t"], check=True)
        with open(os.path.join(self.repo, "README.md"), "w") as f: f.write("# Demo\nA demo app.\n")
        with open(os.path.join(self.repo, "a.py"), "w") as f: f.write("def a():\n    return 1\n")
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True); subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "init"], check=True)
        make_source_tree(self.repo)
        with open(os.path.join(self.repo, "CLAUDE.md"), "w") as f: f.write("# My notes\nkeep me\n")
        os.chdir(self.repo)
    def tearDown(self):
        os.chdir(self._cwd); self.tmp.cleanup(); os.environ.clear(); os.environ.update(self._env)

    def _run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf): rc = cli.run(list(argv))
        return rc, buf.getvalue()

    def test_init_code_project_end_to_end(self):
        rc, out = self._run("init", "--name", "Demo App", "--type", "code", "--packet")
        self.assertEqual(rc, 0, out); self.assertIn("Brain initialized for Demo App (demo-app)", out)
        pdir = os.path.join(self.vault, "projects", "demo-app")
        for f in ("context.md", "architecture.md", "log.md", "codemap.md"): self.assertTrue(os.path.exists(os.path.join(pdir, f)), f)
        fm, _ = vault.parse_frontmatter(vault.read(os.path.join(pdir, "context.md")))
        self.assertEqual((fm["project"], fm["type"], fm["path"]), ("demo-app", "code", os.path.realpath(self.repo)))
        self.assertIn("| [[projects/demo-app/context\\|demo-app]] | code |", vault.read(os.path.join(self.vault, "_system", "project-index.md")))
        self.assertTrue(os.path.exists(os.path.join(self.vault, "_system", "BRAIN.md"))); self.assertTrue(os.path.isdir(os.path.join(self.vault, "concepts")))
        cm = vault.read(os.path.join(self.repo, "CLAUDE.md"))
        self.assertTrue(cm.startswith("# Brain: Demo App\n\nbrain: demo-app\n")); self.assertTrue(cm.endswith("---\n# My notes\nkeep me\n"))
        self.assertEqual(project.resolve_project(self.repo).slug, "demo-app")
        with open(os.environ["BRAIN_USER_SETTINGS"], encoding="utf-8") as f:
            settings = json.load(f)
        self.assertIn("Read(%s/**)" % self.vault, settings["permissions"]["allow"])
        self.assertIn("=== SEEDING PACKET ===", out); self.assertIn("## readme", out); self.assertIn("A demo app.", out); self.assertIn("## deps", out); self.assertIn("next-auth", out)
        self.assertNotIn("# Brain:", out.split("## claude-md")[1].split("## memory")[0])           # packet shows only the user's part of CLAUDE.md

    def test_init_inserts_the_block_after_existing_frontmatter(self):
        """A CLAUDE.md that opens with YAML frontmatter and has no brain line: the slim block
        goes BELOW the frontmatter, or the frontmatter stops being frontmatter."""
        cm = os.path.join(self.repo, "CLAUDE.md")
        with open(cm, "w", encoding="utf-8") as f:
            f.write("---\ndescription: repo rules\n---\n# My notes\nkeep me\n")
        rc, out = self._run("init", "--name", "Demo App", "--type", "code", "--no-permissions")
        self.assertEqual(rc, 0, out)
        text = vault.read(cm)
        self.assertTrue(text.startswith("---\ndescription: repo rules\n---\n# Brain: Demo App\n\nbrain: demo-app\n"), repr(text))
        self.assertTrue(text.endswith("---\n# My notes\nkeep me\n"))
        self.assertEqual(project.resolve_project(self.repo).slug, "demo-app")

    def test_init_refuses_duplicate_and_is_idempotent_on_permissions(self):
        self._run("init", "--name", "Demo App", "--type", "code")
        rc, out = self._run("init", "--name", "demo app", "--type", "code")
        self.assertEqual(rc, 1); self.assertIn("already exists", out)
        n1 = initproj.grant_permissions(self.vault); self.assertEqual(n1, 0)

    def test_init_preflight_blocks_connected_repo_missing_dir_and_bad_settings(self):
        self._run("init", "--name", "Demo App", "--type", "code")                              # repo now connected to demo-app
        rc, out = self._run("init", "--name", "Other", "--type", "code"); self.assertEqual(rc, 1); self.assertIn("already connected to 'demo-app'", out)
        self.assertFalse(os.path.exists(os.path.join(self.vault, "projects", "other")))         # nothing written
        rc, out = self._run("init", "--name", "Ghost", "--type", "code", "--project-dir", "/nonexistent/dir"); self.assertEqual(rc, 1); self.assertIn("does not exist", out)
        with open(os.environ["BRAIN_USER_SETTINGS"], "w") as f: f.write("{not json")
        os.remove(os.path.join(self.repo, "CLAUDE.md"))
        rc, out = self._run("init", "--name", "Third", "--type", "code"); self.assertEqual(rc, 1); self.assertIn("not in the expected shape", out)
        with open(os.environ["BRAIN_USER_SETTINGS"]) as f:
            self.assertEqual(f.read(), "{not json")                                              # untouched
        self.assertFalse(os.path.exists(os.path.join(self.vault, "projects", "third")))
        with open(os.environ["BRAIN_USER_SETTINGS"], "w") as f: f.write('{"permissions": []}')
        rc, out = self._run("init", "--name", "Third", "--type", "code"); self.assertEqual(rc, 1)
        rc, out = self._run("init", "--name", "Third", "--type", "code", "--no-permissions"); self.assertEqual(rc, 0)

    def test_init_with_vault_flag_configures_a_fresh_install(self):
        os.environ["BRAIN_CONFIG"] = os.path.join(self.tmp.name, "fresh.config")
        newvault = os.path.join(self.tmp.name, "newvault")
        rc, out = self._run("init", "--name", "Fresh", "--type", "code", "--vault", newvault, "--no-permissions")
        self.assertEqual(rc, 0, out); self.assertTrue(os.path.isdir(os.path.join(newvault, "_system")))
        self.assertEqual(config.vault_root(), os.path.realpath(newvault))

    def test_grant_permissions_backs_up_before_first_write(self):
        with open(os.environ["BRAIN_USER_SETTINGS"], "w") as f: f.write('{"permissions": {"allow": ["Read(x)"]}, "other": 1}')
        self.assertEqual(initproj.grant_permissions(self.vault), 5)
        with open(os.environ["BRAIN_USER_SETTINGS"] + ".brain-bak") as f:
            self.assertEqual(f.read(), '{"permissions": {"allow": ["Read(x)"]}, "other": 1}')
        with open(os.environ["BRAIN_USER_SETTINGS"]) as f:
            data = json.load(f)
        self.assertEqual(data["other"], 1); self.assertIn("Read(x)", data["permissions"]["allow"])

    def test_empty_settings_file_is_treated_as_absent(self):
        open(os.environ["BRAIN_USER_SETTINGS"], "w").close()                                     # 0-byte file: benign, not malformed
        self.assertIsNone(initproj.settings_shape_error())
        self.assertEqual(initproj.grant_permissions(self.vault), 5)
        with open(os.environ["BRAIN_USER_SETTINGS"], encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("Read(%s/**)" % self.vault, data["permissions"]["allow"])

    def test_init_topic_project(self):
        rc, out = self._run("init", "--name", "Auth Redesign", "--type", "topic")
        self.assertEqual(rc, 0); pdir = os.path.join(self.vault, "projects", "auth-redesign")
        self.assertTrue(os.path.exists(os.path.join(pdir, "context.md"))); self.assertFalse(os.path.exists(os.path.join(pdir, "codemap.md")))
        self.assertIn("| topic | — |", vault.read(os.path.join(self.vault, "_system", "project-index.md")))
        self.assertIn("# My notes", vault.read(os.path.join(self.repo, "CLAUDE.md"))); self.assertNotIn("brain:", vault.read(os.path.join(self.repo, "CLAUDE.md")))

    def test_packet_is_capped_and_complete(self):
        with open(os.path.join(self.repo, "README.md"), "w") as f: f.write("x" * 20000)
        p = initproj.seeding_packet(self.repo, limit=3000)
        self.assertLessEqual(len(p), 3100); self.assertIn("… (truncated)", p)
        for sec in ("## manifest", "## readme", "## git", "## claude-md", "## memory", "## deps", "## entry-points"): self.assertIn(sec, p)

    def test_packet_memory_section_reads_project_memory_files(self):
        # Claude Code keeps the leading dash when encoding cwd: /a/b -> -a-b (no lstrip).
        enc = os.path.realpath(self.repo).replace("/", "-")
        mdir = os.path.join(self.tmp.name, ".claude", "projects", enc, "memory")
        os.makedirs(mdir)
        with open(os.path.join(mdir, "note.md"), "w") as f: f.write("Remember the auth flow quirk.\n")
        p = initproj.seeding_packet(self.repo)
        self.assertIn("## memory", p); self.assertIn("Remember the auth flow quirk.", p)

    def test_init_without_config(self):
        os.environ["BRAIN_CONFIG"] = "/nonexistent"
        rc, out = self._run("init", "--name", "X", "--type", "code"); self.assertEqual(rc, 2); self.assertIn("not configured", out)
