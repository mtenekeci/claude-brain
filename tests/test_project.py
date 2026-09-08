import os, tempfile, unittest
from tests.helpers import make_project
from brain import project

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)

    def test_v2_brain_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_project(tmp, slug="demo", git=False)
            p = project.resolve_project(repo)
            self.assertEqual((p.slug, p.legacy), ("demo", False))
            self.assertEqual(p.project_dir, repo)

    def test_legacy_vault_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_project(tmp, slug="old-app", legacy=True, vault="/Users/x/vault", git=False)
            p = project.resolve_project(repo)
            self.assertEqual((p.slug, p.legacy), ("old-app", True))

    def test_no_claude_md_or_no_brain_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(project.resolve_project(tmp))
            with open(os.path.join(tmp, "CLAUDE.md"), "w") as f: f.write("# Just a repo\n")
            self.assertIsNone(project.resolve_project(tmp))

    def test_rejects_path_shaped_slugs(self):
        """A slug becomes a vault directory name: `..` or `a/b` would escape projects/."""
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ("..", ".", ".hidden", "a/b", "../../etc"):
                with open(os.path.join(tmp, "CLAUDE.md"), "w") as f:
                    f.write("# Brain: x\n\nbrain: %s\n---\n" % bad)
                self.assertIsNone(project.resolve_project(tmp), bad)
            for bad in ("/v/projects/..", "/v/projects/."):
                with open(os.path.join(tmp, "CLAUDE.md"), "w") as f:
                    f.write("# Brain: x\n\nvault: %s\n---\n" % bad)
                self.assertIsNone(project.resolve_project(tmp), bad)
            with open(os.path.join(tmp, "CLAUDE.md"), "w") as f:
                f.write("# Brain: x\n\nbrain: ok-slug.1\n---\n")
            self.assertEqual(project.resolve_project(tmp).slug, "ok-slug.1")

    def test_split_brain_block(self):
        text = "# Brain: x\n\nbrain: x\n---\n# Rest\nmore\n"
        head, rest = project.split_brain_block(text)
        self.assertTrue(head.endswith("---\n"))
        self.assertEqual(rest, "# Rest\nmore\n")
        head2, rest2 = project.split_brain_block("# Brain: x\n\nbrain: x\n")
        self.assertEqual(rest2, "")

    def test_nested_cwd_walks_up_and_project_dir_env_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_project(tmp, slug="demo", git=False)
            nested = os.path.join(repo, "src", "deep"); os.makedirs(nested)
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            p = project.resolve_project(nested)
            self.assertEqual((p.slug, p.project_dir), ("demo", repo))
            other = make_project(os.path.join(tmp, "o"), slug="other", git=False)
            os.environ["CLAUDE_PROJECT_DIR"] = other
            try:
                self.assertEqual(project.resolve_project(nested).slug, "other")
            finally:
                del os.environ["CLAUDE_PROJECT_DIR"]

    def test_vault_project_dir(self):
        self.assertEqual(project.vault_project_dir("/v", "s"), "/v/projects/s")

    def test_vault_project_dir_refuses_a_path_shaped_slug(self):
        """The last line of defence: a caller that forgets `_require_valid_slug` must not be
        able to build a path outside <vault>/projects/ at all."""
        for bad in ("../evil", "..", ".", "a/b", "", "/abs"):
            with self.assertRaises(ValueError):
                project.vault_project_dir("/v", bad)

    def test_undecodable_claude_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "CLAUDE.md"), "wb") as f:
                f.write(b"\xff\xfe# Brain\nbrain: x\n")
            self.assertIsNone(project.resolve_project(tmp))

    def test_claude_md_with_leading_frontmatter_resolves(self):
        """A leading YAML frontmatter block's closing `---` is not the brain-block separator."""
        with tempfile.TemporaryDirectory() as tmp:
            text = "---\ntitle: notes\ntags: [x]\n---\n\n# Brain: demo\n\nbrain: demo\n---\n# Repo notes\n"
            with open(os.path.join(tmp, "CLAUDE.md"), "w", encoding="utf-8") as f:
                f.write(text)
            p = project.resolve_project(tmp)
            self.assertIsNotNone(p)
            self.assertEqual((p.slug, p.legacy), ("demo", False))
            head, rest = project.split_brain_block(text)
            self.assertTrue(head.endswith("brain: demo\n---\n"))
            self.assertEqual(rest, "# Repo notes\n")


if __name__ == "__main__":
    unittest.main()
