"""Launcher construction only: no subprocesses, credentials or network calls."""
import importlib.util
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/"app"))
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "launch_controller", Path(__file__).parents[1] / "app" / "launch_controller.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class RelayRoutingTests(unittest.TestCase):
    def test_visual_adapter_is_explicit_and_unknown_mode_is_rejected(self):
        self.assertEqual(launcher.adapter_filename({'adapter_mode': 'visual'}), 'visual_adapter.py')
        self.assertEqual(launcher.adapter_filename({}), 'guest_adapter.py')
        with self.assertRaises(ValueError):
            launcher.adapter_filename({'adapter_mode': '../elsewhere'})

    def test_default_follows_system_instead_of_stale_ambient_proxy(self):
        with patch.dict(launcher.os.environ, {"BAGUETTE_UPSTREAM_PROXY": "", "HTTPS_PROXY": "http://127.0.0.1:31550"}):
            command = launcher.relay_command()
        self.assertEqual(command[-2:], ["--proxy", "direct"])
        self.assertIn("--credential-file", command)
        self.assertIn("--token-file", command)
        self.assertNotIn("http://127.0.0.1:31550", command)

    def test_explicit_proxy_is_preserved_once(self):
        with patch.dict(launcher.os.environ, {"BAGUETTE_UPSTREAM_PROXY": "http://127.0.0.1:12345"}):
            command = launcher.relay_command()
        self.assertEqual(command[-2:], ["--proxy", "http://127.0.0.1:12345"])
        self.assertEqual(command.count("--proxy"), 1)

    def test_invalid_explicit_proxy_fails_instead_of_silently_going_direct(self):
        with patch.dict(launcher.os.environ, {"BAGUETTE_UPSTREAM_PROXY": "not-a-proxy-url"}):
            with self.assertRaises(ValueError):
                launcher.relay_command()


if __name__ == "__main__":
    unittest.main()
