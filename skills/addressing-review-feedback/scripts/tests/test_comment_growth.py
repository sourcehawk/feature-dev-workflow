from __future__ import annotations

import contextlib
import difflib
import io
import os
import random
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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


class ScanDocStringPositionTest(unittest.TestCase):
    def test_multi_line_string_constant_is_not_a_doc_string(self):
        source = (
            'QUERY = """\n'
            'SELECT * FROM t\n'
            '"""\n'
            'run()\n'
            '\n'
            'def process(job):\n'
            '    """Processes job."""\n'
            '    return job()\n'
        )
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(7, ('"""Processes job."""',), "def process(job):")],
        )

    def test_doc_string_with_a_prefix_is_still_a_doc_string(self):
        source = 'def run(job):\n    r"""Runs job."""\n    return job()\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(2, ('r"""Runs job."""',), "def run(job):")],
        )

    def test_doc_string_at_the_first_statement_of_the_file_has_no_anchor(self):
        source = '"""Module doc."""\nimport os\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(1, ('"""Module doc."""',), "")],
        )

    def test_growth_inside_a_real_doc_string_is_flagged_and_a_string_constant_change_is_not_listed(self):
        old = (
            'QUERY = """\n'
            'SELECT 1\n'
            '"""\n'
            '\n'
            'def process(job):\n'
            '    """Processes."""\n'
            '    return job()\n'
        )
        new = (
            'QUERY = """\n'
            'SELECT 2\n'
            '"""\n'
            '\n'
            'def process(job):\n'
            '    """Processes the job.\n'
            '\n'
            '    Retries once.\n'
            '    """\n'
            '    return job()\n'
        )
        findings = gate.compare("f", old, new, gate.HASH_DOCSTRING)
        self.assertEqual([(f.status, f.flagged) for f in findings], [(gate.GREW, True)])

    def test_doc_string_after_a_def_line_with_a_trailing_comment_that_grew_is_flagged(self):
        old = 'def run(job):  # noqa: C901\n    """Runs job."""\n    return job()\n'
        new = 'def run(job):  # noqa: C901\n    """Runs job.\n\n    Retries two times, then gives up.\n    """\n    return job()\n'
        self.assertEqual(statuses(old, new, gate.HASH_DOCSTRING), [(gate.GREW, 1, 4, True)])

    def test_module_doc_string_after_a_shebang_that_grew_is_flagged(self):
        old = '#!/usr/bin/env python3\n"""Syncs the cache."""\nimport os\n'
        new = '#!/usr/bin/env python3\n"""Syncs the cache.\n\nIt runs every hour and skips a locked file.\n"""\nimport os\n'
        findings = gate.compare("f", old, new, gate.HASH_DOCSTRING)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.GREW, 2, 1, 4, True)],
        )

    def test_module_doc_string_after_an_encoding_line_and_blank_lines_is_a_doc_string(self):
        source = '# -*- coding: utf-8 -*-\n\n\n"""Module doc.\n"""\nimport os\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(1, ("# -*- coding: utf-8 -*-",), "import os"), gate.Block(4, ('"""Module doc.', '"""'), "")],
        )

    def test_doc_string_after_a_def_line_over_several_lines_is_a_doc_string(self):
        source = 'def f(\n    a,\n) -> int:\n    """Adds.\n    """\n    return a\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(4, ('"""Adds.', '"""'), ") -> int:")],
        )

    def test_doc_string_after_a_class_line_is_a_doc_string(self):
        source = 'class Store(Base):  # the cache\n    """Holds.\n    """\n    size = 1\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(2, ('"""Holds.', '"""'), "class Store(Base):  # the cache")],
        )

    def test_triple_quote_at_the_start_of_a_line_outside_doc_position_opens_a_string(self):
        source = 'x = call(\n    """\n    # a line of the string\n    """,\n)\n# Runs x.\nrun(x)\n'
        self.assertEqual(gate.scan(source, gate.HASH_DOCSTRING), [gate.Block(6, ("# Runs x.",), "run(x)")])

    def test_line_of_a_string_is_never_an_anchor(self):
        source = '# Selects the rows.\nQUERY = """SELECT id\nFROM t\n"""\nrun(QUERY)\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(1, ("# Selects the rows.",), "run(QUERY)")],
        )

    def test_triple_quote_inside_a_one_line_string_opens_no_string(self):
        old = "QUOTE = '\"\"\"'\n\n\ndef strip(text):\n    # Drop the quotes.\n    return text.strip(QUOTE)\n"
        new = (
            "QUOTE = '\"\"\"'\n\n\ndef strip(text):\n"
            "    # Drop the quotes.\n"
            "    # Only the outer ones, since an inner quote is part of the text.\n"
            "    # A text with no quotes is returned as it is.\n"
            "    return text.strip(QUOTE)\n"
        )
        self.assertEqual(statuses(old, new, gate.HASH_DOCSTRING), [(gate.GREW, 1, 3, True)])

    def test_escaped_quote_does_not_end_a_one_line_string(self):
        source = 's = "\\"" + """\n# a line of the string\n"""\n# Drop the quotes.\nstrip(s)\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(4, ("# Drop the quotes.",), "strip(s)")],
        )

    def test_triple_quote_inside_a_trailing_comment_opens_no_string(self):
        source = 'x = 1  # a """ in a note\n# Drop the quotes.\nstrip(x)\n'
        self.assertEqual(
            gate.scan(source, gate.HASH_DOCSTRING),
            [gate.Block(2, ("# Drop the quotes.",), "strip(x)")],
        )

