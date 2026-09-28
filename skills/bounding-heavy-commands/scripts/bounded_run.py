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
