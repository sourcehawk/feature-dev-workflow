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

def statuses(old, new, family=gate.SLASH):
    return [(f.status, f.old_length, f.new_length, f.flagged) for f in gate.compare("f", old, new, family)]


class CompareTest(unittest.TestCase):
    def test_unchanged_comment_is_not_listed(self):
        source = "// run starts the job.\nfunc run() {}\n"
        self.assertEqual(statuses(source, source), [])

    def test_comment_that_grew_is_flagged(self):
        old = "// run starts the job.\nfunc run() {}\n"
        new = "// run starts the job.\n// It also stops it.\nfunc run() {}\n"
        self.assertEqual(statuses(old, new), [(gate.GREW, 1, 2, True)])

    def test_comment_that_changed_at_the_same_length_is_listed(self):
        old = "// run starts the job.\nfunc run() {}\n"
        new = "// run starts one job.\nfunc run() {}\n"
        self.assertEqual(statuses(old, new), [(gate.CHANGED, 1, 1, False)])

    def test_comment_that_got_shorter_is_listed(self):
        old = "// run starts the job.\n// It also stops it.\nfunc run() {}\n"
        new = "// run starts the job.\nfunc run() {}\n"
        self.assertEqual(statuses(old, new), [(gate.CHANGED, 2, 1, False)])

    def test_new_comment_is_listed_and_not_flagged(self):
        old = "func run() {}\n"
        new = "// run starts the job.\nfunc run() {}\n"
        self.assertEqual(statuses(old, new), [(gate.ADDED, 0, 1, False)])

    def test_new_parameter_does_not_excuse_a_longer_comment(self):
        old = "// run starts the job.\nfunc run(job Job) error {\n}\n"
        new = "// run starts the job.\n// It waits for limit.\nfunc run(job Job, limit Duration) error {\n}\n"
        self.assertEqual(statuses(old, new), [(gate.GREW, 1, 2, True)])

    def test_unrelated_anchor_is_not_paired(self):
        old = "// run starts the job.\nfunc run(job Job) error {\n}\n"
        new = "// names lists the tenants.\n// It sorts them.\nvar names = load()\n"
        self.assertEqual(statuses(old, new), [(gate.ADDED, 0, 2, False)])

    def test_comment_moved_with_its_code_is_not_listed(self):
        old = "// a does one thing.\nfunc a() {}\n\n// b does one thing.\nfunc b() {}\n"
        new = "// b does one thing.\nfunc b() {}\n\n// a does one thing.\nfunc a() {}\n"
        self.assertEqual(statuses(old, new), [])

    def test_same_anchor_twice_pairs_only_the_changed_block(self):
        old = "func f() {\n\t// first\n\tg()\n\t// second\n\tg()\n}\n"
        new = "func f() {\n\t// first\n\tg()\n\t// second\n\t// and more\n\tg()\n}\n"
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual([(f.status, f.line, f.flagged) for f in findings], [(gate.GREW, 4, True)])

    def test_carriage_return_line_endings_are_compared_as_lines(self):
        old = "// run starts the job.\r\nfunc run() {}\r\n"
        new = "// run starts the job.\r\n// It also stops it.\r\nfunc run() {}\r\n"
        self.assertEqual(statuses(old, new), [(gate.GREW, 1, 2, True)])

    def test_doc_string_that_grew_is_flagged(self):
        old = 'def run(job):\n    """Runs job."""\n    return job()\n'
        new = 'def run(job):\n    """Runs job.\n\n    Retries two times.\n    """\n    return job()\n'
        self.assertEqual(statuses(old, new, gate.HASH_DOCSTRING), [(gate.GREW, 1, 4, True)])

    def test_file_header_that_grew_is_flagged(self):
        old = "# Tools for the build.\n\nimport os\n"
        new = "# Tools for the build.\n# Each tool reads the config.\n\nimport os\n"
        self.assertEqual(statuses(old, new, gate.HASH_DOCSTRING), [(gate.GREW, 1, 2, True)])

if __name__ == "__main__":
    unittest.main()
