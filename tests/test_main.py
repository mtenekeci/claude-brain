import os, subprocess, sys, tempfile, unittest

MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain", "__main__.py")


class MainEntryPointTests(unittest.TestCase):
    """The entry point must never raise and never print outside a brain project — whatever
    Claude Code hands it on stdin."""

    def _run(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["BRAIN_CONFIG"] = os.path.join(tmp, "brain.config")     # no config file at all
            env["CLAUDE_PLUGIN_DATA"] = os.path.join(tmp, "data")
            env.pop("CLAUDE_PROJECT_DIR", None)
            cwd = os.path.join(tmp, "elsewhere")                        # NOT a brain project
            os.makedirs(cwd)
            return subprocess.run([sys.executable, MAIN, "hook", "SessionStart"],
                                  cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)

    def test_garbage_stdin_exits_zero_and_silent(self):
        r = self._run(input=b"not json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"")

    def test_no_stdin_exits_zero_and_silent(self):
        r = self._run(stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"")

    def test_internal_failure_is_logged_and_exits_zero(self):
        """Any exception below main() is logged to brain.log and exits 0, silently."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("brain_main_under_test", MAIN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        env, tmp = dict(os.environ), tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(env)))
        os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(tmp.name, "data")
        original = mod._run
        mod._run = lambda argv: (_ for _ in ()).throw(RuntimeError("kaboom"))
        try:
            self.assertEqual(mod.main(["hook", "SessionStart"]), 0)
        finally:
            mod._run = original
        with open(os.path.join(tmp.name, "data", "brain.log"), encoding="utf-8") as f:
            self.assertIn("kaboom", f.read())


if __name__ == "__main__":
    unittest.main()
