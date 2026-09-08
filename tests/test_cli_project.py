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

    FRONTMATTER_CLAUDE_MD = ("---\ndescription: repo rules\n---\n"
                             "# Brain: demo\n\nbrain: demo\n\nVault context is injected by the claude-brain plugin.\n---\n"
                             "# My notes\nkeep me\n")

    def test_disconnect_preserves_frontmatter_and_backs_up(self):
        claude_md = os.path.join(self.repo, "CLAUDE.md")
        vault.write(claude_md, self.FRONTMATTER_CLAUDE_MD)
        rc, out = self._run("disconnect", "demo"); self.assertEqual(rc, 0)
        text = vault.read(claude_md)
        self.assertTrue(text.startswith("---\ndescription: repo rules\n---\n"), repr(text))
        self.assertIn("# My notes\nkeep me\n", text)
        self.assertNotIn("brain: demo", text)
        backups = [f for f in os.listdir(self.repo) if f.startswith("CLAUDE.md.brain-bak")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(vault.read(os.path.join(self.repo, backups[0])), self.FRONTMATTER_CLAUDE_MD)

    def test_remove_preserves_frontmatter_and_backs_up(self):
        claude_md = os.path.join(self.repo, "CLAUDE.md")
        vault.write(claude_md, self.FRONTMATTER_CLAUDE_MD)
        rc, out = self._run("remove", "demo", "--confirm", "demo"); self.assertEqual(rc, 0)
        text = vault.read(claude_md)
        self.assertTrue(text.startswith("---\ndescription: repo rules\n---\n"), repr(text))
        self.assertIn("# My notes\nkeep me\n", text)
        backups = [f for f in os.listdir(self.repo) if f.startswith("CLAUDE.md.brain-bak")]
        self.assertEqual(len(backups), 1)

    def test_disconnect_keeps_a_frontmatter_only_claude_md(self):
        """Nothing but frontmatter + the brain block: the file must survive with its frontmatter,
        not be os.remove'd because `rest` happened to be empty."""
        claude_md = os.path.join(self.repo, "CLAUDE.md")
        vault.write(claude_md, "---\ndescription: repo rules\n---\n# Brain: demo\n\nbrain: demo\n---\n")
        rc, out = self._run("disconnect", "demo"); self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(claude_md))
        self.assertEqual(vault.read(claude_md), "---\ndescription: repo rules\n---\n")

    def test_map_annotate(self):
        rc, out = self._run("map", "--annotate"); self.assertEqual(rc, 0); self.assertIn("src/", out)

    def test_remove_disconnect_load_reject_path_shaped_slugs(self):
        sentinel = os.path.join(self.vault, "evil"); os.makedirs(sentinel)
        with open(os.path.join(sentinel, "marker"), "w") as f: f.write("keep me")
        # A context.md here makes `<vault>/projects/../evil` look like a real project to every
        # command's existence check — so only the slug guard can stop them.
        with open(os.path.join(sentinel, "context.md"), "w") as f: f.write("---\nproject: evil\npath: —\n---\n")
        rc, out = self._run("remove", "../evil", "--confirm", "../evil")
        self.assertEqual(rc, 1); self.assertIn("invalid slug", out)
        self.assertTrue(os.path.exists(os.path.join(sentinel, "marker")))
        self.assertTrue(os.path.exists(self.pdir))
        rc, out = self._run("disconnect", "../x"); self.assertEqual(rc, 1); self.assertIn("invalid slug", out)
        rc, out = self._run("load", "../x"); self.assertEqual(rc, 1); self.assertIn("invalid slug", out)
        # repair builds <vault>/projects/<slug>/ too — an unchecked '../evil' wrote codemap.md
        # and .brain/ outside projects/ and left CLAUDE.md holding an unmatchable `brain:` line.
        original_claude_md = vault.read(os.path.join(self.repo, "CLAUDE.md"))
        rc, out = self._run("repair", "--slug", "../evil"); self.assertEqual(rc, 1)
        self.assertIn("invalid slug", out)
        self.assertEqual(sorted(os.listdir(sentinel)), ["context.md", "marker"])
        self.assertEqual(vault.read(os.path.join(self.repo, "CLAUDE.md")), original_claude_md)

    def test_load_ignores_a_path_shaped_slug_in_a_concept_used_by_list(self):
        """`_USED_BY_LINK_RE`'s `[^/\\]]+` admits `..`, and these slugs are joined onto a vault
        path — vault-authored is not the same as trusted."""
        with open(os.path.join(self.vault, "context.md"), "w") as f: f.write("SECRET\n")
        cpath = os.path.join(self.vault, "concepts", "nextauth.md")
        vault.write(cpath, vault.read(cpath) + "- [[projects/../context|evil]] — nope\n")
        rc, out = self._run("load", "nextauth")
        self.assertNotIn("SECRET", out)
        self.assertIn("stale link", out)

    def test_clean_orphans_reports_a_deletion_failure_honestly(self):
        # A real v1 script name — the previous fixture used `brain-broken.sh`, which is not one,
        # so the test demonstrated the over-broad glob instead of catching it.
        orphan_dir = os.path.join(self.tmp.name, ".claude", "brain-session-end.sh")
        os.makedirs(orphan_dir)          # a directory named like a hook script: os.remove() must fail on it
        rc, out = self._run("status", "--clean-orphans")
        self.assertEqual(rc, 0); self.assertIn("failed:", out); self.assertIn("brain-session-end.sh", out)
        self.assertTrue(os.path.isdir(orphan_dir))
        self.assertNotIn("removed: brain-session-end.sh", out)

    def test_clean_orphans_never_touches_a_script_that_is_not_a_v1_hook(self):
        """`~/.claude/brain-*.sh` is the user's namespace too. Only the four v1 hook scripts
        were ever installed by brain, and `--clean-orphans` deletes without a confirmation."""
        mine = os.path.join(self.tmp.name, ".claude", "brain-notes.sh")
        os.makedirs(os.path.dirname(mine), exist_ok=True)
        with open(mine, "w") as f: f.write("#!/bin/sh\necho mine\n")
        rc, out = self._run("status", "--clean-orphans")
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(mine))
        self.assertNotIn("brain-notes.sh", out)

    def test_clean_orphans_keeps_a_script_registered_in_user_settings(self):
        """v1 hooks could be registered globally, not per project — a script referenced there
        is in use, not an orphan."""
        script = os.path.join(self.tmp.name, ".claude", "brain-precompact.sh")
        os.makedirs(os.path.dirname(script), exist_ok=True)
        open(script, "w").close()
        with open(os.environ["BRAIN_USER_SETTINGS"], "w") as f:
            f.write(json.dumps({"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": script}]}]}}))
        rc, out = self._run("status", "--clean-orphans")
        self.assertEqual(rc, 0)
        self.assertIn("kept (referenced): brain-precompact.sh", out)
        self.assertTrue(os.path.exists(script))

    def test_config_set_async_regen_echoes_on_off(self):
        rc, out = self._run("config", "set", "async_regen", "on")
        self.assertEqual(rc, 0); self.assertIn("async_regen: on", out)
        self.assertNotIn("True", out)
    def test_graph_dismiss_writes_dismissed_json(self):
        rc, out = self._run("graph", "dismiss", "some-concept"); self.assertEqual(rc, 0)
        self.assertIn("dismissed: some-concept", out)
        with open(os.path.join(self.pdir, ".brain", "dismissed.json")) as f:
            self.assertIn("some-concept", json.load(f)["candidates"])

    def test_repair_refuses_unknown_slug(self):
        original_ctx = vault.read(self.ctx_path)
        rc, out = self._run("repair", "--slug", "nope"); self.assertEqual(rc, 1)
        self.assertIn("not found in vault", out)
        self.assertEqual(vault.read(self.ctx_path), original_ctx)

    def test_repair_refuses_folder_connected_to_another_slug(self):
        original_ctx = vault.read(self.ctx_path)
        vault.write(os.path.join(self.repo, "CLAUDE.md"), "# Brain: other\n\nbrain: other\n---\n# notes\n")
        rc, out = self._run("repair", "--slug", "demo"); self.assertEqual(rc, 1)
        self.assertIn("connected to 'other'", out)
        self.assertIn("brain: other", vault.read(os.path.join(self.repo, "CLAUDE.md")))
        self.assertEqual(vault.read(self.ctx_path), original_ctx)

    def test_repair_rewrites_slim_block_and_preserves_rest(self):
        original_ctx = vault.read(self.ctx_path)
        vault.write(os.path.join(self.repo, "CLAUDE.md"), "# stale notes\nkeep me\n")
        rc, out = self._run("repair", "--slug", "demo"); self.assertEqual(rc, 0)
        self.assertIn("Repaired: demo", out)
        text = vault.read(os.path.join(self.repo, "CLAUDE.md"))
        self.assertIn("brain: demo", text)
        self.assertIn("# stale notes\nkeep me\n", text)
        self.assertTrue(os.path.exists(os.path.join(self.pdir, "codemap.md")))
        # Never touches vault content — compare content, not just existence.
        self.assertEqual(vault.read(self.ctx_path), original_ctx)

    def test_repair_writes_slim_block_when_claude_md_absent(self):
        original_ctx = vault.read(self.ctx_path)
        os.remove(os.path.join(self.repo, "CLAUDE.md"))
        rc, out = self._run("repair", "--slug", "demo"); self.assertEqual(rc, 0)
        self.assertIn("brain: demo", vault.read(os.path.join(self.repo, "CLAUDE.md")))
        self.assertEqual(vault.read(self.ctx_path), original_ctx)

    def test_repair_preserves_frontmatter_and_backs_up_existing_file(self):
        original_ctx = vault.read(self.ctx_path)
        text = ("---\ntitle: hello\n---\n"
                "# Brain: demo\n\nbrain: demo\n\nVault context is injected by the claude-brain plugin.\n---\n"
                "# Repo notes\nkeep me\n")
        claude_md = os.path.join(self.repo, "CLAUDE.md")
        vault.write(claude_md, text)
        rc, out = self._run("repair", "--slug", "demo"); self.assertEqual(rc, 0)
        new_text = vault.read(claude_md)
        self.assertTrue(new_text.startswith("---\ntitle: hello\n---\n"))
        self.assertIn("brain: demo", new_text)
        self.assertIn("# Repo notes\nkeep me\n", new_text)
        backups = [f for f in os.listdir(self.repo) if f.startswith("CLAUDE.md.brain-bak")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(vault.read(os.path.join(self.repo, backups[0])), text)
        # Never touches vault content — compare content, not just existence.
        self.assertEqual(vault.read(self.ctx_path), original_ctx)

    def test_repair_writes_to_resolved_project_dir_not_cwd(self):
        original_ctx = vault.read(self.ctx_path)
        subdir = os.path.join(self.repo, "sub", "dir")
        os.makedirs(subdir)
        os.chdir(subdir)
        rc, out = self._run("repair", "--slug", "demo"); self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(subdir, "CLAUDE.md")))
        self.assertIn("brain: demo", vault.read(os.path.join(self.repo, "CLAUDE.md")))
        self.assertEqual(vault.read(self.ctx_path), original_ctx)


if __name__ == "__main__":
    unittest.main()
