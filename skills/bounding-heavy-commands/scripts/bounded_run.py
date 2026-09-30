#!/usr/bin/env python3
"""Runs a command under a memory reservation that every project of the user shares.

Usage: bounded_run.py [--memory SIZE] [--cpus N] [--exclusive NAME]... [--measure] [--label NAME] -- COMMAND...
       bounded_run.py --measure-rows N,N,... [--memory SIZE] [--exclusive NAME]... [--label NAME] -- COMMAND...
       bounded_run.py --check [--memory SIZE]...

The exit code is the exit code of the command. Exit code 125 means that this
script failed before the command gave a result. A stop signal to this script
(SIGHUP, SIGINT, SIGQUIT, or SIGTERM) stops the command, and then this script
ends by the same signal. So a Ctrl-C at the terminal, which reaches the shell
too, stops a line of joined commands; a signal sent to this script alone does
not stop the shell. A caller that reads the exit status reads 128 plus the
signal.

A measurement prints one row line on the error stream, in a fixed form:

  bounded-run: row label=NAME cpus=N budget=<n>M peak=<n>M held=<n>M|- exact=yes|no exit=CODE

budget is the suggested budget. held is the sampled peak of the memory that
the kernel cannot take back at once under the hard cap, or '-' without it.
A '-' in place of the label or of cpus stands for an option that the call did
not give. --measure-rows measures the command at each processor limit of the
list, the largest first. The largest runs with --memory. Without it, the
largest runs with the default budget where the hard cap is available, and
alone in the queue where it is not. Each smaller one runs with the suggested
budget of the one before it, or with the budget of the one before it when that
run did not exit 0. The exit code is the first exit code that is not 0.

--check runs no command and holds no lock when it returns. Its exit code is 0.
It prints the state of the queue at that moment, one held line for each
running bounded command where the hard cap is available, and one line for
each --memory, in the order given:

  bounded-run: check slots=N slot=<n>M free-slots=N|- free=<n>M|- unused=<n>M|- line=free|busy
  bounded-run: check held unit=NAME budget=<n>M|- used=<n>M|- age=Ns|- dir=PATH|- command=TEXT|-
  bounded-run: check budget=<n>M slots=N headroom=<n>M starts=yes|no

A '-' stands for a value that the check cannot read or count here. starts=yes
means that a run of that budget would start now. It is not a reservation.

A normal call sets none of the environment variables below. A person can
set the tuning values in the profile of the shell, so that every session
on the machine uses the same values. The tests of this script set the
rest, and so do its maintainers when they look for a fault of the script.

Do not set one of them for a single call. A call with its own slot size,
reserve, or lock directory does not share the queue with the other
sessions of the machine, and a call with no cap can take the memory of
all of them.

Tuning values, with their defaults:

  BOUNDED_RUN_SLOT_MIB             size of one memory slot (default 2048)
  BOUNDED_RUN_RESERVE_MIB          memory that the queue never gives out
  BOUNDED_RUN_MEMORY_WAIT_SECONDS  time between two lines of the wait for free memory (default 300)

Values for the tests of this script, and for its maintainers:

  BOUNDED_RUN_TOTAL_MIB            memory of the machine, in place of the measured value
  BOUNDED_RUN_FREE_MIB             free memory for the wait, in place of the measured free memory less the unused budgets
  BOUNDED_RUN_POLL_SECONDS         time between two tries for the slots (default 2)
  BOUNDED_RUN_SAMPLE_SECONDS       time between two memory samples (default 1)
  BOUNDED_RUN_LOCK_DIR             directory of the lock files, as an absolute path
  BOUNDED_RUN_NO_CAP               when set, do not apply the hard cap
"""
from __future__ import annotations

import fcntl
import hashlib
import math
import os
import random
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import ctypes
except ImportError:
    ctypes = None

PREFIX = "bounded-run"
EXIT_WRAPPER = 125
ACTIVE_VARIABLE = "BOUNDED_RUN_ACTIVE"
VALUE_OPTIONS = ("--memory", "--cpus", "--exclusive", "--measure-rows", "--label")
SLOT_MIB = 2048
MINIMUM_RESERVE_MIB = 2048
MINIMUM_HEADROOM_MIB = 1024
POLL_SECONDS = 2.0
LINE_SECONDS = 300.0
MEMORY_WAIT_SECONDS = 300.0
SAMPLE_SECONDS = 1.0
SCOPE_WAIT_SECONDS = 5.0
MARGIN_EXACT = 0.25
MARGIN_APPROXIMATE = 0.5
CACHE_FLOOR_DIVISOR = 4
BUDGET_STEP_MIB = 256
HELD_COMMAND_CHARACTERS = 200
PR_SET_PDEATHSIG = 1
USAGE = (
    "usage: bounded_run.py [--memory SIZE] [--cpus N] [--exclusive NAME]... [--measure] [--label NAME] -- COMMAND...\n"
    "       bounded_run.py --measure-rows N,N,... [--memory SIZE] [--exclusive NAME]... [--label NAME] -- COMMAND...\n"
    "       bounded_run.py --check [--memory SIZE]..."
)
# The exit codes of a run that a stop signal to the wrapper ended: 128 plus SIGHUP, SIGINT, SIGQUIT, or SIGTERM.
STOP_CODES = frozenset(128 + int(signum) for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGTERM))


# The first stop signal that reached the wrapper in this run of main.
_stopped_by: List[int] = []


def _note_stop(signum: int) -> None:
    if not _stopped_by:
        _stopped_by.append(int(signum))


def exit_as(code: int) -> None:
    """Ends the process with the exit code, or, when a stop signal reached the wrapper, by that signal.

    A shell stops a line of joined commands only when the command that runs dies from the signal.
    A caller that reads the status of a death by signal reads 128 plus the signal.
    """
    if _stopped_by:
        signum = _stopped_by[0]
        sys.stdout.flush()
        sys.stderr.flush()
        if signum == signal.SIGQUIT:
            # The default action of SIGQUIT also writes a core file.
            try:
                resource.setrlimit(resource.RLIMIT_CORE, (0, resource.getrlimit(resource.RLIMIT_CORE)[1]))
            except (ValueError, OSError):
                pass
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    sys.exit(code)


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


