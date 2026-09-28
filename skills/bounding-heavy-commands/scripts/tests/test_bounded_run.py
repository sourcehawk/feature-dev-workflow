from __future__ import annotations

import errno
import os
import select
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
                # Call the real flock for the turn lock, raise ENOLCK for slot files
                if flags & bounded_run.fcntl.LOCK_EX and not (flags & bounded_run.fcntl.LOCK_NB):
                    # This is the turn lock (blocking), allow it
                    return None
                # This is a slot lock (non-blocking), fail with ENOLCK
                raise OSError(errno.ENOLCK, "No locks available")

            mock_flock.side_effect = flock_side_effect
            with self.assertRaises(bounded_run.WrapperError) as cm:
                bounded_run.try_reserve(self.directory, 1, 1, [])
            self.assertIn("cannot lock", str(cm.exception))
            self.assertIn("No locks available", str(cm.exception))

    def test_a_lock_error_leaves_no_slot_held(self):
        # Prove that when try_reserve fails mid-way, all locks it took are released.
        # Wrap os.open to track fd -> path mapping, then use it in a flock stub.
        fd_to_path = {}
        real_os_open = os.open

        def tracked_open(path, *args, **kwargs):
            fd = real_os_open(path, *args, **kwargs)
            fd_to_path[fd] = path
            return fd

        # flock will count calls and fail on the second slot file.
        flock_calls_per_file = {}
        real_flock = bounded_run.fcntl.flock

        def counting_flock(fd, flags):
            path = fd_to_path.get(fd, "<unknown>")
            if path not in flock_calls_per_file:
                flock_calls_per_file[path] = 0
            flock_calls_per_file[path] += 1

            # Allow the turn lock and first slot to succeed.
            if "reserve.lock" in path or "slot-000.lock" in path:
                return real_flock(fd, flags)

            # Fail on the second slot with ENOLCK.
            if "slot-001.lock" in path:
                raise OSError(errno.ENOLCK, "No locks available")

            # Any other file succeeds.
            return real_flock(fd, flags)

        with mock.patch.object(os, "open", tracked_open):
            with mock.patch.object(bounded_run.fcntl, "flock", counting_flock):
                # Call try_reserve for 2 slots; it should fail after locking slot-000.
                with self.assertRaises(bounded_run.WrapperError):
                    bounded_run.try_reserve(self.directory, 2, 2, [])

        # Now call try_reserve again with real functions (no patches).
        # If the first slot was not released, this will fail to get 2 slots.
        second_try = bounded_run.try_reserve(self.directory, 2, 2, [])
        self.assertIsNotNone(second_try)
        self.addCleanup(second_try.release)
        self.assertEqual(len(second_try.descriptors), 2)

    def test_the_turn_lock_is_free_while_the_wrapper_waits(self):
        # Hold all slots so reserve has to wait
        blocker = bounded_run.try_reserve(self.directory, 1, 1, [])
        self.addCleanup(blocker.release)

        turn_lock_acquired = []

        def sleep_and_check(seconds):
            # Try to acquire the turn lock while reserve is waiting
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
            # Release the blocker so reserve can succeed
            blocker.release()

        reservation = bounded_run.reserve(self.directory, 1, 1, [], 0.2, sleep=sleep_and_check)
        self.addCleanup(reservation.release)
        self.assertTrue(turn_lock_acquired[0], "turn lock should be free while reserve waits")


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

    def test_two_directories_have_different_ids(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assertNotEqual(bounded_run.repository_id(first), bounded_run.repository_id(second))


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


class MemoryWaitTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        self.log = patcher.start()
        self.addCleanup(patcher.stop)

    def wait(self, values, limit):
        readings = list(values)
        sleeps = []
        result = bounded_run.wait_for_memory(
            4096, limit, 5.0, read_available=lambda: readings.pop(0), sleep=sleeps.append,
        )
        return result, sleeps

    def test_starts_at_once_when_the_memory_is_free(self):
        self.assertEqual(self.wait([8000], 300), (True, []))

    def test_waits_until_the_memory_is_free(self):
        self.assertEqual(self.wait([1000, 2000, 5000], 300), (True, [5.0, 5.0]))

    def test_starts_after_the_time_limit(self):
        self.assertEqual(self.wait([1000, 1000, 1000], 10), (False, [5.0, 5.0]))

    def test_a_limit_of_zero_does_not_wait(self):
        self.assertEqual(self.wait([1000], 0), (False, []))

    def test_a_start_after_the_time_limit_is_a_warning(self):
        self.wait([1000], 0)
        self.assertTrue(self.log.call_args[0][0].startswith("WARNING: "))

    def test_starts_when_the_memory_is_not_readable(self):
        self.assertEqual(self.wait([None], 300), (True, []))


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

        def usable(prefix):
            probes.append(list(prefix))
            return answers[len(probes) - 1]

        return bounded_run.choose_cap_prefix(1024, 2, "unit-1", usable), probes

    def test_uses_the_oom_policy_when_the_first_probe_passes(self):
        prefix, probes = self.choose([True])
        self.assertEqual(prefix, bounded_run.cap_prefix(1024, 2, "unit-1"))
        self.assertEqual(len(probes), 1)
        self.assertIn("OOMPolicy=continue", probes[0])
        self.assertNotIn("unit-1", probes[0])

    def test_uses_the_prefix_without_the_oom_policy_when_only_the_second_probe_passes(self):
        prefix, probes = self.choose([False, True])
        self.assertEqual(prefix, bounded_run.cap_prefix(1024, 2, "unit-1", oom_policy=False))
        self.assertEqual(len(probes), 2)
        self.assertNotIn("OOMPolicy=continue", probes[1])

    def test_no_cap_when_both_probes_fail(self):
        prefix, probes = self.choose([False, False])
        self.assertIsNone(prefix)
        self.assertEqual(len(probes), 2)

    def test_no_command_runs_on_a_different_system(self):
        calls = []

        def run(command, **keywords):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)

        def usable(prefix):
            return bounded_run.cap_usable(prefix, platform="darwin", which=lambda name: "/usr/bin/systemd-run", run=run)

        self.assertIsNone(bounded_run.choose_cap_prefix(1024, 2, "unit-1", usable))
        self.assertEqual(calls, [])

    def probe(self, platform, tool, code=0, error=None):
        calls = []

        def run(command, **keywords):
            calls.append(command)
            if error is not None:
                raise error
            return subprocess.CompletedProcess(command, code)

        usable = bounded_run.cap_usable(
            bounded_run.cap_prefix(1024, 2, "unit-1"), platform=platform, which=lambda name: tool, run=run,
        )
        return usable, calls

    def test_usable_when_the_probe_succeeds(self):
        usable, calls = self.probe("linux", "/usr/bin/systemd-run")
        self.assertTrue(usable)
        self.assertEqual(calls[0][-1], "true")
        self.assertIn("CPUQuota=200%", calls[0])

    def test_not_usable_when_the_probe_fails(self):
        self.assertFalse(self.probe("linux", "/usr/bin/systemd-run", code=1)[0])

    def test_not_usable_when_the_probe_does_not_return(self):
        error = subprocess.TimeoutExpired("systemd-run", 15)
        self.assertFalse(self.probe("linux", "/usr/bin/systemd-run", error=error)[0])

    def test_not_usable_without_the_tool(self):
        usable, calls = self.probe("linux", None)
        self.assertFalse(usable)
        self.assertEqual(calls, [])

    def test_not_usable_on_a_different_system(self):
        usable, calls = self.probe("darwin", "/usr/bin/systemd-run")
        self.assertFalse(usable)
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


