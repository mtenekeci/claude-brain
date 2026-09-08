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

    def test_set_value_refuses_to_touch_a_malformed_config(self):
        """A hand-edited but invalid brain.config must never be silently discarded and rebuilt
        from an empty dict — set_value raises instead, and the file is left byte-identical."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "brain.config")
            os.environ["BRAIN_CONFIG"] = path
            with open(path, "w") as f: f.write("{not valid json")
            with self.assertRaises(ValueError) as cm:
                config.set_value("gate", "off")
            self.assertIn("not valid JSON", str(cm.exception))
            with open(path) as f:
                self.assertEqual(f.read(), "{not valid json")
            # read-only paths still tolerate the malformed file as {} — hooks stay silent
            self.assertIsNone(config.vault_root())
            self.assertEqual(config.gate_mode(), "all")

    def test_set_value_refuses_a_config_that_is_valid_json_but_not_an_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "brain.config")
            os.environ["BRAIN_CONFIG"] = path
            with open(path, "w") as f: f.write("[1, 2, 3]")
            with self.assertRaises(ValueError):
                config.set_value("gate", "off")
            with open(path) as f:
                self.assertEqual(f.read(), "[1, 2, 3]")

    def test_set_value_creates_a_missing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "brain.config")
            os.environ["BRAIN_CONFIG"] = path
            self.assertFalse(os.path.exists(path))
            config.set_value("gate", "commits")
            self.assertEqual(config.gate_mode(), "commits")

    def test_set_value_keeps_unrelated_fields_of_a_well_formed_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "brain.config")
            os.environ["BRAIN_CONFIG"] = path
            with open(path, "w") as f: f.write('{"vault": "/x", "custom": "keep-me"}')
            config.set_value("gate", "commits")
            self.assertEqual(config.load_config()["custom"], "keep-me")