class BlockFormTest(unittest.TestCase):
    def grown(self, path, old, new):
        family = gate.family_for(path)
        return [(f.status, f.old_length, f.new_length, f.flagged) for f in gate.compare(path, old, new, family)]

    def test_block_comment_between_angle_and_hash_grows(self):
        old = "<#\nStarts the job.\n#>\nfunction Start-Job {}\n"
        new = "<#\nStarts the job.\nIt also stops it.\n#>\nfunction Start-Job {}\n"
        self.assertEqual(self.grown("job.ps1", old, new), [(gate.GREW, 3, 4, True)])

    def test_block_comment_between_begin_and_end_grows(self):
        old = "=begin\nStarts the job.\n=end\ndef start\nend\n"
        new = "=begin\nStarts the job.\nIt also stops it.\n=end\ndef start\nend\n"
        self.assertEqual(self.grown("job.rb", old, new), [(gate.GREW, 3, 4, True)])

    def test_block_comment_between_hash_and_equals_grows(self):
        old = "#=\nStarts the job.\n=#\nfunction start() end\n"
        new = "#=\nStarts the job.\nIt also stops it.\n=#\nfunction start() end\n"
        self.assertEqual(self.grown("job.jl", old, new), [(gate.GREW, 3, 4, True)])

    def test_line_comments_of_these_file_types_still_count(self):
        for path in ("job.ps1", "job.rb", "job.jl"):
            with self.subTest(path=path):
                old = "# Starts the job.\nstart()\n"
                new = "# Starts the job.\n# It also stops it.\nstart()\n"
                self.assertEqual(self.grown(path, old, new), [(gate.GREW, 1, 2, True)])


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
        self.assertEqual(statuses(old, new), [(gate.ADDED, 0, 2, False), (gate.REMOVED, 1, 0, False)])

    def test_comment_moved_with_its_code_is_not_listed(self):
        old = "// a does one thing.\nfunc a() {}\n\n// b does one thing.\nfunc b() {}\n"
        new = "// b does one thing.\nfunc b() {}\n\n// a does one thing.\nfunc a() {}\n"
        self.assertEqual(statuses(old, new), [])

    def test_same_anchor_twice_pairs_only_the_changed_block(self):
        old = "func f() {\n\t// first\n\tg()\n\t// second\n\tg()\n}\n"
        new = "func f() {\n\t// first\n\tg()\n\t// second\n\t// and more\n\tg()\n}\n"
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual([(f.status, f.line, f.flagged) for f in findings], [(gate.GREW, 4, True)])

    def test_mixed_line_endings_are_still_compared_as_lines(self):
        old = "// run starts the job.\nfunc run() {}\n"
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

    def test_module_doc_comment_with_no_anchor_that_grew_is_flagged(self):
        old = '"""Module doc."""\nimport os\n'
        new = '"""Module doc.\n\nExplains more.\n"""\nimport os\n'
        self.assertEqual(statuses(old, new, gate.HASH_DOCSTRING), [(gate.GREW, 1, 4, True)])

    def test_comment_at_the_end_of_the_file_that_grew_is_flagged(self):
        old = "x = 1\n# trailing note\n"
        new = "x = 1\n# trailing note\n# with more detail\n"
        self.assertEqual(statuses(old, new, gate.HASH), [(gate.GREW, 1, 2, True)])

    def test_new_comment_above_a_grown_comment_does_not_hide_the_growth(self):
        old = "// run starts the job.\nfunc run(job Job) error {\n}\n"
        new = (
            "// run starts a job.\n"
            "func run() {\n"
            "}\n"
            "\n"
            "// run starts the job.\n"
            "// It waits for limit.\n"
            "func run(job Job, limit Duration) error {\n"
            "}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.flagged) for f in findings],
            [(gate.ADDED, 1, False), (gate.GREW, 5, True)],
        )

    def test_new_sibling_with_a_similar_anchor_does_not_hide_the_growth(self):
        old = "// Sends one message.\nexport function send(msg: Message): void {\n}\n"
        new = (
            "// Sends a batch.\n"
            "export function sendAll(msgs: Message[]): void {\n"
            "}\n"
            "\n"
            "// Sends one message.\n"
            "// Retries when the socket closes.\n"
            "export function send(msg: Message, retry: number): void {\n"
            "}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.ADDED, 1, 0, 1, False), (gate.GREW, 5, 1, 2, True)],
        )

    def test_new_sibling_with_the_same_anchor_does_not_hide_the_growth(self):
        old = (
            "func load() error {\n"
            "\terr := read()\n"
            "\t// The file may be missing on first start.\n"
            "\tif err != nil {\n"
            "\t\treturn nil\n"
            "\t}\n"
            "\treturn nil\n"
            "}\n"
        )
        new = (
            "func save() error {\n"
            "\terr := write()\n"
            "\t// Log and continue.\n"
            "\tif err != nil {\n"
            "\t\treturn nil\n"
            "\t}\n"
            "\treturn nil\n"
            "}\n"
            "\n"
            "func load() error {\n"
            "\terr := read()\n"
            "\t// The file may be missing on first start.\n"
            "\t// A missing file means an empty store, so it is not an error.\n"
            "\tif err != nil {\n"
            "\t\treturn nil\n"
            "\t}\n"
            "\treturn nil\n"
            "}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.ADDED, 3, 0, 1, False), (gate.GREW, 12, 1, 2, True)],
        )

    def test_renamed_declaration_is_paired_by_its_comment_not_by_a_new_one_with_its_old_name(self):
        old = "// parse reads a header.\nfunc parse(b []byte) (Header, error) {\n}\n"
        new = (
            "// parse is kept for old callers.\n"
            "func parse(b []byte) (Header, error) {\n"
            "}\n"
            "\n"
            "// decode reads a header.\n"
            "// It rejects a header longer than the limit.\n"
            "func decode(b []byte, limit int) (Header, error) {\n"
            "}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.ADDED, 1, 0, 1, False), (gate.GREW, 5, 1, 2, True)],
        )

    def test_block_that_grew_with_new_words_is_flagged_beside_a_sibling_that_copies_the_old_words(self):
        old = "// Close the file.\nfunc (f *File) Close() error {\n}\n"
        new = (
            "// Close the file.\n"
            "func (f *File) CloseAll() error {\n"
            "}\n"
            "\n"
            "// Flushes pending writes first; a\n"
            "// second call is a no-op.\n"
            "func (f *File) Close() error {\n"
            "}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.CHANGED, 1, 1, 1, False), (gate.GREW, 5, 1, 2, True)],
        )

    def test_rewritten_block_that_grew_is_flagged_beside_a_sibling_with_most_of_the_old_words(self):
        old = "// Send writes the message to the socket.\nfunc Send(m Message) error {\n}\n"
        new = (
            "// SendAll writes each message to the socket.\n"
            "func SendAll(ms []Message) error {\n"
            "}\n"
            "\n"
            "// Send frames m, writes it, and retries\n"
            "// once when the write times out.\n"
            "func Send(m Message) error {\n"
            "}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.CHANGED, 1, 1, 1, False), (gate.GREW, 5, 1, 2, True)],
        )

    def test_new_blocks_above_similar_anchors_do_not_share_a_block_changed_in_place(self):
        old = "// Start starts the server.\nfunc (s *Server) Start() error {\n}\n"
        new = (
            "// Start runs the server.\nfunc (s *Server) Start() error {\n}\n\n"
            "// Stop halts the server and\n// waits for open requests.\nfunc (s *Server) Stop() error {\n}\n\n"
            "// Reload reads the config file\n// again and applies it.\nfunc (s *Server) Reload() error {\n}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.flagged) for f in findings],
            [(gate.CHANGED, 1, False), (gate.ADDED, 5, False), (gate.ADDED, 10, False)],
        )

    def test_new_doc_strings_do_not_share_a_doc_string_changed_in_place(self):
        old = 'class S:\n    def start(self):\n        """Start the server."""\n'
        new = (
            'class S:\n    def start(self):\n        """Run the server."""\n\n'
            '    def stop(self):\n        """Stop the server.\n\n        Waits for open requests.\n        """\n'
        )
        findings = gate.compare("f", old, new, gate.HASH_DOCSTRING)
        self.assertEqual([(f.status, f.line, f.flagged) for f in findings], [(gate.CHANGED, 3, False), (gate.ADDED, 6, False)])

    def test_identical_copy_of_a_block_that_grew_does_not_hide_the_growth(self):
        old = (
            "func load() error {\n\t// Check the error.\n\tif err != nil {\n\t}\n}\n"
        )
        new = (
            "func save() error {\n\t// Check the error.\n\tif err != nil {\n\t}\n}\n"
            "\n"
            "func load() error {\n\t// Check the error.\n\t// A missing file is not an error.\n\tif err != nil {\n\t}\n}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.ADDED, 2, 0, 1, False), (gate.GREW, 8, 1, 2, True)],
        )

    def test_block_left_free_by_an_identical_copy_pairs_only_with_the_block_that_freed_it(self):
        old = (
            "// Close the file.\nfunc (f *File) Close() error {\n}\n\n"
            "// Close the file quickly.\nfunc (f *File) CloseFast() error {\n}\n"
        )
        new = (
            "// Close the file.\nfunc (f *File) Close() error {\n}\n\n"
            "// Close the file quickly,\n// and flush it.\nfunc (f *File) CloseFast() error {\n}\n\n"
            "// CloseAll closes each file\n// in the list.\nfunc (f *File) CloseAll() error {\n}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.GREW, 5, 1, 2, True), (gate.ADDED, 10, 0, 2, False)],
        )

    def test_copy_stays_unchanged_beside_a_new_block_of_the_same_length(self):
        old = "func f() {\n\t// Check the error.\n\tif err != nil {\n\t}\n}\n"
        new = (
            "func f() {\n\t// Check the error again.\n\tif err != nil {\n\t}\n"
            "\t// Check the error.\n\tif err != nil {\n\t}\n}\n"
        )
        self.assertEqual(statuses(old, new), [(gate.ADDED, 0, 1, False)])

    def test_copy_stays_unchanged_beside_a_longer_block_that_keeps_only_some_of_its_words(self):
        old = "// Close the file.\nfunc (f *File) Close() error {\n}\n"
        new = (
            "// Close the file.\nfunc (f *File) Close() error {\n}\n\n"
            "// Close each socket\n// and the log.\nfunc (f *File) CloseAll() error {\n}\n"
        )
        self.assertEqual(statuses(old, new), [(gate.ADDED, 0, 2, False)])

    def test_copy_of_a_block_with_no_words_stays_unchanged_beside_a_longer_block(self):
        old = "// --------\nfunc (s *Server) Start() error {\n}\n"
        new = (
            "// --------\nfunc (s *Server) Start() error {\n}\n\n"
            "// Stop halts the server.\n// It waits.\nfunc (s *Server) Stop() error {\n}\n"
        )
        self.assertEqual(statuses(old, new), [(gate.ADDED, 0, 2, False)])

    def test_two_copies_stay_unchanged_beside_a_longer_block_above_another_anchor(self):
        check = "\t// Check the error.\n\tif err != nil {\n\t}\n"
        old = "func f() {\n" + check + check + "}\n"
        new = "// Check the error, then\n// log it.\nvar logger = newLogger()\n\nfunc f() {\n" + check + check + "}\n"
        self.assertEqual(statuses(old, new), [(gate.ADDED, 0, 2, False)])

    def test_second_copy_pairs_with_a_changed_block_when_the_longer_block_is_itself_unchanged(self):
        check = "\t// Check the error.\n\tif err != nil {\n\t}\n"
        longer = "\t// Check the error.\n\t// It may be nil.\n\tif err != nil {\n\t}\n"
        other = "\t// Retry once,\n\t// then stop,\n\t// and report.\n\tif err != nil {\n\t}\n"
        old = "func f() {\n" + check + longer + other + "}\n"
        new = "func f() {\n" + check + check + longer + "}\n"
        self.assertEqual(statuses(old, new), [(gate.CHANGED, 3, 1, False)])

    def test_identical_copy_of_a_doc_string_that_grew_does_not_hide_the_growth(self):
        old = 'class A:\n    def __init__(self):\n        """Set up."""\n        pass\n'
        new = (
            'class B:\n    def __init__(self):\n        """Set up."""\n        pass\n\n'
            'class A:\n    def __init__(self):\n        """Set up.\n\n        Opens the log.\n        """\n        pass\n'
        )
        findings = gate.compare("f", old, new, gate.HASH_DOCSTRING)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.ADDED, 3, 0, 1, False), (gate.GREW, 8, 1, 4, True)],
        )

    def test_unchanged_block_stays_unlisted_when_the_longer_block_that_keeps_its_words_pairs_elsewhere(self):
        old = (
            "func f() {\n"
            "\t// Check the error.\n\tif err != nil {\n\t}\n"
            "\t// Check the error, then log it.\n\tif err != nil {\n\t}\n"
            "}\n"
        )
        new = (
            "func f() {\n"
            "\t// Check the error.\n\tif err != nil {\n\t}\n"
            "\t// Check the error, then log it.\n\t// The log holds the path.\n\tif err != nil {\n\t}\n"
            "}\n"
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.GREW, 5, 1, 2, True)],
        )

    def test_comment_rewritten_fully_above_the_same_anchor_is_paired(self):
        old = "// run starts the job.\nfunc run() {}\n"
        new = "// Blocks until every worker has stopped.\nfunc run() {}\n"
        self.assertEqual(statuses(old, new), [(gate.CHANGED, 1, 1, False)])

    def test_common_anchor_text_pairs_blocks_in_order(self):
        # Each grown block keeps every word of both old blocks above the same
        # anchor, so every pairing scores the same and position decides. The
        # third copy has no old block of its own and shares the nearer one.
        old = "func f() {\n\t// keep\n\tk()\n\t// retry\n\tcall()\n\t// retry\n\t// hard\n\tcall()\n}\n"
        grown = "\t// retry\n\t// hard\n\t// now\n\tcall()\n"
        new = "func f() {\n" + grown * 3 + "\t// keep\n\tk()\n}\n"
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length) for f in findings],
            [(gate.GREW, 2, 1, 3), (gate.GREW, 6, 1, 3), (gate.GREW, 10, 2, 3)],
        )

    def test_growth_is_flagged_when_a_sibling_above_an_equal_anchor_keeps_the_old_words(self):
        def function(name, comment):
            lines = "".join("\t// %s\n" % line for line in comment)
            return "func %s() error {\n\terr := io()\n%s\tif err != nil {\n\t\treturn nil\n\t}\n\treturn nil\n}\n" % (name, lines)

        old = function("load", ["The file may be missing on first start."])
        new = (
            function("save", ["The file may be missing on first start or save."])
            + "\n"
            + function("load", ["The file may be missing on first start.", "A missing file means an empty store."])
        )
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.CHANGED, 1, 1, False), (gate.GREW, 1, 2, True)],
        )

    def test_inline_comment_deleted_while_its_code_line_stays(self):
        old = "// run starts the job.\nfunc run() {}\n"
        new = "func run() {}\n"
        findings = gate.compare("f", old, new, gate.SLASH)
        self.assertEqual(
            [(f.status, f.line, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.REMOVED, 1, 1, 0, False)],
        )

    def test_doc_string_deleted_while_its_def_line_stays(self):
        old = 'def run(job):\n    """Runs job."""\n    return job()\n'
        new = 'def run(job):\n    return job()\n'
        findings = gate.compare("f", old, new, gate.HASH_DOCSTRING)
        self.assertEqual(
            [(f.status, f.old_length, f.new_length, f.flagged) for f in findings],
            [(gate.REMOVED, 1, 0, False)],
        )

    def test_anchor_ratio_at_the_limit_pairs(self):
        old_anchor = "func send(msg Message) error {"
        new_anchor = "func load(ctx Context) error {"
        self.assertEqual(difflib.SequenceMatcher(None, old_anchor, new_anchor).ratio(), gate.SIMILAR_ANCHOR)
        old = "// send writes one message.\n%s\n}\n" % old_anchor
        new = "// send writes one message.\n// It retries once.\n%s\n}\n" % new_anchor
        self.assertEqual(statuses(old, new), [(gate.GREW, 1, 2, True)])

    def test_anchor_ratio_just_above_the_limit_pairs(self):
        old_anchor = "func run(job Job) error {"
        new_anchor = "func process(item Item) error {"
        ratio = difflib.SequenceMatcher(None, old_anchor, new_anchor).ratio()
        self.assertGreaterEqual(ratio, gate.SIMILAR_ANCHOR)
        old = "// run starts the job.\n%s\n}\n" % old_anchor
        new = "// run starts the job.\n// It waits for limit.\n%s\n}\n" % new_anchor
        self.assertEqual(statuses(old, new), [(gate.GREW, 1, 2, True)])

    def test_anchor_ratio_just_below_the_limit_does_not_pair(self):
        old_anchor = "func run(job Job) error {"
        new_anchor = "func process(items Items) error {"
        ratio = difflib.SequenceMatcher(None, old_anchor, new_anchor).ratio()
        self.assertLess(ratio, gate.SIMILAR_ANCHOR)
        old = "// run starts the job.\n%s\n}\n" % old_anchor
        new = "// run starts the job.\n// It waits for limit.\n%s\n}\n" % new_anchor
        self.assertEqual(statuses(old, new), [(gate.ADDED, 0, 2, False), (gate.REMOVED, 1, 0, False)])

