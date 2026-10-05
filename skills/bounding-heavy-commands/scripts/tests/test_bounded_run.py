from __future__ import annotations

import errno
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
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


class UsageTextTest(unittest.TestCase):
    def test_says_who_sets_the_environment_variables(self):
        self.assertIn(
            "A normal call sets none of the environment variables below.",
            bounded_run.__doc__,
        )

    def test_names_the_risk_of_a_variable_for_a_single_call(self):
        text = " ".join(bounded_run.__doc__.split())
        self.assertIn(
            "Do not set one of them for a single call. A call with its own slot size, reserve, or lock "
            "directory does not share the queue with the other sessions of the machine, and a call with "
            "no cap can take the memory of all of them.",
            text,
        )

    def test_says_who_the_test_values_are_for(self):
        text = " ".join(bounded_run.__doc__.split())
        self.assertIn("The tests of this script set the rest, and so do its maintainers when they look for a fault of the script.", text)
        self.assertIn("Values for the tests of this script, and for its maintainers:", text)
        self.assertNotIn("diagnosis", text)

    def test_lists_the_free_memory_for_the_tests(self):
        values = bounded_run.__doc__.split("Values for the tests of this script, and for its maintainers:")[1]
        self.assertIn("BOUNDED_RUN_FREE_MIB", values)


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

    def test_the_queue_holds_its_slots_when_the_reserve_leaves_one_or_more(self):
        self.assertEqual(bounded_run.queue_mib(32768, 2048, 8192), 24576)

    def test_the_queue_keeps_the_reserve_on_a_machine_with_less_than_one_slot_after_it(self):
        self.assertEqual(bounded_run.queue_mib(3072, 2048, 2048), 1024)

    def test_the_queue_has_the_memory_of_the_machine_when_the_reserve_leaves_nothing(self):
        self.assertEqual(bounded_run.queue_mib(1024, 2048, 2048), 1024)
        self.assertEqual(bounded_run.queue_mib(4096, 2048, 4096), 2048)

    def test_default_reserve_is_a_quarter_with_a_minimum(self):
        self.assertEqual(bounded_run.default_reserve_mib(32768), 8192)
        self.assertEqual(bounded_run.default_reserve_mib(4096), 2048)

    def test_a_budget_takes_the_slots_that_cover_it(self):
        self.assertEqual(bounded_run.slots_needed(6144, 2048, 12), 3)
        self.assertEqual(bounded_run.slots_needed(6145, 2048, 12), 4)
        self.assertEqual(bounded_run.slots_needed(100, 2048, 12), 1)

    def test_a_budget_too_large_for_a_float_takes_all_slots(self):
        self.assertEqual(bounded_run.slots_needed(10 ** 400, 2048, 12), 12)

    def test_a_budget_larger_than_the_queue_takes_all_slots(self):
        self.assertEqual(bounded_run.slots_needed(99999, 2048, 3), 3)

    def test_default_budget_is_a_quarter_in_full_slots(self):
        self.assertEqual(bounded_run.default_budget_mib(32768, 2048), 8192)
        self.assertEqual(bounded_run.default_budget_mib(6000, 2048), 2048)

    def test_default_budget_is_never_zero(self):
        self.assertEqual(bounded_run.default_budget_mib(0, 2048), 1)

    def test_default_budget_is_never_more_than_the_total(self):
        self.assertEqual(bounded_run.default_budget_mib(1024, 2048), 1024)
        self.assertEqual(bounded_run.default_budget_mib(2048, 2048), 2048)

    def test_total_memory_of_this_machine_is_positive(self):
        self.assertGreater(bounded_run.total_memory_mib(), 0)

    def test_a_physical_memory_that_cannot_be_read_is_reported(self):
        failures = (
            FileNotFoundError(errno.ENOENT, "No such file or directory"),
            subprocess.TimeoutExpired("sysctl", 10),
            subprocess.CompletedProcess(["sysctl"], 1, stdout=""),
        )
        for failure in failures:
            with self.subTest(failure=failure):
                run = mock.Mock(side_effect=failure) if isinstance(failure, Exception) else mock.Mock(return_value=failure)
                with mock.patch.object(bounded_run.os, "sysconf", side_effect=ValueError("unknown")), \
                        mock.patch.object(bounded_run.subprocess, "run", run):
                    with self.assertRaises(bounded_run.WrapperError) as caught:
                        bounded_run.physical_memory_mib()
                self.assertIn("cannot read the memory of the machine", str(caught.exception))


