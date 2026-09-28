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