class PairCostTest(unittest.TestCase):
    def test_pairing_across_files_does_not_score_every_pair(self):
        # Blocks that share no word can never keep half of the old words, so a
        # pairing that scores them anyway is quadratic in its slowest step.
        old = [gate.Block(n + 1, ("// removed%d closes it." % n,), "return nil") for n in range(200)]
        new = [gate.Block(n + 1, ("// added%d opens it." % n, "// twice%d." % n), "return nil") for n in range(200)]
        with mock.patch.object(gate.difflib, "SequenceMatcher", wraps=difflib.SequenceMatcher) as matcher:
            pairs, removed = gate.pair(old, new, gate.KEPT_ACROSS_FILES)
        self.assertEqual((set(pairs.values()), len(removed)), ({None}, 200))
        self.assertLessEqual(matcher.call_count, len(old))

    def test_index_of_words_gives_the_same_pairs_as_scoring_every_pair(self):
        def every_block(old_words, postings, indexes, min_kept):
            return indexes if old_words else []

        rng = random.Random(7)
        words = "a b c d e f".split()

        def block():
            text = tuple(
                "// " + " ".join(rng.choice(words) for _ in range(rng.randint(0, 5))) for _ in range(rng.randint(1, 3))
            )
            return gate.Block(1, text, rng.choice(["func a() {", "func b() {", "return nil", ""]))

        for _ in range(2000):
            old = [block() for _ in range(rng.randint(0, 6))]
            new = [block() for _ in range(rng.randint(0, 6))]
            indexed = gate.pair(old, new, gate.KEPT_ACROSS_FILES, one_file=False)
            with mock.patch.object(gate, "_reach", side_effect=every_block):
                self.assertEqual(gate.pair(old, new, gate.KEPT_ACROSS_FILES, one_file=False), indexed, (old, new))

    def test_block_across_files_pairs_at_exactly_the_limit_of_kept_words(self):
        new = [gate.Block(1, ("// alpha gamma delta",), "return nil")]
        half = [gate.Block(1, ("// alpha beta",), "return nil")]
        third = [gate.Block(1, ("// alpha beta epsilon",), "return nil")]
        self.assertEqual(gate._kept(["alpha", "beta"], ["alpha", "gamma", "delta"]), gate.KEPT_ACROSS_FILES)
        self.assertLess(gate._kept(["alpha", "beta", "epsilon"], ["alpha", "gamma", "delta"]), gate.KEPT_ACROSS_FILES)
        self.assertEqual(gate.pair(half, new, gate.KEPT_ACROSS_FILES, one_file=False), ({0: 0}, ()))
        self.assertEqual(gate.pair(third, new, gate.KEPT_ACROSS_FILES, one_file=False), ({0: None}, (0,)))