class CgroupLimitTest(unittest.TestCase):
    """Gives total_memory_mib a /proc and a cgroup filesystem in a temporary directory, and 16 GiB of physical memory."""

    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.proc = os.path.join(self.base.name, "proc")
        self.cgroups = os.path.join(self.base.name, "cgroups")
        os.makedirs(os.path.join(self.proc, "self"))
        os.makedirs(self.cgroups)

    def membership(self, text):
        Path(self.proc, "self", "cgroup").write_text(text)

    def limit(self, relative, name, value):
        directory = os.path.join(self.cgroups, relative)
        os.makedirs(directory, exist_ok=True)
        Path(directory, name).write_text(value + "\n")

    def total(self):
        return bounded_run.total_memory_mib(proc_root=self.proc, cgroup_root=self.cgroups, read_physical=lambda: 16384)

    def test_a_limit_in_the_cgroup_of_the_process(self):
        self.membership("0::/user.slice/unit-1.scope\n")
        self.limit("user.slice/unit-1.scope", "memory.max", str(6 * 1024 ** 3))
        self.assertEqual(self.total(), 6144)

    def test_a_limit_in_a_parent_only(self):
        self.membership("0::/user.slice/unit-1.scope\n")
        self.limit("user.slice/unit-1.scope", "memory.max", "max")
        self.limit("user.slice", "memory.max", str(4 * 1024 ** 3))
        self.assertEqual(self.total(), 4096)

    def test_the_smallest_limit_wins(self):
        self.membership("0::/user.slice/unit-1.scope\n")
        self.limit("user.slice/unit-1.scope", "memory.max", str(8 * 1024 ** 3))
        self.limit("user.slice", "memory.max", str(3 * 1024 ** 3))
        self.limit("", "memory.max", str(5 * 1024 ** 3))
        self.assertEqual(self.total(), 3072)

    def test_max_on_each_level_is_no_limit(self):
        self.membership("0::/user.slice/unit-1.scope\n")
        for relative in ("user.slice/unit-1.scope", "user.slice", ""):
            self.limit(relative, "memory.max", "max")
        self.assertEqual(self.total(), 16384)

    def test_no_cgroup_files_is_no_limit(self):
        self.assertEqual(self.total(), 16384)

    def test_a_membership_without_limit_files_is_no_limit(self):
        self.membership("0::/user.slice/unit-1.scope\n")
        self.assertEqual(self.total(), 16384)

    def test_a_limit_larger_than_the_physical_memory_is_no_limit(self):
        self.membership("0::/\n")
        self.limit("", "memory.max", str(64 * 1024 ** 3))
        self.assertEqual(self.total(), 16384)

    def test_a_file_that_is_not_readable_is_no_limit(self):
        self.membership("0::/user.slice\n")
        os.makedirs(os.path.join(self.cgroups, "user.slice", "memory.max"))
        self.assertEqual(self.total(), 16384)

    def test_cgroup_version_1(self):
        self.membership("12:cpu,cpuacct:/user.slice\n5:memory:/user.slice/unit-1.scope\n0::/user.slice/unit-1.scope\n")
        self.limit("memory/user.slice/unit-1.scope", "memory.limit_in_bytes", "9223372036854771712")
        self.limit("memory/user.slice", "memory.limit_in_bytes", str(2 * 1024 ** 3))
        self.assertEqual(self.total(), 2048)

    def test_cgroup_version_1_without_a_limit(self):
        self.membership("5:memory:/user.slice\n")
        self.limit("memory/user.slice", "memory.limit_in_bytes", "9223372036854771712")
        self.limit("memory", "memory.limit_in_bytes", "9223372036854771712")
        self.assertEqual(self.total(), 16384)


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        settings = bounded_run.Settings({}, read_total=lambda: 16384)
        self.assertEqual(settings.slot_mib, 2048)
        self.assertEqual(settings.total_mib, 16384)
        self.assertEqual(settings.reserve_mib, 4096)
        self.assertEqual(settings.poll_seconds, 2.0)
        self.assertEqual(settings.memory_wait_seconds, 300.0)
        self.assertFalse(settings.no_cap)
        self.assertIsNone(settings.free_mib)

    def test_a_set_free_memory(self):
        self.assertEqual(bounded_run.Settings({"BOUNDED_RUN_FREE_MIB": "3000"}, read_total=lambda: 1).free_mib, 3000)

    def test_overrides(self):
        settings = bounded_run.Settings({
            "BOUNDED_RUN_SLOT_MIB": "1024", "BOUNDED_RUN_TOTAL_MIB": "4096",
            "BOUNDED_RUN_RESERVE_MIB": "1024", "BOUNDED_RUN_POLL_SECONDS": "0.05",
            "BOUNDED_RUN_MEMORY_WAIT_SECONDS": "0", "BOUNDED_RUN_NO_CAP": "1",
        }, read_total=lambda: 1)
        self.assertEqual((settings.slot_mib, settings.total_mib, settings.reserve_mib), (1024, 4096, 1024))
        self.assertEqual((settings.poll_seconds, settings.memory_wait_seconds), (0.05, 0.0))
        self.assertTrue(settings.no_cap)

    def test_a_set_total_reads_nothing_of_the_machine(self):
        with mock.patch("builtins.open", side_effect=AssertionError("open")), \
                mock.patch.object(bounded_run.os, "sysconf", side_effect=AssertionError("sysconf")), \
                mock.patch.object(bounded_run.subprocess, "run", side_effect=AssertionError("run")):
            settings = bounded_run.Settings({"BOUNDED_RUN_TOTAL_MIB": "4096"})
        self.assertEqual(settings.total_mib, 4096)

    def test_rejects_an_interval_of_zero(self):
        for name in ("BOUNDED_RUN_POLL_SECONDS", "BOUNDED_RUN_SAMPLE_SECONDS"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(bounded_run.WrapperError, name + " must be more than zero"):
                    bounded_run.Settings({name: "0"}, read_total=lambda: 1)

    def test_rejects_a_value_that_is_not_a_number(self):
        with self.assertRaises(bounded_run.WrapperError):
            bounded_run.Settings({"BOUNDED_RUN_POLL_SECONDS": "fast"}, read_total=lambda: 1)

    def test_rejects_a_value_that_is_not_finite(self):
        for name in ("BOUNDED_RUN_SLOT_MIB", "BOUNDED_RUN_TOTAL_MIB", "BOUNDED_RUN_POLL_SECONDS"):
            for text in ("nan", "inf", "1e400"):
                with self.subTest(name=name, text=text):
                    with self.assertRaises(bounded_run.WrapperError):
                        bounded_run.Settings({name: text}, read_total=lambda: 16384)


class LockDirectoryTest(unittest.TestCase):
    def test_override_wins(self):
        environ = {"BOUNDED_RUN_LOCK_DIR": "/x/locks", "XDG_RUNTIME_DIR": "/run/user/7"}
        self.assertEqual(bounded_run.lock_directory(environ, 7), "/x/locks")

    def test_rejects_an_override_that_is_not_an_absolute_path(self):
        for value in ("locks", "./locks", "../x/locks"):
            with self.subTest(value=value):
                with self.assertRaises(bounded_run.WrapperError) as caught:
                    bounded_run.lock_directory({"BOUNDED_RUN_LOCK_DIR": value}, 7)
                self.assertIn("BOUNDED_RUN_LOCK_DIR", str(caught.exception))
                self.assertIn("'%s'" % value, str(caught.exception))

    def test_uses_the_runtime_directory(self):
        self.assertEqual(bounded_run.lock_directory({"XDG_RUNTIME_DIR": "/run/user/7"}, 7), "/run/user/7/bounded-run")

    def test_ignores_a_runtime_directory_that_is_not_an_absolute_path(self):
        self.assertEqual(bounded_run.lock_directory({"XDG_RUNTIME_DIR": "run"}, 999999999), "/tmp/bounded-run-999999999")

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

    def test_a_directory_that_cannot_be_closed_is_reported(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, "locks")
            os.mkdir(path, 0o755)
            error = PermissionError(errno.EPERM, "Operation not permitted")
            with mock.patch.object(bounded_run.os, "chmod", side_effect=error):
                with self.assertRaises(bounded_run.WrapperError) as caught:
                    bounded_run.ensure_lock_directory(path, os.getuid())
            self.assertIn(path, str(caught.exception))
            self.assertIn("Operation not permitted", str(caught.exception))

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


class ReserveTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.directory = self.base.name

    def test_takes_the_slots_that_it_needs(self):
        reservation = bounded_run.try_reserve(self.directory, 3, 2, [])
        self.addCleanup(reservation.release)
        self.assertEqual(len(reservation.descriptors), 2)

    def test_gives_nothing_when_too_few_slots_are_free(self):
        first = bounded_run.try_reserve(self.directory, 3, 2, [])
        self.addCleanup(first.release)
        self.assertIsNone(bounded_run.try_reserve(self.directory, 3, 2, []))

    def test_holds_no_slot_after_a_failed_try(self):
        first = bounded_run.try_reserve(self.directory, 3, 2, [])
        self.addCleanup(first.release)
        self.assertIsNone(bounded_run.try_reserve(self.directory, 3, 2, []))
        third = bounded_run.try_reserve(self.directory, 3, 1, [])
        self.assertIsNotNone(third)
        third.release()

    def test_release_frees_the_slots(self):
        first = bounded_run.try_reserve(self.directory, 2, 2, [])
        first.release()
        second = bounded_run.try_reserve(self.directory, 2, 2, [])
        self.assertIsNotNone(second)
        second.release()

    def test_an_exclusive_lock_blocks_the_same_name(self):
        first = bounded_run.try_reserve(self.directory, 4, 1, ["exclusive-abc-port.lock"])
        self.addCleanup(first.release)
        self.assertIsNone(bounded_run.try_reserve(self.directory, 4, 1, ["exclusive-abc-port.lock"]))

    def test_a_blocked_exclusive_lock_holds_no_slot(self):
        first = bounded_run.try_reserve(self.directory, 2, 1, ["exclusive-abc-port.lock"])
        self.addCleanup(first.release)
        self.assertIsNone(bounded_run.try_reserve(self.directory, 2, 1, ["exclusive-abc-port.lock"]))
        other = bounded_run.try_reserve(self.directory, 2, 1, [])
        self.assertIsNotNone(other)
        other.release()

    def test_a_different_name_does_not_block(self):
        first = bounded_run.try_reserve(self.directory, 4, 1, ["exclusive-abc-port.lock"])
        self.addCleanup(first.release)
        second = bounded_run.try_reserve(self.directory, 4, 1, ["exclusive-abc-tool.lock"])
        self.assertIsNotNone(second)
        second.release()

    def test_the_descriptors_are_not_inheritable(self):
        reservation = bounded_run.try_reserve(self.directory, 2, 2, ["exclusive-abc-port.lock"])
        self.addCleanup(reservation.release)
        for descriptor in reservation.descriptors:
            self.assertFalse(os.get_inheritable(descriptor))

    def test_reserve_tries_again_until_the_slots_are_free(self):
        first = bounded_run.try_reserve(self.directory, 1, 1, [])
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                first.release()

        second = bounded_run.reserve(self.directory, 1, 1, [], 0.2, sleep=sleep)
        self.addCleanup(second.release)
        self.assertEqual(len(sleeps), 2)
        for seconds in sleeps:
            self.assertGreaterEqual(seconds, 0.1)
            self.assertLess(seconds, 0.3)

    def test_a_lock_error_that_is_not_a_busy_lock_is_reported(self):
        with mock.patch.object(bounded_run.fcntl, "flock") as mock_flock:
            def flock_side_effect(fd, flags):
                if flags & bounded_run.fcntl.LOCK_EX and not (flags & bounded_run.fcntl.LOCK_NB):
                    return None
                raise OSError(errno.ENOLCK, "No locks available")

            mock_flock.side_effect = flock_side_effect
            with self.assertRaises(bounded_run.WrapperError) as cm:
                bounded_run.try_reserve(self.directory, 1, 1, [])
            self.assertIn("cannot lock", str(cm.exception))
            self.assertIn("No locks available", str(cm.exception))

    def test_a_lock_error_of_the_turn_file_is_reported(self):
        with mock.patch.object(bounded_run.fcntl, "flock", side_effect=OSError(errno.ENOLCK, "No locks available")):
            with self.assertRaises(bounded_run.WrapperError) as caught:
                bounded_run.try_reserve(self.directory, 1, 1, [])
        self.assertIn("cannot lock", str(caught.exception))
        self.assertIn("reserve.lock", str(caught.exception))
        self.assertIn("No locks available", str(caught.exception))

    def test_a_lock_error_leaves_no_slot_held(self):
        fd_to_path = {}
        real_os_open = os.open

        def tracked_open(path, *args, **kwargs):
            fd = real_os_open(path, *args, **kwargs)
            fd_to_path[fd] = path
            return fd

        flock_calls_per_file = {}
        real_flock = bounded_run.fcntl.flock

        def counting_flock(fd, flags):
            path = fd_to_path.get(fd, "<unknown>")
            if path not in flock_calls_per_file:
                flock_calls_per_file[path] = 0
            flock_calls_per_file[path] += 1

            if "reserve.lock" in path or "slot-000.lock" in path:
                return real_flock(fd, flags)

            if "slot-001.lock" in path:
                raise OSError(errno.ENOLCK, "No locks available")

            return real_flock(fd, flags)

        with mock.patch.object(os, "open", tracked_open):
            with mock.patch.object(bounded_run.fcntl, "flock", counting_flock):
                with self.assertRaises(bounded_run.WrapperError):
                    bounded_run.try_reserve(self.directory, 2, 2, [])

        # A slot that the failed call still held makes this call fail.
        second_try = bounded_run.try_reserve(self.directory, 2, 2, [])
        self.assertIsNotNone(second_try)
        self.addCleanup(second_try.release)
        self.assertEqual(len(second_try.descriptors), 2)

    def test_a_slot_file_that_cannot_be_opened_is_reported(self):
        os.mkdir(os.path.join(self.directory, "slot-000.lock"))
        with self.assertRaises(bounded_run.WrapperError) as caught:
            bounded_run.try_reserve(self.directory, 1, 1, [])
        self.assertIn("slot-000.lock", str(caught.exception))
        self.assertIn(os.strerror(errno.EISDIR), str(caught.exception))

    def test_a_turn_file_that_cannot_be_opened_is_reported(self):
        os.mkdir(os.path.join(self.directory, "reserve.lock"))
        with self.assertRaises(bounded_run.WrapperError) as caught:
            bounded_run.try_reserve(self.directory, 1, 1, [])
        self.assertIn("reserve.lock", str(caught.exception))
        self.assertIn(os.strerror(errno.EISDIR), str(caught.exception))

    def test_an_open_error_leaves_no_slot_held(self):
        blocked = os.path.join(self.directory, "slot-001.lock")
        os.mkdir(blocked)
        with self.assertRaises(bounded_run.WrapperError):
            bounded_run.try_reserve(self.directory, 2, 2, ["exclusive-abc-port.lock"])
        os.rmdir(blocked)
        second = bounded_run.try_reserve(self.directory, 2, 2, ["exclusive-abc-port.lock"])
        self.assertIsNotNone(second, "a slot or the exclusive lock is still held")
        second.release()

    def test_the_turn_lock_is_free_while_the_wrapper_waits(self):
        blocker = bounded_run.try_reserve(self.directory, 1, 1, [])
        self.addCleanup(blocker.release)

        turn_lock_acquired = []

        def sleep_and_check(seconds):
            turn_path = os.path.join(self.directory, "reserve.lock")
            turn_fd = os.open(turn_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                import fcntl
                fcntl.flock(turn_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                turn_lock_acquired.append(True)
            except OSError:
                turn_lock_acquired.append(False)
            finally:
                os.close(turn_fd)
            blocker.release()

        reservation = bounded_run.reserve(self.directory, 1, 1, [], 0.2, sleep=sleep_and_check)
        self.addCleanup(reservation.release)
        self.assertTrue(turn_lock_acquired[0], "turn lock should be free while reserve waits")

    def line_is_free(self):
        descriptor = os.open(os.path.join(self.directory, "line.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            bounded_run.fcntl.flock(descriptor, bounded_run.fcntl.LOCK_EX | bounded_run.fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
        finally:
            os.close(descriptor)

    def test_the_waiter_at_the_head_keeps_the_line_while_it_waits(self):
        blocker = bounded_run.try_reserve(self.directory, 1, 1, [])
        free_during_wait = []

        def sleep(seconds):
            free_during_wait.append(self.line_is_free())
            if len(free_during_wait) == 2:
                blocker.release()

        reservation = bounded_run.reserve(self.directory, 1, 1, [], 0.2, sleep=sleep)
        self.addCleanup(reservation.release)
        self.assertEqual(free_during_wait, [False, False])
        self.assertTrue(self.line_is_free(), "the line lock is still held after the slots were taken")

    def test_the_head_leaves_the_line_when_no_slot_comes_free_for_the_time_limit(self):
        blocker = bounded_run.try_reserve(self.directory, 2, 1, [])
        now = [0.0]
        free_during_wait = []

        def sleep(seconds):
            now[0] += 4.0
            free_during_wait.append(self.line_is_free())
            if len(free_during_wait) == 5:
                blocker.release()

        reservation = bounded_run.reserve(
            self.directory, 2, 2, [], 0.2, sleep=sleep, clock=lambda: now[0], line_seconds=10.0,
        )
        self.addCleanup(reservation.release)
        self.assertEqual(free_during_wait[:2], [False, False])
        self.assertIn(True, free_during_wait[2:4])

    def test_a_slot_that_comes_free_restarts_the_time_limit_of_the_head(self):
        first = bounded_run.try_reserve(self.directory, 3, 1, [])
        second = bounded_run.try_reserve(self.directory, 3, 1, [])
        now = [0.0]
        free_during_wait = []

        def sleep(seconds):
            now[0] += 4.0
            free_during_wait.append(self.line_is_free())
            if len(free_during_wait) == 2:
                first.release()
            if len(free_during_wait) == 4:
                second.release()

        reservation = bounded_run.reserve(
            self.directory, 3, 3, [], 0.2, sleep=sleep, clock=lambda: now[0], line_seconds=10.0,
        )
        self.addCleanup(reservation.release)
        self.assertEqual(free_during_wait, [False, False, False, False])

    def test_a_waiter_does_not_keep_the_line_while_its_exclusive_name_is_held(self):
        holder = bounded_run.try_reserve(self.directory, 2, 1, ["exclusive-abc-port.lock"])
        free_during_wait = []

        def sleep(seconds):
            free_during_wait.append(self.line_is_free())
            if len(free_during_wait) == 2:
                holder.release()

        reservation = bounded_run.reserve(self.directory, 2, 1, ["exclusive-abc-port.lock"], 0.2, sleep=sleep)
        self.addCleanup(reservation.release)
        self.assertEqual(free_during_wait, [True, True])


class LockFileTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.path = os.path.join(self.base.name, "slot-000.lock")

    def test_a_file_that_was_deleted_before_the_lock_is_not_the_lock(self):
        real_open = bounded_run._open_lock_file
        calls = []

        def open_then_delete(path):
            descriptor = real_open(path)
            calls.append(descriptor)
            if len(calls) == 1:
                os.unlink(path)
            return descriptor

        with mock.patch.object(bounded_run, "_open_lock_file", open_then_delete):
            descriptor = bounded_run._try_lock(self.path)
        self.addCleanup(os.close, descriptor)
        self.assertEqual(len(calls), 2)
        self.assertTrue(os.path.samestat(os.stat(self.path), os.fstat(descriptor)))

    def test_a_lock_makes_the_file_new_for_a_cleaner_of_old_files(self):
        Path(self.path).write_text("")
        os.utime(self.path, (1000, 1000))
        descriptor = bounded_run._try_lock(self.path)
        self.addCleanup(os.close, descriptor)
        self.assertGreater(os.stat(self.path).st_mtime, time.time() - 60)
        self.assertGreater(os.stat(self.path).st_atime, time.time() - 60)

    def test_the_turn_lock_is_not_a_file_that_was_deleted_before_the_lock(self):
        real_open = bounded_run._open_lock_file
        turn_path = os.path.join(self.base.name, "reserve.lock")
        opened = []

        def open_then_delete(path):
            descriptor = real_open(path)
            if path == turn_path:
                opened.append(descriptor)
                if len(opened) == 1:
                    os.unlink(path)
            return descriptor

        with mock.patch.object(bounded_run, "_open_lock_file", open_then_delete):
            reservation = bounded_run.try_reserve(self.base.name, 1, 1, [])
        self.addCleanup(reservation.release)
        self.assertEqual(len(opened), 2)


class ExclusiveNameTest(unittest.TestCase):
    def test_name_holds_the_repository_and_the_resource(self):
        self.assertEqual(bounded_run.exclusive_file_name("abc123", "port-8080"), "exclusive-abc123-port-8080.lock")

    def test_rejects_a_name_with_a_path(self):
        for name in ("../x", "a/b", "", "a b"):
            with self.subTest(name=name):
                with self.assertRaises(bounded_run.WrapperError):
                    bounded_run.exclusive_file_name("abc123", name)

    def test_worktrees_of_one_repository_have_the_same_id(self):
        with tempfile.TemporaryDirectory() as base:
            main = os.path.join(base, "main")
            other = os.path.join(base, "other")
            os.mkdir(main)
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
            subprocess.run(git + ["init", "--quiet", main], check=True)
            subprocess.run(git + ["-C", main, "commit", "--quiet", "--allow-empty", "-m", "first"], check=True)
            subprocess.run(git + ["-C", main, "worktree", "add", "--quiet", "--detach", other], check=True)
            self.assertEqual(bounded_run.repository_id(main), bounded_run.repository_id(other))

    def test_a_git_call_that_takes_too_long_gives_an_error(self):
        slow = subprocess.TimeoutExpired(["git"], 10)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(bounded_run.subprocess, "run", side_effect=slow):
            with self.assertRaisesRegex(bounded_run.WrapperError, "cannot find the repository of"):
                bounded_run.repository_id(directory)

    def test_a_git_fault_other_than_no_repository_gives_an_error(self):
        done = subprocess.CompletedProcess(["git"], 128, "", "fatal: detected dubious ownership in repository at '/x'\n")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(bounded_run.subprocess, "run", return_value=done):
            with self.assertRaisesRegex(bounded_run.WrapperError, "cannot find the repository of .*dubious ownership"):
                bounded_run.repository_id(directory)

    def test_git_answers_in_the_language_that_the_wrapper_reads(self):
        done = subprocess.CompletedProcess(["git"], 128, "", "fatal: not a git repository (or any of the parent directories): .git\n")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(bounded_run.subprocess, "run", return_value=done) as run:
            bounded_run.repository_id(directory)
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_a_machine_with_no_git_uses_the_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(bounded_run.subprocess, "run", side_effect=FileNotFoundError("git")):
                without = bounded_run.repository_id(directory)
            self.assertEqual(without, bounded_run.repository_id(directory))

    def test_two_directories_have_different_ids(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assertNotEqual(bounded_run.repository_id(first), bounded_run.repository_id(second))


class RunningCountTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.directory = self.base.name

    def hold(self, name):
        descriptor = bounded_run._try_lock(os.path.join(self.directory, name))
        self.addCleanup(os.close, descriptor)

    def test_counts_no_command_in_an_empty_directory(self):
        self.assertEqual(bounded_run.running_commands(self.directory), 0)

    def test_counts_each_run_file_that_a_process_holds(self):
        self.hold(bounded_run.run_file_name("bounded-run-1-000001"))
        self.hold(bounded_run.run_file_name("bounded-run-2-000002"))
        self.assertEqual(bounded_run.running_commands(self.directory), 2)

    def test_slot_files_are_not_running_commands(self):
        self.hold("slot-000.lock")
        self.assertEqual(bounded_run.running_commands(self.directory), 0)

    def test_a_run_file_that_no_process_holds_is_removed_and_not_counted(self):
        path = os.path.join(self.directory, bounded_run.run_file_name("bounded-run-3-000003"))
        open(path, "w").close()
        self.assertEqual(bounded_run.running_commands(self.directory), 0)
        self.assertFalse(os.path.exists(path))


class MemoryReadTest(unittest.TestCase):
    def test_reads_the_available_memory_of_meminfo(self):
        text = "MemTotal:       32000000 kB\nMemFree:         1000000 kB\nMemAvailable:    8388608 kB\n"
        self.assertEqual(bounded_run.parse_meminfo(text), 8192)

    def test_meminfo_without_the_line_gives_nothing(self):
        self.assertIsNone(bounded_run.parse_meminfo("MemTotal: 1 kB\n"))

    def test_reads_the_pages_of_vm_stat(self):
        text = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                               10000.\n"
            "Pages active:                            900000.\n"
            "Pages inactive:                           20000.\n"
            "Pages speculative:                         2000.\n"
            "Pages wired down:                        100000.\n"
        )
        self.assertEqual(bounded_run.parse_vm_stat(text), 32000 * 16384 // (1024 * 1024))

    def test_vm_stat_without_a_page_size_gives_nothing(self):
        self.assertIsNone(bounded_run.parse_vm_stat("Pages free: 10.\n"))


class CgroupFreeMemoryTest(unittest.TestCase):
    """Gives available_memory_mib a /proc with 16 GiB free and a cgroup filesystem in a temporary directory."""

    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.proc = os.path.join(self.base.name, "proc")
        self.cgroups = os.path.join(self.base.name, "cgroups")
        os.makedirs(os.path.join(self.proc, "self"))
        os.makedirs(self.cgroups)
        Path(self.proc, "meminfo").write_text("MemTotal: 33554432 kB\nMemAvailable: 16777216 kB\n")

    def membership(self, text):
        Path(self.proc, "self", "cgroup").write_text(text)

    def write(self, relative, name, value):
        directory = os.path.join(self.cgroups, relative)
        os.makedirs(directory, exist_ok=True)
        Path(directory, name).write_text(value + "\n")

    def available(self):
        return bounded_run.available_memory_mib(proc_root=self.proc, cgroup_root=self.cgroups)

    def test_a_cgroup_that_is_nearly_full_on_a_free_host(self):
        self.membership("0::/container\n")
        self.write("container", "memory.max", str(4096 * 1024 ** 2))
        self.write("container", "memory.current", str(4000 * 1024 ** 2))
        self.write("container", "memory.stat", "anon 1\ninactive_file %d\nactive_file 5\n" % (100 * 1024 ** 2))
        self.assertEqual(self.available(), 196)

    def test_a_cgroup_without_a_limit_gives_the_free_memory_of_the_host(self):
        self.membership("0::/container\n")
        self.write("container", "memory.max", "max")
        self.write("container", "memory.current", str(4000 * 1024 ** 2))
        self.write("container", "memory.stat", "inactive_file 0\n")
        self.assertEqual(self.available(), 16384)

    def test_a_cgroup_whose_use_cannot_be_read_gives_the_free_memory_of_the_host(self):
        cases = {
            "no files of use": {},
            "no memory.stat": {"memory.current": str(4000 * 1024 ** 2)},
            "no memory.current": {"memory.stat": "inactive_file 0\n"},
            "no inactive_file line": {"memory.current": str(4000 * 1024 ** 2), "memory.stat": "anon 1\n"},
            "not a number": {"memory.current": "many", "memory.stat": "inactive_file 0\n"},
        }
        for name, files in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.cgroups)
                self.membership("0::/container\n")
                self.write("container", "memory.max", str(4096 * 1024 ** 2))
                for file_name, text in files.items():
                    self.write("container", file_name, text)
                self.assertEqual(self.available(), 16384)

    def test_no_cgroup_files_gives_the_free_memory_of_the_host(self):
        self.assertEqual(self.available(), 16384)

    def test_a_parent_with_a_larger_limit_and_less_free_memory_decides(self):
        self.membership("0::/container/unit-1.scope\n")
        self.write("container/unit-1.scope", "memory.max", str(4096 * 1024 ** 2))
        self.write("container/unit-1.scope", "memory.current", str(1024 * 1024 ** 2))
        self.write("container/unit-1.scope", "memory.stat", "inactive_file 0\n")
        self.write("container", "memory.max", str(8192 * 1024 ** 2))
        self.write("container", "memory.current", str(8000 * 1024 ** 2))
        self.write("container", "memory.stat", "inactive_file 0\n")
        self.assertEqual(self.available(), 192)

    def test_levels_with_the_same_limit_give_the_smallest_free_memory(self):
        for full in ("container", "container/unit-1.scope"):
            with self.subTest(full=full):
                shutil.rmtree(self.cgroups)
                self.membership("0::/container/unit-1.scope\n")
                for level in ("container", "container/unit-1.scope"):
                    self.write(level, "memory.max", str(4096 * 1024 ** 2))
                    self.write(level, "memory.current", str((4000 if level == full else 1024) * 1024 ** 2))
                    self.write(level, "memory.stat", "inactive_file 0\n")
                self.assertEqual(self.available(), 96)

    def test_the_use_is_read_at_the_level_of_the_limit_in_a_parent(self):
        self.membership("0::/container/unit-1.scope\n")
        self.write("container/unit-1.scope", "memory.max", "max")
        self.write("container/unit-1.scope", "memory.current", str(100 * 1024 ** 2))
        self.write("container/unit-1.scope", "memory.stat", "inactive_file 0\n")
        self.write("container", "memory.max", str(4096 * 1024 ** 2))
        self.write("container", "memory.current", str(3072 * 1024 ** 2))
        self.write("container", "memory.stat", "inactive_file %d\n" % (512 * 1024 ** 2))
        self.assertEqual(self.available(), 1536)

    def test_cgroup_version_1(self):
        self.membership("12:cpu,cpuacct:/user.slice\n5:memory:/container\n0::/container\n")
        self.write("memory/container", "memory.limit_in_bytes", str(2048 * 1024 ** 2))
        self.write("memory/container", "memory.usage_in_bytes", str(1536 * 1024 ** 2))
        self.write("memory/container", "memory.stat", "cache 1\ninactive_file 7\ntotal_inactive_file %d\n" % (256 * 1024 ** 2))
        self.write("memory", "memory.limit_in_bytes", "9223372036854771712")
        self.assertEqual(self.available(), 768)

    def test_a_use_above_the_limit_gives_zero(self):
        self.membership("0::/container\n")
        self.write("container", "memory.max", str(1024 * 1024 ** 2))
        self.write("container", "memory.current", str(2048 * 1024 ** 2))
        self.write("container", "memory.stat", "inactive_file 0\n")
        self.assertEqual(self.available(), 0)

    def test_an_inactive_file_cache_larger_than_the_use_is_no_use(self):
        self.membership("0::/container\n")
        self.write("container", "memory.max", str(1024 * 1024 ** 2))
        self.write("container", "memory.current", str(100 * 1024 ** 2))
        self.write("container", "memory.stat", "inactive_file %d\n" % (200 * 1024 ** 2))
        self.assertEqual(self.available(), 1024)


class MemoryWaitTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        self.log = patcher.start()
        self.addCleanup(patcher.stop)

    def wait(self, values, limit, outstanding=None, headroom=0, oversleep=1):
        readings = list(values)
        sleeps = []
        now = [0.0]

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds * oversleep

        bounded_run.wait_for_memory(
            4096, limit, 5.0, headroom_mib=headroom, read_available=lambda: readings.pop(0),
            read_outstanding=lambda: outstanding, sleep=sleep, clock=lambda: now[0],
        )
        return sleeps

    def lines(self):
        return [call[0][0] for call in self.log.call_args_list]

    def test_starts_at_once_when_the_memory_is_free(self):
        self.assertEqual(self.wait([8000], 300), [])

    def test_waits_until_the_memory_is_free(self):
        self.assertEqual(self.wait([1000, 2000, 5000], 300), [5.0, 5.0])

    def test_does_not_start_after_the_time_limit_while_the_memory_is_not_free(self):
        self.assertEqual(self.wait([1000] * 7 + [5000], 10), [5.0] * 7)
        lines = self.lines()
        self.assertTrue(lines[-1].endswith("; starting"), lines)
        self.assertFalse(any(line.endswith("; starting") for line in lines[:-1]), lines)

    def test_a_limit_of_zero_does_not_start_while_the_memory_is_not_free(self):
        self.assertEqual(self.wait([1000, 1000, 5000], 0), [5.0, 5.0])

    def test_the_time_limit_is_the_time_between_two_lines_of_the_wait(self):
        self.wait([1000] * 7 + [5000], 10)
        waiting = [line for line in self.lines() if "waiting" in line]
        self.assertEqual(len(waiting), 4, waiting)
        self.assertIn("still waiting", waiting[1])

    def test_the_time_between_two_lines_is_real_time(self):
        self.wait([1000] * 3 + [5000], 100, oversleep=10)
        waiting = [line for line in self.lines() if "waiting" in line]
        self.assertEqual(len(waiting), 2, waiting)
        self.assertTrue(waiting[1].endswith("; still waiting after 100s"), waiting)

    def test_starts_when_the_memory_is_not_readable(self):
        self.assertEqual(self.wait([None], 300), [])
        self.assertEqual(self.lines(), ["cannot read the free memory; starting"])

    def test_each_reading_holds_the_lock_and_the_call_returns_with_it_held(self):
        events = []
        readings = [1000, 5000]

        def read():
            events.append("read")
            return readings.pop(0)

        bounded_run.wait_for_memory(
            4096, 300, 5.0, read_available=read, sleep=lambda seconds: events.append("sleep"),
            lock=lambda: events.append("lock"), unlock=lambda: events.append("unlock"),
        )
        self.assertEqual(events, ["lock", "read", "unlock", "sleep", "lock", "read"])

    def test_reads_the_unused_budgets_before_and_after_the_free_memory(self):
        events = []

        def read_available():
            events.append("free")
            return 8000

        def read_outstanding():
            events.append("unused")
            return 0

        bounded_run.wait_for_memory(
            4096, 300, 5.0, read_available=read_available, read_outstanding=read_outstanding, sleep=lambda seconds: None,
        )
        self.assertEqual(events, ["unused", "free", "unused"])

    def test_counts_the_larger_of_the_unused_budgets_read_before_and_after_the_free_memory(self):
        for first, second in ((1000, 3000), (3000, 1000)):
            with self.subTest(first=first, second=second):
                unused = [first, second, 0, 0]
                readings = [4000, 8000]
                sleeps = []
                bounded_run.wait_for_memory(
                    2048, 300, 5.0, read_available=lambda: readings.pop(0), read_outstanding=lambda: unused.pop(0),
                    sleep=sleeps.append,
                )
                self.assertEqual(sleeps, [5.0])

    def test_the_headroom_is_not_given_out(self):
        self.assertEqual(self.wait([5000, 5200], 300, headroom=1024), [5.0])

    def test_a_line_of_the_wait_names_each_part_of_the_count(self):
        self.wait([4000, 8000], 300, outstanding=1500, headroom=1024)
        self.assertEqual(
            self.lines()[0],
            "4000 MiB free, 1500 MiB of running budgets unused, 1024 MiB headroom, budget 4096 MiB; waiting",
        )

    def test_a_line_of_the_wait_says_when_the_unused_budgets_are_not_counted(self):
        self.wait([8000], 300, outstanding=None, headroom=1024)
        self.assertEqual(
            self.lines()[0],
            "8000 MiB free, unused running budgets not counted here, 1024 MiB headroom, budget 4096 MiB; starting",
        )


    def test_stops_when_the_memory_is_not_free_and_no_bounded_command_runs(self):
        with self.assertRaises(bounded_run.NoMemory) as raised:
            bounded_run.wait_for_memory(4096, 300, 5.0, read_available=lambda: 1000, read_running=lambda: 0,
                                        sleep=lambda seconds: self.fail("waits"))
        self.assertEqual(raised.exception.available, 1000)

    def test_waits_while_another_bounded_command_runs(self):
        readings = [1000, 5000]
        sleeps = []
        bounded_run.wait_for_memory(4096, 300, 5.0, read_available=lambda: readings.pop(0), read_running=lambda: 1,
                                    sleep=sleeps.append)
        self.assertEqual(sleeps, [5.0])

    def test_starts_when_the_memory_is_free_and_no_bounded_command_runs(self):
        bounded_run.wait_for_memory(4096, 300, 5.0, read_available=lambda: 8000, read_running=lambda: 0,
                                    sleep=lambda seconds: self.fail("waits"))

    def test_starts_when_the_memory_is_not_readable_and_no_bounded_command_runs(self):
        bounded_run.wait_for_memory(4096, 300, 5.0, read_available=lambda: None, read_running=lambda: 0,
                                    sleep=lambda seconds: self.fail("waits"))

    def test_stops_with_the_lock_released(self):
        events = []
        with self.assertRaises(bounded_run.NoMemory):
            bounded_run.wait_for_memory(4096, 300, 5.0, read_available=lambda: 1000, read_running=lambda: 0,
                                        lock=lambda: events.append("lock"), unlock=lambda: events.append("unlock"))
        self.assertEqual(events, ["lock", "unlock"])

    def test_starts_when_the_last_bounded_command_ends_between_the_reads(self):
        readings = [1000, 8000]
        bounded_run.wait_for_memory(4096, 300, 5.0, read_available=lambda: readings.pop(0), read_running=lambda: 0,
                                    sleep=lambda seconds: self.fail("waits"))
        self.assertEqual(readings, [])

    def test_a_stop_gives_the_free_memory_read_after_the_count(self):
        readings = [1000, 2000]
        with self.assertRaises(bounded_run.NoMemory) as raised:
            bounded_run.wait_for_memory(4096, 300, 5.0, read_available=lambda: readings.pop(0), read_running=lambda: 0,
                                        sleep=lambda seconds: self.fail("waits"))
        self.assertEqual(raised.exception.available, 2000)


class HeadroomTest(unittest.TestCase):
    def test_a_tenth_of_the_memory(self):
        self.assertEqual(bounded_run.headroom_mib(27703, 2048, 20480), 2770)

    def test_never_less_than_the_minimum(self):
        self.assertEqual(bounded_run.headroom_mib(4096, 1024, 4096), 1024)

    def test_no_headroom_for_a_budget_of_the_whole_queue(self):
        self.assertEqual(bounded_run.headroom_mib(27703, 20480, 20480), 0)

    def test_the_budget_and_the_headroom_never_need_more_than_the_queue(self):
        self.assertEqual(bounded_run.headroom_mib(27703, 19000, 20480), 1480)


class FitTest(unittest.TestCase):
    # 28000 MiB machine: reserve 7000, queue 20480, headroom 2800 below the queue.
    def fit(self, available, outstanding=None):
        return bounded_run.largest_fit_mib(available, outstanding, 28000, 20480)

    def test_the_budget_and_its_headroom_fit_in_the_free_memory(self):
        self.assertEqual(self.fit(14000), 11008)

    def test_each_value_starts_and_the_next_step_does_not(self):
        for available in (1500, 4000, 14000, 21000):
            with self.subTest(available=available):
                fits = self.fit(available)
                headroom = bounded_run.headroom_mib(28000, fits, 20480)
                self.assertTrue(fits == 0 or bounded_run.memory_fits(fits, available, None, headroom))
                larger = fits + bounded_run.BUDGET_STEP_MIB
                self.assertFalse(larger <= 20480 and bounded_run.memory_fits(larger, available, None, bounded_run.headroom_mib(28000, larger, 20480)))

    def test_nothing_fits_below_the_headroom(self):
        self.assertEqual(self.fit(2000), 0)

    def test_the_whole_queue_needs_no_headroom(self):
        self.assertEqual(self.fit(20480), 20480)

    def test_the_unused_budgets_are_not_free(self):
        self.assertEqual(self.fit(14000, outstanding=4000), self.fit(10000))


class UnusedBudgetTest(unittest.TestCase):
    """Gives unused_budget_mib a slice of the cgroup filesystem in a temporary directory."""

    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.slice = os.path.join(self.base.name, "app.slice")
        os.makedirs(self.slice)

    def scope(self, name, limit, current):
        directory = os.path.join(self.slice, name)
        os.makedirs(directory)
        if limit is not None:
            Path(directory, "memory.max").write_text(limit + "\n")
        if current is not None:
            Path(directory, "memory.current").write_text(current + "\n")

    def unused(self, skip=()):
        return bounded_run.unused_budget_mib(self.slice, skip)

    def test_adds_the_unused_part_of_each_budget(self):
        self.scope("bounded-run-10-aaaaaa.scope", str(6144 * 1024 ** 2), str(1024 * 1024 ** 2))
        self.scope("bounded-run-11-bbbbbb.scope", str(2048 * 1024 ** 2), str(512 * 1024 ** 2))
        self.assertEqual(self.unused(), 5120 + 1536)

    def test_a_scope_above_its_budget_adds_nothing(self):
        self.scope("bounded-run-10-aaaaaa.scope", str(1024 * 1024 ** 2), str(2048 * 1024 ** 2))
        self.assertEqual(self.unused(), 0)

    def test_skips_the_probe_scopes(self):
        self.scope("bounded-run-10-aaaaaa-probe.scope", str(6144 * 1024 ** 2), "0")
        self.assertEqual(self.unused(), 0)

    def test_skips_the_scopes_that_the_caller_names(self):
        self.scope("bounded-run-10-aaaaaa.scope", str(6144 * 1024 ** 2), "0")
        self.scope("bounded-run-11-bbbbbb.scope", str(2048 * 1024 ** 2), "0")
        self.assertEqual(self.unused(skip=["bounded-run-10-aaaaaa.scope"]), 2048)

    def test_skips_a_scope_with_no_budget(self):
        self.scope("bounded-run-10-aaaaaa.scope", "max", "0")
        self.assertEqual(self.unused(), 0)

    def test_skips_units_of_other_programs(self):
        self.scope("editor-1.scope", str(6144 * 1024 ** 2), "0")
        self.scope("bounded-run-10-aaaaaa.service", str(6144 * 1024 ** 2), "0")
        self.assertEqual(self.unused(), 0)

    def test_skips_a_scope_that_ends_while_it_is_read(self):
        self.scope("bounded-run-10-aaaaaa.scope", str(6144 * 1024 ** 2), None)
        self.scope("bounded-run-11-bbbbbb.scope", None, None)
        self.assertEqual(self.unused(), 0)

    def test_no_slice_gives_nothing(self):
        self.assertEqual(bounded_run.unused_budget_mib(os.path.join(self.base.name, "gone"), ()), 0)

    def test_the_slice_is_the_parent_of_the_probe_scope(self):
        self.assertEqual(
            bounded_run.scope_parent_directory("0::/user.slice/user@1000.service/app.slice/unit-1-probe.scope\n", "/cg"),
            "/cg/user.slice/user@1000.service/app.slice",
        )

    def test_the_scope_of_this_process(self):
        with tempfile.TemporaryDirectory() as proc:
            os.mkdir(os.path.join(proc, "self"))
            Path(proc, "self", "cgroup").write_text("0::/user.slice/app.slice/bounded-run-2-111111.scope\n")
            self.assertEqual(bounded_run.own_scope_name(proc_root=proc), "bounded-run-2-111111.scope")

    def test_no_scope_of_this_process_without_its_cgroup(self):
        with tempfile.TemporaryDirectory() as proc:
            self.assertIsNone(bounded_run.own_scope_name(proc_root=proc))

    def test_no_slice_without_a_cgroup_version_2_line(self):
        self.assertIsNone(bounded_run.scope_parent_directory("", "/cg"))
        self.assertIsNone(bounded_run.scope_parent_directory("4:memory:/user.slice/unit-1-probe.scope\n", "/cg"))

    def test_the_wait_for_a_scope_ends_after_its_time_limit_of_real_time(self):
        now = [0.0]

        def slow_sleep(seconds):
            now[0] += 10 * seconds

        self.assertFalse(bounded_run.wait_for_scope(self.slice, "bounded-run-1-000000", 1.0, sleep=slow_sleep, clock=lambda: now[0]))
        self.assertLessEqual(now[0], 1.2)

    def test_a_running_command_that_uses_little_of_a_large_budget_holds_back_the_next(self):
        self.scope("bounded-run-10-aaaaaa.scope", str(6144 * 1024 ** 2), str(1024 * 1024 ** 2))
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            shutil.rmtree(os.path.join(self.slice, "bounded-run-10-aaaaaa.scope"))

        with mock.patch.object(bounded_run, "log"):
            bounded_run.wait_for_memory(
                4096, 300, 5.0, headroom_mib=1024, read_available=lambda: 8000,
                read_outstanding=lambda: self.unused(), sleep=sleep,
            )
        self.assertEqual(sleeps, [5.0])


class HeldCommandTest(unittest.TestCase):
    """Gives held_commands a slice of the cgroup filesystem and a process filesystem in temporary directories."""

    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.slice = os.path.join(self.base.name, "app.slice")
        self.proc = os.path.join(self.base.name, "proc")
        os.makedirs(self.slice)
        os.makedirs(self.proc)
        Path(self.proc, "uptime").write_text("170.52 300.00\n")

    def scope(self, name, limit=str(4096 * 1024 ** 2), current=str(1024 * 1024 ** 2), pids=("100",), cpu_max="400000 100000"):
        directory = os.path.join(self.slice, name)
        os.makedirs(directory)
        if cpu_max is not None:
            Path(directory, "cpu.max").write_text(cpu_max + "\n")
        Path(directory, "memory.max").write_text(limit + "\n")
        Path(directory, "memory.current").write_text(current + "\n")
        Path(directory, "cgroup.procs").write_text("".join(pid + "\n" for pid in pids))

    def process(self, pid, arguments, start_ticks=5000, cwd="/work/project"):
        directory = os.path.join(self.proc, str(pid))
        os.makedirs(directory)
        Path(directory, "stat").write_text("%d (python 3) S %s %d 0 0\n" % (pid, " ".join(["0"] * 18), start_ticks))
        Path(directory, "cmdline").write_bytes(b"".join(argument.encode() + b"\0" for argument in arguments))
        os.symlink(cwd, os.path.join(directory, "cwd"))

    def held(self, skip=()):
        return bounded_run.held_commands(self.slice, skip, proc_root=self.proc, ticks=100, machine=16)

    def inside(self, *command):
        return ["python3", "/x/bounded_run.py", "--inside-cap", "/l/peak-u", "bounded-run-100-aaaaaa", "--"] + list(command)

    def test_names_the_budget_the_use_the_age_the_directory_and_the_command(self):
        self.scope("bounded-run-100-aaaaaa.scope", pids=("105", "100"))
        self.process(100, self.inside("sh", "-c", "make test"))
        self.process(105, ["make", "test"], start_ticks=9000, cwd="/elsewhere")
        self.assertEqual(self.held(), [
            "unit=bounded-run-100-aaaaaa budget=4096M used=1024M cpus=4 age=120s dir=/work/project command=sh -c make test",
        ])

    def test_a_scope_with_no_budget_gives_a_dash(self):
        self.scope("bounded-run-100-aaaaaa.scope", limit="max")
        self.process(100, self.inside("tool"))
        self.assertIn(" budget=- ", self.held()[0])

    def test_skips_probe_scopes_named_scopes_and_other_units(self):
        self.scope("bounded-run-100-aaaaaa-probe.scope")
        self.scope("bounded-run-101-bbbbbb.scope")
        self.scope("editor-1.scope")
        self.scope("bounded-run-102-cccccc.scope")
        self.process(100, self.inside("tool"))
        held = self.held(skip=["bounded-run-101-bbbbbb.scope"])
        self.assertEqual([line.split()[0] for line in held], ["unit=bounded-run-102-cccccc"])

    def test_a_process_that_cannot_be_read_gives_dashes(self):
        self.scope("bounded-run-100-aaaaaa.scope", pids=("999",))
        self.assertEqual(self.held(), ["unit=bounded-run-100-aaaaaa budget=4096M used=1024M cpus=4 age=- dir=- command=-"])

    def test_a_scope_with_no_process_gives_dashes(self):
        self.scope("bounded-run-100-aaaaaa.scope", pids=())
        self.assertTrue(self.held()[0].endswith(" age=- dir=- command=-"), self.held())

    def test_a_scope_that_ends_while_it_is_read_is_skipped(self):
        self.scope("bounded-run-100-aaaaaa.scope")
        self.process(100, self.inside("tool"))
        listing = os.listdir(self.slice) + ["bounded-run-200-dddddd.scope"]
        with mock.patch.object(bounded_run.os, "listdir", return_value=listing):
            held = self.held()
        self.assertEqual([line.split()[0] for line in held], ["unit=bounded-run-100-aaaaaa"])

    def test_a_long_command_is_cut_and_stays_on_one_line(self):
        self.scope("bounded-run-100-aaaaaa.scope")
        self.process(100, self.inside("sh", "-c", "first\nsecond " + "x" * 300))
        command = self.held()[0].split(" command=", 1)[1]
        self.assertEqual(len(command), bounded_run.HELD_COMMAND_CHARACTERS)
        self.assertTrue(command.startswith("sh -c first second x"), command)

    def test_a_directory_with_a_line_break_stays_on_one_line(self):
        self.scope("bounded-run-100-aaaaaa.scope")
        self.process(100, self.inside("tool"), cwd="/work/two\nlines")
        self.assertEqual(self.held(), ["unit=bounded-run-100-aaaaaa budget=4096M used=1024M cpus=4 age=120s dir=/work/two lines command=tool"])

    def test_control_characters_of_the_command_and_the_directory_become_question_marks(self):
        self.scope("bounded-run-100-aaaaaa.scope")
        self.process(100, self.inside("printf", "\x1b[2Jdone"), cwd="/work/\x1b[31mred")
        self.assertEqual(self.held(), ["unit=bounded-run-100-aaaaaa budget=4096M used=1024M cpus=4 age=120s dir=/work/?[31mred command=printf ?[2Jdone"])

    def test_a_command_without_the_prefix_of_the_wrapper_is_given_whole(self):
        self.scope("bounded-run-100-aaaaaa.scope")
        self.process(100, ["sleep", "60"])
        self.assertTrue(self.held()[0].endswith(" command=sleep 60"), self.held())

    def test_no_slice_gives_no_line(self):
        self.assertEqual(bounded_run.held_commands(os.path.join(self.base.name, "gone"), (), proc_root=self.proc), [])

    def test_a_part_of_a_processor_counts_as_a_whole_one(self):
        self.scope("bounded-run-100-aaaaaa.scope", cpu_max="150000 100000")
        self.process(100, self.inside("tool"))
        self.assertIn(" cpus=2 ", self.held()[0])

    def test_a_scope_with_no_quota_holds_every_processor(self):
        self.scope("bounded-run-100-aaaaaa.scope", cpu_max="max 100000")
        self.process(100, self.inside("tool"))
        self.assertIn(" cpus=16 ", self.held()[0])

    def test_a_quota_that_cannot_be_read_gives_a_dash(self):
        self.scope("bounded-run-100-aaaaaa.scope", cpu_max=None)
        self.process(100, self.inside("tool"))
        self.assertIn(" cpus=- ", self.held()[0])


class CpusInUseTest(unittest.TestCase):
    """Gives cpus_in_use a slice of the cgroup filesystem in a temporary directory, on a machine of 16 processors."""

    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.slice = os.path.join(self.base.name, "app.slice")
        os.makedirs(self.slice)

    def scope(self, name, cpu_max):
        directory = os.path.join(self.slice, name)
        os.makedirs(directory)
        if cpu_max is not None:
            Path(directory, "cpu.max").write_text(cpu_max + "\n")

    def used(self, skip=()):
        return bounded_run.cpus_in_use(self.slice, skip, machine=16)

    def test_adds_the_quotas_of_the_bounded_scopes_each_rounded_up(self):
        self.scope("bounded-run-1-aaaaaa.scope", "800000 100000")
        self.scope("bounded-run-2-bbbbbb.scope", "150000 100000")
        self.assertEqual(self.used(), 10)

    def test_a_scope_with_no_quota_counts_every_processor(self):
        self.scope("bounded-run-1-aaaaaa.scope", "max 100000")
        self.scope("bounded-run-2-bbbbbb.scope", "200000 100000")
        self.assertEqual(self.used(), 18)

    def test_skips_probe_scopes_named_scopes_and_other_units(self):
        self.scope("bounded-run-1-aaaaaa-probe.scope", "800000 100000")
        self.scope("bounded-run-2-bbbbbb.scope", "800000 100000")
        self.scope("editor-1.scope", "800000 100000")
        self.scope("bounded-run-3-cccccc.scope", "300000 100000")
        self.assertEqual(self.used(skip=["bounded-run-2-bbbbbb.scope"]), 3)

    def test_no_running_scope_uses_no_processor(self):
        self.assertEqual(self.used(), 0)

    def test_a_scope_that_ends_while_it_is_read_is_skipped(self):
        self.scope("bounded-run-1-aaaaaa.scope", "200000 100000")
        listing = os.listdir(self.slice) + ["bounded-run-9-dddddd.scope"]
        with mock.patch.object(bounded_run.os, "listdir", return_value=listing):
            self.assertEqual(self.used(), 2)

    def test_a_running_scope_whose_quota_cannot_be_read_makes_the_sum_unknown(self):
        self.scope("bounded-run-1-aaaaaa.scope", "200000 100000")
        self.scope("bounded-run-2-bbbbbb.scope", None)
        self.assertIsNone(self.used())


class CapTest(unittest.TestCase):
    def test_prefix_holds_the_limits(self):
        self.assertEqual(bounded_run.cap_prefix(6144, 4, "unit-1"), [
            "systemd-run", "--user", "--scope", "--quiet", "--collect", "--unit", "unit-1",
            "-p", "MemoryMax=6144M", "-p", "MemorySwapMax=0", "-p", "OOMPolicy=continue",
            "-p", "CPUQuota=400%", "--",
        ])

    def test_prefix_without_cpus_has_no_quota(self):
        self.assertNotIn("CPUQuota", " ".join(bounded_run.cap_prefix(6144, None, "unit-1")))

    def test_prefix_without_the_oom_policy(self):
        prefix = bounded_run.cap_prefix(6144, None, "unit-1", oom_policy=False)
        self.assertNotIn("OOMPolicy", " ".join(prefix))
        self.assertIn("MemoryMax=6144M", prefix)

    def choose(self, answers):
        probes = []

        def probe(prefix):
            probes.append(list(prefix))
            return answers[len(probes) - 1]

        return bounded_run.choose_cap_prefix(1024, 2, "unit-1", probe), probes

    def test_uses_the_oom_policy_when_the_first_probe_passes(self):
        choice, probes = self.choose(["0::/app.slice/unit-1-probe.scope\n"])
        self.assertEqual(choice, (bounded_run.cap_prefix(1024, 2, "unit-1"), "0::/app.slice/unit-1-probe.scope\n"))
        self.assertEqual(len(probes), 1)
        self.assertIn("OOMPolicy=continue", probes[0])
        self.assertNotIn("unit-1", probes[0])

    def test_uses_the_prefix_without_the_oom_policy_when_only_the_second_probe_passes(self):
        choice, probes = self.choose([None, ""])
        self.assertEqual(choice, (bounded_run.cap_prefix(1024, 2, "unit-1", oom_policy=False), ""))
        self.assertEqual(len(probes), 2)
        self.assertNotIn("OOMPolicy=continue", probes[1])

    def test_no_cap_when_both_probes_fail(self):
        choice, probes = self.choose([None, None])
        self.assertIsNone(choice)
        self.assertEqual(len(probes), 2)

    def test_no_command_runs_on_a_different_system(self):
        calls = []

        def run(command, **keywords):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)

        def probe(prefix):
            return bounded_run.probe_cap(prefix, platform="darwin", which=lambda name: "/usr/bin/systemd-run", run=run)

        self.assertIsNone(bounded_run.choose_cap_prefix(1024, 2, "unit-1", probe))
        self.assertEqual(calls, [])

    def probe(self, platform, tool, code=0, error=None, output=None):
        calls = []

        def run(command, **keywords):
            calls.append(command)
            if error is not None:
                raise error
            return subprocess.CompletedProcess(command, code, stdout=output)

        found = bounded_run.probe_cap(
            bounded_run.cap_prefix(1024, 2, "unit-1"), platform=platform, which=lambda name: tool, run=run,
        )
        return found, calls

    def test_the_probe_gives_the_cgroup_of_its_scope(self):
        found, calls = self.probe("linux", "/usr/bin/systemd-run", output="0::/app.slice/unit-1.scope\n")
        self.assertEqual(found, "0::/app.slice/unit-1.scope\n")
        self.assertEqual(calls[0][-2:], ["cat", "/proc/self/cgroup"])
        self.assertIn("CPUQuota=200%", calls[0])

    def test_a_probe_with_no_output_is_usable(self):
        self.assertEqual(self.probe("linux", "/usr/bin/systemd-run")[0], "")

    def test_not_usable_when_the_probe_fails(self):
        self.assertIsNone(self.probe("linux", "/usr/bin/systemd-run", code=1)[0])

    def test_not_usable_when_the_probe_does_not_return(self):
        error = subprocess.TimeoutExpired("systemd-run", 15)
        self.assertIsNone(self.probe("linux", "/usr/bin/systemd-run", error=error)[0])

    def test_not_usable_without_the_tool(self):
        found, calls = self.probe("linux", None)
        self.assertIsNone(found)
        self.assertEqual(calls, [])

    def test_not_usable_on_a_different_system(self):
        found, calls = self.probe("darwin", "/usr/bin/systemd-run")
        self.assertIsNone(found)
        self.assertEqual(calls, [])


class MeasurementTest(unittest.TestCase):
    def test_finds_the_cgroup_of_the_unit(self):
        with tempfile.TemporaryDirectory() as proc:
            os.mkdir(os.path.join(proc, "42"))
            Path(proc, "42", "cgroup").write_text("0::/user.slice/user-1.slice/app.slice/unit-1.scope\n")
            self.assertEqual(
                bounded_run.cgroup_directory(42, "unit-1", proc_root=proc, cgroup_root="/cg"),
                "/cg/user.slice/user-1.slice/app.slice/unit-1.scope",
            )

    def test_ignores_the_cgroup_before_the_scope_exists(self):
        with tempfile.TemporaryDirectory() as proc:
            os.mkdir(os.path.join(proc, "42"))
            Path(proc, "42", "cgroup").write_text("0::/user.slice/user-1.slice/session-2.scope\n")
            self.assertIsNone(bounded_run.cgroup_directory(42, "unit-1", proc_root=proc))

    def test_a_process_that_is_gone_has_no_cgroup(self):
        with tempfile.TemporaryDirectory() as proc:
            self.assertIsNone(bounded_run.cgroup_directory(42, "unit-1", proc_root=proc))

    def test_reads_the_peak_of_the_cgroup(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "memory.peak").write_text("%d\n" % (300 * 1024 * 1024))
            Path(directory, "memory.current").write_text("%d\n" % (100 * 1024 * 1024))
            self.assertEqual(bounded_run.cgroup_peak_mib(directory), 300)

    def test_reads_the_current_value_when_the_peak_file_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "memory.current").write_text("%d\n" % (100 * 1024 * 1024))
            self.assertEqual(bounded_run.cgroup_peak_mib(directory), 100)

    def test_reads_only_the_files_that_the_caller_names(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "memory.current").write_text("%d\n" % (100 * 1024 * 1024))
            self.assertIsNone(bounded_run.cgroup_peak_mib(directory, names=("memory.peak",)))

    def test_a_cgroup_without_files_gives_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(bounded_run.cgroup_peak_mib(directory))

    def test_adds_the_memory_of_the_process_group(self):
        text = "  100  2048\n  100  1024\n  200  9999\n    1   512\n"
        self.assertEqual(bounded_run.parse_group_rss_mib(text, 100), 3)

    def test_a_group_with_no_process_gives_nothing(self):
        self.assertIsNone(bounded_run.parse_group_rss_mib("  200  9999\n", 100))

    def test_reads_the_memory_of_a_real_process_group(self):
        self.assertGreater(bounded_run.group_rss_mib(os.getpgrp()), 0)

    def test_the_peak_of_the_system_has_a_different_unit_on_each_system(self):
        self.assertEqual(bounded_run.rusage_peak_mib(2048 * 1024, platform="linux"), 2048)
        self.assertEqual(bounded_run.rusage_peak_mib(2048 * 1024 * 1024, platform="darwin"), 2048)

    def test_the_suggested_budget_has_a_margin(self):
        self.assertEqual(bounded_run.suggested_budget_mib(4000, approximate=False), 5120)
        self.assertEqual(bounded_run.suggested_budget_mib(4000, approximate=True), 6144)

    def test_a_peak_that_is_mostly_file_cache_gets_a_budget_near_its_held_memory_or_the_cache_floor(self):
        # 300 MiB held gives 512 MiB with the margin of a sample; a quarter of the 8000 MiB peak gives 2560 MiB.
        self.assertEqual(bounded_run.suggested_budget_mib(8000, approximate=False, held_mib=300), 2560)

    def test_held_memory_that_grows_gets_a_budget_that_covers_it(self):
        self.assertEqual(bounded_run.suggested_budget_mib(8000, approximate=False, held_mib=5000), 7680)

    def test_the_budget_from_held_memory_is_never_more_than_the_budget_from_the_peak(self):
        self.assertEqual(bounded_run.suggested_budget_mib(4000, approximate=False, held_mib=3900), 5120)

    def test_no_held_memory_gives_the_budget_from_the_peak(self):
        self.assertEqual(bounded_run.suggested_budget_mib(4000, approximate=False, held_mib=None), 5120)

    def write_stat(self, directory, **fields):
        Path(directory, "memory.stat").write_text("".join("%s %d\n" % (name, value * 1024 * 1024) for name, value in fields.items()))

    def test_held_memory_is_what_the_kernel_cannot_take_back_at_once(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_stat(directory, anon=100, file=5000, kernel=20, kernel_stack=1, slab_unreclaimable=2, shmem=30,
                            file_dirty=40, file_writeback=50, inactive_file=4000, active_file=900, slab_reclaimable=10)
            self.assertEqual(bounded_run.cgroup_held_mib(directory), 230)

    def test_held_memory_without_the_kernel_line_adds_the_parts_of_kernel_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_stat(directory, anon=100, kernel_stack=1, slab_unreclaimable=2, sock=3, percpu=4, pagetables=50,
                            sec_pagetables=6, vmalloc=7, slab_reclaimable=60)
            self.assertEqual(bounded_run.cgroup_held_mib(directory), 173)

    def test_held_memory_counts_only_the_lines_that_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_stat(directory, anon=100, file=5000, inactive_file=5000)
            self.assertEqual(bounded_run.cgroup_held_mib(directory), 100)

    def test_dirty_file_pages_are_held(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_stat(directory, anon=10, file=3000, file_dirty=1500, file_writeback=500)
            self.assertEqual(bounded_run.cgroup_held_mib(directory), 2010)

    def test_a_cgroup_without_a_readable_stat_file_has_no_held_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(bounded_run.cgroup_held_mib(directory))
            Path(directory, "memory.stat").write_text("file 100\ninactive_file 100\n")
            self.assertIsNone(bounded_run.cgroup_held_mib(directory))

    def test_the_tracker_keeps_the_largest_held_sample(self):
        samples = [100, None, 900, 300]
        tracker = bounded_run.PeakTracker(lambda: 1000, 0.01, read_held=lambda: samples.pop(0) if samples else 300)
        tracker.start()
        deadline = time.time() + 5
        while samples and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(tracker.finish(), 1000)
        self.assertEqual(tracker.held, 900)

    def test_a_tracker_without_a_held_reader_has_no_held_memory(self):
        tracker = bounded_run.PeakTracker(lambda: 1000, 0.01)
        tracker.start()
        tracker.finish()
        self.assertIsNone(tracker.held)

    def test_the_tracker_keeps_the_largest_sample(self):
        samples = [100, None, 900, 300]
        tracker = bounded_run.PeakTracker(lambda: samples.pop(0) if samples else 300, 0.01)
        tracker.start()
        deadline = time.time() + 5
        while samples and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(tracker.finish(), 900)

    def test_the_tracker_survives_a_reader_that_fails(self):
        calls = []

        def read():
            calls.append(1)
            raise OSError("gone")

        tracker = bounded_run.PeakTracker(read, 0.01)
        tracker.start()
        deadline = time.time() + 5
        while not calls and time.time() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(len(calls), 1, "the reader never ran")
        self.assertIsNone(tracker.finish())


class ArgumentTest(unittest.TestCase):
    def test_reads_all_options(self):
        options = bounded_run.parse_arguments(
            ["--memory", "6G", "--cpus", "4", "--exclusive", "a", "--exclusive", "b", "--measure", "--", "tool", "--memory", "x"]
        )
        self.assertEqual(
            (options.memory, options.cpus, options.exclusive, options.measure, options.command),
            ("6G", 4, ["a", "b"], True, ["tool", "--memory", "x"]),
        )

    def test_rejects_bad_arguments(self):
        for arguments in (["tool"], ["--memory", "6G", "--"], ["--fast", "--", "tool"], ["--memory", "--", "tool"], ["--cpus", "0", "--", "tool"], ["--cpus", "two", "--", "tool"]):
            with self.subTest(arguments=arguments):
                with self.assertRaises(bounded_run.WrapperError):
                    bounded_run.parse_arguments(arguments)

    def test_a_repeated_exclusive_name_is_kept_one_time(self):
        options = bounded_run.parse_arguments(
            ["--exclusive", "port", "--exclusive", "cache", "--exclusive", "port", "--", "tool"]
        )
        self.assertEqual(options.exclusive, ["port", "cache"])

    def test_reads_the_rows_largest_first_and_each_one_time(self):
        options = bounded_run.parse_arguments(["--measure-rows", "4,16,8,4", "--label", "unit-tests", "--", "tool"])
        self.assertEqual((options.rows, options.label, options.measure), ([16, 8, 4], "unit-tests", True))

    def test_rejects_bad_rows_and_labels(self):
        for arguments in (
            ["--measure-rows", "0,2", "--", "tool"],
            ["--measure-rows", "two", "--", "tool"],
            ["--measure-rows", "", "--", "tool"],
            ["--measure-rows", "4,,2", "--", "tool"],
            ["--measure-rows", "\u00b2", "--", "tool"],
            ["--measure-rows", "9" * 5000, "--", "tool"],
            ["--measure-rows", "1000000", "--", "tool"],
            ["--measure-rows", "4,2", "--cpus", "2", "--", "tool"],
            ["--measure", "--label", "unit tests", "--", "tool"],
            ["--measure", "--label", "-", "--", "tool"],
            ["--measure", "--label", "lint\n", "--", "tool"],
            ["--label", "lint", "--", "tool"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(bounded_run.WrapperError):
                    bounded_run.parse_arguments(arguments)


class InsideCapTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.proc = os.path.join(self.base.name, "proc")
        self.cgroups = os.path.join(self.base.name, "cgroups")
        self.peak_file = os.path.join(self.base.name, "peak")
        os.makedirs(os.path.join(self.proc, str(os.getpid())))
        Path(self.proc, str(os.getpid()), "cgroup").write_text("0::/user.slice/unit-1.scope\n")
        self.cgroup = os.path.join(self.cgroups, "user.slice", "unit-1.scope")
        os.makedirs(self.cgroup)

    def inside(self, command, unit="unit-1"):
        return bounded_run.inside_cap(self.peak_file, unit, command, proc_root=self.proc, cgroup_root=self.cgroups)

    def test_writes_the_peak_after_the_command_stops(self):
        Path(self.cgroup, "memory.peak").write_text("%d\n" % (300 * 1024 * 1024))
        self.assertEqual(self.inside([sys.executable, "-c", "import sys; sys.exit(6)"]), 6)
        self.assertEqual(bounded_run.read_peak_file(self.peak_file), 300)
        self.assertFalse(os.path.exists(self.peak_file))

    def signal_at_start(self, signals):
        real = subprocess.Popen

        def start_then_signal(*args, **kwargs):
            for signum in signals:
                os.kill(os.getpid(), signum)
            return real(*args, **kwargs)

        return mock.patch.object(bounded_run.subprocess, "Popen", start_then_signal)

    def test_a_stop_signal_before_the_command_runs_stops_the_command(self):
        started = time.monotonic()
        with self.signal_at_start([signal.SIGQUIT]):
            code = self.inside([sys.executable, "-c", "import time; time.sleep(20)"])
        self.assertEqual(code, 128 + signal.SIGQUIT)
        self.assertLess(time.monotonic() - started, 10)

    def test_two_stop_signals_before_the_command_runs_kill_the_command(self):
        started = time.monotonic()
        with self.signal_at_start([signal.SIGTERM, signal.SIGTERM]):
            code = self.inside([sys.executable, "-c", "import time; time.sleep(20)"])
        self.assertEqual(code, 128 + signal.SIGKILL)
        self.assertLess(time.monotonic() - started, 10)

    def test_writes_nothing_without_the_peak_file_of_the_kernel(self):
        Path(self.cgroup, "memory.current").write_text("%d\n" % (100 * 1024 * 1024))
        self.assertEqual(self.inside([sys.executable, "-c", "pass"]), 0)
        self.assertIsNone(bounded_run.read_peak_file(self.peak_file))

    def test_writes_nothing_outside_the_cgroup_of_the_unit(self):
        Path(self.cgroup, "memory.peak").write_text("%d\n" % (300 * 1024 * 1024))
        self.assertEqual(self.inside([sys.executable, "-c", "pass"], unit="unit-2"), 0)
        self.assertIsNone(bounded_run.read_peak_file(self.peak_file))

    def test_a_command_that_a_signal_stopped_gives_128_plus_the_signal(self):
        script = "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
        self.assertEqual(self.inside([sys.executable, "-c", script]), 137)

    def test_a_command_that_does_not_exist_gives_125(self):
        self.assertEqual(self.inside(["/nonexistent/tool-for-the-test"]), 125)

    def test_puts_the_signal_handlers_back(self):
        before = signal.getsignal(signal.SIGTERM)
        self.inside([sys.executable, "-c", "pass"])
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_a_stop_signal_while_the_peak_is_read_does_not_end_the_process(self):
        # A signal with its default action ends the process that runs the test, so a child process runs inside_cap.
        script = (
            "import os, signal, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import bounded_run\n"
            "proc, cgroups, peak_file = sys.argv[2:5]\n"
            "os.makedirs(os.path.join(proc, str(os.getpid())))\n"
            "with open(os.path.join(proc, str(os.getpid()), 'cgroup'), 'w') as handle:\n"
            "    handle.write('0::/user.slice/unit-1.scope\\n')\n"
            "def read_peak(directory, names=()):\n"
            "    os.kill(os.getpid(), signal.SIGTERM)\n"
            "    return 300\n"
            "bounded_run.cgroup_peak_mib = read_peak\n"
            "sys.exit(bounded_run.inside_cap(peak_file, 'unit-1', [sys.executable, '-c', 'import sys; sys.exit(6)'], proc_root=proc, cgroup_root=cgroups))\n"
        )
        child_proc = os.path.join(self.base.name, "child-proc")
        done = subprocess.run(
            [sys.executable, "-c", script, str(SCRIPTS), child_proc, self.cgroups, self.peak_file],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(bounded_run.read_peak_file(self.peak_file), 300)

    def test_a_peak_file_with_other_text_gives_nothing(self):
        Path(self.peak_file).write_text("not a number\n")
        self.assertIsNone(bounded_run.read_peak_file(self.peak_file))


class RunCommandTest(unittest.TestCase):
    def test_an_error_after_the_start_stops_the_command(self):
        pids = []

        def cleanup():
            for pid in pids:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass

        self.addCleanup(cleanup)

        def on_start(pid):
            pids.append(pid)
            raise RuntimeError("boom")

        command = [sys.executable, "-c", "import time; time.sleep(300)", "run-command-test-marker-8f2c1"]
        with self.assertRaises(RuntimeError):
            bounded_run.run_command(command, dict(os.environ), on_start=on_start)
        self.assertEqual(len(pids), 1)
        deadline = time.time() + 10
        alive = True
        while alive and time.time() < deadline:
            try:
                os.kill(pids[0], 0)
                time.sleep(0.05)
            except ProcessLookupError:
                alive = False
        self.assertFalse(alive, "the command still runs")


class SignalAtStartTest(unittest.TestCase):
    def test_two_stop_signals_before_the_command_runs_end_a_command_that_ignores_the_first(self):
        real = subprocess.Popen

        base = tempfile.TemporaryDirectory()
        self.addCleanup(base.cleanup)
        ready = os.path.join(base.name, "ready")

        def start_then_signal(*args, **kwargs):
            process = real(*args, **kwargs)
            limit = time.monotonic() + 30
            while not os.path.exists(ready) and time.monotonic() < limit:
                time.sleep(0.02)
            os.kill(os.getpid(), signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGTERM)
            return process

        script = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(%r, 'w').close(); time.sleep(20)" % ready
        started = time.monotonic()
        with mock.patch.object(bounded_run.subprocess, "Popen", start_then_signal):
            code, _ = bounded_run.run_command([sys.executable, "-c", script], os.environ)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertLess(time.monotonic() - started, 10)


class LeftProcessTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        self.log = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_process_that_the_command_leaves_running_gives_a_warning(self):
        groups = []

        def stop():
            for group in groups:
                try:
                    os.killpg(group, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        self.addCleanup(stop)
        code, _ = bounded_run.run_command(["sh", "-c", "sleep 300 >/dev/null 2>&1 &"], os.environ, on_start=groups.append)
        self.assertEqual(code, 0)
        self.log.assert_called_once_with("WARNING: the command left a process that still runs; the queue does not count its memory")

    def test_a_command_that_leaves_no_process_gives_no_warning(self):
        code, _ = bounded_run.run_command(["sh", "-c", "sleep 0.1 & wait"], os.environ)
        self.assertEqual(code, 0)
        self.log.assert_not_called()


class ParentDeathSignalTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        self.log = patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_on_a_different_system(self):
        self.assertIsNone(bounded_run.parent_death_signal(platform="darwin"))

    def test_nothing_without_ctypes(self):
        with mock.patch.object(bounded_run, "ctypes", None):
            self.assertIsNone(bounded_run.parent_death_signal(platform="linux"))
        self.log.assert_not_called()

    def test_nothing_without_prctl(self):
        for library in (mock.Mock(side_effect=OSError("no library")), mock.Mock(return_value=object())):
            with self.subTest(library=library):
                with mock.patch.object(bounded_run, "ctypes", mock.Mock(CDLL=library)):
                    self.assertIsNone(bounded_run.parent_death_signal(platform="linux"))
        self.log.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith("linux"), "only Linux has a parent-death signal")
    def test_a_child_whose_parent_is_already_gone_exits(self):
        with mock.patch.object(bounded_run.os, "getpid", return_value=1):
            set_signal = bounded_run.parent_death_signal()
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], preexec_fn=set_signal)

        def stop():
            if process.poll() is None:
                process.kill()
                process.wait()

        self.addCleanup(stop)
        self.assertEqual(process.wait(timeout=60), bounded_run.EXIT_WRAPPER)

    def test_a_call_that_the_kernel_refuses_gives_a_warning_and_the_child_runs(self):
        library = mock.Mock(return_value=mock.Mock(prctl=mock.Mock(return_value=-1)))
        with mock.patch.object(bounded_run, "ctypes", mock.Mock(CDLL=library)):
            set_signal = bounded_run.parent_death_signal(platform="linux")
        process = subprocess.Popen([sys.executable, "-c", "pass"], preexec_fn=set_signal, stderr=subprocess.PIPE, text=True)
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        self.assertIn("bounded-run: WARNING: cannot set the parent-death signal; the command lives on after a hard kill of the wrapper", errors)

    @unittest.skipUnless(sys.platform.startswith("linux"), "only Linux has a parent-death signal")
    def test_a_child_of_this_process_runs(self):
        process = subprocess.Popen([sys.executable, "-c", "pass"], preexec_fn=bounded_run.parent_death_signal(), stderr=subprocess.PIPE, text=True)
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, errors), (0, ""))

    @unittest.skipUnless(sys.platform.startswith("linux"), "only Linux has a parent-death signal")
    def test_a_child_of_this_process_runs_with_no_pipe(self):
        process = subprocess.Popen([sys.executable, "-c", "pass"], preexec_fn=bounded_run.parent_death_signal())
        self.assertEqual(process.wait(timeout=60), 0)


class BoundedCleanupTest(unittest.TestCase):
    """Calls bounded() in this process, with run_command and probe_cap replaced by stubs.

    No real command, no real cgroup, and no real subprocess run outside the stubs.
    """

    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.directory = os.path.join(self.base.name, "locks")
        os.makedirs(self.directory, 0o700, exist_ok=True)
        self.environ = dict(os.environ)
        self.environ.pop("BOUNDED_RUN_ACTIVE", None)
        self.environ.pop("BOUNDED_RUN_NO_CAP", None)
        self.environ.update({
            "BOUNDED_RUN_LOCK_DIR": self.directory,
            "BOUNDED_RUN_TOTAL_MIB": "4096",
            "BOUNDED_RUN_RESERVE_MIB": "0",
            "BOUNDED_RUN_SLOT_MIB": "2048",
            "BOUNDED_RUN_POLL_SECONDS": "0.05",
            "BOUNDED_RUN_MEMORY_WAIT_SECONDS": "0",
            "BOUNDED_RUN_SAMPLE_SECONDS": "0.1",
            "BOUNDED_RUN_FREE_MIB": "1048576",
        })

    def test_the_peak_file_is_removed_when_the_run_fails_after_the_start(self):
        def fake_run_command(command, environ, on_start=None):
            index = command.index("--inside-cap")
            with open(command[index + 1], "w") as handle:
                handle.write("123\n")
            raise RuntimeError("boom")

        options = bounded_run.Options()
        options.memory = "2G"
        options.command = [sys.executable, "-c", "pass"]

        with mock.patch.object(bounded_run, "probe_cap", return_value=""), \
                mock.patch.object(bounded_run, "run_command", fake_run_command):
            with self.assertRaises(RuntimeError):
                bounded_run.bounded(options, self.environ)

        names = os.listdir(self.directory)
        self.assertEqual([name for name in names if name.startswith("peak-")], [])

        reservation = bounded_run.try_reserve(self.directory, 2, 2, [])
        self.assertIsNotNone(reservation, "the slots are still held")
        reservation.release()

    def test_a_budget_larger_than_the_queue_caps_and_waits_at_the_memory_of_the_queue(self):
        commands = []
        waits = []

        def fake_run_command(command, environ, on_start=None):
            commands.append(list(command))
            return 0, 0

        options = bounded_run.Options()
        options.memory = "64G"
        options.command = [sys.executable, "-c", "pass"]

        with mock.patch.object(bounded_run, "probe_cap", return_value=""), \
                mock.patch.object(bounded_run, "wait_for_memory", side_effect=lambda budget, *rest, **keywords: waits.append(budget)), \
                mock.patch.object(bounded_run, "run_command", fake_run_command):
            self.assertEqual(bounded_run.bounded(options, self.environ), 0)

        self.assertEqual(waits, [4096])
        self.assertIn("MemoryMax=4096M", commands[0])

    def capped_command(self, cpus):
        commands = []

        def fake_run_command(command, environ, on_start=None):
            commands.append(list(command))
            return 0, 0

        options = bounded_run.Options()
        options.memory = "1G"
        options.cpus = cpus
        options.command = [sys.executable, "-c", "pass"]
        with mock.patch.object(bounded_run, "probe_cap", return_value=""), \
                mock.patch.object(bounded_run, "machine_cpus", return_value=16), \
                mock.patch.object(bounded_run, "run_command", fake_run_command):
            self.assertEqual(bounded_run.bounded(options, self.environ), 0)
        return commands[0]

    def test_the_cap_of_a_run_without_cpus_holds_half_the_processors(self):
        self.assertIn("CPUQuota=800%", self.capped_command(None))

    def test_the_cap_of_a_run_with_cpus_holds_them(self):
        self.assertIn("CPUQuota=300%", self.capped_command(3))

    def wait_arguments(self, probe_output, environ=None):
        waits = []
        options = bounded_run.Options()
        options.memory = "1G"
        options.command = [sys.executable, "-c", "pass"]
        if environ is None:
            environ = dict(self.environ)
            del environ["BOUNDED_RUN_FREE_MIB"]
        with mock.patch.object(bounded_run, "probe_cap", return_value=probe_output), \
                mock.patch.object(bounded_run, "own_scope_name", return_value="bounded-run-2-111111.scope"), \
                mock.patch.object(bounded_run, "wait_for_memory", side_effect=lambda *arguments, **keywords: waits.append(keywords)), \
                mock.patch.object(bounded_run, "run_command", return_value=(0, 0)):
            self.assertEqual(bounded_run.bounded(options, environ), 0)
        return waits[0]

    def test_the_wait_keeps_a_headroom_of_the_memory_of_the_machine(self):
        self.assertEqual(self.wait_arguments(None)["headroom_mib"], bounded_run.headroom_mib(4096, 1024, 4096))

    def run_with_free_memory(self, memory, total, free):
        options = bounded_run.Options()
        options.memory = memory
        options.command = [sys.executable, "-c", "pass"]
        environ = dict(self.environ, BOUNDED_RUN_TOTAL_MIB=str(total), BOUNDED_RUN_RESERVE_MIB="", BOUNDED_RUN_FREE_MIB=str(free))

        real_wait = bounded_run.wait_for_memory

        def sleep(seconds):
            raise AssertionError("the command waits")

        def wait(*arguments, **keywords):
            return real_wait(*arguments, sleep=sleep, **keywords)

        with mock.patch.object(bounded_run, "probe_cap", return_value=None), \
                mock.patch.object(bounded_run, "wait_for_memory", wait), \
                mock.patch.object(bounded_run, "run_command", return_value=(0, 0)):
            return bounded_run.bounded(options, environ)

    def test_a_budget_of_the_whole_queue_starts_when_the_memory_of_the_queue_is_free(self):
        queue = bounded_run.queue_mib(27703, 2048, bounded_run.default_reserve_mib(27703))
        self.assertEqual(self.run_with_free_memory("%dM" % queue, 27703, queue), 0)

    def test_a_small_budget_waits_for_its_headroom_while_another_command_runs(self):
        descriptor = bounded_run._try_lock(os.path.join(self.directory, bounded_run.run_file_name("bounded-run-9-000009")))
        self.addCleanup(os.close, descriptor)
        with self.assertRaisesRegex(AssertionError, "the command waits"):
            self.run_with_free_memory("2G", 27703, 2048 + bounded_run.headroom_mib(27703, 2048, 20480) - 1)

    def test_a_small_budget_stops_without_its_headroom_when_no_command_runs(self):
        self.assertEqual(self.run_with_free_memory("2G", 27703, 2048 + bounded_run.headroom_mib(27703, 2048, 20480) - 1),
                         bounded_run.EXIT_NO_MEMORY)

    def test_a_small_budget_starts_with_its_headroom_free(self):
        self.assertEqual(self.run_with_free_memory("2G", 27703, 2048 + bounded_run.headroom_mib(27703, 2048, 20480)), 0)

    def test_a_set_free_memory_replaces_the_free_memory_and_the_unused_budgets(self):
        output = "0::/user.slice/app.slice/bounded-run-1-000000-probe.scope\n"
        keywords = self.wait_arguments(output, dict(self.environ, BOUNDED_RUN_FREE_MIB="3000"))
        with mock.patch.object(bounded_run, "unused_budget_mib", side_effect=AssertionError("unused")), \
                mock.patch.object(bounded_run, "available_memory_mib", side_effect=AssertionError("available")):
            self.assertEqual(keywords["read_available"](), 3000)
            self.assertIsNone(keywords["read_outstanding"]())

    def test_the_wait_counts_the_unused_budgets_beside_the_scope_of_the_probe(self):
        calls = []

        def unused(parent, skip):
            calls.append((parent, list(skip)))
            return 777

        output = "0::/user.slice/app.slice/bounded-run-1-000000-probe.scope\n"
        keywords = self.wait_arguments(output)
        with mock.patch.object(bounded_run, "unused_budget_mib", unused):
            self.assertEqual(keywords["read_outstanding"](), 777)
        parent, skip = calls[0]
        self.assertEqual(parent, "/sys/fs/cgroup/user.slice/app.slice")
        self.assertIn("bounded-run-2-111111.scope", skip)
        self.assertTrue(any(re.match(r"^bounded-run-%d-[0-9a-f]{6}\.scope$" % os.getpid(), name) for name in skip), skip)

    def run_with_scopes(self, appears):
        """Runs bounded() with a capped command whose scope appears in a temporary slice in two steps, or never when appears is false.

        The scope appears first with no memory limit, then with its limit. Returns whether the memory lock was free before the
        scope, before its limit, and when the command started.
        """
        scopes = os.path.join(self.base.name, "slice")
        os.makedirs(scopes)
        lock_path = os.path.join(self.directory, "memory.lock")
        free = {}

        def lock_is_free():
            descriptor = bounded_run._try_lock(lock_path)
            if descriptor is None:
                return False
            os.close(descriptor)
            return True

        def fake_run_command(command, environ, on_start=None):
            scope = os.path.join(scopes, command[command.index("--inside-cap") + 2] + ".scope")

            def appear():
                time.sleep(0.2)
                free["before the scope"] = lock_is_free()
                if appears:
                    os.mkdir(scope)
                    Path(scope, "memory.max").write_text("max\n")
                time.sleep(0.2)
                free["before the limit"] = lock_is_free()
                if appears:
                    Path(scope, "memory.current").write_text("0\n")
                    Path(scope, "memory.max").write_text("%d\n" % (1024 * 1024 ** 2))

            thread = threading.Thread(target=appear)
            thread.start()
            on_start(os.getpid())
            thread.join()
            free["at the start"] = lock_is_free()
            return 0, 0

        options = bounded_run.Options()
        options.memory = "1G"
        options.command = [sys.executable, "-c", "pass"]
        with mock.patch.object(bounded_run, "probe_cap", return_value="0::/slice/bounded-run-1-000000-probe.scope\n"), \
                mock.patch.object(bounded_run, "scope_parent_directory", return_value=scopes), \
                mock.patch.object(bounded_run, "SCOPE_WAIT_SECONDS", 1.0), \
                mock.patch.object(bounded_run, "run_command", fake_run_command):
            self.assertEqual(bounded_run.bounded(options, self.environ), 0)
        return free

    def test_the_next_memory_check_waits_until_the_scope_of_the_command_counts(self):
        free = self.run_with_scopes(appears=True)
        self.assertEqual(free, {"before the scope": False, "before the limit": False, "at the start": True})

    def test_a_scope_that_never_appears_frees_the_memory_check_after_a_time_limit(self):
        started = time.monotonic()
        free = self.run_with_scopes(appears=False)
        self.assertEqual(free, {"before the scope": False, "before the limit": False, "at the start": True})
        self.assertLess(time.monotonic() - started, 5)

    def test_the_wait_counts_no_unused_budget_without_a_cap(self):
        self.assertIsNone(self.wait_arguments(None)["read_outstanding"]())

    def test_the_wait_counts_no_unused_budget_without_a_cgroup_version_2(self):
        self.assertIsNone(self.wait_arguments("")["read_outstanding"]())


    def test_the_command_holds_a_run_file_while_it_runs_and_removes_it_after(self):
        seen = []

        def fake_run_command(command, environ, on_start=None):
            on_start(os.getpid())
            seen.append(bounded_run.running_commands(self.directory))
            return 0, 0

        options = bounded_run.Options()
        options.memory = "1G"
        options.command = [sys.executable, "-c", "pass"]
        with mock.patch.object(bounded_run, "probe_cap", return_value=None), \
                mock.patch.object(bounded_run, "run_command", fake_run_command):
            self.assertEqual(bounded_run.bounded(options, self.environ), 0)
        self.assertEqual(seen, [1])
        self.assertEqual([name for name in os.listdir(self.directory) if name.startswith("run-")], [])

    def test_a_row_that_stops_for_memory_ends_the_rows(self):
        calls = []

        def once(row, environ):
            calls.append(row.cpus)
            raise bounded_run.NoMemory(0, None)

        options = bounded_run.parse_arguments(["--measure-rows", "8,4", "--", "true"])
        with mock.patch.object(bounded_run, "bounded_once", once):
            self.assertEqual(bounded_run.bounded(options, self.environ), bounded_run.EXIT_NO_MEMORY)
        self.assertEqual(calls, [8])

    def test_a_row_that_stops_for_memory_after_a_failed_row_exits_75(self):
        def once(row, environ):
            if row.cpus == 8:
                return 1, 100
            raise bounded_run.NoMemory(0, None)

        options = bounded_run.parse_arguments(["--measure-rows", "8,4", "--", "true"])
        with mock.patch.object(bounded_run, "bounded_once", once):
            self.assertEqual(bounded_run.bounded(options, self.environ), bounded_run.EXIT_NO_MEMORY)

    def test_a_row_whose_command_exits_75_by_itself_does_not_end_the_rows(self):
        answers = iter([(bounded_run.EXIT_NO_MEMORY, 100), (0, 50)])
        calls = []

        def once(row, environ):
            calls.append(row.cpus)
            return next(answers)

        options = bounded_run.parse_arguments(["--measure-rows", "8,4", "--", "true"])
        with mock.patch.object(bounded_run, "bounded_once", once):
            self.assertEqual(bounded_run.bounded(options, self.environ), bounded_run.EXIT_NO_MEMORY)
        self.assertEqual(calls, [8, 4])

    def test_the_wait_counts_a_scope_of_an_older_wrapper_as_a_running_command(self):
        scopes = os.path.join(self.base.name, "slice")
        os.makedirs(os.path.join(scopes, "bounded-run-7-abcdef.scope"))
        os.makedirs(os.path.join(scopes, "bounded-run-2-111111.scope"))
        output = "0::/slice/bounded-run-1-000000-probe.scope\n"
        with mock.patch.object(bounded_run, "scope_parent_directory", return_value=scopes):
            keywords = self.wait_arguments(output)
        self.assertGreaterEqual(keywords["read_running"](), 1)
        os.rmdir(os.path.join(scopes, "bounded-run-7-abcdef.scope"))
        self.assertEqual(keywords["read_running"](), 0)


class MeasuredRowTest(unittest.TestCase):
    """Calls bounded() in this process, with run_command replaced by a stub and no hard cap.

    The stub gives each run the exit code and the ru_maxrss of the next answer, and keeps the
    budget and the processors that the wrapper gave to the command.
    """

    def setUp(self):
        self.lines = []
        patcher = mock.patch.object(bounded_run, "log", side_effect=self.lines.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.environ = dict(os.environ)
        self.environ.pop("BOUNDED_RUN_ACTIVE", None)
        self.environ.update({
            "BOUNDED_RUN_LOCK_DIR": os.path.join(self.base.name, "locks"),
            "BOUNDED_RUN_TOTAL_MIB": "8192",
            "BOUNDED_RUN_RESERVE_MIB": "0",
            "BOUNDED_RUN_SLOT_MIB": "2048",
            "BOUNDED_RUN_POLL_SECONDS": "0.05",
            "BOUNDED_RUN_MEMORY_WAIT_SECONDS": "0",
            "BOUNDED_RUN_SAMPLE_SECONDS": "0.1",
            "BOUNDED_RUN_NO_CAP": "1",
            "BOUNDED_RUN_FREE_MIB": "1048576",
        })
        self.runs = []

    def run_bounded(self, arguments, answers):
        remaining = list(answers)

        def fake_run_command(command, environ, on_start=None):
            self.runs.append((int(environ["BOUNDED_RUN_CPUS"]), int(environ["BOUNDED_RUN_MEMORY_MIB"])))
            code, peak_mib = remaining.pop(0)
            return code, peak_mib * 1024

        options = bounded_run.parse_arguments(arguments + ["--", sys.executable, "-c", "pass"])
        with mock.patch.object(bounded_run, "run_command", fake_run_command), \
                mock.patch.object(bounded_run, "rusage_peak_mib", side_effect=lambda maxrss: maxrss // 1024):
            return bounded_run.bounded(options, self.environ)

    def row_lines(self):
        return [line for line in self.lines if line.startswith("row ")]

    def test_a_measurement_prints_one_row_line(self):
        self.assertEqual(self.run_bounded(["--measure", "--cpus", "4", "--label", "unit-tests"], [(0, 1000)]), 0)
        self.assertEqual(self.row_lines(), ["row label=unit-tests cpus=4 budget=1536M peak=1000M held=- exact=no exit=0"])

    def test_a_run_without_cpus_gets_half_the_processors_rounded_down_and_at_least_one(self):
        for machine, expected in ((16, 8), (7, 3), (1, 1)):
            self.runs = []
            with mock.patch.object(bounded_run, "machine_cpus", return_value=machine):
                self.run_bounded(["--memory", "1G"], [(0, 100)])
            self.assertEqual(self.runs, [(expected, 1024)], machine)

    def test_the_processor_headroom_is_a_tenth_of_the_machine_rounded_up(self):
        for machine, expected in ((16, 2), (10, 1), (8, 1), (32, 4), (64, 7), (1, 1)):
            self.assertEqual(bounded_run.cpu_headroom(machine), expected, machine)

    def test_a_run_with_cpus_gets_them_on_any_machine(self):
        with mock.patch.object(bounded_run, "machine_cpus", return_value=16):
            self.run_bounded(["--memory", "1G", "--cpus", "12"], [(0, 100)])
        self.assertEqual(self.runs, [(12, 1024)])

    def test_a_row_line_marks_the_options_that_were_not_given(self):
        self.run_bounded(["--measure"], [(3, 100)])
        self.assertEqual(self.row_lines(), ["row label=- cpus=- budget=256M peak=100M held=- exact=no exit=3"])

    def run_capped(self, arguments, peak_mib, stat):
        """Runs bounded() as if under the hard cap, with a cgroup of fake files whose memory.stat holds stat in MiB."""
        cgroup = os.path.join(self.base.name, "cgroup")
        os.makedirs(cgroup, exist_ok=True)
        Path(cgroup, "memory.peak").write_text("%d\n" % (peak_mib * 1024 * 1024))
        Path(cgroup, "memory.stat").write_text("".join("%s %d\n" % (name, value * 1024 * 1024) for name, value in stat.items()))
        environ = dict(self.environ)
        del environ["BOUNDED_RUN_NO_CAP"]

        def fake_run_command(command, environ, on_start=None):
            on_start(os.getpid())
            return 0, 0

        options = bounded_run.parse_arguments(arguments + ["--", sys.executable, "-c", "pass"])
        with mock.patch.object(bounded_run, "run_command", fake_run_command), \
                mock.patch.object(bounded_run, "choose_cap_prefix", return_value=(["true"], "")), \
                mock.patch.object(bounded_run, "cgroup_directory", return_value=cgroup), \
                mock.patch.object(bounded_run, "read_peak_file", return_value=peak_mib):
            return bounded_run.bounded(options, environ)

    def test_a_capped_command_whose_peak_is_mostly_file_cache_gets_a_budget_from_its_held_memory(self):
        self.assertEqual(self.run_capped(["--measure", "--memory", "8G"], 8000, {"anon": 300, "file": 7600, "inactive_file": 7000}), 0)
        self.assertEqual(self.row_lines(), ["row label=- cpus=- budget=2560M peak=8000M held=300M exact=yes exit=0"])
        self.assertIn("budget 8192 MiB, peak 8000 MiB (cgroup), held 300 MiB (sampled), exit 0", self.lines)

    def test_a_capped_command_whose_held_memory_is_large_gets_a_budget_that_covers_it(self):
        self.run_capped(["--measure", "--memory", "8G"], 8000, {"anon": 4000, "file_dirty": 1000, "file": 3500})
        self.assertEqual(self.row_lines(), ["row label=- cpus=- budget=7680M peak=8000M held=5000M exact=yes exit=0"])

    def test_a_capped_command_with_no_held_memory_in_its_stat_file_gets_the_budget_from_its_peak(self):
        self.run_capped(["--measure", "--memory", "8G"], 8000, {})
        self.assertEqual(self.row_lines()[0], "row label=- cpus=- budget=10240M peak=8000M held=- exact=yes exit=0")

    def test_a_run_that_does_not_measure_prints_no_row_line(self):
        self.run_bounded(["--memory", "2G"], [(0, 100)])
        self.assertEqual(self.row_lines(), [])

    def test_rows_run_largest_first_and_each_smaller_row_gets_the_budget_of_the_row_before_it(self):
        code = self.run_bounded(["--measure-rows", "2,8,4", "--label", "build"], [(0, 1000), (0, 500), (0, 200)])
        self.assertEqual(code, 0)
        # The first row has no budget yet and no cap, so it holds the whole queue of 8192 MiB.
        self.assertEqual(self.runs, [(8, 8192), (4, 1536), (2, 768)])
        self.assertEqual(self.row_lines(), [
            "row label=build cpus=8 budget=1536M peak=1000M held=- exact=no exit=0",
            "row label=build cpus=4 budget=768M peak=500M held=- exact=no exit=0",
            "row label=build cpus=2 budget=512M peak=200M held=- exact=no exit=0",
        ])

    def test_the_largest_row_runs_with_the_given_memory(self):
        self.run_bounded(["--measure-rows", "8,4", "--memory", "4G"], [(0, 1000), (0, 500)])
        self.assertEqual(self.runs, [(8, 4096), (4, 1536)])

    def test_the_row_after_a_failed_row_gets_the_budget_of_the_failed_row(self):
        code = self.run_bounded(["--measure-rows", "8,4,2"], [(1, 300), (0, 1000), (2, 100)])
        self.assertEqual(code, 1)
        self.assertEqual(self.runs, [(8, 8192), (4, 8192), (2, 1536)])
        self.assertEqual([line.split()[-1] for line in self.row_lines()], ["exit=1", "exit=0", "exit=2"])

    def test_a_row_that_a_stop_signal_ended_ends_the_rows(self):
        code = self.run_bounded(["--measure-rows", "8,4,2"], [(0, 1000), (130, 100), (0, 100)])
        self.assertEqual(code, 130)
        self.assertEqual(self.runs, [(8, 8192), (4, 1536)])
        self.assertEqual(len(self.row_lines()), 2)

    def test_a_stop_signal_after_a_failed_row_keeps_the_first_exit_code(self):
        code = self.run_bounded(["--measure-rows", "8,4,2"], [(1, 1000), (130, 100), (0, 100)])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.runs), 2)

    def test_a_stop_signal_while_a_later_row_waits_keeps_the_first_exit_code(self):
        for failure, expected in ((1, 1), (0, 128 + signal.SIGTERM)):
            with self.subTest(failure=failure):
                real_once = bounded_run.bounded_once
                calls = []

                def once(options, environ):
                    calls.append(options.cpus)
                    if len(calls) == 2:
                        os.kill(os.getpid(), signal.SIGTERM)
                        time.sleep(5)
                    return real_once(options, environ)

                before = signal.getsignal(signal.SIGTERM)
                self.runs = []
                with mock.patch.object(bounded_run, "bounded_once", once):
                    code = self.run_bounded(["--measure-rows", "8,4,2"], [(failure, 1000)])
                self.assertEqual(code, expected)
                self.assertEqual(calls, [8, 4])
                self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_a_stop_signal_outside_a_row_ends_main_with_its_code(self):
        options = ["--measure-rows", "8,4", "--", sys.executable, "-c", "pass"]
        with mock.patch.object(bounded_run, "bounded", side_effect=bounded_run._Stopped(int(signal.SIGTERM))):
            self.assertEqual(bounded_run.main(options, self.environ), 128 + signal.SIGTERM)

    def test_an_interrupt_while_a_later_row_waits_keeps_the_first_exit_code(self):
        real_once = bounded_run.bounded_once
        calls = []

        def once(options, environ):
            calls.append(options.cpus)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real_once(options, environ)

        with mock.patch.object(bounded_run, "bounded_once", once):
            code = self.run_bounded(["--measure-rows", "8,4,2"], [(1, 1000)])
        self.assertEqual(code, 1)
        self.assertEqual(calls, [8, 4])


class FirstMeasurementTest(unittest.TestCase):
    """Calls bounded() in this process with eight slots of 2 GiB, so the default budget of 4096 MiB needs two.

    reserve, run_command, and probe_cap are stubs: no lock is waited for and no command or probe runs.
    """

    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.environ = dict(os.environ)
        self.environ.pop("BOUNDED_RUN_ACTIVE", None)
        self.environ.pop("BOUNDED_RUN_NO_CAP", None)
        self.environ.update({
            "BOUNDED_RUN_LOCK_DIR": os.path.join(self.base.name, "locks"),
            "BOUNDED_RUN_TOTAL_MIB": "16384",
            "BOUNDED_RUN_RESERVE_MIB": "0",
            "BOUNDED_RUN_SLOT_MIB": "2048",
            "BOUNDED_RUN_POLL_SECONDS": "0.05",
            "BOUNDED_RUN_MEMORY_WAIT_SECONDS": "0",
            "BOUNDED_RUN_SAMPLE_SECONDS": "0.1",
            "BOUNDED_RUN_FREE_MIB": "1048576",
        })

    def run_bounded(self, arguments, probe_output):
        """Returns, for each run, the slots it reserved, the budget its command got, and the MemoryMax of its cap or None."""
        runs = []

        def fake_reserve(directory, count, needed, exclusive_files, poll_seconds):
            runs.append([needed])
            return bounded_run.Reservation([])

        def fake_run_command(command, environ, on_start=None):
            caps = [int(part[len("MemoryMax="):-1]) for part in command if part.startswith("MemoryMax=")]
            runs[-1] += [int(environ["BOUNDED_RUN_MEMORY_MIB"]), caps[0] if caps else None]
            return 0, 1024

        options = bounded_run.parse_arguments(arguments + ["--", sys.executable, "-c", "pass"])
        with mock.patch.object(bounded_run, "probe_cap", return_value=probe_output), \
                mock.patch.object(bounded_run, "reserve", fake_reserve), \
                mock.patch.object(bounded_run, "run_command", fake_run_command):
            self.assertEqual(bounded_run.bounded(options, self.environ), 0)
        return runs

    def test_with_a_cap_a_first_measurement_takes_the_slots_of_the_default_budget(self):
        self.assertEqual(self.run_bounded(["--measure"], ""), [[2, 4096, 4096]])

    def test_without_a_cap_a_first_measurement_takes_the_whole_queue(self):
        self.assertEqual(self.run_bounded(["--measure"], None), [[8, 16384, None]])

    def test_with_a_cap_the_largest_measured_row_takes_the_slots_of_the_default_budget(self):
        self.assertEqual(self.run_bounded(["--measure-rows", "4,2"], "")[0], [2, 4096, 4096])

    def test_without_a_cap_the_largest_measured_row_takes_the_whole_queue(self):
        self.assertEqual(self.run_bounded(["--measure-rows", "4,2"], None)[0], [8, 16384, None])


class CheckTest(unittest.TestCase):
    """Calls check() in this process with four slots of 2 GiB, a headroom of 1024 MiB, 16 processors, and no hard cap.

    The test holds lock files of the queue itself, as a running command and a waiter hold them.
    """

    def setUp(self):
        self.lines = []
        patcher = mock.patch.object(bounded_run, "log", side_effect=self.lines.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(bounded_run, "machine_cpus", return_value=16)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.directory = os.path.join(self.base.name, "locks")
        os.mkdir(self.directory, 0o700)
        self.environ = dict(os.environ)
        self.environ.pop("BOUNDED_RUN_ACTIVE", None)
        self.environ.update({
            "BOUNDED_RUN_LOCK_DIR": self.directory,
            "BOUNDED_RUN_TOTAL_MIB": "8192",
            "BOUNDED_RUN_RESERVE_MIB": "0",
            "BOUNDED_RUN_SLOT_MIB": "2048",
            "BOUNDED_RUN_NO_CAP": "1",
        })

    def hold(self, name):
        descriptor = bounded_run._try_lock(os.path.join(self.directory, name))
        self.assertIsNotNone(descriptor)
        self.addCleanup(os.close, descriptor)
        return descriptor

    def check(self, budgets=(), available=16384, outstanding=None):
        options = bounded_run.parse_arguments(["--check"] + [part for budget in budgets for part in ("--memory", budget)])
        code = bounded_run.check(options.budgets, self.environ, read_available=lambda: available, read_outstanding=lambda: outstanding)
        self.assertEqual(code, 0)
        return self.lines

    def test_reports_the_slots_the_memory_and_the_line(self):
        self.assertEqual(self.check(), [
            "check slots=4 slot=2048M free-slots=4 free=16384M unused=- cpus=16 cpus-used=- cpus-headroom=2 cpus-free=- line=free fits=8192M",
        ])

    def test_the_largest_budget_that_fits_now(self):
        self.assertTrue(self.check(available=4000)[0].endswith(" fits=2816M"))

    def test_no_fit_when_the_free_memory_is_not_readable(self):
        self.assertTrue(self.check(available=None)[0].endswith(" fits=-"))

    def test_a_budget_of_the_whole_queue_starts_when_the_memory_of_the_queue_is_free(self):
        self.assertEqual(self.check(["8G"], available=8192)[-1], "check budget=8192M slots=4 headroom=0M starts=yes")

    def test_the_free_memory_for_the_tests_replaces_the_measured_one(self):
        self.environ["BOUNDED_RUN_FREE_MIB"] = "4096"
        lines = self.check(["2G"], available=0, outstanding=65536)
        self.assertIn(" free=4096M unused=- ", lines[0])
        self.assertEqual(lines[-1], "check budget=2048M slots=1 headroom=1024M starts=yes")

    def test_counts_the_slots_that_running_commands_hold(self):
        self.hold("slot-000.lock")
        self.hold("slot-002.lock")
        self.assertIn(" free-slots=2 ", self.check()[0])

    def test_a_command_can_take_every_free_slot_after_the_check(self):
        self.hold("slot-001.lock")
        self.check(["2G"])
        reservation = bounded_run.try_reserve(self.directory, 4, 3, [])
        self.assertIsNotNone(reservation, "the check still holds a slot")
        reservation.release()
        line = bounded_run._try_lock(os.path.join(self.directory, "line.lock"))
        self.assertIsNotNone(line, "the check still holds the line")
        os.close(line)

    def test_a_waiter_in_the_line_makes_the_line_busy_and_no_budget_starts(self):
        self.hold("line.lock")
        lines = self.check(["2G"])
        self.assertTrue(" line=busy fits=" in lines[0], lines)
        self.assertEqual(lines[1], "check budget=2048M slots=1 headroom=1024M starts=no")

    def test_a_count_of_slots_that_another_command_takes_at_that_moment_is_not_given(self):
        self.hold("reserve.lock")
        lines = self.check(["2G"])
        self.assertIn(" free-slots=- ", lines[0])
        self.assertEqual(lines[1], "check budget=2048M slots=1 headroom=1024M starts=no")

    def test_each_budget_gets_its_slots_and_its_answer_in_the_order_given(self):
        self.hold("slot-000.lock")
        self.hold("slot-001.lock")
        lines = self.check(["2G", "4096M", "5G"])
        self.assertEqual(lines[1:], [
            "check budget=2048M slots=1 headroom=1024M starts=yes",
            "check budget=4096M slots=2 headroom=1024M starts=yes",
            "check budget=5120M slots=3 headroom=1024M starts=no",
        ])

    def test_a_budget_starts_only_when_the_free_memory_less_the_unused_budgets_and_the_headroom_holds_it(self):
        lines = self.check(["2G", "4G"], available=6000, outstanding=900)
        self.assertEqual(lines[0], "check slots=4 slot=2048M free-slots=4 free=6000M unused=900M cpus=16 cpus-used=- cpus-headroom=2 cpus-free=- line=free fits=3840M")
        self.assertEqual(lines[1:], ["check budget=2048M slots=1 headroom=1024M starts=yes", "check budget=4096M slots=2 headroom=1024M starts=no"])

    def test_a_budget_starts_when_the_free_memory_cannot_be_read_as_the_wait_does(self):
        lines = self.check(["2G"], available=None)
        self.assertIn(" free=- ", lines[0])
        self.assertEqual(lines[1], "check budget=2048M slots=1 headroom=1024M starts=yes")

    def test_a_budget_larger_than_the_queue_needs_every_slot_and_the_memory_of_the_queue(self):
        lines = self.check(["64G"], available=9300)
        self.assertEqual(lines[1], "check budget=65536M slots=4 headroom=0M starts=yes")

    def test_counts_the_larger_of_the_unused_budgets_read_before_and_after_the_free_memory(self):
        unused = [100, 900]
        options = bounded_run.parse_arguments(["--check"])
        bounded_run.check(options.budgets, self.environ, read_available=lambda: 6000, read_outstanding=lambda: unused.pop(0))
        self.assertIn(" unused=900M ", self.lines[0])

    def test_counts_the_unused_budgets_beside_the_scope_of_the_probe(self):
        self.environ.pop("BOUNDED_RUN_NO_CAP")
        output = "0::/user.slice/app.slice/bounded-run-1-000000-probe.scope\n"
        calls = []

        def unused(parent, skip):
            calls.append(parent)
            return 700

        options = bounded_run.parse_arguments(["--check"])
        with mock.patch.object(bounded_run, "probe_cap", return_value=output), \
                mock.patch.object(bounded_run, "unused_budget_mib", unused), \
                mock.patch.object(bounded_run, "held_commands", return_value=[]):
            self.assertEqual(bounded_run.check(options.budgets, self.environ, read_available=lambda: 9000), 0)
        self.assertEqual(set(calls), {"/sys/fs/cgroup/user.slice/app.slice"})
        self.assertIn(" unused=700M ", self.lines[0])

    def check_with_cap(self, cpus_in_use):
        self.environ.pop("BOUNDED_RUN_NO_CAP")
        output = "0::/user.slice/app.slice/bounded-run-1-000000-probe.scope\n"
        options = bounded_run.parse_arguments(["--check", "--memory", "2G"])
        with mock.patch.object(bounded_run, "probe_cap", return_value=output), \
                mock.patch.object(bounded_run, "unused_budget_mib", return_value=0), \
                mock.patch.object(bounded_run, "cpus_in_use", cpus_in_use), \
                mock.patch.object(bounded_run, "held_commands", return_value=[]):
            bounded_run.check(options.budgets, self.environ, read_available=lambda: 9000)
        return self.lines

    def test_counts_the_processors_of_the_running_commands_beside_the_scope_of_the_probe(self):
        calls = []

        def cpus_in_use(parent, skip):
            calls.append((parent, list(skip)))
            return 12

        lines = self.check_with_cap(cpus_in_use)
        self.assertEqual(calls, [("/sys/fs/cgroup/user.slice/app.slice", [])])
        self.assertIn(" cpus=16 cpus-used=12 cpus-headroom=2 cpus-free=2 line=free", lines[0])
        self.assertEqual(lines[1], "check budget=2048M slots=1 headroom=1024M starts=yes")

    def test_processors_that_cannot_be_counted_give_a_dash(self):
        self.assertIn(" cpus=16 cpus-used=- cpus-headroom=2 cpus-free=- ", self.check_with_cap(lambda parent, skip: None)[0])

    def test_no_processor_is_free_when_the_running_commands_use_the_headroom(self):
        self.assertIn(" cpus-used=16 cpus-headroom=2 cpus-free=0 ", self.check_with_cap(lambda parent, skip: 16)[0])

    def test_names_each_held_command_after_the_state_line(self):
        self.environ.pop("BOUNDED_RUN_NO_CAP")
        output = "0::/user.slice/app.slice/bounded-run-1-000000-probe.scope\n"
        calls = []

        def held(parent, skip):
            calls.append(parent)
            return ["unit=bounded-run-7-abcdef budget=4096M used=100M age=5s dir=/w command=tool"]

        options = bounded_run.parse_arguments(["--check", "--memory", "2G"])
        with mock.patch.object(bounded_run, "probe_cap", return_value=output), \
                mock.patch.object(bounded_run, "unused_budget_mib", return_value=0), \
                mock.patch.object(bounded_run, "held_commands", held):
            bounded_run.check(options.budgets, self.environ, read_available=lambda: 9000)
        self.assertEqual(calls, ["/sys/fs/cgroup/user.slice/app.slice"])
        self.assertEqual(self.lines[1], "check held unit=bounded-run-7-abcdef budget=4096M used=100M age=5s dir=/w command=tool")
        self.assertTrue(self.lines[2].startswith("check budget=2048M "), self.lines)

    def test_a_check_inside_a_bounded_command_counts_its_unused_budget_too(self):
        self.environ.pop("BOUNDED_RUN_NO_CAP")
        output = "0::/user.slice/app.slice/bounded-run-1-000000-probe.scope\n"
        skips = []

        def unused(parent, skip):
            skips.append(list(skip))
            return 0

        options = bounded_run.parse_arguments(["--check"])
        with mock.patch.object(bounded_run, "probe_cap", return_value=output), \
                mock.patch.object(bounded_run, "own_scope_name", return_value="bounded-run-2-111111.scope"), \
                mock.patch.object(bounded_run, "unused_budget_mib", unused), \
                mock.patch.object(bounded_run, "held_commands", return_value=[]):
            bounded_run.check(options.budgets, self.environ, read_available=lambda: 9000)
        self.assertEqual(skips, [[], []])

    def test_a_check_inside_a_bounded_command_names_that_command_too(self):
        self.environ.pop("BOUNDED_RUN_NO_CAP")
        output = "0::/user.slice/app.slice/bounded-run-1-000000-probe.scope\n"
        skips = []

        def held(parent, skip):
            skips.append(list(skip))
            return []

        options = bounded_run.parse_arguments(["--check"])
        with mock.patch.object(bounded_run, "probe_cap", return_value=output), \
                mock.patch.object(bounded_run, "own_scope_name", return_value="bounded-run-2-111111.scope"), \
                mock.patch.object(bounded_run, "unused_budget_mib", return_value=0), \
                mock.patch.object(bounded_run, "held_commands", held):
            bounded_run.check(options.budgets, self.environ, read_available=lambda: 9000)
        self.assertEqual(skips, [[]])

    def test_the_slots_and_the_line_are_read_after_the_cap_probe(self):
        self.environ.pop("BOUNDED_RUN_NO_CAP")
        events = []
        real_free_slots = bounded_run._free_slots

        def probe(prefix):
            events.append("probe")
            return None

        def free_slots(*arguments, **keywords):
            events.append("slots")
            return real_free_slots(*arguments, **keywords)

        options = bounded_run.parse_arguments(["--check"])
        with mock.patch.object(bounded_run, "probe_cap", probe), mock.patch.object(bounded_run, "_free_slots", free_slots):
            bounded_run.check(options.budgets, self.environ, read_available=lambda: 9000)
        self.assertEqual(events[-1], "slots")
        self.assertIn("probe", events)

    def test_no_held_line_without_a_cap(self):
        self.hold("slot-000.lock")
        self.assertFalse(any(line.startswith("check held") for line in self.check(["2G"])))

    def test_counts_no_unused_budget_without_a_cap(self):
        options = bounded_run.parse_arguments(["--check"])
        with mock.patch.object(bounded_run, "probe_cap") as probe:
            bounded_run.check(options.budgets, self.environ, read_available=lambda: 9000)
        probe.assert_not_called()
        self.assertIn(" unused=- ", self.lines[0])


class CheckArgumentTest(unittest.TestCase):
    def test_reads_each_budget_in_order(self):
        options = bounded_run.parse_arguments(["--check", "--memory", "6G", "--memory", "512M"])
        self.assertEqual((options.check, options.budgets), (True, [6144, 512]))

    def test_the_check_option_can_come_after_a_budget(self):
        self.assertEqual(bounded_run.parse_arguments(["--memory", "2G", "--check"]).budgets, [2048])

    def test_needs_no_budget(self):
        self.assertEqual(bounded_run.parse_arguments(["--check"]).budgets, [])

    def test_a_command_after_the_check_option_is_a_command_of_a_run(self):
        options = bounded_run.parse_arguments(["--memory", "2G", "--", "tool", "--check"])
        self.assertEqual((options.check, options.command), (False, ["tool", "--check"]))

    def test_the_value_of_an_option_is_not_the_check_option(self):
        options = bounded_run.parse_arguments(["--exclusive", "--check", "--", "tool"])
        self.assertEqual((options.check, options.exclusive, options.command), (False, ["--check"], ["tool"]))

    def test_rejects_a_command_and_the_other_options(self):
        for arguments in (
            ["--check", "--", "tool"],
            ["--check", "--memory", "2G", "--", "tool"],
            ["--check", "--cpus", "2"],
            ["--check", "--exclusive", "port"],
            ["--check", "--measure"],
            ["--check", "--measure-rows", "4,2"],
            ["--check", "--label", "lint"],
            ["--check", "--memory"],
            ["--check", "--memory", "six"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(bounded_run.WrapperError):
                    bounded_run.parse_arguments(arguments)


class WrapperProcessCase(unittest.TestCase):
    """Runs the script as a process, with two slots of 2 GiB and no hard cap."""

    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.events = os.path.join(self.base.name, "events")
        self.environ = dict(os.environ)
        self.environ.pop("BOUNDED_RUN_ACTIVE", None)
        self.environ.update({
            "BOUNDED_RUN_LOCK_DIR": os.path.join(self.base.name, "locks"),
            "BOUNDED_RUN_TOTAL_MIB": "6144",
            "BOUNDED_RUN_RESERVE_MIB": "2048",
            "BOUNDED_RUN_SLOT_MIB": "2048",
            "BOUNDED_RUN_POLL_SECONDS": "0.05",
            "BOUNDED_RUN_MEMORY_WAIT_SECONDS": "0",
            "BOUNDED_RUN_SAMPLE_SECONDS": "0.1",
            "BOUNDED_RUN_NO_CAP": "1",
            "BOUNDED_RUN_FREE_MIB": "1048576",
            "EVENTS": self.events,
        })
        self.processes = []
        self._stderr_buffers = {}

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        for line in self.read_events():
            try:
                os.kill(int(line.split()[2]), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def wrapper(self, options, command, **environ):
        variables = dict(self.environ)
        variables.update(environ)
        process = subprocess.Popen(
            [sys.executable, WRAPPER] + options + ["--"] + command,
            env=variables, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        return process

    def worker(self, name, memory, hold="0.3", options=(), release=""):
        command = [sys.executable, "-c", WORKER, name]
        return self.wrapper(["--memory", memory] + list(options), command, HOLD=hold, RELEASE=release)

    def read_events(self):
        try:
            with open(self.events) as handle:
                return handle.read().splitlines()
        except OSError:
            return []

    def wait_for_event(self, kind, name, seconds=60.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            for line in self.read_events():
                if line.split()[:2] == [kind, name]:
                    return line
            time.sleep(0.02)
        self.fail("no '%s %s' event after %s seconds; events: %s" % (kind, name, seconds, self.read_events()))

    def wait_for_stderr(self, process, substring, seconds=60.0):
        """Reads the process's raw error-stream descriptor until substring appears, or fails by seconds.

        Reads os.read() on the raw descriptor, never process.stderr's own buffered readline()/read():
        select() only reports the descriptor ready, it says nothing about how many lines are
        sitting in the pipe. A buffered readline() can pull more than one already-arrived line
        out of the pipe in a single call and return just the first, leaving the rest sitting in
        Python's own buffer where select() can no longer see them and this loop would wait for a
        line it already holds. Keeps what it reads in self._stderr_buffers, keyed by process, so
        a later call to stderr_of() for the same process resumes from here instead of losing or
        re-reading any of it.
        """
        deadline = time.time() + seconds
        buffer = self._stderr_buffers.setdefault(process, "")
        fd = process.stderr.fileno()
        while substring not in buffer:
            remaining = deadline - time.time()
            if remaining <= 0:
                self.fail("no line with %r on the error stream after %s seconds; stderr so far: %s" % (substring, seconds, buffer))
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.5))
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    self.fail("the error stream closed with no line %r; stderr so far: %s" % (substring, buffer))
                buffer += chunk.decode(errors="replace")
                self._stderr_buffers[process] = buffer
        return buffer

    def stderr_of(self, process):
        """Returns everything the process wrote to its error stream, once it has stopped.

        Combines what wait_for_stderr already took off the raw descriptor (if any) with a final
        raw read of whatever is left, so the two never compete for the same bytes through two
        different buffers. Call only after the process has exited, so the final read reaches
        end-of-file instead of blocking.
        """
        buffer = self._stderr_buffers.pop(process, "")
        fd = process.stderr.fileno()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                return buffer
            buffer += chunk.decode(errors="replace")

    def gone(self, pid, seconds=10.0):
        """Returns True when the process stops, or is a zombie, within seconds."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            try:
                if Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()[0] == "Z":
                    return True
            except OSError:
                return True
            time.sleep(0.05)
        return False

    def kill_later(self, pid):
        def kill():
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        self.addCleanup(kill)

    def peak_concurrency(self):
        running = 0
        peak = 0
        for line in self.read_events():
            running += 1 if line.startswith("start ") else -1
            peak = max(peak, running)
        return peak


class WrapperProcessTest(WrapperProcessCase):
    def test_a_budget_that_does_not_fit_with_no_command_running_exits_75_and_frees_its_slots(self):
        environ = dict(self.environ, BOUNDED_RUN_TOTAL_MIB="28000", BOUNDED_RUN_FREE_MIB="14000")
        environ.pop("BOUNDED_RUN_RESERVE_MIB", None)
        done = subprocess.run([sys.executable, WRAPPER, "--memory", "12288M", "--", "true"], env=environ,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertIn("bounded-run: no-memory budget=12288M free=14000M headroom=2800M fits=11008M", done.stderr)
        reservation = bounded_run.try_reserve(os.path.join(self.base.name, "locks"), 10, 10, [])
        self.assertIsNotNone(reservation)
        reservation.release()

    def test_passes_the_exit_code(self):
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "import sys; sys.exit(7)"])
        self.assertEqual(process.wait(timeout=60), 7)

    def test_passes_the_output(self):
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "print('from the command')"])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(output, "from the command\n")
        self.assertIn("bounded-run: budget 2048 MiB", errors)

    def test_a_command_that_a_signal_stopped_gives_128_plus_the_signal(self):
        script = "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", script])
        self.assertEqual(process.wait(timeout=60), 137)

    def test_a_failure_of_the_wrapper_gives_125(self):
        process = subprocess.Popen(
            [sys.executable, WRAPPER, "--memory", "2G", "tool"], env=self.environ,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 125)
        self.assertTrue(errors.startswith("bounded-run: "), errors)

    def test_a_command_that_does_not_exist_gives_125(self):
        process = self.wrapper(["--memory", "2G"], ["/nonexistent/tool-for-the-test"])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 125)
        self.assertIn("cannot start", errors)
        follower = self.worker("after", "4G", hold="0")  # ends at once; the test waits for it to end
        self.assertEqual(follower.wait(timeout=60), 0)

    def test_the_command_gets_the_budget_and_the_marker(self):
        script = "import os; print(os.environ['BOUNDED_RUN_ACTIVE'], os.environ['BOUNDED_RUN_MEMORY_MIB'], os.environ['BOUNDED_RUN_CPUS'])"
        process = self.wrapper(["--memory", "2G", "--cpus", "3"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(output, "1 2048 3\n")

    def test_a_command_without_cpus_gets_half_the_processors_of_the_machine(self):
        script = "import os; print(os.environ['BOUNDED_RUN_CPUS'])"
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(output, "%d\n" % max(1, (os.cpu_count() or 1) // 2), errors)

    def test_the_command_reads_the_input_of_the_wrapper(self):
        variables = dict(self.environ)
        process = subprocess.Popen(
            [sys.executable, WRAPPER, "--memory", "2G", "--", sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
            env=variables, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        output, errors = process.communicate("text for the command", timeout=60)
        self.assertEqual((process.returncode, output), (0, "TEXT FOR THE COMMAND\n"), errors)

    def test_a_nested_call_does_not_wait_for_its_own_slots(self):
        inner = [sys.executable, WRAPPER, "--memory", "4G", "--", sys.executable, "-c", "import sys; print('inner'); sys.exit(3)"]
        process = self.wrapper(["--memory", "4G"], inner)
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, output), (3, "inner\n"), errors)
        self.assertIn("nested call", errors)

    def test_a_nested_call_of_a_command_that_does_not_exist_gives_125(self):
        process = self.wrapper(["--memory", "2G"], ["/nonexistent/tool-for-the-test"], BOUNDED_RUN_ACTIVE="1")
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 125, errors)
        self.assertNotIn("Traceback", errors)

    def test_a_stop_signal_stops_the_command(self):
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
            with self.subTest(signal=signum):
                name = "stopped-%d" % signum
                process = self.worker(name, "2G", hold="300")
                line = self.wait_for_event("start", name)
                process.send_signal(signum)
                self.assertEqual(process.wait(timeout=60), -signum)
                child = int(line.split()[2])
                deadline = time.time() + 5
                alive = True
                while alive and time.time() < deadline:
                    try:
                        os.kill(child, 0)
                        time.sleep(0.05)
                    except ProcessLookupError:
                        alive = False
                self.assertFalse(alive, "the command still runs")

    def test_a_hangup_stops_the_command_and_ends_the_wrapper_by_the_hangup(self):
        name = "hangup-129"
        process = self.worker(name, "2G", hold="300")
        line = self.wait_for_event("start", name)
        process.send_signal(signal.SIGHUP)
        self.assertEqual(process.wait(timeout=60), -signal.SIGHUP)
        child = int(line.split()[2])
        deadline = time.time() + 5
        alive = True
        while alive and time.time() < deadline:
            try:
                os.kill(child, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                alive = False
        self.assertFalse(alive, "the command still runs")

    def test_a_second_stop_signal_kills_a_command_that_ignores_the_first(self):
        script = (
            "import os, signal, sys, time\n"
            "def event(kind):\n"
            "    descriptor = os.open(os.environ['EVENTS'], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)\n"
            "    os.write(descriptor, ('%s stubborn %d\\n' % (kind, os.getpid())).encode())\n"
            "    os.close(descriptor)\n"
            "def ignore(signum, frame):\n"
            "    event('signaled')\n"
            "signal.signal(signal.SIGTERM, ignore)\n"
            "event('start')\n"
            "time.sleep(300)\n"  # runs until the second signal kills it; never meant to end on its own
        )
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", script])
        line = self.wait_for_event("start", "stubborn")
        process.send_signal(signal.SIGTERM)
        self.wait_for_event("signaled", "stubborn", seconds=60.0)
        self.assertIsNone(process.poll())
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=60), -signal.SIGTERM)
        child = int(line.split()[2])
        deadline = time.time() + 5
        alive = True
        while alive and time.time() < deadline:
            try:
                os.kill(child, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                alive = False
        self.assertFalse(alive, "the command still runs")

    def test_commands_never_run_together_beyond_the_slots(self):
        workers = [self.worker("w%d" % index, "2G", hold="0.3") for index in range(6)]  # brief; the test waits for each to end
        for process in workers:
            self.assertEqual(process.wait(timeout=60), 0)
        events = self.read_events()
        self.assertEqual(len([line for line in events if line.startswith("start ")]), 6)
        self.assertEqual(len([line for line in events if line.startswith("end ")]), 6)
        self.assertLessEqual(self.peak_concurrency(), 2)

    def test_a_command_that_needs_all_slots_runs_alone(self):
        workers = [self.worker("w%d" % index, "4G", hold="0.2") for index in range(3)]  # brief; the test waits for each to end
        for process in workers:
            self.assertEqual(process.wait(timeout=60), 0)
        self.assertEqual(self.peak_concurrency(), 1)

    def test_a_waiting_command_holds_no_slot_and_is_not_overtaken(self):
        release = os.path.join(self.base.name, "release")
        long_holder = self.worker("holder", "2G", hold="300", release=release)  # runs until the release file below ends it early
        self.wait_for_event("start", "holder")
        large = self.worker("large", "4G", hold="0")  # ends at once once it gets its slots; the test waits for it to end
        self.wait_for_stderr(large, "waiting for")
        self.assertEqual(bounded_run._free_slots(self.environ["BOUNDED_RUN_LOCK_DIR"], 2), 1)
        small = self.worker("small", "2G", hold="0")  # ends at once; the test waits for it to end
        self.wait_for_stderr(small, "behind other commands")
        Path(release).write_text("")
        self.assertEqual(large.wait(timeout=60), 0)
        self.assertEqual(small.wait(timeout=60), 0)
        self.assertEqual(long_holder.wait(timeout=60), 0)
        order = [line.split()[:2] for line in self.read_events()]
        self.assertLess(order.index(["end", "holder"]), order.index(["start", "large"]))
        self.assertLess(order.index(["start", "large"]), order.index(["start", "small"]))

    def test_a_hard_kill_of_the_wrapper_frees_the_slots_at_once(self):
        holder = self.worker("holder", "4G", hold="300")  # runs until the kill below ends it
        self.wait_for_event("start", "holder")
        holder.kill()
        holder.wait(timeout=60)
        started = time.time()
        follower = self.worker("follower", "4G", hold="0")  # ends at once; the test waits for it to end
        self.assertEqual(follower.wait(timeout=60), 0)
        self.assertLess(time.time() - started, 30.0)

    @unittest.skipUnless(sys.platform.startswith("linux"), "only Linux has a parent-death signal")
    def test_a_hard_kill_of_the_wrapper_stops_the_command(self):
        process = self.worker("orphan", "2G", hold="300")  # runs until the kill below ends it
        command = int(self.wait_for_event("start", "orphan").split()[2])
        self.kill_later(command)
        process.kill()
        process.wait(timeout=60)
        self.assertTrue(self.gone(command), "the command still runs")

    def test_the_command_does_not_inherit_the_locks(self):
        script = (
            "import os\n"
            "directory = os.environ['BOUNDED_RUN_LOCK_DIR']\n"
            "locks = set()\n"
            "for name in os.listdir(directory):\n"
            "    info = os.stat(os.path.join(directory, name))\n"
            "    locks.add((info.st_dev, info.st_ino))\n"
            "found = 0\n"
            "for descriptor in range(3, 256):\n"
            "    try:\n"
            "        info = os.fstat(descriptor)\n"
            "    except OSError:\n"
            "        continue\n"
            "    if (info.st_dev, info.st_ino) in locks:\n"
            "        found += 1\n"
            "print('locks', len(locks), 'inherited', found)\n"
        )
        process = self.wrapper(["--memory", "4G", "--exclusive", "port"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        # The command can list the lock directory before the wrapper makes its run file.
        self.assertIn(output, ("locks 6 inherited 0\n", "locks 7 inherited 0\n"), errors)

    def test_commands_with_the_same_exclusive_name_take_turns(self):
        workers = [self.worker("w%d" % index, "2G", hold="0.3", options=["--exclusive", "port-8080"]) for index in range(3)]  # brief; the test waits for each to end
        for process in workers:
            self.assertEqual(process.wait(timeout=60), 0)
        self.assertEqual(self.peak_concurrency(), 1)

    def test_a_budget_larger_than_the_queue_runs_with_a_warning(self):
        first = self.worker("first", "64G", hold="0.3")  # brief; the test waits for each to end
        second = self.worker("second", "64G", hold="0.3")
        output, errors = first.communicate(timeout=60)
        self.assertEqual(first.returncode, 0, errors)
        self.assertIn("WARNING: the budget of 65536 MiB is more than the 4096 MiB of the queue; the budget is 4096 MiB", errors)
        self.assertRegex(errors, r"bounded-run: budget 4096 MiB, peak ")
        self.assertEqual(second.wait(timeout=60), 0)
        self.assertEqual(self.peak_concurrency(), 1)

    def test_a_budget_too_large_for_a_float_gives_the_budget_of_the_queue(self):
        process = self.wrapper(["--memory", "1" + "0" * 400 + "G"], [sys.executable, "-c", "pass"])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        self.assertNotIn("Traceback", errors)
        self.assertRegex(errors, r"bounded-run: budget 4096 MiB, peak ")

    def test_a_budget_larger_than_the_queue_gives_the_command_the_budget_of_the_queue(self):
        script = "import os; print(os.environ['BOUNDED_RUN_MEMORY_MIB'])"
        process = self.wrapper(["--memory", "64G"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, output), (0, "4096\n"), errors)

    def test_a_lock_directory_that_is_a_file_gives_125(self):
        path = os.path.join(self.base.name, "a-file")
        Path(path).write_text("")
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "print('ran')"], BOUNDED_RUN_LOCK_DIR=path)
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, output), (125, ""), errors)
        self.assertIn("bounded-run: cannot use the lock directory", errors)

    def test_a_relative_lock_directory_gives_125(self):
        variables = dict(self.environ, BOUNDED_RUN_LOCK_DIR="locks")
        process = subprocess.Popen(
            [sys.executable, WRAPPER, "--memory", "2G", "--", sys.executable, "-c", "print('ran')"],
            env=variables, cwd=self.base.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, output), (125, ""), errors)
        self.assertTrue(errors.startswith("bounded-run: "), errors)
        self.assertIn("BOUNDED_RUN_LOCK_DIR", errors)
        self.assertNotIn("Traceback", errors)
        self.assertFalse(os.path.exists(os.path.join(self.base.name, "locks")))

    def test_a_lock_file_that_cannot_be_opened_gives_125(self):
        os.makedirs(os.path.join(self.environ["BOUNDED_RUN_LOCK_DIR"], "reserve.lock"))
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "print('ran')"])
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, output), (125, ""), errors)
        self.assertTrue(errors.startswith("bounded-run: "), errors)
        self.assertNotIn("Traceback", errors)

    def test_an_exclusive_name_in_a_removed_working_directory_gives_125(self):
        script = 'mkdir gone && cd gone && rmdir ../gone && exec "$@"'
        process = subprocess.Popen(
            ["sh", "-c", script, "sh", sys.executable, WRAPPER, "--memory", "2G", "--exclusive", "port", "--", sys.executable, "-c", "print('ran')"],
            env=self.environ, cwd=self.base.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, output), (125, ""), errors)
        self.assertTrue(errors.startswith("bounded-run: "), errors)
        self.assertNotIn("Traceback", errors)

    def test_each_run_reports_the_budget_and_the_peak(self):
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "pass"])
        output, errors = process.communicate(timeout=60)
        self.assertRegex(errors, r"bounded-run: budget 2048 MiB, peak \d+ MiB \(sampled, approximate\), held -, exit 0\n")
        self.assertNotIn("suggested budget", errors)

    def test_the_default_budget_on_a_small_machine_is_not_more_than_its_memory(self):
        process = self.wrapper([], [sys.executable, "-c", "pass"], BOUNDED_RUN_TOTAL_MIB="1024", BOUNDED_RUN_RESERVE_MIB="")
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        budget = int(re.search(r"bounded-run: budget (\d+) MiB, peak", errors).group(1))
        self.assertLessEqual(budget, 1024)

    def test_a_budget_on_a_machine_smaller_than_one_slot_is_not_more_than_its_memory(self):
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "pass"], BOUNDED_RUN_TOTAL_MIB="1024", BOUNDED_RUN_RESERVE_MIB="")
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        self.assertIn("WARNING: the budget of 2048 MiB is more than the 1024 MiB of the queue; the budget is 1024 MiB", errors)
        self.assertRegex(errors, r"bounded-run: budget 1024 MiB, peak ")

    def test_a_budget_on_a_machine_with_less_than_one_slot_after_the_reserve_keeps_the_reserve(self):
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "pass"], BOUNDED_RUN_TOTAL_MIB="3072", BOUNDED_RUN_RESERVE_MIB="")
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        self.assertIn("WARNING: the budget of 2048 MiB is more than the 1024 MiB of the queue; the budget is 1024 MiB", errors)
        self.assertNotIn("reserve", errors)

    def test_a_reserve_that_leaves_nothing_gives_a_warning(self):
        process = self.wrapper(["--memory", "1G"], [sys.executable, "-c", "pass"], BOUNDED_RUN_TOTAL_MIB="1024", BOUNDED_RUN_RESERVE_MIB="")
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        self.assertIn("WARNING: the reserve of 2048 MiB leaves no memory of the 1024 MiB of the machine; the queue does not keep the reserve", errors)

    def test_without_a_cap_the_output_says_so(self):
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "pass"])
        output, errors = process.communicate(timeout=60)
        self.assertIn("no hard cap is available here", errors)

    def test_a_first_measurement_runs_alone_in_the_queue_without_a_cap(self):
        command = [sys.executable, "-c", WORKER, "measured"]
        first = self.wrapper(["--measure"], command, HOLD="1.0")
        self.wait_for_event("start", "measured")
        second = self.worker("second", "2G", hold="0.1")
        self.assertEqual(first.wait(timeout=60), 0)
        self.assertEqual(second.wait(timeout=60), 0)
        self.assertEqual(self.peak_concurrency(), 1)
        self.assertIn("bounded-run: budget 4096 MiB, peak ", self.stderr_of(first))

    def test_a_first_measurement_waits_for_the_commands_that_run_without_a_cap(self):
        first = self.worker("first", "2G", hold="1.0")
        self.wait_for_event("start", "first")
        second = self.wrapper(["--measure"], [sys.executable, "-c", WORKER, "measured"], HOLD="0.1")
        self.assertEqual(first.wait(timeout=60), 0)
        self.assertEqual(second.wait(timeout=60), 0)
        self.assertEqual(self.peak_concurrency(), 1)

    def test_a_measurement_with_a_budget_takes_the_slots_of_the_budget(self):
        first = self.wrapper(["--measure", "--memory", "2G"], [sys.executable, "-c", WORKER, "measured"], HOLD="1.0")
        self.wait_for_event("start", "measured")
        second = self.worker("second", "2G", hold="0.1")
        self.wait_for_event("start", "second")
        self.assertEqual(first.wait(timeout=60), 0)
        self.assertEqual(second.wait(timeout=60), 0)
        self.assertEqual(self.peak_concurrency(), 2)

    def test_a_first_measurement_waits_for_the_memory_of_the_default_budget_only(self):
        reads = []

        def wait(budget, limit, poll, **rest):
            reads.append(budget)

        options = bounded_run.Options()
        options.measure = True
        options.command = [sys.executable, "-c", "pass"]
        environ = dict(self.environ, BOUNDED_RUN_TOTAL_MIB="34816", BOUNDED_RUN_RESERVE_MIB="2048")
        with mock.patch.object(bounded_run, "wait_for_memory", wait), mock.patch.object(bounded_run, "log"):
            self.assertEqual(bounded_run.bounded(options, environ), 0)
        self.assertEqual(reads, [bounded_run.default_budget_mib(34816, 2048)])

    def test_measure_mode_reports_a_peak_and_a_budget(self):
        script = "import time\ndata = bytearray(150 * 1024 * 1024)\nfor index in range(0, len(data), 4096):\n    data[index] = 1\ntime.sleep(1.0)\n"
        process = self.wrapper(["--measure"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        peak = [line for line in errors.splitlines() if " peak " in line][0]
        value = int(peak.split(" peak ")[1].split()[0])
        self.assertGreaterEqual(value, 140)
        self.assertLess(value, 1024)
        self.assertIn("sampled, approximate", peak)
        suggested = [line for line in errors.splitlines() if "suggested budget" in line][0]
        self.assertEqual(int(suggested.split()[-2]) % 256, 0)
        self.assertGreaterEqual(int(suggested.split()[-2]), value * 1.5)

    def test_measured_rows_print_their_row_lines_in_order(self):
        script = "import os; print(os.environ['BOUNDED_RUN_CPUS'])"
        process = self.wrapper(["--measure-rows", "1,2", "--label", "lint"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        self.assertEqual(output.split(), ["2", "1"])
        rows = re.findall(r"^bounded-run: row label=lint cpus=(\d+) budget=\d+M peak=\d+M held=- exact=no exit=0$", errors, re.MULTILINE)
        self.assertEqual(rows, ["2", "1"], errors)

    def test_an_interrupt_in_the_queue_ends_the_wrapper_by_the_interrupt_with_no_traceback(self):
        holder = self.worker("holder", "4G", hold="300")
        self.wait_for_event("start", "holder")
        waiting = self.worker("waiting", "4G", hold="0")  # never reached; interrupted while still queued

        self.wait_for_stderr(waiting, "waiting for")

        waiting.send_signal(signal.SIGINT)
        self.assertEqual(waiting.wait(timeout=60), -signal.SIGINT)
        buffer = self.stderr_of(waiting)
        self.assertNotIn("Traceback", buffer)
        for line in buffer.splitlines():
            self.assertTrue(line.startswith("bounded-run: "), buffer)

        holder.send_signal(signal.SIGTERM)
        self.assertEqual(holder.wait(timeout=60), -signal.SIGTERM)

    def hold_the_line(self):
        os.makedirs(self.environ["BOUNDED_RUN_LOCK_DIR"], exist_ok=True)
        descriptor = os.open(os.path.join(self.environ["BOUNDED_RUN_LOCK_DIR"], "line.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        bounded_run.fcntl.flock(descriptor, bounded_run.fcntl.LOCK_EX)
        return descriptor

    def test_an_interrupt_behind_others_in_the_line_ends_the_wrapper_by_the_interrupt_with_no_traceback(self):
        line = self.hold_the_line()
        self.addCleanup(os.close, line)
        waiting = self.worker("waiting", "2G", hold="0")  # never reached; interrupted while still in the line
        self.wait_for_stderr(waiting, "behind other commands")
        waiting.send_signal(signal.SIGINT)
        self.assertEqual(waiting.wait(timeout=10), -signal.SIGINT)
        buffer = self.stderr_of(waiting)
        self.assertNotIn("Traceback", buffer)
        self.assertIn("interrupted while waiting", buffer)

    def test_a_waiter_that_dies_in_the_line_does_not_block_the_next(self):
        release = os.path.join(self.base.name, "release")
        holder = self.worker("holder", "2G", hold="300", release=release)  # runs until the release file below ends it
        self.wait_for_event("start", "holder")
        head = self.worker("head", "4G", hold="0")  # killed while it waits at the head of the line
        self.wait_for_stderr(head, "waiting for")
        follower = self.worker("follower", "4G", hold="0")  # ends at once once it gets its slots
        self.wait_for_stderr(follower, "behind other commands")
        head.kill()
        head.wait(timeout=60)
        Path(release).write_text("")
        self.assertEqual(holder.wait(timeout=60), 0)
        self.assertEqual(follower.wait(timeout=30), 0)
        directory = self.environ["BOUNDED_RUN_LOCK_DIR"]
        for name in os.listdir(directory):
            self.assertTrue(name.endswith(".lock"), name)
            self.assertEqual(os.path.getsize(os.path.join(directory, name)), 0, name)

    def a_large_command_starts_under_a_steady_stream_of_small_commands(self, options, command):
        """Keeps at least one slot held by 1-slot commands, and fails when the large command does not start in time."""
        large = None
        stream = []
        deadline = time.time() + 30
        try:
            while time.time() < deadline:
                if sum(1 for process in stream if process.poll() is None) < 4:
                    stream.append(self.worker("small%d" % len(stream), "2G", hold="0.3"))  # brief; the test waits for each to end
                if large is None and len(stream) >= 4:
                    self.wait_for_event("start", "small0")
                    large = self.wrapper(options, command)
                if large is not None and any(line.split()[:2] == ["start", "large"] for line in self.read_events()):
                    break
                time.sleep(0.05)
            else:
                self.fail("the large command did not start within 30 seconds, while %d small commands started" % len(stream))
        finally:
            for process in stream:
                process.wait(timeout=60)
        self.assertEqual(large.wait(timeout=60), 0)
        self.assertGreater(len([line for line in self.read_events() if line.startswith("start small")]), 4)

    def test_a_command_that_needs_all_slots_starts_while_small_commands_keep_arriving(self):
        self.a_large_command_starts_under_a_steady_stream_of_small_commands(
            ["--memory", "4G"], [sys.executable, "-c", WORKER, "large"],
        )

    def test_a_first_measurement_starts_while_small_commands_keep_arriving(self):
        self.a_large_command_starts_under_a_steady_stream_of_small_commands(
            ["--measure"], [sys.executable, "-c", WORKER, "large"],
        )


class CheckProcessTest(WrapperProcessCase):
    def check(self, arguments):
        process = subprocess.Popen(
            [sys.executable, WRAPPER, "--check"] + arguments, env=self.environ,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        output, errors = process.communicate(timeout=60)
        return process.returncode, output, errors

    def test_prints_the_check_lines_on_the_error_stream_and_exits_0(self):
        holder = self.worker("holder", "2G", hold="300")
        self.wait_for_event("start", "holder")
        code, output, errors = self.check(["--memory", "2G", "--memory", "4G"])
        self.assertEqual((code, output), (0, ""), errors)
        self.assertRegex(errors, r"^bounded-run: check slots=2 slot=2048M free-slots=1 free=(\d+M|-) unused=- cpus=\d+ cpus-used=- cpus-headroom=\d+ cpus-free=- line=free fits=(\d+M|-)\n")
        self.assertRegex(errors, r"\nbounded-run: check budget=2048M slots=1 headroom=1024M starts=(yes|no)\nbounded-run: check budget=4096M slots=2 headroom=0M starts=no\n$")
        holder.kill()

    def test_a_command_starts_at_once_after_the_check(self):
        self.assertEqual(self.check([])[0], 0)
        self.assertEqual(self.worker("after", "4G", hold="0").wait(timeout=60), 0)

    def test_a_fault_of_the_call_gives_125(self):
        code, output, errors = self.check(["--cpus", "2"])
        self.assertEqual(code, 125)
        self.assertTrue(errors.startswith("bounded-run: "), errors)
        self.assertNotIn("check slots=", errors)


# Writes the pid of its parent, the wrapper, to the file in PARENT, then holds until the wrapper stops it.
PARENT_WRITER = "import os, time; open(os.environ['PARENT'], 'w').write(str(os.getppid())); time.sleep(300)"


@unittest.skipIf(shutil.which("bash") is None, "needs bash")
class JoinedLineTest(WrapperProcessCase):
    """Runs the wrapper as the first call of a line of bash that joins its calls with ';'.

    A terminal sends Ctrl-C to the whole process group of the line. Bash stops the line only when
    the call that runs dies from the signal. A plain sh can end from the signal by itself, so it proves nothing.
    """

    def line(self, path, then, options, command, **environ):
        """Starts `wrapper; <then> "$0"` with $0 set to path, in a new process group."""
        variables = dict(self.environ)
        variables.update(environ)
        process = subprocess.Popen(
            ["bash", "-c", '"$@"; ' + then + ' "$0"', path, sys.executable, WRAPPER] + options + ["--"] + command,
            env=variables, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        self.processes.append(process)

        def kill_group():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        self.addCleanup(kill_group)
        return process

    def wait_for_file(self, path, seconds=60.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                text = Path(path).read_text()
            except OSError:
                text = ""
            if text:
                return text
            time.sleep(0.02)
        self.fail("no %s after %s seconds" % (path, seconds))

    def test_an_interrupt_while_the_command_runs_stops_the_line(self):
        marker = os.path.join(self.base.name, "next-ran")
        process = self.line(marker, "touch", ["--memory", "2G"], [sys.executable, "-c", WORKER, "joined"], HOLD="300")
        self.wait_for_event("start", "joined")
        os.killpg(process.pid, signal.SIGINT)
        self.assertEqual(process.wait(timeout=60), -signal.SIGINT, self.stderr_of(process))
        self.assertFalse(os.path.exists(marker), "the next command of the line ran")

    def test_an_interrupt_while_the_wrapper_waits_in_the_queue_stops_the_line(self):
        holder = self.worker("holder", "4G", hold="300")  # holds every slot until the SIGTERM below
        self.wait_for_event("start", "holder")
        marker = os.path.join(self.base.name, "next-ran")
        process = self.line(marker, "touch", ["--memory", "4G"], [sys.executable, "-c", WORKER, "queued"], HOLD="0")
        self.wait_for_stderr(process, "waiting for")
        os.killpg(process.pid, signal.SIGINT)
        self.assertEqual(process.wait(timeout=60), -signal.SIGINT)
        self.assertIn("interrupted while waiting", self.stderr_of(process))
        self.assertFalse(os.path.exists(marker), "the next command of the line ran")
        holder.send_signal(signal.SIGTERM)
        holder.wait(timeout=60)

    def test_an_interrupt_while_rows_are_measured_stops_the_rows_and_the_line(self):
        marker = os.path.join(self.base.name, "next-ran")
        process = self.line(marker, "touch", ["--measure-rows", "2,1"], [sys.executable, "-c", WORKER, "rows"], HOLD="300")
        self.wait_for_event("start", "rows")
        os.killpg(process.pid, signal.SIGINT)
        self.assertEqual(process.wait(timeout=60), -signal.SIGINT)
        errors = self.stderr_of(process)
        self.assertIn("stopped by a signal; the rows after --cpus 2 are not measured", errors)
        self.assertFalse(os.path.exists(marker), "the next command of the line ran")

    def test_an_interrupt_after_a_failed_row_still_stops_the_line(self):
        marker = os.path.join(self.base.name, "next-ran")
        fail_then_hold = "import os, sys\nif os.environ['BOUNDED_RUN_CPUS'] == '2':\n    sys.exit(3)\n" + WORKER
        process = self.line(marker, "touch", ["--measure-rows", "2,1"], [sys.executable, "-c", fail_then_hold, "rows"], HOLD="300")
        self.wait_for_event("start", "rows")
        os.killpg(process.pid, signal.SIGINT)
        self.assertEqual(process.wait(timeout=60), -signal.SIGINT)
        errors = self.stderr_of(process)
        self.assertRegex(errors, r"row label=- cpus=2 .* exit=3")
        self.assertFalse(os.path.exists(marker), "the next command of the line ran")

    def test_a_command_that_exits_130_by_itself_does_not_stop_the_line(self):
        status = os.path.join(self.base.name, "status")
        process = self.line(status, "echo $? >", ["--memory", "2G"], [sys.executable, "-c", "import sys; sys.exit(130)"])
        self.assertEqual(process.wait(timeout=60), 0, self.stderr_of(process))
        self.assertEqual(Path(status).read_text(), "130\n")

    def test_the_caller_reads_128_plus_the_signal(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum):
                status = os.path.join(self.base.name, "status-%d" % signum)
                parent = os.path.join(self.base.name, "parent-%d" % signum)
                # Only the wrapper gets the signal, so bash itself does not stop and reads the status.
                process = self.line(status, "echo $? >", ["--memory", "2G"], [sys.executable, "-c", PARENT_WRITER], PARENT=parent)
                os.kill(int(self.wait_for_file(parent)), signum)
                self.assertEqual(process.wait(timeout=60), 0, self.stderr_of(process))
                self.assertEqual(Path(status).read_text(), "%d\n" % (128 + signum))


@unittest.skipUnless(
    bounded_run.choose_cap_prefix(256, 1, "bounded-run-test-%d" % os.getpid(), bounded_run.probe_cap) is not None,
    "no hard cap on this machine",
)
class HardCapTest(WrapperProcessCase):
    def setUp(self):
        super().setUp()
        del self.environ["BOUNDED_RUN_NO_CAP"]

    def test_a_command_that_does_not_exist_gives_125(self):
        process = self.wrapper(["--memory", "2G"], ["/nonexistent/tool-for-the-test"])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 125, errors)

    def test_the_cap_stops_a_command_that_passes_its_budget(self):
        script = "data = bytearray(1024 * 1024 * 1024)\nfor index in range(0, len(data), 4096):\n    data[index] = 1\nprint('survived')\n"
        process = self.wrapper(["--memory", "256M", "--cpus", "1"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, output), (137, ""), errors)
        self.assertIn("the hard cap stopped it", errors)

    def test_a_short_command_gets_its_peak_from_the_cgroup(self):
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                process = self.wrapper(["--memory", "1G", "--cpus", "2"], [sys.executable, "-c", "print(1)"])
                output, errors = process.communicate(timeout=60)
                self.assertEqual((process.returncode, output), (0, "1\n"), errors)
                self.assertRegex(errors, r"bounded-run: budget 1024 MiB, peak \d+ MiB \(cgroup\), held (\d+ MiB \(sampled\)|-), exit 0\n")
        locks = os.listdir(self.environ["BOUNDED_RUN_LOCK_DIR"])
        self.assertEqual([name for name in locks if name.startswith("peak-")], [])

    def test_a_stop_signal_stops_a_capped_command(self):
        process = self.worker("capped", "1G", hold="300")
        line = self.wait_for_event("start", "capped")
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=60), -signal.SIGTERM)
        with self.assertRaises(ProcessLookupError):
            deadline = time.time() + 5
            while time.time() < deadline:
                os.kill(int(line.split()[2]), 0)
                time.sleep(0.05)

    def test_a_hard_kill_of_the_wrapper_stops_the_inside_process_and_the_command(self):
        process = self.worker("capped-orphan", "1G", hold="300")  # runs until the kill below ends it
        command = int(self.wait_for_event("start", "capped-orphan").split()[2])
        inside = int(Path("/proc/%d/stat" % command).read_text().rsplit(")", 1)[1].split()[1])
        self.kill_later(inside)
        self.kill_later(command)
        self.assertIn(b"--inside-cap", Path("/proc/%d/cmdline" % inside).read_bytes())
        process.kill()
        process.wait(timeout=60)
        self.assertTrue(self.gone(inside), "the --inside-cap process still runs")
        self.assertTrue(self.gone(command), "the command still runs")

    def test_the_peak_comes_from_the_cgroup(self):
        script = "import time\ndata = bytearray(150 * 1024 * 1024)\nfor index in range(0, len(data), 4096):\n    data[index] = 1\ntime.sleep(1.2)\n"
        process = self.wrapper(["--memory", "1G", "--measure"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        peak = [line for line in errors.splitlines() if " peak " in line][0]
        self.assertIn("(cgroup)", peak)
        self.assertGreaterEqual(int(peak.split(" peak ")[1].split()[0]), 140)
        held = re.search(r"^bounded-run: row .* held=(\d+)M exact=yes exit=0$", errors, re.MULTILINE)
        self.assertIsNotNone(held, errors)
        self.assertGreaterEqual(int(held.group(1)), 140)

    def test_no_peak_file_is_left_behind_after_a_failing_command(self):
        process = self.wrapper(["--memory", "1G"], [sys.executable, "-c", "import sys; sys.exit(9)"])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 9, errors)
        self.assertIn("(cgroup)", errors)
        locks = os.listdir(self.environ["BOUNDED_RUN_LOCK_DIR"])
        self.assertEqual([name for name in locks if name.startswith("peak-")], [])


if __name__ == "__main__":
    unittest.main()
