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
