import os, subprocess, tempfile, unittest
from tests.helpers import make_project
from brain import gitinfo

class GitInfoTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)

    def test_branch_sha_and_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_project(tmp)
            self.assertEqual(gitinfo.current_branch(repo), "main")
            self.assertEqual(len(gitinfo.head_sha(repo)), 40)
            self.assertEqual(gitinfo.commits_today(repo), ["init"])
            self.assertEqual(gitinfo.last_subject(repo), "init")
            with open(os.path.join(repo, "b.py"), "w") as f: f.write("x=1\n")
            files = gitinfo.changed_files_today(repo)
            self.assertIn("a.py", files); self.assertIn("b.py", files)

    def test_outside_git_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(gitinfo.current_branch(tmp), "")
            self.assertEqual(gitinfo.commits_today(tmp), [])
            self.assertEqual(gitinfo.changed_files_today(tmp), [])
            self.assertEqual(gitinfo.last_subject(tmp), "")

    def test_rename_yields_new_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_project(tmp)
            subprocess.run(["git", "-C", repo, "mv", "a.py", "renamed.py"], check=True)
            files = gitinfo.changed_files_today(repo)
            self.assertIn("renamed.py", files)
            for f in files:
                self.assertNotIn(" -> ", f)
