#!/usr/bin/env python3
"""Runs a command under a memory reservation that every project of the user shares.

Usage: bounded_run.py [--memory SIZE] [--cpus N] [--exclusive NAME]... [--measure] -- COMMAND...

The exit code is the exit code of the command. Exit code 125 means that this
script failed before the command gave a result.

These environment variables are settings for the machine, not for one call.
Two sessions with different values do not count the same slots.

  BOUNDED_RUN_SLOT_MIB             size of one memory slot (default 2048)
  BOUNDED_RUN_RESERVE_MIB          memory that the queue never gives out
  BOUNDED_RUN_TOTAL_MIB            memory of the machine, in place of the measured value
  BOUNDED_RUN_POLL_SECONDS         time between two tries for the slots (default 2)
  BOUNDED_RUN_MEMORY_WAIT_SECONDS  time limit of the wait for free memory (default 300)
  BOUNDED_RUN_SAMPLE_SECONDS       time between two memory samples (default 1)
  BOUNDED_RUN_LOCK_DIR             directory of the lock files
  BOUNDED_RUN_NO_CAP               when set, do not apply the hard cap
"""
from __future__ import annotations

import fcntl
import hashlib
import math
import os
import random
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

PREFIX = "bounded-run"
EXIT_WRAPPER = 125
ACTIVE_VARIABLE = "BOUNDED_RUN_ACTIVE"
SLOT_MIB = 2048
MINIMUM_RESERVE_MIB = 2048
POLL_SECONDS = 2.0
MEMORY_WAIT_SECONDS = 300.0
SAMPLE_SECONDS = 1.0
MARGIN_EXACT = 0.25
MARGIN_APPROXIMATE = 0.5
BUDGET_STEP_MIB = 256
USAGE = "usage: bounded_run.py [--memory SIZE] [--cpus N] [--exclusive NAME]... [--measure] -- COMMAND..."


class WrapperError(Exception):
    """A failure of the wrapper, not of the command."""


def log(message: str) -> None:
    sys.stderr.write("%s: %s\n" % (PREFIX, message))
    sys.stderr.flush()


def parse_size_mib(text: str) -> int:
    parts = re.match(r"^(\d+)([GgMm]?)$", text.strip())
    if parts is None:
        raise WrapperError("cannot read the size '%s'; use a form such as 6G or 4096M" % text)
    value = int(parts.group(1))
    if parts.group(2) in ("G", "g"):
        value *= 1024
    if value <= 0:
        raise WrapperError("the size '%s' must be more than zero" % text)
    return value


def total_memory_mib() -> int:
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except (ValueError, OSError):
        done = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10)
        return int(done.stdout.strip()) // (1024 * 1024)


