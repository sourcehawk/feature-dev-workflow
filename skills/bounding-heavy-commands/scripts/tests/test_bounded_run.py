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


if __name__ == "__main__":
    unittest.main()
