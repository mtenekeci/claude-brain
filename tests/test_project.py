import os, tempfile, unittest
from tests.helpers import make_project
from brain import project

class ProjectTests(unittest.TestCase):
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