def physical_memory_mib() -> int:
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except (ValueError, OSError):
        pass
    try:
        done = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10)
        return int(done.stdout.strip()) // (1024 * 1024)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise WrapperError("cannot read the memory of the machine: %s" % error)


def _limits_upward(root: str, path: str, name: str) -> List[Tuple[int, str]]:
    found = []
    relative = path.strip("/")
    while True:
        directory = os.path.join(root, relative)
        try:
            with open(os.path.join(directory, name)) as handle:
                found.append((int(handle.read().strip()), directory))
        except (OSError, ValueError):
            pass
        if not relative:
            return found
        relative = os.path.dirname(relative)


def _cgroup_limits(proc_root: str, cgroup_root: str) -> List[Tuple[int, str, str, str]]:
    """Returns the memory limit in bytes of each level of the cgroup of this process, with the directory of
    that level and the names of its use file and of the inactive file cache line in its memory.stat."""
    try:
        with open(os.path.join(proc_root, "self", "cgroup")) as handle:
            text = handle.read()
    except (OSError, ValueError):
        return []
    limits: List[Tuple[int, str, str, str]] = []
    for line in text.splitlines():
        parts = line.strip().split(":", 2)
        if len(parts) != 3:
            continue
        if parts[0] == "0" and parts[1] == "":
            for limit, directory in _limits_upward(cgroup_root, parts[2], "memory.max"):
                limits.append((limit, directory, "memory.current", "inactive_file"))
        elif "memory" in parts[1].split(","):
            for limit, directory in _limits_upward(os.path.join(cgroup_root, "memory"), parts[2], "memory.limit_in_bytes"):
                limits.append((limit, directory, "memory.usage_in_bytes", "total_inactive_file"))
    return limits


def cgroup_limit_mib(proc_root: str = "/proc", cgroup_root: str = "/sys/fs/cgroup") -> Optional[int]:
    """Returns the smallest memory limit of the cgroup of this process and of its parents, or None."""
    limits = _cgroup_limits(proc_root, cgroup_root)
    return min(limits)[0] // (1024 * 1024) if limits else None


def _level_available(limit: int, directory: str, use_name: str, inactive_name: str) -> Optional[int]:
    try:
        with open(os.path.join(directory, use_name)) as handle:
            use = int(handle.read().strip())
        with open(os.path.join(directory, "memory.stat")) as handle:
            stat_text = handle.read()
    except (OSError, ValueError):
        return None
    # The kernel takes back the inactive file cache when the cgroup reaches its limit, so that cache is not use.
    for line in stat_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == inactive_name and parts[1].isdigit():
            return max(0, limit - max(0, use - int(parts[1]))) // (1024 * 1024)
    return None


def cgroup_available_mib(proc_root: str = "/proc", cgroup_root: str = "/sys/fs/cgroup") -> Optional[int]:
    """Returns the smallest free memory of the cgroup of this process and of its parents: the limit of a
    level less the use at that level. Returns None when the use at the smallest limit cannot be read."""
    limits = _cgroup_limits(proc_root, cgroup_root)
    if not limits:
        return None
    smallest = _level_available(*min(limits))
    if smallest is None:
        return None
    others = [_level_available(*level) for level in limits]
    return min([smallest] + [value for value in others if value is not None])


def total_memory_mib(
    proc_root: str = "/proc", cgroup_root: str = "/sys/fs/cgroup",
    read_physical: Callable[[], int] = physical_memory_mib,
) -> int:
    """Returns the physical memory, or the memory limit of the cgroup of this process when that is smaller."""
    physical = read_physical()
    # Cgroup version 1 writes a number near 2**63 when the cgroup has no limit.
    limit = cgroup_limit_mib(proc_root, cgroup_root)
    return physical if limit is None else min(physical, limit)