def default_reserve_mib(total_mib: int) -> int:
    return max(MINIMUM_RESERVE_MIB, total_mib // 4)


def slot_count(total_mib: int, slot_mib: int, reserve_mib: int) -> int:
    return max(1, (total_mib - reserve_mib) // slot_mib)


def slots_needed(budget_mib: int, slot_mib: int, count: int) -> int:
    return min(count, max(1, math.ceil(budget_mib / slot_mib)))


def default_budget_mib(total_mib: int, slot_mib: int) -> int:
    return max(1, math.ceil(total_mib / 4 / slot_mib)) * slot_mib


class Settings:
    def __init__(self, environ: Mapping[str, str], read_total: Callable[[], int] = total_memory_mib) -> None:
        self.slot_mib = int(_number(environ, "BOUNDED_RUN_SLOT_MIB", SLOT_MIB))
        total = environ.get("BOUNDED_RUN_TOTAL_MIB")
        self.total_mib = int(_number(environ, "BOUNDED_RUN_TOTAL_MIB", 0)) if total else read_total()
        self.reserve_mib = int(_number(environ, "BOUNDED_RUN_RESERVE_MIB", default_reserve_mib(self.total_mib)))
        self.poll_seconds = _number(environ, "BOUNDED_RUN_POLL_SECONDS", POLL_SECONDS)
        self.memory_wait_seconds = _number(environ, "BOUNDED_RUN_MEMORY_WAIT_SECONDS", MEMORY_WAIT_SECONDS)
        self.sample_seconds = _number(environ, "BOUNDED_RUN_SAMPLE_SECONDS", SAMPLE_SECONDS)
        self.no_cap = bool(environ.get("BOUNDED_RUN_NO_CAP"))
        if self.slot_mib <= 0:
            raise WrapperError("BOUNDED_RUN_SLOT_MIB must be more than zero")


def _number(environ: Mapping[str, str], name: str, fallback: float) -> float:
    text = environ.get(name)
    if text is None or text == "":
        return fallback
    try:
        value = float(text)
    except ValueError:
        raise WrapperError("cannot read %s='%s'; use a number" % (name, text))
    if value < 0:
        raise WrapperError("%s must not be less than zero" % name)
    return value


def lock_directory(environ: Mapping[str, str], uid: int) -> str:
    override = environ.get("BOUNDED_RUN_LOCK_DIR")
    if override:
        return override
    runtime = environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return os.path.join(runtime, PREFIX)
    login_directory = "/run/user/%d" % uid
    try:
        if os.stat(login_directory).st_uid == uid:
            return os.path.join(login_directory, PREFIX)
    except OSError:
        pass
    return "/tmp/%s-%d" % (PREFIX, uid)


def ensure_lock_directory(path: str, uid: int) -> None:
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        info = os.lstat(path)
    except OSError as error:
        raise WrapperError("cannot use the lock directory %s: %s" % (path, error))
    if not stat.S_ISDIR(info.st_mode):
        raise WrapperError("the lock directory %s is not a directory" % path)
    if info.st_uid != uid:
        raise WrapperError("the lock directory %s belongs to a different user" % path)
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(path, 0o700)


def repository_id(directory: str) -> str:
    root = os.path.realpath(directory)
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=directory, capture_output=True, text=True, timeout=10,
        )
        if done.returncode == 0 and done.stdout.strip():
            root = os.path.realpath(os.path.join(directory, done.stdout.strip()))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return hashlib.sha256(root.encode("utf-8")).hexdigest()[:12]


def exclusive_file_name(repository: str, name: str) -> str:
    if re.match(r"^[A-Za-z0-9._-]+$", name) is None:
        raise WrapperError("cannot use the name '%s'; use letters, digits, '.', '_' and '-'" % name)
    return "exclusive-%s-%s.lock" % (repository, name)


class Reservation:
    def __init__(self, descriptors: Sequence[int]) -> None:
        self.descriptors = list(descriptors)

    def release(self) -> None:
        for descriptor in self.descriptors:
            os.close(descriptor)
        self.descriptors = []


def _try_lock(path: str) -> Optional[int]:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    except OSError as error:
        os.close(descriptor)
        error_text = error.strerror if error.strerror else str(error)
        raise WrapperError("cannot lock %s: %s. The lock directory must be on a filesystem that supports file locks." % (path, error_text))
    return descriptor


def try_reserve(directory: str, count: int, needed: int, exclusive_files: Sequence[str]) -> Optional[Reservation]:
    turn = os.open(os.path.join(directory, "reserve.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    held: List[int] = []
    try:
        fcntl.flock(turn, fcntl.LOCK_EX)
        names = list(exclusive_files) + ["slot-%03d.lock" % index for index in range(count)]
        slots = 0
        for position, name in enumerate(names):
            is_slot = position >= len(exclusive_files)
            if is_slot and slots == needed:
                break
            descriptor = _try_lock(os.path.join(directory, name))
            if descriptor is None:
                if is_slot:
                    continue
                break
            held.append(descriptor)
            if is_slot:
                slots += 1
        if slots == needed and len(held) == needed + len(exclusive_files):
            reservation = Reservation(held)
            held = []
            return reservation
        return None
    finally:
        for descriptor in held:
            os.close(descriptor)
        os.close(turn)


def reserve(
    directory: str, count: int, needed: int, exclusive_files: Sequence[str], poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> Reservation:
    announced = False
    while True:
        reservation = try_reserve(directory, count, needed, exclusive_files)
        if reservation is not None:
            log("holding %d of %d slot(s)" % (needed, count))
            return reservation
        if not announced:
            log("waiting for %d of %d slot(s)" % (needed, count))
            announced = True
        sleep(poll_seconds * (0.5 + random.random()))


def parse_meminfo(text: str) -> Optional[int]:
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return None


def parse_vm_stat(text: str) -> Optional[int]:
    page = None
    pages = 0
    for line in text.splitlines():
        size = re.search(r"page size of (\d+) bytes", line)
        if size is not None:
            page = int(size.group(1))
        counted = re.match(r"^Pages (free|inactive|speculative):\s+(\d+)\.", line)
        if counted is not None:
            pages += int(counted.group(2))
    if page is None:
        return None
    return pages * page // (1024 * 1024)


def available_memory_mib() -> Optional[int]:
    try:
        with open("/proc/meminfo") as handle:
            return parse_meminfo(handle.read())
    except OSError:
        pass
    try:
        done = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_vm_stat(done.stdout)


def wait_for_memory(
    budget_mib: int, limit_seconds: float, poll_seconds: float,
    read_available: Callable[[], Optional[int]] = available_memory_mib,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    waited = 0.0
    while True:
        available = read_available()
        if available is None:
            log("cannot read the free memory; starting")
            return True
        if available >= budget_mib:
            log("%d MiB free, budget %d MiB; starting" % (available, budget_mib))
            return True
        if waited >= limit_seconds:
            log("WARNING: only %d MiB free after %ds, budget %d MiB; starting" % (available, waited, budget_mib))
            return False
        log("%d MiB free, budget %d MiB; waiting (%d of %ds)" % (available, budget_mib, waited, limit_seconds))
        sleep(poll_seconds)
        waited += poll_seconds


def cap_prefix(budget_mib: int, cpus: Optional[int], unit: str) -> List[str]:
    prefix = [
        "systemd-run", "--user", "--scope", "--quiet", "--collect", "--unit", unit,
        "-p", "MemoryMax=%dM" % budget_mib,
        "-p", "MemorySwapMax=0",
    ]
    if cpus is not None:
        prefix += ["-p", "CPUQuota=%d%%" % (cpus * 100)]
    return prefix + ["--"]


def cap_usable(
    prefix: Sequence[str], platform: str = sys.platform,
    which: Callable[[str], Optional[str]] = shutil.which,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> bool:
    if not platform.startswith("linux") or which("systemd-run") is None:
        return False
    try:
        done = run(list(prefix) + ["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def cgroup_directory(pid: int, unit: str, proc_root: str = "/proc", cgroup_root: str = "/sys/fs/cgroup") -> Optional[str]:
    try:
        with open(os.path.join(proc_root, str(pid), "cgroup")) as handle:
            text = handle.read()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("0::") and line.strip().endswith("/%s.scope" % unit):
            return cgroup_root + line.strip()[3:]
    return None


def cgroup_peak_mib(directory: str, names: Sequence[str] = ("memory.peak", "memory.current")) -> Optional[int]:
    for name in names:
        try:
            with open(os.path.join(directory, name)) as handle:
                return math.ceil(int(handle.read().strip()) / (1024 * 1024))
        except (OSError, ValueError):
            continue
    return None


def parse_group_rss_mib(text: str, group: int) -> Optional[int]:
    total = 0
    found = False
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == str(group) and parts[1].isdigit():
            total += int(parts[1])
            found = True
    if not found:
        return None
    return math.ceil(total / 1024)


def group_rss_mib(group: int) -> Optional[int]:
    try:
        done = subprocess.run(["ps", "-A", "-o", "pgid=", "-o", "rss="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_group_rss_mib(done.stdout, group)


def rusage_peak_mib(maxrss: int, platform: str = sys.platform) -> int:
    if platform == "darwin":
        return math.ceil(maxrss / (1024 * 1024))
    return math.ceil(maxrss / 1024)


def suggested_budget_mib(peak_mib: int, approximate: bool) -> int:
    margin = MARGIN_APPROXIMATE if approximate else MARGIN_EXACT
    return max(1, math.ceil(peak_mib * (1 + margin) / BUDGET_STEP_MIB)) * BUDGET_STEP_MIB


class PeakTracker(threading.Thread):
    def __init__(self, read_sample: Callable[[], Optional[int]], interval: float) -> None:
        super().__init__(daemon=True)
        self.read_sample = read_sample
        self.interval = interval
        self.peak: Optional[int] = None
        self.done = threading.Event()

    def run(self) -> None:
        while True:
            self.sample()
            if self.done.wait(self.interval):
                return

    def sample(self) -> None:
        try:
            value = self.read_sample()
        except Exception:
            value = None
        if value is not None and (self.peak is None or value > self.peak):
            self.peak = value

    def finish(self) -> Optional[int]:
        self.done.set()
        self.join(timeout=15)
        return self.peak


def exit_code_of(status: int) -> int:
    code = os.waitstatus_to_exitcode(status)
    if code < 0:
        return 128 - code
    return code


def run_command(
    command: Sequence[str], environ: Mapping[str, str],
    on_start: Optional[Callable[[int], None]] = None,
) -> Tuple[int, int]:
    """Runs the command in its own process group. Returns the exit code and ru_maxrss."""
    received: List[int] = []
    started: List[int] = []

    def forward(signum: int, frame: object) -> None:
        received.append(signum)
        if started:
            try:
                os.killpg(started[0], signum if len(received) == 1 else signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    previous = {signum: signal.signal(signum, forward) for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        try:
            process = subprocess.Popen(list(command), env=dict(environ), start_new_session=True)
        except OSError as error:
            raise WrapperError("cannot start '%s': %s" % (command[0], error))
        started.append(process.pid)
        try:
            if received:
                try:
                    os.killpg(process.pid, received[0])
                except (ProcessLookupError, PermissionError):
                    pass
            if on_start is not None:
                on_start(process.pid)
            _, status, usage = os.wait4(process.pid, 0)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                os.waitpid(process.pid, 0)
            except ChildProcessError:
                pass
            raise
        process.returncode = exit_code_of(status)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    if received:
        return 128 + received[0], usage.ru_maxrss
    return process.returncode, usage.ru_maxrss


def inside_cap(
    peak_file: str, unit: str, command: Sequence[str],
    proc_root: str = "/proc", cgroup_root: str = "/sys/fs/cgroup",
) -> int:
    """Runs the command as a child in the cgroup of the cap, then writes the peak of that cgroup.

    The cgroup exists for as long as this process is in it. Thus the peak is readable after the
    command stops, which is not possible from outside the cgroup.
    """
    def keep_running(signum: int, frame: object) -> None:
        pass

    previous = {signum: signal.signal(signum, keep_running) for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        try:
            process = subprocess.Popen(list(command))
        except OSError as error:
            log("cannot start '%s': %s" % (command[0], error))
            return EXIT_WRAPPER
        _, status = os.waitpid(process.pid, 0)
        process.returncode = exit_code_of(status)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    directory = cgroup_directory(os.getpid(), unit, proc_root, cgroup_root)
    peak = cgroup_peak_mib(directory, names=("memory.peak",)) if directory is not None else None
    if peak is not None:
        try:
            with open(peak_file, "w") as handle:
                handle.write("%d\n" % peak)
        except OSError:
            pass
    return process.returncode


def read_peak_file(path: str) -> Optional[int]:
    try:
        with open(path) as handle:
            text = handle.read().strip()
        os.unlink(path)
    except OSError:
        return None
    return int(text) if text.isdigit() else None


class Options:
    def __init__(self) -> None:
        self.memory: Optional[str] = None
        self.cpus: Optional[int] = None
        self.exclusive: List[str] = []
        self.measure = False
        self.command: List[str] = []


def parse_arguments(argv: Sequence[str]) -> Options:
    options = Options()
    arguments = list(argv)
    if "--" not in arguments:
        raise WrapperError("the '--' before the command is missing\n" + USAGE)
    split = arguments.index("--")
    options.command = arguments[split + 1:]
    if not options.command:
        raise WrapperError("the command is missing\n" + USAGE)
    flags = arguments[:split]
    while flags:
        flag = flags.pop(0)
        if flag == "--measure":
            options.measure = True
            continue
        if flag not in ("--memory", "--cpus", "--exclusive"):
            raise WrapperError("cannot read the option '%s'\n%s" % (flag, USAGE))
        if not flags:
            raise WrapperError("the option '%s' needs a value\n%s" % (flag, USAGE))
        value = flags.pop(0)
        if flag == "--memory":
            options.memory = value
        elif flag == "--exclusive":
            if value not in options.exclusive:
                options.exclusive.append(value)
        else:
            if not value.isdigit() or int(value) < 1:
                raise WrapperError("cannot read --cpus '%s'; use a whole number of 1 or more" % value)
            options.cpus = int(value)
    return options


def bounded(options: Options, environ: Mapping[str, str]) -> int:
    settings = Settings(environ)
    if options.memory is not None:
        budget = parse_size_mib(options.memory)
    else:
        budget = default_budget_mib(settings.total_mib, settings.slot_mib)
    command = list(options.command)
    if shutil.which(command[0], path=environ.get("PATH")) is None:
        raise WrapperError("cannot start '%s': the command does not exist" % command[0])

    count = slot_count(settings.total_mib, settings.slot_mib, settings.reserve_mib)
    needed = slots_needed(budget, settings.slot_mib, count)
    if budget > count * settings.slot_mib:
        log("WARNING: the budget of %d MiB is more than the %d MiB of the queue; the command takes all slots" % (budget, count * settings.slot_mib))
    uid = os.getuid()
    directory = lock_directory(environ, uid)
    ensure_lock_directory(directory, uid)
    repository = repository_id(os.getcwd()) if options.exclusive else ""
    exclusive_files = [exclusive_file_name(repository, name) for name in options.exclusive]

    child_environ: Dict[str, str] = dict(environ)
    child_environ[ACTIVE_VARIABLE] = "1"
    child_environ["BOUNDED_RUN_MEMORY_MIB"] = str(budget)
    child_environ["BOUNDED_RUN_CPUS"] = str(options.cpus if options.cpus is not None else (os.cpu_count() or 1))

    reservation = reserve(directory, count, needed, exclusive_files, settings.poll_seconds)
    try:
        wait_for_memory(budget, settings.memory_wait_seconds, settings.poll_seconds)
        code, maxrss = run_command(command, child_environ)
    finally:
        reservation.release()

    log("budget %d MiB, exit %d" % (budget, code))
    return code


def main(argv: Optional[Sequence[str]] = None, environ: Optional[Mapping[str, str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    variables = os.environ if environ is None else environ
    try:
        if len(arguments) > 4 and arguments[0] == "--inside-cap" and arguments[3] == "--":
            return inside_cap(arguments[1], arguments[2], arguments[4:])
        options = parse_arguments(arguments)
        if variables.get(ACTIVE_VARIABLE):
            log("nested call; running the command directly")
            try:
                os.execvpe(options.command[0], options.command, dict(variables))
            except OSError as error:
                raise WrapperError("cannot start '%s': %s" % (options.command[0], error))
        return bounded(options, variables)
    except WrapperError as error:
        log(str(error))
        return EXIT_WRAPPER


if __name__ == "__main__":
    sys.exit(main())
