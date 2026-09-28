from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import bounded_run  # noqa: E402

WRAPPER = str(SCRIPTS / "bounded_run.py")

# Appends one event line to the file in EVENTS, holds, then appends the end event.
# The hold stops after HOLD seconds, or when the file in RELEASE exists.
WORKER = (
    "import os, sys, time\n"
    "def event(kind):\n"
    "    descriptor = os.open(os.environ['EVENTS'], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)\n"
    "    os.write(descriptor, ('%s %s %d\\n' % (kind, sys.argv[1], os.getpid())).encode())\n"
    "    os.close(descriptor)\n"
    "event('start')\n"
    "release = os.environ.get('RELEASE')\n"
    "deadline = time.time() + float(os.environ.get('HOLD', '0.3'))\n"
    "while time.time() < deadline and not (release and os.path.exists(release)):\n"
    "    time.sleep(0.02)\n"
    "event('end')\n"
)


class SizeTest(unittest.TestCase):
    def test_reads_gibibytes(self):
        self.assertEqual(bounded_run.parse_size_mib("6G"), 6144)

    def test_reads_mebibytes(self):
        self.assertEqual(bounded_run.parse_size_mib("4096M"), 4096)

    def test_reads_a_number_without_a_unit_as_mebibytes(self):
        self.assertEqual(bounded_run.parse_size_mib("512"), 512)

    def test_reads_a_lower_case_unit(self):
        self.assertEqual(bounded_run.parse_size_mib("2g"), 2048)

    def test_rejects_text_that_is_not_a_size(self):
        for text in ("", "six", "6GB", "-1G", "1.5G", "0"):
            with self.subTest(text=text):
                with self.assertRaises(bounded_run.WrapperError):
                    bounded_run.parse_size_mib(text)


class SlotCountTest(unittest.TestCase):
    def test_divides_the_memory_after_the_reserve(self):
        self.assertEqual(bounded_run.slot_count(32768, 2048, 8192), 12)

    def test_gives_one_slot_on_a_small_machine(self):
        self.assertEqual(bounded_run.slot_count(2048, 2048, 2048), 1)

    def test_default_reserve_is_a_quarter_with_a_minimum(self):
        self.assertEqual(bounded_run.default_reserve_mib(32768), 8192)
        self.assertEqual(bounded_run.default_reserve_mib(4096), 2048)

    def test_a_budget_takes_the_slots_that_cover_it(self):
        self.assertEqual(bounded_run.slots_needed(6144, 2048, 12), 3)
        self.assertEqual(bounded_run.slots_needed(6145, 2048, 12), 4)
        self.assertEqual(bounded_run.slots_needed(100, 2048, 12), 1)

    def test_a_budget_larger_than_the_queue_takes_all_slots(self):
        self.assertEqual(bounded_run.slots_needed(99999, 2048, 3), 3)

    def test_default_budget_is_a_quarter_in_full_slots(self):
        self.assertEqual(bounded_run.default_budget_mib(32768, 2048), 8192)
        self.assertEqual(bounded_run.default_budget_mib(6000, 2048), 2048)

    def test_total_memory_of_this_machine_is_positive(self):
        self.assertGreater(bounded_run.total_memory_mib(), 0)


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        settings = bounded_run.Settings({}, read_total=lambda: 16384)
        self.assertEqual(settings.slot_mib, 2048)
        self.assertEqual(settings.total_mib, 16384)
        self.assertEqual(settings.reserve_mib, 4096)
        self.assertEqual(settings.poll_seconds, 2.0)
        self.assertEqual(settings.memory_wait_seconds, 300.0)
        self.assertFalse(settings.no_cap)

    def test_overrides(self):
        settings = bounded_run.Settings({
            "BOUNDED_RUN_SLOT_MIB": "1024", "BOUNDED_RUN_TOTAL_MIB": "4096",
            "BOUNDED_RUN_RESERVE_MIB": "1024", "BOUNDED_RUN_POLL_SECONDS": "0.05",
            "BOUNDED_RUN_MEMORY_WAIT_SECONDS": "0", "BOUNDED_RUN_NO_CAP": "1",
        }, read_total=lambda: 1)
        self.assertEqual((settings.slot_mib, settings.total_mib, settings.reserve_mib), (1024, 4096, 1024))
        self.assertEqual((settings.poll_seconds, settings.memory_wait_seconds), (0.05, 0.0))
        self.assertTrue(settings.no_cap)

    def test_rejects_a_value_that_is_not_a_number(self):
        with self.assertRaises(bounded_run.WrapperError):
            bounded_run.Settings({"BOUNDED_RUN_POLL_SECONDS": "fast"}, read_total=lambda: 1)


class LockDirectoryTest(unittest.TestCase):
    def test_override_wins(self):
        environ = {"BOUNDED_RUN_LOCK_DIR": "/x/locks", "XDG_RUNTIME_DIR": "/run/user/7"}
        self.assertEqual(bounded_run.lock_directory(environ, 7), "/x/locks")

    def test_uses_the_runtime_directory(self):
        self.assertEqual(bounded_run.lock_directory({"XDG_RUNTIME_DIR": "/run/user/7"}, 7), "/run/user/7/bounded-run")

    def test_falls_back_to_a_directory_for_the_user(self):
        self.assertEqual(bounded_run.lock_directory({}, 999999999), "/tmp/bounded-run-999999999")

    def test_does_not_depend_on_TMPDIR(self):
        self.assertEqual(bounded_run.lock_directory({"TMPDIR": "/elsewhere"}, 999999999), "/tmp/bounded-run-999999999")

    def test_creates_the_directory_for_the_user_only(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, "locks")
            bounded_run.ensure_lock_directory(path, os.getuid())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)

    def test_closes_a_directory_that_other_users_can_read(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, "locks")
            os.mkdir(path, 0o755)
            bounded_run.ensure_lock_directory(path, os.getuid())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)

    def test_rejects_a_directory_of_a_different_user(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(bounded_run.WrapperError):
                bounded_run.ensure_lock_directory(base, os.getuid() + 1)

    def test_rejects_a_symbolic_link(self):
        with tempfile.TemporaryDirectory() as base:
            link = os.path.join(base, "link")
            os.symlink(base, link)
            with self.assertRaises(bounded_run.WrapperError):
                bounded_run.ensure_lock_directory(link, os.getuid())


if __name__ == "__main__":
    unittest.main()