def default_reserve_mib(total_mib: int) -> int:
    return max(MINIMUM_RESERVE_MIB, total_mib // 4)


def headroom_mib(total_mib: int, budget_mib: int, queue_mib: int) -> int:
    """Returns the memory that the wait for free memory keeps free beside the budget for the programs outside the queue.

    The budget and the headroom together never need more than queue_mib, so a budget of the whole queue gets no headroom.
    """
    # The reserve of the queue already keeps memory for the programs outside it.
    return max(0, min(max(MINIMUM_HEADROOM_MIB, total_mib // 10), queue_mib - budget_mib))


def slot_count(total_mib: int, slot_mib: int, reserve_mib: int) -> int:
    return max(1, (total_mib - reserve_mib) // slot_mib)


def queue_mib(total_mib: int, slot_mib: int, reserve_mib: int) -> int:
    """Returns the most memory that the commands of the queue hold together."""
    after_reserve = total_mib - reserve_mib
    if after_reserve >= slot_mib:
        return slot_count(total_mib, slot_mib, reserve_mib) * slot_mib
    if after_reserve > 0:
        return after_reserve
    return max(1, min(total_mib, slot_mib))


def slots_needed(budget_mib: int, slot_mib: int, count: int) -> int:
    return min(count, max(1, -(-budget_mib // slot_mib)))


def default_budget_mib(total_mib: int, slot_mib: int) -> int:
    return max(1, min(total_mib, max(1, math.ceil(total_mib / 4 / slot_mib)) * slot_mib))


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
        free = environ.get("BOUNDED_RUN_FREE_MIB")
        self.free_mib = int(_number(environ, "BOUNDED_RUN_FREE_MIB", 0)) if free else None
        if self.slot_mib <= 0:
            raise WrapperError("BOUNDED_RUN_SLOT_MIB must be more than zero")
        # A loop that sleeps for zero seconds never ends its wait and takes a full processor.
        if self.poll_seconds <= 0:
            raise WrapperError("BOUNDED_RUN_POLL_SECONDS must be more than zero")
        if self.sample_seconds <= 0:
            raise WrapperError("BOUNDED_RUN_SAMPLE_SECONDS must be more than zero")


def _number(environ: Mapping[str, str], name: str, fallback: float) -> float:
    text = environ.get(name)
    if text is None or text == "":
        return fallback
    try:
        value = float(text)
    except ValueError:
        raise WrapperError("cannot read %s='%s'; use a number" % (name, text))
    if not math.isfinite(value):
        raise WrapperError("cannot read %s='%s'; use a number" % (name, text))
    if value < 0:
        raise WrapperError("%s must not be less than zero" % name)
    return value


def lock_directory(environ: Mapping[str, str], uid: int) -> str:
    override = environ.get("BOUNDED_RUN_LOCK_DIR")
    if override:
        if not os.path.isabs(override):
            raise WrapperError("cannot use BOUNDED_RUN_LOCK_DIR='%s'; use an absolute path" % override)
        return override
    runtime = environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isabs(runtime):
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
        try:
            os.chmod(path, 0o700)
        except OSError as error:
            raise WrapperError("cannot use the lock directory %s: %s" % (path, error))


def repository_id(directory: str) -> str:
    root = os.path.realpath(directory)
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=directory, capture_output=True, text=True, timeout=10,
            env=dict(os.environ, LC_ALL="C", LANGUAGE="C"),
        )
        if done.returncode == 0 and done.stdout.strip():
            root = os.path.realpath(os.path.join(directory, done.stdout.strip()))
        elif "not a git repository" not in done.stderr:
            # A fault of git in a worktree must not give that worktree a lock of its own.
            lines = done.stderr.strip().splitlines()
            raise WrapperError("cannot find the repository of %s: %s" % (directory, lines[0] if lines else "git gave no answer"))
    except FileNotFoundError:
        # A machine with no git has no worktrees, so the directory names the repository.
        pass
    except (OSError, subprocess.TimeoutExpired) as error:
        # The directory in place of the repository gives each worktree a lock of its own.
        raise WrapperError("cannot find the repository of %s: %s" % (directory, error))
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


def _open_lock_file(path: str) -> int:
    try:
        return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as error:
        raise WrapperError("cannot open %s: %s" % (path, error.strerror if error.strerror else error))


def _is_the_file_at(path: str, descriptor: int) -> bool:
    try:
        return os.path.samestat(os.stat(path), os.fstat(descriptor))
    except OSError:
        return False


def _refresh(descriptor: int) -> None:
    # A cleaner of a temporary directory deletes a file by its age, also while a lock is held on it.
    try:
        os.utime(descriptor)
    except (OSError, TypeError, NotImplementedError):
        pass


def _lock(path: str, wait: bool) -> Optional[int]:
    """Locks the file that the path names now. Returns None when wait is false and the lock is held."""
    while True:
        descriptor = _open_lock_file(path)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return None
        except OSError as error:
            os.close(descriptor)
            raise _lock_error(path, error)
        except BaseException:
            os.close(descriptor)
            raise
        # A file that was deleted after the open is locked by this process only: the next caller makes a new one.
        if _is_the_file_at(path, descriptor):
            _refresh(descriptor)
            return descriptor
        os.close(descriptor)


def _try_lock(path: str) -> Optional[int]:
    return _lock(path, wait=False)


def _lock_error(path: str, error: OSError) -> WrapperError:
    error_text = error.strerror if error.strerror else str(error)
    return WrapperError("cannot lock %s: %s. The lock directory must be on a filesystem that supports file locks." % (path, error_text))


def try_reserve(directory: str, count: int, needed: int, exclusive_files: Sequence[str]) -> Optional[Reservation]:
    turn_path = os.path.join(directory, "reserve.lock")
    turn = _lock(turn_path, wait=True)
    held: List[int] = []
    try:
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


def _names_free(directory: str, exclusive_files: Sequence[str]) -> bool:
    for name in exclusive_files:
        descriptor = _try_lock(os.path.join(directory, name))
        if descriptor is None:
            return False
        os.close(descriptor)
    return True


def _free_slots(directory: str, count: int, wait: bool = True) -> Optional[int]:
    """Returns the number of free slots, or None when wait is false and a waiter holds the turn lock."""
    turn = _lock(os.path.join(directory, "reserve.lock"), wait=wait)
    if turn is None:
        return None
    try:
        free = 0
        for index in range(count):
            descriptor = _try_lock(os.path.join(directory, "slot-%03d.lock" % index))
            if descriptor is not None:
                os.close(descriptor)
                free += 1
        return free
    finally:
        os.close(turn)


def reserve(
    directory: str, count: int, needed: int, exclusive_files: Sequence[str], poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    line_seconds: float = LINE_SECONDS,
) -> Reservation:
    """Waits in the line of all waiters, then for the slots and the exclusive names, and holds them.

    Only the waiter at the head of the line tries for slots, so a command that arrives later cannot
    take the slots that the head waits for. The head leaves the line when no slot comes free for
    line_seconds, so a command that never ends cannot stop the whole queue.
    """
    announced: List[bool] = []

    def announce() -> None:
        if not announced:
            log("waiting for %d of %d slot(s)" % (needed, count))
            announced.append(True)

    def pause() -> None:
        sleep(poll_seconds * (0.5 + random.random()))

    line_path = os.path.join(directory, "line.lock")
    behind = False
    while True:
        # A name held by a command that does not end would stop the whole line.
        while not _names_free(directory, exclusive_files):
            announce()
            pause()
        line = _lock(line_path, wait=False)
        if line is None:
            announce()
            if not behind:
                log("waiting behind other commands in the line")
                behind = True
            line = _lock(line_path, wait=True)
        try:
            reservation = None
            most_free = -1
            since = clock()
            while True:
                reservation = try_reserve(directory, count, needed, exclusive_files)
                if reservation is not None or not _names_free(directory, exclusive_files):
                    break
                free = _free_slots(directory, count)
                if free > most_free:
                    most_free, since = free, clock()
                elif clock() - since >= line_seconds:
                    log("no slot came free for %ds; letting the commands behind this one try first" % line_seconds)
                    break
                announce()
                pause()
        finally:
            os.close(line)
        if reservation is not None:
            log("holding %d of %d slot(s)" % (needed, count))
            return reservation
        # The waiters behind this one need a moment to take the line before this one asks again.
        pause()


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


def available_memory_mib(proc_root: str = "/proc", cgroup_root: str = "/sys/fs/cgroup") -> Optional[int]:
    """Returns the free memory of the machine, or the free memory of the cgroup of this process when that is smaller."""
    try:
        with open(os.path.join(proc_root, "meminfo")) as handle:
            meminfo = handle.read()
    except OSError:
        try:
            done = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return parse_vm_stat(done.stdout)
    found = [value for value in (parse_meminfo(meminfo), cgroup_available_mib(proc_root, cgroup_root)) if value is not None]
    return min(found) if found else None


def memory_fits(budget_mib: int, available: Optional[int], outstanding: Optional[int], headroom_mib: int) -> bool:
    """Returns whether a command of the budget may start. True when the free memory is not known."""
    return available is None or available - (outstanding or 0) - headroom_mib >= budget_mib


def wait_for_memory(
    budget_mib: int, interval_seconds: float, poll_seconds: float, headroom_mib: int = 0,
    read_available: Callable[[], Optional[int]] = available_memory_mib,
    read_outstanding: Callable[[], Optional[int]] = lambda: None,
    sleep: Callable[[float], None] = time.sleep,
    lock: Callable[[], None] = lambda: None,
    unlock: Callable[[], None] = lambda: None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Returns when the free memory, less the unused budgets of running commands and the headroom, holds the budget.

    There is no time limit, so the call can block for as long as the machine is full. Returns at once when
    the free memory cannot be read. read_outstanding gives None where the unused budgets cannot be counted.
    The call returns with lock held: the caller calls unlock once the new command counts in read_outstanding.
    """
    started = clock()
    next_line: Optional[float] = None
    while True:
        lock()
        # A running command that grows or shrinks during the reads moves both values. The larger of the two unused
        # counts around the free memory is the one that matches it or errs on the safe side.
        before = read_outstanding()
        available = read_available()
        if available is None:
            log("cannot read the free memory; starting")
            return
        after = read_outstanding()
        outstanding = None if before is None or after is None else max(before, after)
        counted = "unused running budgets not counted here" if outstanding is None else "%d MiB of running budgets unused" % outstanding
        state = "%d MiB free, %s, %d MiB headroom, budget %d MiB" % (available, counted, headroom_mib, budget_mib)
        if memory_fits(budget_mib, available, outstanding, headroom_mib):
            log(state + "; starting")
            return
        waited = clock() - started
        if next_line is None or waited >= next_line:
            log(state + ("; waiting" if next_line is None else "; still waiting after %ds" % waited))
            next_line = waited + interval_seconds
        unlock()
        sleep(poll_seconds)


def cap_prefix(budget_mib: int, cpus: Optional[int], unit: str, oom_policy: bool = True) -> List[str]:
    prefix = [
        "systemd-run", "--user", "--scope", "--quiet", "--collect", "--unit", unit,
        "-p", "MemoryMax=%dM" % budget_mib,
        "-p", "MemorySwapMax=0",
    ]
    if oom_policy:
        prefix += ["-p", "OOMPolicy=continue"]
    if cpus is not None:
        prefix += ["-p", "CPUQuota=%d%%" % (cpus * 100)]
    return prefix + ["--"]


def probe_cap(
    prefix: Sequence[str], platform: str = sys.platform,
    which: Callable[[str], Optional[str]] = shutil.which,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> Optional[str]:
    """Runs a short command under the prefix. Returns None when the prefix does not work here, else the
    text of /proc/self/cgroup inside the probe scope, which can be empty."""
    if not platform.startswith("linux") or which("systemd-run") is None:
        return None
    try:
        done = run(list(prefix) + ["cat", "/proc/self/cgroup"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout or ""


def choose_cap_prefix(
    budget_mib: int, cpus: Optional[int], unit: str,
    probe: Callable[[Sequence[str]], Optional[str]],
) -> Optional[Tuple[List[str], str]]:
    """Returns the prefix of the hard cap for the unit and the output of its probe, or None when no cap is usable here."""
    # A scope unit accepts OOMPolicy= from systemd 253; an older systemd rejects the whole prefix.
    for oom_policy in (True, False):
        found = probe(cap_prefix(budget_mib, cpus, unit + "-probe", oom_policy))
        if found is not None:
            return cap_prefix(budget_mib, cpus, unit, oom_policy), found
    return None


def _unified_path(cgroup_text: str) -> Optional[str]:
    for line in cgroup_text.splitlines():
        if line.startswith("0::"):
            return line.strip()[3:]
    return None


def scope_parent_directory(probe_output: str, cgroup_root: str = "/sys/fs/cgroup") -> Optional[str]:
    """Returns the directory that holds the scope of the probe, or None without a cgroup version 2 line."""
    path = _unified_path(probe_output)
    return None if path is None else os.path.dirname(cgroup_root + path)


def own_scope_name(proc_root: str = "/proc") -> Optional[str]:
    """Returns the name of the cgroup of this process, or None when it cannot be read."""
    try:
        with open(os.path.join(proc_root, "self", "cgroup")) as handle:
            path = _unified_path(handle.read())
    except OSError:
        return None
    return None if path is None else os.path.basename(path)


def _bounded_scopes(parent: str, skip: Sequence[str]) -> List[str]:
    """Returns the names of the scopes of bounded commands in parent, less the probe scopes and the names in skip."""
    try:
        names = os.listdir(parent)
    except OSError:
        return []
    return sorted(
        name for name in names
        if name.startswith(PREFIX + "-") and name.endswith(".scope") and not name.endswith("-probe.scope") and name not in skip
    )


def unused_budget_mib(parent: str, skip: Sequence[str]) -> int:
    """Returns the part of their budgets that the bounded commands whose scopes are in parent do not use yet.

    Probe scopes, the scopes named in skip, and scopes with no memory limit add nothing.
    """
    unused = 0
    for name in _bounded_scopes(parent, skip):
        try:
            with open(os.path.join(parent, name, "memory.max")) as handle:
                limit = handle.read().strip()
            with open(os.path.join(parent, name, "memory.current")) as handle:
                current = int(handle.read().strip())
            if limit == "max":
                continue
            unused += max(0, int(limit) - current)
        except (OSError, ValueError):
            # A scope ends between the listing and the read.
            continue
    return unused // (1024 * 1024)


def _scope_counts(path: str) -> bool:
    try:
        with open(os.path.join(path, "memory.max")) as handle:
            limit = handle.read().strip()
        with open(os.path.join(path, "memory.current")) as handle:
            int(handle.read().strip())
    except (OSError, ValueError):
        return False
    return limit.isdigit()


def wait_for_scope(
    parent: str, unit: str, limit_seconds: float,
    sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Returns True when the scope of the unit is in parent with its memory limit, as unused_budget_mib counts it,
    or False when it is not there after limit_seconds."""
    path = os.path.join(parent, unit + ".scope")
    deadline = clock() + limit_seconds
    # systemd makes the directory of the scope before it writes the limit.
    while not _scope_counts(path):
        if clock() >= deadline:
            return False
        sleep(0.02)
    return True


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return None


def _process_age_seconds(pid: int, proc_root: str, ticks: int) -> Optional[int]:
    stat_text = _read_text(os.path.join(proc_root, str(pid), "stat"))
    uptime = _read_text(os.path.join(proc_root, "uptime"))
    try:
        # The name of the process can hold spaces and ')', so the fields are counted from its last ')'.
        start = int(stat_text.rsplit(")", 1)[1].split()[19])
        return max(0, int(float(uptime.split()[0]) - start / ticks))
    except (AttributeError, IndexError, ValueError):
        return None


def _one_line(text: str) -> str:
    # The check prints one line for each command: a line break in an argument or a path would split the line,
    # and a control character would act on the terminal.
    return "".join(character if character.isprintable() else "?" for character in " ".join(text.split()))


def _held_command(pid: int, proc_root: str) -> Optional[str]:
    text = _read_text(os.path.join(proc_root, str(pid), "cmdline"))
    if not text:
        return None
    arguments = text.rstrip("\0").split("\0")
    if "--inside-cap" in arguments:
        at = arguments.index("--inside-cap")
        if arguments[at + 3:at + 4] == ["--"]:
            arguments = arguments[at + 4:]
    return _one_line(" ".join(arguments))[:HELD_COMMAND_CHARACTERS]


def held_commands(parent: str, skip: Sequence[str], proc_root: str = "/proc", ticks: Optional[int] = None) -> List[str]:
    """Returns one text for each running bounded command whose scope is in parent, as the fields of a check line.

    A field that cannot be read is '-'. Probe scopes and the scopes named in skip give no text.
    """
    if ticks is None:
        ticks = os.sysconf("SC_CLK_TCK")

    def mib(text: Optional[str]) -> str:
        return "%dM" % (int(text) // (1024 * 1024)) if text is not None and text.strip().isdigit() else "-"

    held = []
    for name in _bounded_scopes(parent, skip):
        directory = os.path.join(parent, name)
        limit = _read_text(os.path.join(directory, "memory.max"))
        current = _read_text(os.path.join(directory, "memory.current"))
        pids = [int(line) for line in (_read_text(os.path.join(directory, "cgroup.procs")) or "").split() if line.isdigit()]
        if not os.path.isdir(directory):
            # The scope ended while it was read.
            continue
        # The wrapper starts the first process of the scope, and that process starts the command.
        pid = min(pids) if pids else None
        age = _process_age_seconds(pid, proc_root, ticks) if pid is not None else None
        try:
            working = os.readlink(os.path.join(proc_root, str(pid), "cwd")) if pid is not None else None
        except OSError:
            working = None
        if working is not None:
            working = _one_line(working)
        command = _held_command(pid, proc_root) if pid is not None else None
        held.append("unit=%s budget=%s used=%s age=%s dir=%s command=%s" % (
            name[:-len(".scope")], mib(limit), mib(current), "-" if age is None else "%ds" % age,
            working or "-", command or "-"))
    return held


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


# The kernel cannot take back these pages at once to keep a cgroup under its limit: dirty and writeback file pages
# must reach the disk first. An older kernel has no 'kernel' line, and there its parts stand in for it.
HELD_FIELDS = ("anon", "shmem", "file_dirty", "file_writeback")
KERNEL_PARTS = ("kernel_stack", "pagetables", "sec_pagetables", "slab_unreclaimable", "sock", "percpu", "vmalloc")


def cgroup_held_mib(directory: str) -> Optional[int]:
    """Returns the memory of the cgroup that the kernel cannot take back at once, from its memory.stat.

    Returns None when the file cannot be read or has none of the lines of that memory.
    """
    text = _read_text(os.path.join(directory, "memory.stat"))
    if text is None:
        return None
    fields = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            fields[parts[0]] = int(parts[1])
    if "kernel" in fields:
        # The 'kernel' line also counts the reclaimable slab, the cache of file names and inodes.
        fields["kernel"] = max(0, fields["kernel"] - fields.get("slab_reclaimable", 0))
    names = HELD_FIELDS + (("kernel",) if "kernel" in fields else KERNEL_PARTS)
    found = [fields[name] for name in names if name in fields]
    return math.ceil(sum(found) / (1024 * 1024)) if found else None


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


def _with_margin(mib: int, approximate: bool) -> int:
    margin = MARGIN_APPROXIMATE if approximate else MARGIN_EXACT
    return max(1, math.ceil(mib * (1 + margin) / BUDGET_STEP_MIB)) * BUDGET_STEP_MIB


def suggested_budget_mib(peak_mib: int, approximate: bool, held_mib: Optional[int] = None) -> int:
    """Returns the suggested budget in MiB for a command with the peak. An approximate peak gets the larger margin.

    held_mib is the sampled peak of the memory that the kernel cannot take back at once. With it, the budget
    covers that memory and a quarter of the peak, and it is never more than the budget from the peak alone.
    """
    from_peak = _with_margin(peak_mib, approximate)
    if held_mib is None:
        return from_peak
    # A command that reads the same files again and again slows down when the cap leaves no room for their cache.
    cache_floor = _with_margin(math.ceil(peak_mib / CACHE_FLOOR_DIVISOR), approximate)
    return min(from_peak, max(_with_margin(held_mib, True), cache_floor))


def _larger(current: Optional[int], read: Callable[[], Optional[int]]) -> Optional[int]:
    try:
        value = read()
    except Exception:
        value = None
    if value is not None and (current is None or value > current):
        return value
    return current


class PeakTracker(threading.Thread):
    """Keeps the largest sample of read_sample in peak, and of read_held in held, until finish.

    held stays None without read_held or when read_held gives no value.
    """

    def __init__(
        self, read_sample: Callable[[], Optional[int]], interval: float,
        read_held: Optional[Callable[[], Optional[int]]] = None,
    ) -> None:
        super().__init__(daemon=True)
        self.read_sample = read_sample
        self.read_held = read_held
        self.interval = interval
        self.peak: Optional[int] = None
        self.held: Optional[int] = None
        self.done = threading.Event()

    def run(self) -> None:
        while True:
            self.sample()
            if self.done.wait(self.interval):
                return

    def sample(self) -> None:
        self.peak = _larger(self.peak, self.read_sample)
        if self.read_held is not None:
            self.held = _larger(self.held, self.read_held)

    def finish(self) -> Optional[int]:
        self.done.set()
        self.join(timeout=15)
        return self.peak


def exit_code_of(status: int) -> int:
    code = os.waitstatus_to_exitcode(status)
    if code < 0:
        return 128 - code
    return code


def parent_death_signal(platform: str = sys.platform) -> Optional[Callable[[], None]]:
    """Returns a preexec_fn that makes the kernel kill the child when this process stops, or None where no such call exists.

    The kernel ties the signal to the thread that starts the child, and preexec_fn is safe only
    while this process has no other thread: call Popen from the main thread before a tracker starts.
    """
    # macOS has no parent-death signal: there a command lives on after a hard kill of the wrapper.
    if ctypes is None or not platform.startswith("linux"):
        return None
    try:
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return None
    parent = os.getpid()
    kill = int(signal.SIGKILL)

    def set_signal() -> None:
        if prctl(PR_SET_PDEATHSIG, kill, 0, 0, 0) != 0:
            os.write(2, ("%s: WARNING: cannot set the parent-death signal; the command lives on after a hard kill of the wrapper\n" % PREFIX).encode())
        # A parent that stopped before the call sends no signal; the child then has a new parent.
        if os.getppid() != parent:
            os._exit(EXIT_WRAPPER)

    return set_signal


def _group_runs(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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

    previous = {signum: signal.signal(signum, forward) for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)}
    try:
        try:
            process = subprocess.Popen(list(command), env=dict(environ), start_new_session=True, preexec_fn=parent_death_signal())
        except OSError as error:
            raise WrapperError("cannot start '%s': %s" % (command[0], error))
        started.append(process.pid)
        try:
            if received:
                try:
                    os.killpg(process.pid, received[0] if len(received) == 1 else signal.SIGKILL)
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
        if not received and _group_runs(process.pid):
            log("WARNING: the command left a process that still runs; the queue does not count its memory")
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    if received:
        _note_stop(received[0])
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
    early: List[int] = []
    started: List[int] = []

    def keep_running(signum: int, frame: object) -> None:
        # The wrapper sends a signal to the process group, so the command gets its own copy once it runs.
        if not started:
            early.append(signum)

    previous = {signum: signal.signal(signum, keep_running) for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)}
    try:
        try:
            process = subprocess.Popen(list(command), preexec_fn=parent_death_signal())
        except OSError as error:
            log("cannot start '%s': %s" % (command[0], error))
            return EXIT_WRAPPER
        started.append(process.pid)
        if early:
            try:
                os.kill(process.pid, early[0] if len(early) == 1 else signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        _, status = os.waitpid(process.pid, 0)
        process.returncode = exit_code_of(status)
        # After the kernel kills a process of the scope for memory, systemd can stop the scope with SIGTERM.
        directory = cgroup_directory(os.getpid(), unit, proc_root, cgroup_root)
        peak = cgroup_peak_mib(directory, names=("memory.peak",)) if directory is not None else None
        if peak is not None:
            try:
                with open(peak_file, "w") as handle:
                    handle.write("%d\n" % peak)
            except OSError:
                pass
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
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
        self.rows: List[int] = []
        self.label: Optional[str] = None
        self.command: List[str] = []
        self.check = False
        self.budgets: List[int] = []


def _check_option_given(flags: Sequence[str]) -> bool:
    position = 0
    while position < len(flags):
        if flags[position] == "--check":
            return True
        position += 2 if flags[position] in VALUE_OPTIONS else 1
    return False


def _parse_check(flags: Sequence[str], has_command: bool) -> Options:
    options = Options()
    options.check = True
    if has_command:
        raise WrapperError("--check runs no command; remove the '--' and the command\n" + USAGE)
    remaining = list(flags)
    while remaining:
        flag = remaining.pop(0)
        if flag == "--check":
            continue
        if flag != "--memory":
            raise WrapperError("--check takes only --memory, not '%s'\n%s" % (flag, USAGE))
        if not remaining:
            raise WrapperError("the option '--memory' needs a value\n" + USAGE)
        options.budgets.append(parse_size_mib(remaining.pop(0)))
    return options


def parse_arguments(argv: Sequence[str]) -> Options:
    options = Options()
    arguments = list(argv)
    split = arguments.index("--") if "--" in arguments else len(arguments)
    if _check_option_given(arguments[:split]):
        return _parse_check(arguments[:split], split < len(arguments))
    if "--" not in arguments:
        raise WrapperError("the '--' before the command is missing\n" + USAGE)
    options.command = arguments[split + 1:]
    if not options.command:
        raise WrapperError("the command is missing\n" + USAGE)
    flags = arguments[:split]
    while flags:
        flag = flags.pop(0)
        if flag == "--measure":
            options.measure = True
            continue
        if flag not in VALUE_OPTIONS:
            raise WrapperError("cannot read the option '%s'\n%s" % (flag, USAGE))
        if not flags:
            raise WrapperError("the option '%s' needs a value\n%s" % (flag, USAGE))
        value = flags.pop(0)
        if flag == "--memory":
            options.memory = value
        elif flag == "--exclusive":
            if value not in options.exclusive:
                options.exclusive.append(value)
        elif flag == "--label":
            # The row line separates its fields with spaces and marks a missing label with '-'.
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is None:
                raise WrapperError("cannot use the label '%s'; use letters, digits, '.', '_' and '-', and start with a letter or a digit" % value)
            options.label = value
        elif flag == "--measure-rows":
            parts = value.split(",")
            # int() of a very long number is slow on some versions of Python and raises ValueError on others.
            rows = [int(part) for part in parts if re.fullmatch(r"[0-9]{1,6}", part)]
            if len(rows) != len(parts) or min(rows) < 1:
                raise WrapperError("cannot read --measure-rows '%s'; use whole numbers from 1 to 999999, such as 16,8,4" % value)
            options.rows = sorted(set(rows), reverse=True)
            options.measure = True
        else:
            if not value.isdigit() or int(value) < 1:
                raise WrapperError("cannot read --cpus '%s'; use a whole number of 1 or more" % value)
            options.cpus = int(value)
    if options.rows and options.cpus is not None:
        raise WrapperError("use --measure-rows or --cpus, not both\n" + USAGE)
    if options.label is not None and not options.measure:
        raise WrapperError("--label needs --measure or --measure-rows\n" + USAGE)
    return options


class _Stopped(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _raise_stopped(signum: int, frame: object) -> None:
    raise _Stopped(signum)


def bounded(options: Options, environ: Mapping[str, str]) -> int:
    if not options.rows:
        return bounded_once(options, environ)[0]
    # run_command sets its own handlers while a row runs and puts these back after it.
    previous = {signum: signal.signal(signum, _raise_stopped) for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)}
    try:
        return _bounded_rows(options, environ)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _bounded_rows(options: Options, environ: Mapping[str, str]) -> int:
    memory = options.memory
    result = 0
    measured = 0
    try:
        for cpus in options.rows:
            row = Options()
            row.memory, row.cpus, row.exclusive, row.measure, row.label, row.command = (
                memory, cpus, options.exclusive, True, options.label, options.command)
            code, suggested = bounded_once(row, environ)
            measured += 1
            if code in STOP_CODES:
                log("stopped by a signal; the rows after --cpus %d are not measured" % cpus)
                return result or code
            if code == 0:
                memory = "%dM" % suggested
            else:
                # A run that stopped early has a peak that is too small to be the budget of a smaller command.
                result = result or code
    except (KeyboardInterrupt, _Stopped) as stop:
        # A signal while a row runs comes back as its exit code. A signal at any other time in the list raises.
        signum = stop.signum if isinstance(stop, _Stopped) else int(signal.SIGINT)
        _note_stop(signum)
        log("stopped by a signal; %d of %d rows are measured" % (measured, len(options.rows)))
        return result or 128 + signum
    return result


def bounded_once(options: Options, environ: Mapping[str, str]) -> Tuple[int, int]:
    """Runs the command one time. Returns the exit code and the suggested budget in MiB."""
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
    if settings.reserve_mib >= settings.total_mib:
        log("WARNING: the reserve of %d MiB leaves no memory of the %d MiB of the machine; the queue does not keep the reserve" % (settings.reserve_mib, settings.total_mib))
    most = queue_mib(settings.total_mib, settings.slot_mib, settings.reserve_mib)
    if budget > most:
        log("WARNING: the budget of %d MiB is more than the %d MiB of the queue; the budget is %d MiB" % (budget, most, most))
        budget = most
    wait_budget = budget
    uid = os.getuid()
    directory = lock_directory(environ, uid)
    ensure_lock_directory(directory, uid)
    repository = ""
    if options.exclusive:
        try:
            repository = repository_id(os.getcwd())
        except OSError as error:
            raise WrapperError("cannot read the working directory for --exclusive: %s" % error)
    exclusive_files = [exclusive_file_name(repository, name) for name in options.exclusive]

    unit = "%s-%d-%06x" % (PREFIX, os.getpid(), random.randrange(16 ** 6))
    choice = None if settings.no_cap else choose_cap_prefix(budget, options.cpus, unit, probe_cap)
    prefix = choice[0] if choice is not None else None
    capped = prefix is not None
    if options.measure and options.memory is None and not capped:
        # The peak of this command is not known yet, and without the cap only the queue keeps it from the other commands.
        budget, needed = most, count
    # Every scope of the user that systemd-run makes with no slice option goes to the slice of the probe.
    scopes = scope_parent_directory(choice[1]) if choice is not None else None
    # A wrapper that runs inside a bounded scope does its work in the budget of that scope.
    skip = [name for name in (unit + ".scope", own_scope_name()) if name is not None]

    def read_available() -> Optional[int]:
        return available_memory_mib() if settings.free_mib is None else settings.free_mib

    def read_outstanding() -> Optional[int]:
        if settings.free_mib is not None or scopes is None:
            return None
        return unused_budget_mib(scopes, skip)

    peak_file = os.path.join(directory, "peak-%s" % unit)
    if prefix is not None:
        inside = [sys.executable, os.path.abspath(__file__), "--inside-cap", peak_file, unit, "--"]
        command = prefix + inside + command
    else:
        log("no hard cap is available here; the queue and the wait for free memory are the full protection")

    child_environ: Dict[str, str] = dict(environ)
    child_environ[ACTIVE_VARIABLE] = "1"
    child_environ["BOUNDED_RUN_MEMORY_MIB"] = str(budget)
    child_environ["BOUNDED_RUN_CPUS"] = str(options.cpus if options.cpus is not None else (os.cpu_count() or 1))

    trackers: List[PeakTracker] = []

    def start_tracker(pid: int) -> None:
        if capped:
            def read_sample() -> Optional[int]:
                found = cgroup_directory(pid, unit)
                return cgroup_peak_mib(found) if found is not None else None

            def read_held() -> Optional[int]:
                found = cgroup_directory(pid, unit)
                return cgroup_held_mib(found) if found is not None else None
            interval = min(settings.sample_seconds, 0.5)
        else:
            def read_sample() -> Optional[int]:
                return group_rss_mib(pid)
            read_held = None
            interval = settings.sample_seconds
        tracker = PeakTracker(read_sample, interval, read_held)
        tracker.start()
        trackers.append(tracker)

    # Without one lock over the check and the start, two wrappers with different slots both pass the check before either scope counts.
    memory_lock_path = os.path.join(directory, "memory.lock")
    memory_lock: List[int] = []

    def lock_memory() -> None:
        descriptor = _lock(memory_lock_path, wait=True)
        if descriptor is not None:
            memory_lock.append(descriptor)

    def unlock_memory() -> None:
        while memory_lock:
            os.close(memory_lock.pop())

    def on_start(pid: int) -> None:
        start_tracker(pid)
        if scopes is not None and memory_lock:
            if not wait_for_scope(scopes, unit, SCOPE_WAIT_SECONDS):
                log("the scope of the command did not appear after %ds; the next command may not count its budget" % SCOPE_WAIT_SECONDS)
        unlock_memory()

    reported: Optional[int] = None
    reservation = reserve(directory, count, needed, exclusive_files, settings.poll_seconds)
    try:
        wait_for_memory(
            wait_budget, settings.memory_wait_seconds, settings.poll_seconds,
            headroom_mib=headroom_mib(settings.total_mib, wait_budget, most),
            read_available=read_available, read_outstanding=read_outstanding,
            lock=lock_memory, unlock=unlock_memory,
        )
        code, maxrss = run_command(command, child_environ, on_start)
        tracked = trackers[0].finish() if trackers else None
        held = trackers[0].held if trackers else None
    finally:
        unlock_memory()
        if capped:
            reported = read_peak_file(peak_file)
        reservation.release()

    exact = reported is not None
    peak = max(reported or tracked or 0, rusage_peak_mib(maxrss))
    log("budget %d MiB, peak %d MiB (%s), held %s, exit %d" % (
        budget, peak, "cgroup" if exact else "sampled, approximate", "-" if held is None else "%d MiB (sampled)" % held, code))
    if capped and code == 137:
        log("the command was killed; if the peak is near the budget, the hard cap stopped it")
    suggested = suggested_budget_mib(peak, not exact, held)
    if options.measure:
        log("suggested budget %d MiB" % suggested)
        log("row label=%s cpus=%s budget=%dM peak=%dM held=%s exact=%s exit=%d" % (
            options.label or "-", options.cpus if options.cpus is not None else "-", suggested, peak,
            "-" if held is None else "%dM" % held, "yes" if exact else "no", code))
    return code, suggested


def check(
    budgets: Sequence[int], environ: Mapping[str, str],
    read_available: Callable[[], Optional[int]] = available_memory_mib,
    read_outstanding: Optional[Callable[[], Optional[int]]] = None,
) -> int:
    """Prints the state of the queue and, for each budget in MiB, whether a run of that budget would start now.

    Takes no reservation and holds no lock when it returns. read_outstanding gives the unused budgets of the
    running commands, or None where they cannot be counted; by default the check finds them as a run does.
    """
    settings = Settings(environ)
    count = slot_count(settings.total_mib, settings.slot_mib, settings.reserve_mib)
    most = queue_mib(settings.total_mib, settings.slot_mib, settings.reserve_mib)
    uid = os.getuid()
    directory = lock_directory(environ, uid)
    ensure_lock_directory(directory, uid)
    unit = "%s-%d-%06x" % (PREFIX, os.getpid(), random.randrange(16 ** 6))
    # The probe can take seconds, so the state of the queue is read after it.
    choice = None if settings.no_cap else choose_cap_prefix(settings.slot_mib, None, unit, probe_cap)
    # A waiter tries for slots only while it holds the turn lock, so a count under that lock never makes a free slot look held to it.
    free_slots = _free_slots(directory, count, wait=False)
    line = _try_lock(os.path.join(directory, "line.lock"))
    if line is not None:
        os.close(line)
    scopes = scope_parent_directory(choice[1]) if choice is not None else None
    if read_outstanding is None:
        # A wrapper that starts on its own counts every bounded scope, also the one that this check runs in.
        def read_outstanding() -> Optional[int]:
            return None if scopes is None else unused_budget_mib(scopes, ())

    if settings.free_mib is None:
        before = read_outstanding()
        available = read_available()
        after = read_outstanding()
        outstanding = None if before is None or after is None else max(before, after)
    else:
        available, outstanding = settings.free_mib, None

    def mib(value: Optional[int]) -> str:
        return "-" if value is None else "%dM" % value

    log("check slots=%d slot=%dM free-slots=%s free=%s unused=%s line=%s" % (
        count, settings.slot_mib, "-" if free_slots is None else free_slots, mib(available), mib(outstanding),
        "free" if line is not None else "busy"))
    for held in held_commands(scopes, ()) if scopes is not None else []:
        log("check held " + held)
    for budget in budgets:
        needed = slots_needed(budget, settings.slot_mib, count)
        headroom = headroom_mib(settings.total_mib, min(budget, most), most)
        starts = (line is not None and free_slots is not None and free_slots >= needed
                  and memory_fits(min(budget, most), available, outstanding, headroom))
        log("check budget=%dM slots=%d headroom=%dM starts=%s" % (budget, needed, headroom, "yes" if starts else "no"))
    return 0


def main(argv: Optional[Sequence[str]] = None, environ: Optional[Mapping[str, str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    variables = os.environ if environ is None else environ
    del _stopped_by[:]
    try:
        if len(arguments) > 4 and arguments[0] == "--inside-cap" and arguments[3] == "--":
            return inside_cap(arguments[1], arguments[2], arguments[4:])
        options = parse_arguments(arguments)
        if options.check:
            return check(options.budgets, variables)
        if variables.get(ACTIVE_VARIABLE):
            log("nested call; running the command directly")
            try:
                os.execvpe(options.command[0], options.command, dict(variables))
            except OSError as error:
                raise WrapperError("cannot start '%s': %s" % (options.command[0], error))
        try:
            return bounded(options, variables)
        except KeyboardInterrupt:
            _note_stop(signal.SIGINT)
            log("interrupted while waiting")
            return 130
        except _Stopped as stop:
            # The handlers of --measure-rows can fire after its list ends, before they are put back.
            _note_stop(stop.signum)
            log("stopped by a signal")
            return 128 + stop.signum
    except WrapperError as error:
        log(str(error))
        return EXIT_WRAPPER


if __name__ == "__main__":
    exit_as(main())
