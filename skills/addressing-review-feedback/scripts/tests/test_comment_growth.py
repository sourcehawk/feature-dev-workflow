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

def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


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
            ["git", "rev-parse", "HEAD"], cwd=self.path, check=True, stdout=subprocess.PIPE
        ).stdout.decode().strip()


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
        self.repo.write("a.go", OLD)
        self.repo.commit("add a")
        sh(self.repo.path, "git", "checkout", "-q", "-b", "topic")
        self.repo.write("a.go", GROWN)
        self.repo.commit("grow a")
        sh(self.repo.path, "git", "checkout", "-q", "main")
        self.repo.write("b.go", OLD)
        self.repo.commit("add b on main")
        sh(self.repo.path, "git", "checkout", "-q", "topic")
        self.assertEqual(self.summary(gate.run(self.repo.path, "main")), [("a.go", gate.GREW, True)])

    def test_untracked_file_is_scanned(self):
        self.repo.write("new.go", OLD)
        self.assertEqual(self.summary(gate.run(self.repo.path, "HEAD")), [("new.go", gate.ADDED, False)])

    def test_renamed_file_is_compared_with_its_base_path(self):
        body = "".join("func step%d() {}\n" % n for n in range(20))
        self.repo.write("old.go", OLD + body)
        base = self.repo.commit("add old")
        sh(self.repo.path, "git", "mv", "old.go", "new.go")
        self.repo.write("new.go", GROWN + body)
        self.assertEqual(self.summary(gate.run(self.repo.path, base)), [("new.go", gate.GREW, True)])

    def test_deleted_file_is_not_listed(self):
        self.repo.write("a.go", OLD)
        base = self.repo.commit("add a")
        os.remove(os.path.join(self.repo.path, "a.go"))
        report = gate.run(self.repo.path, base)
        self.assertEqual((report.findings, report.not_checked), ((), ()))

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

    def test_no_flag_exits_zero(self):
        self.repo.write("a.go", "// run starts one job.\nfunc run() {}\n")
        status, out, _ = self.call(self.base)
        self.assertEqual(status, 0)
        self.assertIn("     a.go:1  CHANGED  1 -> 1 lines  | func run() {}", out)
        self.assertIn("0 flagged, 1 listed, 0 not checked", out)

    def test_flag_exits_one_and_names_the_block(self):
        self.repo.write("a.go", GROWN)
        status, out, _ = self.call(self.base)
        self.assertEqual(status, 1)
        self.assertIn("FLAG a.go:1  GREW  1 -> 2 lines  | func run() {}", out)
        self.assertIn("1 flagged, 1 listed, 0 not checked", out)

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
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            status, _, _ = self.call("HEAD")
        self.assertEqual(status, 2)

if __name__ == "__main__":
    unittest.main()
