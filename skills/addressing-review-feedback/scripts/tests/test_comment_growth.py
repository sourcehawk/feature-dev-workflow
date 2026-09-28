from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import comment_growth as gate  # noqa: E402


class FamilyForTest(unittest.TestCase):
    def test_extension_selects_the_family(self):
        self.assertIs(gate.family_for("pkg/server.go"), gate.SLASH)
        self.assertIs(gate.family_for("tools/run.py"), gate.HASH_DOCSTRING)
        self.assertIs(gate.family_for("db/schema.SQL"), gate.DASH)

    def test_file_name_selects_the_family_when_there_is_no_extension(self):
        self.assertIs(gate.family_for("build/Makefile"), gate.HASH)

    def test_unknown_extension_has_no_family(self):
        self.assertIsNone(gate.family_for("notes.xyz"))

    def test_prose_and_data_files_are_skipped(self):
        self.assertTrue(gate.is_skipped("README.md"))
        self.assertTrue(gate.is_skipped("package.json"))
        self.assertFalse(gate.is_skipped("main.go"))


class ScanTest(unittest.TestCase):
    def test_line_markers_form_one_block_anchored_on_the_next_code_line(self):
        source = "// first\n// second\nfunc run() {\n}\n"
        self.assertEqual(
            gate.scan(source, gate.SLASH),
            [gate.Block(1, ("// first", "// second"), "func run() {")],
        )

    def test_marker_after_code_is_not_a_comment(self):
        source = 'url := "http://example.invalid" // trailing\n'
        self.assertEqual(gate.scan(source, gate.SLASH), [])

    def test_delimited_block_runs_to_its_closing_delimiter(self):
        source = "/*\n * about\n */\nint run(void);\n"
        self.assertEqual(
            gate.scan(source, gate.SLASH),
            [gate.Block(1, ("/*", "* about", "*/"), "int run(void);")],
        )

    def test_delimited_block_on_one_line(self):
        source = "/* short */\nint run(void);\n"
        self.assertEqual(gate.scan(source, gate.SLASH), [gate.Block(1, ("/* short */",), "int run(void);")])

    def test_doc_string_anchors_on_the_line_before_it(self):
        source = 'def run(job):\n    """Runs job.\n\n    Returns the status.\n    """\n    return job()\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(2, ('"""Runs job.', "", "Returns the status.", '"""'), "def run(job):")],
        )

    def test_doc_string_on_one_line(self):
        source = 'def run(job):\n    """Runs job."""\n    return job()\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(2, ('"""Runs job."""',), "def run(job):")],
        )

    def test_blank_line_divides_two_blocks_that_share_an_anchor(self):
        source = "# license\n\n# about run\nrun() {\n"
        self.assertEqual(
            gate.scan(source, gate.HASH),
            [gate.Block(1, ("# license",), "run() {"), gate.Block(3, ("# about run",), "run() {")],
        )

    def test_block_at_the_end_of_the_file_has_no_anchor(self):
        self.assertEqual(gate.scan("x = 1\n# trailing note\n", gate.HASH), [gate.Block(2, ("# trailing note",), "")])

    def test_delimiter_that_never_closes_runs_to_the_end_of_the_file(self):
        source = "/* open\nint run(void);\n"
        self.assertEqual(gate.scan(source, gate.SLASH), [gate.Block(1, ("/* open", "int run(void);"), "")])

    def test_markup_family_has_no_line_marker(self):
        source = "<!-- about\n     the page -->\n<main>\n"
        self.assertEqual(
            gate.scan(source, gate.MARKUP),
            [gate.Block(1, ("<!-- about", "the page -->"), "<main>")],
        )

    def test_delimiter_wins_over_a_line_marker_with_the_same_start(self):
        source = "--[[\nabout\n]]\nlocal x = 1\n-- note\nlocal y = 2\n"
        self.assertEqual(
            gate.scan(source, gate.DASH),
            [gate.Block(1, ("--[[", "about", "]]"), "local x = 1"), gate.Block(5, ("-- note",), "local y = 2")],
        )

if __name__ == "__main__":
    unittest.main()