def _isolated_git_env():
    """A git environment freed from this machine's global config and from a repository inherited via the shell."""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)
    return env


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, env=_isolated_git_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class Repository:
    """A throwaway git repository with one commit on branch main."""

    def __init__(self, test):
        self._directory = tempfile.TemporaryDirectory()
        test.addCleanup(self._directory.cleanup)
        self.path = os.path.realpath(self._directory.name)
        sh(self.path, "git", "init", "-q")
        sh(self.path, "git", "checkout", "-q", "-b", "main")
        self.write("README.md", "seed\n")
        self.commit("seed")

    def write(self, name, text):
        full_path = os.path.join(self.path, name)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def commit(self, message):
        sh(self.path, "git", "add", "--all")
        sh(
            self.path, "git", "-c", "user.name=gate", "-c", "user.email=gate@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-q", "-m", message,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.path, check=True, env=_isolated_git_env(), stdout=subprocess.PIPE
        ).stdout.decode().strip()


class GitEnvIsolationTest(unittest.TestCase):
    def test_repository_setup_ignores_a_hostile_global_config(self):
        with tempfile.TemporaryDirectory() as scratch:
            hooks_dir = os.path.join(scratch, "hooks")
            os.makedirs(hooks_dir)
            hook_path = os.path.join(hooks_dir, "pre-commit")
            with open(hook_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\nexit 1\n")
            os.chmod(hook_path, 0o755)
            global_config = os.path.join(scratch, "gitconfig")
            with open(global_config, "w", encoding="utf-8") as handle:
                handle.write("[core]\n\thooksPath = %s\n" % hooks_dir)
            previous = os.environ.get("GIT_CONFIG_GLOBAL")
            self.addCleanup(
                lambda: os.environ.pop("GIT_CONFIG_GLOBAL", None)
                if previous is None
                else os.environ.update(GIT_CONFIG_GLOBAL=previous)
            )
            os.environ["GIT_CONFIG_GLOBAL"] = global_config
            repo = Repository(self)
            self.assertTrue(os.path.isdir(os.path.join(repo.path, ".git")))


OLD = "// run starts the job.\nfunc run() {}\n"
GROWN = "// run starts the job.\n// It also stops it.\nfunc run() {}\n"


class RunTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(self)

    def summary(self, report):
        return [(f.path, f.status, f.flagged) for f in report.findings]

    def test_change_in_the_working_tree_is_compared_with_the_base(self):
        self.repo.write("a.go", OLD)
        base = self.repo.commit("add a")
        self.repo.write("a.go", GROWN)
        report = gate.run(self.repo.path, base)
        self.assertEqual(self.summary(report), [("a.go", gate.GREW, True)])
        self.assertTrue(report.flagged)

    def test_committed_change_is_compared_with_the_base(self):
        self.repo.write("a.go", OLD)
        base = self.repo.commit("add a")
        self.repo.write("a.go", GROWN)
        self.repo.commit("grow a")
        self.assertEqual(self.summary(gate.run(self.repo.path, base)), [("a.go", gate.GREW, True)])

    def test_comparison_starts_at_the_merge_base(self):
        # shared.go exists at the fork. main shortens its comment after the
        # fork; topic never touches shared.go. Diffing against main's tip
        # (the wrong base) would show shared.go growing back to its longer
        # form; diffing against the merge base omits it, since topic's copy
        # never changed relative to the fork.
        self.repo.write("shared.go", "// shared does one thing.\n// It also does another.\nfunc shared() {}\n")
        self.repo.commit("add shared")
        sh(self.repo.path, "git", "checkout", "-q", "-b", "topic")
        sh(self.repo.path, "git", "checkout", "-q", "main")
        self.repo.write("shared.go", "// shared does one thing.\nfunc shared() {}\n")
        self.repo.commit("shorten the comment on main")
        sh(self.repo.path, "git", "checkout", "-q", "topic")
        self.assertEqual(gate.run(self.repo.path, "main").findings, ())

    def test_untracked_file_is_scanned(self):
        self.repo.write("new.go", OLD)
        self.assertEqual(self.summary(gate.run(self.repo.path, "HEAD")), [("new.go", gate.ADDED, False)])

    def test_symbolic_link_is_not_followed_out_of_the_repository(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = os.path.join(outside.name, "secret.go")
        with open(target, "w") as handle:
            handle.write(GROWN)
        self.repo.write("keep.go", "func keep() {}\n")
        base = self.repo.commit("add keep")
        os.symlink(target, os.path.join(self.repo.path, "probe.go"))
        os.symlink(os.path.join(outside.name, "missing.go"), os.path.join(self.repo.path, "dangling.go"))
        self.assertEqual(self.summary(gate.run(self.repo.path, base)), [])

    def test_directory_that_became_a_symbolic_link_is_not_followed(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with open(os.path.join(outside.name, "file.go"), "w") as handle:
            handle.write(GROWN)
        self.repo.write("pkg/file.go", OLD)
        base = self.repo.commit("add pkg")
        os.remove(os.path.join(self.repo.path, "pkg", "file.go"))
        os.rmdir(os.path.join(self.repo.path, "pkg"))
        os.symlink(outside.name, os.path.join(self.repo.path, "pkg"))
        self.assertEqual(
            [(f.path, f.status, f.flagged) for f in gate.run(self.repo.path, base).findings if f.path.startswith("pkg/")],
            [("pkg/file.go", gate.REMOVED, False)],
        )

    def test_renamed_file_is_compared_with_its_base_path(self):
        body = "".join("func step%d() {}\n" % n for n in range(20))
        self.repo.write("old.go", OLD + body)
        base = self.repo.commit("add old")
        sh(self.repo.path, "git", "mv", "old.go", "new.go")
        self.repo.write("new.go", GROWN + body)
        self.assertEqual(self.summary(gate.run(self.repo.path, base)), [("new.go", gate.GREW, True)])

    def test_renamed_file_with_a_new_extension_is_scanned_with_the_syntax_of_its_base_path(self):
        body = "".join("def step%d(): pass\n" % n for n in range(20))
        self.repo.write("old.py", "# run starts the job.\ndef run(): pass\n" + body)
        base = self.repo.commit("add old")
        sh(self.repo.path, "git", "mv", "old.py", "new.go")
        self.repo.write("new.go", "// run starts the job.\n// It also stops it.\ndef run(): pass\n" + body)
        self.assertEqual(self.summary(gate.run(self.repo.path, base)), [("new.go", gate.GREW, True)])

    def test_removed_comment_of_a_renamed_file_is_listed_at_the_old_path(self):
        body = "".join("func step%d() {}\n" % n for n in range(20))
        self.repo.write("old.go", OLD + body)
        base = self.repo.commit("add old")
        sh(self.repo.path, "git", "mv", "old.go", "new.go")
        self.repo.write("new.go", "func run() {}\n" + body)
        self.assertEqual(
            [(f.path, f.line, f.status) for f in gate.run(self.repo.path, base).findings],
            [("old.go", 1, gate.REMOVED)],
        )

    def test_deleted_file_lists_its_removed_comments(self):
        self.repo.write("a.go", OLD)
        base = self.repo.commit("add a")
        os.remove(os.path.join(self.repo.path, "a.go"))
        report = gate.run(self.repo.path, base)
        self.assertEqual(
            [(f.path, f.status, f.old_length, f.new_length, f.flagged) for f in report.findings],
            [("a.go", gate.REMOVED, 1, 0, False)],
        )
        self.assertEqual(report.not_checked, ())
        self.assertFalse(report.flagged)

    def test_block_that_moved_to_another_file_and_grew_is_flagged_at_its_new_path(self):
        retry = "// retry calls f until it succeeds.\nfunc retry(f func() error) error {\n\treturn f()\n}\n"
        self.repo.write("a.go", "package p\n\nfunc keep() {}\n\n" + retry)
        self.repo.write("b.go", "package p\n\nfunc other() {}\n")
        base = self.repo.commit("add a and b")
        self.repo.write("a.go", "package p\n\nfunc keep() {}\n")
        self.repo.write(
            "b.go",
            "package p\n\nfunc other() {}\n\n"
            "// retry calls f until it succeeds.\n"
            "// It waits one second between two calls.\n"
            "// It stops after five calls.\n"
            "func retry(f func() error) error {\n\treturn f()\n}\n",
        )
        report = gate.run(self.repo.path, base)
        self.assertEqual(
            [(f.path, f.line, f.status, f.old_length, f.new_length, f.flagged) for f in report.findings],
            [("b.go", 5, gate.GREW, 1, 3, True)],
        )
        self.assertEqual(
            gate.render(report).splitlines()[0],
            "FLAG b.go:5  GREW  1 -> 3 lines  | func retry(f func() error) error {  (moved from a.go, old line 5)",
        )

    def test_moved_blocks_name_their_old_lines_and_only_their_own_file(self):
        self.repo.write(
            "a.go",
            "package a\n\n// retry calls f until it succeeds.\nfunc retry(f func() error) error {\n}\n\n"
            "// wait sleeps for d.\nfunc wait(d Duration) {\n}\n",
        )
        self.repo.write("c.go", "package c\n\n// count counts.\nfunc count() {\n}\n")
        base = self.repo.commit("add a and c")
        os.remove(os.path.join(self.repo.path, "a.go"))
        self.repo.write(
            "b.go",
            "package b\n\nfunc x() {\n}\n\n"
            "// retry calls f until it succeeds.\n// It waits between two calls.\nfunc retry(f func() error) error {\n}\n\n"
            "// wait sleeps for d seconds.\nfunc wait(d Duration) {\n}\n",
        )
        self.repo.write("c.go", "package c\n\n// count counts the calls.\nfunc count() {\n}\n")
        self.assertEqual(
            gate.render(gate.run(self.repo.path, base)).splitlines(),
            [
                "FLAG b.go:6  GREW  1 -> 2 lines  | func retry(f func() error) error {  (moved from a.go, old line 3)",
                "     b.go:11  CHANGED  1 -> 1 lines  | func wait(d Duration) {  (moved from a.go, old line 7)",
                "     c.go:3  CHANGED  1 -> 1 lines  | func count() {",
                "1 flagged, 3 listed, 0 removed, 0 not checked",
            ],
        )

    def test_unrelated_blocks_above_a_common_anchor_in_two_files_are_not_paired(self):
        self.repo.write("a.go", "package a\n\nfunc A() error {\n\tx()\n\t// Nothing to undo.\n\treturn nil\n}\n")
        self.repo.write("b.go", "package b\n\nfunc B() error {\n\ty()\n\treturn nil\n}\n")
        self.repo.write("a.py", 'class A:\n    def run(self):\n        """Run it."""\n        return 1\n')
        self.repo.write("b.py", "class B:\n    pass\n")
        base = self.repo.commit("add the files")
        self.repo.write("a.go", "package a\n\nfunc A() error {\n\tx()\n\treturn nil\n}\n")
        self.repo.write(
            "b.go",
            "package b\n\nfunc B() error {\n\ty()\n"
            "\t// The caller retries on error, so a partial\n"
            "\t// write here is safe: the next call starts\n"
            "\t// from the saved offset.\n"
            "\treturn nil\n}\n",
        )
        self.repo.write("a.py", "class A:\n    pass\n")
        self.repo.write(
            "b.py", 'class B:\n    def sum(self):\n        """Add the values.\n\n        Skips None.\n        """\n        return 2\n'
        )
        report = gate.run(self.repo.path, base)
        self.assertEqual(
            [(f.path, f.status, f.flagged) for f in report.findings],
            [
                ("a.go", gate.REMOVED, False),
                ("a.py", gate.REMOVED, False),
                ("b.go", gate.ADDED, False),
                ("b.py", gate.ADDED, False),
            ],
        )

    def test_too_many_blocks_to_pair_across_files_are_listed_and_the_report_says_so(self):
        retry = "// retry calls f until it succeeds.\nfunc retry(f func() error) error {\n\treturn f()\n}\n"
        self.repo.write("a.go", "package p\n\n" + retry + "\n// wait sleeps.\nfunc wait() {\n}\n")
        base = self.repo.commit("add a")
        os.remove(os.path.join(self.repo.path, "a.go"))
        self.repo.write("b.go", "package p\n\n// retry calls f until it succeeds.\n// It waits.\nfunc retry(f func() error) error {\n}\n")
        with mock.patch.object(gate, "MOST_PAIRS_ACROSS_FILES", 0):
            report = gate.run(self.repo.path, base)
        self.assertEqual(
            [(f.path, f.status, f.flagged) for f in report.findings],
            [("a.go", gate.REMOVED, False), ("a.go", gate.REMOVED, False), ("b.go", gate.ADDED, False)],
        )
        self.assertEqual(report.not_paired_across_files, (2, 1))
        self.assertIn(
            "     2 removed and 1 added blocks NOT PAIRED ACROSS FILES, too many to compare; read their diff",
            gate.render(report),
        )
        self.assertEqual(
            gate.render(report).splitlines()[-1],
            "0 flagged, 3 listed, 2 removed, 0 not checked, 3 not paired across files",
        )

    def test_pairing_across_files_runs_at_exactly_the_cap(self):
        self.repo.write("a.go", "package p\n\n// retry calls f until it succeeds.\nfunc retry(f func() error) error {\n}\n")
        base = self.repo.commit("add a")
        os.remove(os.path.join(self.repo.path, "a.go"))
        self.repo.write("b.go", "package p\n\n// retry calls f until it succeeds.\n// It waits.\nfunc retry(f func() error) error {\n}\n")
        with mock.patch.object(gate, "MOST_PAIRS_ACROSS_FILES", 1):
            report = gate.run(self.repo.path, base)
        self.assertEqual([(f.path, f.status) for f in report.findings], [("b.go", gate.GREW)])
        self.assertIsNone(report.not_paired_across_files)

    def test_old_block_of_another_file_is_not_shared_with_a_longer_block(self):
        self.repo.write("a.go", "package p\n\n// Close the file now.\nfunc (f *File) Close() error {\n}\n")
        base = self.repo.commit("add a")
        os.remove(os.path.join(self.repo.path, "a.go"))
        self.repo.write(
            "b.go",
            "package p\n\n// Close the file now.\nfunc (f *File) CloseAll() error {\n}\n\n"
            "// Close the file, and flush\n// it first.\nfunc (f *File) Close() error {\n}\n",
        )
        self.assertEqual(
            [(f.path, f.line, f.status) for f in gate.run(self.repo.path, base).findings],
            [("b.go", 3, gate.CHANGED), ("b.go", 7, gate.ADDED)],
        )

    def test_copy_in_another_file_is_the_old_block_moved_unchanged(self):
        check = "\t// Check the error.\n\tif err != nil {\n\t}\n"
        self.repo.write("a.go", "package p\n\nfunc load() {\n" + check + "}\n")
        base = self.repo.commit("add a")
        os.remove(os.path.join(self.repo.path, "a.go"))
        self.repo.write("b.go", "package p\n\nfunc load() {\n" + check + "}\n")
        self.repo.write("c.go", "package p\n\nfunc save() {\n\t// Check the error.\n\t// Log it.\n\tif err != nil {\n\t}\n}\n")
        self.assertEqual(
            [(f.path, f.status) for f in gate.run(self.repo.path, base).findings], [("c.go", gate.ADDED)]
        )

    def test_block_of_a_removed_file_pairs_with_one_block_of_another_file(self):
        self.repo.write("a.go", "package p\n\n// retry calls f until it succeeds.\nfunc retry(f func() error) error {\n}\n")
        base = self.repo.commit("add a")
        os.remove(os.path.join(self.repo.path, "a.go"))
        self.repo.write(
            "b.go",
            "package p\n\n"
            "// retryAll calls f until it succeeds,\n// for each f.\nfunc retryAll(fs []func() error) error {\n}\n\n"
            "// retry calls f until it succeeds.\n// It waits between two calls.\nfunc retry(f func() error) error {\n}\n",
        )
        self.assertEqual(
            [(f.path, f.line, f.status, f.flagged) for f in gate.run(self.repo.path, base).findings],
            [("b.go", 3, gate.ADDED, False), ("b.go", 8, gate.GREW, True)],
        )

    def test_block_with_no_words_is_not_paired_across_files(self):
        self.repo.write("a.py", "x = 1\n\n#*******\n\ndef main():\n    return x\n")
        base = self.repo.commit("add a")
        os.remove(os.path.join(self.repo.path, "a.py"))
        self.repo.write("b.py", "y = 2\n\n# Reads the arguments\n# and runs the tool.\ndef main():\n    return y\n")
        self.assertEqual(
            [(f.path, f.status, f.flagged) for f in gate.run(self.repo.path, base).findings],
            [("a.py", gate.REMOVED, False), ("b.py", gate.ADDED, False)],
        )

    def test_block_that_moved_to_another_file_unchanged_is_not_listed(self):
        retry = "// retry calls f until it succeeds.\nfunc retry(f func() error) error {\n\treturn f()\n}\n"
        self.repo.write("a.go", "package p\n\nfunc keep() {}\n\n" + retry)
        self.repo.write("b.go", "package p\n\nfunc other() {}\n")
        base = self.repo.commit("add a and b")
        self.repo.write("a.go", "package p\n\nfunc keep() {}\n")
        self.repo.write("b.go", "package p\n\nfunc other() {}\n\n" + retry)
        self.assertEqual(gate.run(self.repo.path, base).findings, ())

    def test_unknown_file_type_is_listed_as_not_checked(self):
        self.repo.write("rules.xyz", "?? a comment in a syntax the gate does not know\n")
        report = gate.run(self.repo.path, "HEAD")
        self.assertEqual(report.not_checked, ("rules.xyz",))
        self.assertFalse(report.flagged)

    def test_prose_file_is_skipped_without_a_report(self):
        self.repo.write("README.md", "seed\n<!-- note -->\n")
        report = gate.run(self.repo.path, "HEAD")
        self.assertEqual((report.findings, report.not_checked), ((), ()))

    def test_user_facing_path_is_listed_and_not_flagged(self):
        self.repo.write("api/types.go", OLD)
        self.repo.write("pkg/a.go", OLD)
        base = self.repo.commit("add both")
        self.repo.write("api/types.go", GROWN)
        self.repo.write("pkg/a.go", GROWN)
        report = gate.run(self.repo.path, base, ["api/*"])
        self.assertEqual(
            [(f.path, f.status, f.flagged, f.user_facing) for f in report.findings],
            [("api/types.go", gate.GREW, False, True), ("pkg/a.go", gate.GREW, True, False)],
        )

    def test_removed_comment_in_a_user_facing_path_is_marked_user_facing(self):
        self.repo.write("api/types.go", OLD)
        base = self.repo.commit("add api")
        self.repo.write("api/types.go", "func run() {}\n")
        report = gate.run(self.repo.path, base, ["api/*"])
        self.assertEqual(
            [(f.path, f.status, f.flagged, f.user_facing) for f in report.findings],
            [("api/types.go", gate.REMOVED, False, True)],
        )

    def test_run_from_a_subdirectory_covers_the_repository(self):
        self.repo.write("pkg/a.go", OLD)
        base = self.repo.commit("add a")
        self.repo.write("pkg/a.go", GROWN)
        report = gate.run(os.path.join(self.repo.path, "pkg"), base)
        self.assertEqual(self.summary(report), [("pkg/a.go", gate.GREW, True)])

    def test_staged_change_is_seen(self):
        self.repo.write("a.go", OLD)
        base = self.repo.commit("add a")
        self.repo.write("a.go", GROWN)
        sh(self.repo.path, "git", "add", "a.go")
        self.assertEqual(self.summary(gate.run(self.repo.path, base)), [("a.go", gate.GREW, True)])

    def test_path_with_a_space_and_a_letter_outside_ascii(self):
        self.repo.write("pkg/my fíle.go", OLD)
        base = self.repo.commit("add file")
        self.repo.write("pkg/my fíle.go", GROWN)
        self.assertEqual(self.summary(gate.run(self.repo.path, base)), [("pkg/my fíle.go", gate.GREW, True)])

    def test_bytes_that_are_not_text_do_not_stop_the_run(self):
        self.repo.write("a.go", OLD)
        base = self.repo.commit("add a")
        with open(os.path.join(self.repo.path, "a.go"), "wb") as handle:
            handle.write(b"// run starts the caf\xe9.\n// It also stops it.\nfunc run() {}\n")
        self.assertEqual(self.summary(gate.run(self.repo.path, base)), [("a.go", gate.GREW, True)])

    def test_unknown_base_is_a_git_error(self):
        with self.assertRaises(gate.GitError):
            gate.run(self.repo.path, "no-such-ref")

    def test_run_ignores_an_inherited_git_dir(self):
        other = Repository(self)
        other.write("other.go", "// unrelated file in a different repository.\nfunc other() {}\n")
        other.commit("seed other")
        previous = os.environ.get("GIT_DIR")
        self.addCleanup(
            lambda: os.environ.pop("GIT_DIR", None) if previous is None else os.environ.update(GIT_DIR=previous)
        )
        os.environ["GIT_DIR"] = os.path.join(other.path, ".git")
        self.repo.write("a.go", OLD)
        base = self.repo.commit("add a")
        self.repo.write("a.go", GROWN)
        report = gate.run(self.repo.path, base)
        self.assertEqual(self.summary(report), [("a.go", gate.GREW, True)])

    def test_cmakelists_txt_is_checked_as_a_hash_family_file(self):
        self.repo.write("CMakeLists.txt", "# Configures the build.\nadd_executable(app main.c)\n")
        base = self.repo.commit("add CMakeLists")
        self.repo.write("CMakeLists.txt", "# Configures the build.\n# Uses C11.\nadd_executable(app main.c)\n")
        report = gate.run(self.repo.path, base)
        self.assertEqual(self.summary(report), [("CMakeLists.txt", gate.GREW, True)])

    def test_user_facing_matching_never_calls_fnmatch_fnmatch(self):
        self.repo.write("a.go", OLD)
        base = self.repo.commit("add a")
        self.repo.write("a.go", GROWN)
        with mock.patch("comment_growth.fnmatch.fnmatch", side_effect=AssertionError("must use fnmatchcase")):
            report = gate.run(self.repo.path, base, ["*.go"])
        self.assertEqual([(f.path, f.flagged) for f in report.findings], [("a.go", False)])

class MainTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(self)
        self.repo.write("a.go", OLD)
        self.base = self.repo.commit("add a")
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.repo.path)

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                status = gate.main(list(argv))
            except SystemExit as stop:
                status = stop.code
        return status, out.getvalue(), err.getvalue()

    def test_blocks_not_paired_across_files_alone_exit_zero(self):
        os.remove(os.path.join(self.repo.path, "a.go"))
        self.repo.write("b.go", GROWN)
        with mock.patch.object(gate, "MOST_PAIRS_ACROSS_FILES", 0):
            status, out, _ = self.call(self.base)
        self.assertEqual(status, 0)
        self.assertIn("2 not paired across files", out)

    def test_no_flag_exits_zero(self):
        self.repo.write("a.go", "// run starts one job.\nfunc run() {}\n")
        status, out, _ = self.call(self.base)
        self.assertEqual(status, 0)
        self.assertIn("     a.go:1  CHANGED  1 -> 1 lines  | func run() {}", out)
        self.assertIn("0 flagged, 1 listed, 0 removed, 0 not checked", out)

    def test_flag_exits_one_and_names_the_block(self):
        self.repo.write("a.go", GROWN)
        status, out, _ = self.call(self.base)
        self.assertEqual(status, 1)
        self.assertIn("FLAG a.go:1  GREW  1 -> 2 lines  | func run() {}", out)
        self.assertIn("1 flagged, 1 listed, 0 removed, 0 not checked", out)

    def test_removed_comment_alone_exits_zero(self):
        self.repo.write("a.go", "func run() {}\n")
        status, out, _ = self.call(self.base)
        self.assertEqual(status, 0)
        self.assertIn("     a.go (old line 1)  REMOVED  1 -> 0 lines  | func run() {}", out)
        self.assertIn("0 flagged, 1 listed, 1 removed, 0 not checked", out)

    def test_user_facing_option_removes_the_flag(self):
        self.repo.write("a.go", GROWN)
        status, out, _ = self.call(self.base, "--user-facing", "*.go")
        self.assertEqual(status, 0)
        self.assertIn("(user-facing, not flagged)", out)

    def test_not_checked_file_is_in_the_output(self):
        self.repo.write("rules.xyz", "?? note\n")
        status, out, _ = self.call(self.base)
        self.assertEqual(status, 0)
        self.assertIn("rules.xyz  NOT CHECKED", out)

    def test_git_error_exits_two(self):
        status, _, err = self.call("no-such-ref")
        self.assertEqual(status, 2)
        self.assertIn("comment_growth:", err)

    def test_usage_error_exits_two(self):
        status, _, _ = self.call("--no-such-option")
        self.assertEqual(status, 2)

    def test_outside_a_repository_exits_two(self):
        with tempfile.TemporaryDirectory() as parent:
            directory = os.path.join(parent, "no-repo")
            os.makedirs(directory)
            previous = os.environ.get("GIT_CEILING_DIRECTORIES")
            self.addCleanup(
                lambda: os.environ.pop("GIT_CEILING_DIRECTORIES", None)
                if previous is None
                else os.environ.update(GIT_CEILING_DIRECTORIES=previous)
            )
            os.environ["GIT_CEILING_DIRECTORIES"] = parent
            os.chdir(directory)
            status, _, _ = self.call("HEAD")
        self.assertEqual(status, 2)

    def test_missing_git_program_exits_two_with_one_message(self):
        previous = os.environ.get("PATH")
        self.addCleanup(
            lambda: os.environ.pop("PATH", None) if previous is None else os.environ.update(PATH=previous)
        )
        os.environ["PATH"] = ""
        status, _, err = self.call(self.base)
        self.assertEqual(status, 2)
        self.assertEqual(len(err.rstrip("\n").splitlines()), 1)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read an unreadable file")
    def test_unreadable_file_exits_two_with_one_message(self):
        self.repo.write("a.go", GROWN)
        path = os.path.join(self.repo.path, "a.go")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        status, _, err = self.call(self.base)
        self.assertEqual(status, 2)
        self.assertEqual(len(err.rstrip("\n").splitlines()), 1)

if __name__ == "__main__":
    unittest.main()
