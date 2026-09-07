import os, tempfile, unittest
from tests.helpers import make_vault, write_config
from brain import config

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)

    def test_vault_root_from_env_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(tmp)
            write_config(tmp, vault)
            self.assertEqual(config.vault_root(), vault)

    def test_missing_config_returns_none(self):
        os.environ["BRAIN_CONFIG"] = "/nonexistent/brain.config"
        self.assertIsNone(config.vault_root())

    def test_async_regen_defaults_true_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(tmp)
            write_config(tmp, vault, extra={"async_regen": True})
            self.assertTrue(config.async_regen())
            write_config(tmp, vault, extra={"async_regen": False})
            self.assertFalse(config.async_regen())
        os.environ["BRAIN_CONFIG"] = "/nonexistent/brain.config"
        self.assertTrue(config.async_regen())        # no config file at all → default on

    def test_data_dir_created_and_log_error_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(tmp, "data")
            d = config.data_dir()
            self.assertTrue(os.path.isdir(d))
            config.log_error("boom")
            with open(os.path.join(d, "brain.log")) as f:
                self.assertIn("boom", f.read())
