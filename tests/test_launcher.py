# SPDX-License-Identifier: GPL-2.0+
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "launcher.sh"


class LauncherTests(unittest.TestCase):
    def run_launcher(self, directory, status):
        project = Path(directory) / "project with spaces"
        project.mkdir(exist_ok=True)
        shutil.copyfile(LAUNCHER, project / "launcher.sh")
        interpreter = project / ".venv/bin/python"
        interpreter.parent.mkdir(parents=True, exist_ok=True)
        interpreter.write_text(
            '#!/usr/bin/env bash\n'
            'printf "stdout: %s %s %s\\n" "$@"\n'
            'printf "stderr: traceback\\n" >&2\n'
            'printf "unbuffered=%s faulthandler=%s\\n" "$PYTHONUNBUFFERED" "$PYTHONFAULTHANDLER"\n'
            f'exit {status}\n'
        )
        interpreter.chmod(0o700)
        home = Path(directory) / "home"
        result = subprocess.run(
            ["bash", str(project / "launcher.sh")], cwd=directory,
            env={**os.environ, "HOME": str(home)}, capture_output=True, text=True,
            timeout=10, check=False,
        )
        return result, home / ".config/ippon/logs"

    def test_stdout_stderr_and_failure_status_are_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            result, logs = self.run_launcher(directory, 7)
            self.assertEqual(result.returncode, 7, result.stderr)
            latest = logs / "latest.log"
            self.assertTrue(latest.is_symlink())
            text = latest.read_text()
            self.assertIn("stdout: -m ippon view", text)
            self.assertIn("stderr: traceback", text)
            self.assertIn("unbuffered=1 faulthandler=1", text)
            self.assertIn("exit status: 7", text)
            self.assertIn("stderr: traceback", result.stdout)
            self.assertEqual(latest.stat().st_mode & 0o777, 0o600)

    def test_each_launch_keeps_a_separate_log(self):
        with tempfile.TemporaryDirectory() as directory:
            first, logs = self.run_launcher(directory, 139)
            first_target = (logs / "latest.log").resolve()
            second, _ = self.run_launcher(directory, 0)
            self.assertEqual(first.returncode, 139, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotEqual(first_target, (logs / "latest.log").resolve())
            self.assertIn("exit status: 139", first_target.read_text())
            self.assertIn("exit status: 0", (logs / "latest.log").read_text())


if __name__ == "__main__":
    unittest.main()