class BoundedCleanupTest(unittest.TestCase):
    """Calls bounded() in this process, with run_command and cap_usable replaced by stubs.

    No real command, no real cgroup, and no real subprocess run outside the stubs.
    """

    def setUp(self):
        patcher = mock.patch.object(bounded_run, "log")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.directory = os.path.join(self.base.name, "locks")
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

        with mock.patch.object(bounded_run, "cap_usable", return_value=True), \
                mock.patch.object(bounded_run, "run_command", fake_run_command):
            with self.assertRaises(RuntimeError):
                bounded_run.bounded(options, self.environ)

        names = os.listdir(self.directory)
        self.assertEqual([name for name in names if name.startswith("peak-")], [])

        reservation = bounded_run.try_reserve(self.directory, 2, 2, [])
        self.assertIsNotNone(reservation, "the slots are still held")
        reservation.release()


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

    def peak_concurrency(self):
        running = 0
        peak = 0
        for line in self.read_events():
            running += 1 if line.startswith("start ") else -1
            peak = max(peak, running)
        return peak


class WrapperProcessTest(WrapperProcessCase):
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
        for signum, code in ((signal.SIGTERM, 143), (signal.SIGINT, 130)):
            with self.subTest(signal=signum):
                name = "stopped-%d" % code
                process = self.worker(name, "2G", hold="300")
                line = self.wait_for_event("start", name)
                process.send_signal(signum)
                self.assertEqual(process.wait(timeout=60), code)
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

    def test_a_hangup_stops_the_command_and_gives_129(self):
        name = "hangup-129"
        process = self.worker(name, "2G", hold="300")
        line = self.wait_for_event("start", name)
        process.send_signal(signal.SIGHUP)
        self.assertEqual(process.wait(timeout=60), 129)
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
        self.assertEqual(process.wait(timeout=60), 143)
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

    def test_a_waiting_command_holds_no_slot(self):
        release = os.path.join(self.base.name, "release")
        long_holder = self.worker("holder", "2G", hold="300", release=release)  # runs until the release file below ends it early
        self.wait_for_event("start", "holder")
        large = self.worker("large", "4G", hold="0")  # ends at once once it gets its slots; the test waits for it to end
        self.wait_for_stderr(large, "waiting for")
        small = self.worker("small", "2G", hold="0")  # ends at once; the test waits for it to end
        self.assertEqual(small.wait(timeout=60), 0)
        names = [line.split()[1] for line in self.read_events() if line.startswith("end ")]
        self.assertEqual(names, ["small"])
        Path(release).write_text("")
        self.assertEqual(large.wait(timeout=60), 0)
        self.assertEqual(long_holder.wait(timeout=60), 0)
        order = [line.split()[:2] for line in self.read_events()]
        self.assertLess(order.index(["end", "holder"]), order.index(["start", "large"]))

    def test_a_hard_kill_of_the_wrapper_frees_the_slots_at_once(self):
        holder = self.worker("holder", "4G", hold="300")  # runs until the kill below ends it
        self.wait_for_event("start", "holder")
        holder.kill()
        holder.wait(timeout=60)
        started = time.time()
        follower = self.worker("follower", "4G", hold="0")  # ends at once; the test waits for it to end
        self.assertEqual(follower.wait(timeout=60), 0)
        self.assertLess(time.time() - started, 30.0)

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
        self.assertEqual(output, "locks 4 inherited 0\n", errors)

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
        self.assertIn("WARNING: the budget of 65536 MiB is more than the 4096 MiB of the queue", errors)
        self.assertEqual(second.wait(timeout=60), 0)
        self.assertEqual(self.peak_concurrency(), 1)

    def test_a_lock_directory_that_is_a_file_gives_125(self):
        path = os.path.join(self.base.name, "a-file")
        Path(path).write_text("")
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "print('ran')"], BOUNDED_RUN_LOCK_DIR=path)
        output, errors = process.communicate(timeout=60)
        self.assertEqual((process.returncode, output), (125, ""), errors)
        self.assertIn("bounded-run: cannot use the lock directory", errors)

    def test_each_run_reports_the_budget_and_the_peak(self):
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "pass"])
        output, errors = process.communicate(timeout=60)
        self.assertRegex(errors, r"bounded-run: budget 2048 MiB, peak \d+ MiB \(sampled, approximate\), exit 0\n")
        self.assertNotIn("suggested budget", errors)

    def test_without_a_cap_the_output_says_so(self):
        process = self.wrapper(["--memory", "2G"], [sys.executable, "-c", "pass"])
        output, errors = process.communicate(timeout=60)
        self.assertIn("no hard cap is available here", errors)

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

    def test_an_interrupt_in_the_queue_gives_130_and_no_traceback(self):
        holder = self.worker("holder", "4G", hold="300")
        self.wait_for_event("start", "holder")
        waiting = self.worker("waiting", "4G", hold="0")  # never reached; interrupted while still queued

        self.wait_for_stderr(waiting, "waiting for")

        waiting.send_signal(signal.SIGINT)
        self.assertEqual(waiting.wait(timeout=60), 130)
        buffer = self.stderr_of(waiting)
        self.assertNotIn("Traceback", buffer)
        for line in buffer.splitlines():
            self.assertTrue(line.startswith("bounded-run: "), buffer)

        holder.send_signal(signal.SIGTERM)
        self.assertEqual(holder.wait(timeout=60), 143)


