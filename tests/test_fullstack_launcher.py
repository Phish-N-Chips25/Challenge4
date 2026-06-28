import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import run_fullstack


class FullstackLauncherTests(unittest.TestCase):
    def test_choose_simagia_python_prefers_explicit_env(self):
        root = Path(tempfile.mkdtemp())

        command = run_fullstack.choose_simagia_python(
            root,
            {"SIMALGIA_PYTHON": "/tmp/custom-python"},
        )

        self.assertEqual(command, ["/tmp/custom-python"])

    def test_choose_simagia_python_prefers_repo_python310_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python_bin = root / ".venv-simagia310" / "bin" / "python"
            python_bin.parent.mkdir(parents=True)
            python_bin.write_text("", encoding="utf-8")

            command = run_fullstack.choose_simagia_python(root, {})

        self.assertEqual(command, [str(python_bin)])

    def test_build_simagia_env_enables_booster_bridge(self):
        env = run_fullstack.build_simagia_env(
            {"PATH": os.environ.get("PATH", "")},
            simulated_sensors=True,
        )

        self.assertEqual(env["USE_BOOSTER_BRIDGE"], "1")
        self.assertEqual(env["SENTINEL_SIM"], "1")
        self.assertEqual(env["PYTHONUNBUFFERED"], "1")

    def test_import_probe_reports_missing_modules_as_json(self):
        probe = run_fullstack.import_probe_code(["json", "module_that_should_not_exist_123"])

        result = subprocess.run(
            [sys.executable, "-c", probe],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), ["module_that_should_not_exist_123"])

    def test_booster_launcher_runs_in_new_session(self):
        args = SimpleNamespace(dry_run=False)

        with patch.object(run_fullstack, "run_command") as run_command:
            run_fullstack.run_booster_stack(args, {"PATH": ""})

        booster_call = run_command.call_args_list[1]
        self.assertEqual(booster_call.args[0], ["./tools/run_sentinelmas_booster.sh"])
        self.assertTrue(booster_call.kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
