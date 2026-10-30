"""Own temporary processes only; never start RPC, WeChat or a guest VM."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).parents[1] / "vm" / "guest-agent-launcher.zsh"


@unittest.skipUnless(sys.platform == "darwin", "macOS libproc identity checks")
class GuestLifecycleTests(unittest.TestCase):
    def shell(self, body, *args, timeout=10):
        return subprocess.run(
            ["/bin/zsh", "-c", 'source "$1"; task_python="$2"; ' + body,
             "lifecycle-test", str(SCRIPT), sys.executable, *map(str, args)],
            text=True, capture_output=True, timeout=timeout)

    def inspect(self, process, executable, command):
        result = self.shell('baguette_lifecycle inspect "$3" "$4" "$5"', process.pid, executable, command)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_source_does_not_start_supervision_or_request_permissions(self):
        result = self.shell('print SOURCED')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "SOURCED")
        self.assertNotIn("permission_probe", SCRIPT.read_text())

    def test_kernel_lock_blocks_duplicate_then_recovers_after_sigkill(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "supervisor.lock"
            holder = subprocess.Popen(
                ["/bin/zsh", "-c", 'source "$1"; baguette_acquire_lock "$2"; print LOCKED; read -t 30 task_fixture_wait || true; print DONE',
                 "lock-test", str(SCRIPT), str(lock)],
                text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "LOCKED")
                contender = self.shell('baguette_acquire_lock "$3"', lock)
                self.assertNotEqual(contender.returncode, 0)
                inode = lock.stat().st_ino
                holder.kill()
                holder.wait(timeout=3)
                recovered = self.shell('baguette_acquire_lock "$3"; print RECOVERED', lock)
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                self.assertIn("RECOVERED", recovered.stdout)
                self.assertEqual(lock.stat().st_ino, inode)
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.wait(timeout=3)
                holder.stdin.close()
                holder.stdout.close()
                holder.stderr.close()

    def test_recycled_or_mismatched_process_identity_never_gets_signalled(self):
        process = subprocess.Popen(["/bin/sleep", "30"])
        try:
            record = self.inspect(process, "/bin/sleep", "/bin/sleep 30")
            for key, wrong in (("uid", os.getuid() + 1), ("executable", "/bin/echo"),
                               ("started", "an older process generation"), ("command", "/bin/sleep 999")):
                changed = dict(record, **{key: wrong})
                result = self.shell('baguette_lifecycle stop "$3" .2', json.dumps(changed))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNone(process.poll())
        finally:
            process.terminate()
            process.wait(timeout=3)

    def test_old_generation_cleanup_cannot_delete_new_owner_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            lock = runtime / "guest-agent.supervisor.lock"
            lock.touch()
            inode = lock.stat().st_ino
            for generation, launcher_pid, child_pid in (("old", 100, 200), ("new", 101, 201)):
                result = self.shell('baguette_lifecycle publish "$3" "$4" "$5" "$6"', runtime,
                                    generation, json.dumps({"pid": launcher_pid}), json.dumps({"pid": child_pid}))
                self.assertEqual(result.returncode, 0, result.stderr)
            self.shell('baguette_lifecycle cleanup "$3" old 100 200', runtime)
            self.assertEqual(json.loads((runtime / "guest-agent-owner.json").read_text())["generation"], "new")
            self.assertEqual((runtime / "guest-agent.pid").read_text().strip(), "201")
            self.assertEqual((runtime / "guest-agent-owner.json").stat().st_mode & 0o777, 0o600)
            self.shell('baguette_lifecycle cleanup "$3" new 101 201', runtime)
            self.assertFalse((runtime / "guest-agent-owner.json").exists())
            self.assertFalse((runtime / "guest-agent.pid").exists())
            self.assertEqual(lock.stat().st_ino, inode)

    def test_shutdown_waits_for_term_handler_before_returning(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "delayed-child.zsh"
            fixture.write_text("trap 'sleep .6; exit 0' TERM\nprint READY\nwhile true; do sleep .1; done\n")
            process = subprocess.Popen(["/bin/zsh", str(fixture)], text=True, stdout=subprocess.PIPE)
            try:
                self.assertEqual(process.stdout.readline().strip(), "READY")
                record = self.inspect(process, "/bin/zsh", "/bin/zsh " + str(fixture))
                started = time.monotonic()
                result = self.shell('baguette_lifecycle stop "$3" 2', json.dumps(record))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertGreaterEqual(time.monotonic() - started, .5)
                self.assertEqual(process.wait(timeout=2), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                process.stdout.close()

    def test_owned_child_ignoring_term_is_killed_after_bounded_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "ignoring-child.zsh"
            fixture.write_text("trap '' TERM\nprint READY\nwhile true; do sleep .1; done\n")
            process = subprocess.Popen(["/bin/zsh", str(fixture)], text=True, stdout=subprocess.PIPE)
            try:
                self.assertEqual(process.stdout.readline().strip(), "READY")
                record = self.inspect(process, "/bin/zsh", "/bin/zsh " + str(fixture))
                started = time.monotonic()
                result = self.shell('baguette_lifecycle stop "$3" .2', json.dumps(record))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertLess(time.monotonic() - started, 3)
                self.assertEqual(process.wait(timeout=2), -signal.SIGKILL)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                process.stdout.close()


if __name__ == "__main__":
    unittest.main()