@unittest.skipUnless(
    bounded_run.choose_cap_prefix(256, 1, "bounded-run-test-%d" % os.getpid(), bounded_run.cap_usable) is not None,
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
                self.assertRegex(errors, r"bounded-run: budget 1024 MiB, peak \d+ MiB \(cgroup\), exit 0\n")
        locks = os.listdir(self.environ["BOUNDED_RUN_LOCK_DIR"])
        self.assertEqual([name for name in locks if name.startswith("peak-")], [])

    def test_a_stop_signal_stops_a_capped_command(self):
        process = self.worker("capped", "1G", hold="300")
        line = self.wait_for_event("start", "capped")
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=60), 143)
        with self.assertRaises(ProcessLookupError):
            deadline = time.time() + 5
            while time.time() < deadline:
                os.kill(int(line.split()[2]), 0)
                time.sleep(0.05)

    def test_the_peak_comes_from_the_cgroup(self):
        script = "import time\ndata = bytearray(150 * 1024 * 1024)\nfor index in range(0, len(data), 4096):\n    data[index] = 1\ntime.sleep(1.2)\n"
        process = self.wrapper(["--memory", "1G", "--measure"], [sys.executable, "-c", script])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, errors)
        peak = [line for line in errors.splitlines() if " peak " in line][0]
        self.assertIn("(cgroup)", peak)
        self.assertGreaterEqual(int(peak.split(" peak ")[1].split()[0]), 140)

    def test_no_peak_file_is_left_behind_after_a_failing_command(self):
        process = self.wrapper(["--memory", "1G"], [sys.executable, "-c", "import sys; sys.exit(9)"])
        output, errors = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 9, errors)
        self.assertIn("(cgroup)", errors)
        locks = os.listdir(self.environ["BOUNDED_RUN_LOCK_DIR"])
        self.assertEqual([name for name in locks if name.startswith("peak-")], [])


if __name__ == "__main__":
    unittest.main()
