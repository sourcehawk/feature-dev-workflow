#!/usr/bin/env python3
"""Lists the comment blocks that changed since a base ref and flags the ones that grew.

Usage: comment_growth.py [base] [--user-facing GLOB]...

The comparison starts at the merge base of base and HEAD and ends at the
working tree. Exit status: 0 when nothing is flagged, 1 when a block is
flagged, 2 on a usage error or a git error. A flag is not a verdict.
"""
from __future__ import annotations

import argparse
import difflib
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

AFTER = "after"
BEFORE = "before"


@dataclass(frozen=True)
class Family:
    name: str
    line_markers: Tuple[str, ...]
    delimiters: Tuple[Tuple[str, str], ...]
    # The side of the anchor line for a delimited block. A block of line
    # markers always takes the code line after it.
    delimited_anchor: str
    # True when the family's delimiters double as a plain string literal in
    # its language, so an opening delimiter is a doc comment only in the
    # position of one: the first statement of the file, or right after a
    # line that ends with ':'. Elsewhere it is a string a code line opens.
    doc_position_only: bool = False


SLASH = Family("slash", ("//",), (("/*", "*/"),), AFTER)
HASH = Family("hash", ("#",), (), AFTER)
HASH_DOCSTRING = Family("hash-docstring", ("#",), (('"""', '"""'), ("'''", "'''")), BEFORE, doc_position_only=True)
DASH = Family("dash", ("--",), (("--[[", "]]"), ("{-", "-}"), ("/*", "*/")), AFTER)
MARKUP = Family("markup", (), (("<!--", "-->"),), AFTER)
SEMICOLON = Family("semicolon", (";",), (), AFTER)
PERCENT = Family("percent", ("%",), (), AFTER)

EXTENSIONS: Dict[str, Family] = {}
for _family, _extensions in (
    (SLASH, ".c .h .cc .cpp .cxx .hpp .cs .java .js .jsx .mjs .cjs .ts .tsx .go .rs .swift .kt .kts .scala .dart .php .m .mm .proto .groovy .gradle .zig .css .scss .less .v .sv"),
    (HASH, ".sh .bash .zsh .fish .rb .pl .pm .yaml .yml .toml .tf .tfvars .hcl .r .ex .exs .nix .mk .cmake .ps1 .conf .cfg .properties .jl .tcl .awk"),
    (HASH_DOCSTRING, ".py .pyi"),
    (DASH, ".sql .lua .hs .elm .adb .ads .vhd .vhdl"),
    (MARKUP, ".html .htm .xml .xsl .vue .svelte"),
    (SEMICOLON, ".clj .cljs .cljc .edn .lisp .el .scm .rkt .ini .asm .s"),
    (PERCENT, ".erl .hrl .tex .sty .pro"),
):
    for _extension in _extensions.split():
        EXTENSIONS[_extension] = _family

FILENAMES: Dict[str, Family] = {
    "Makefile": HASH,
    "GNUmakefile": HASH,
    "Dockerfile": HASH,
    "Containerfile": HASH,
    "Rakefile": HASH,
    "Gemfile": HASH,
    "Justfile": HASH,
    "CMakeLists.txt": HASH,
}

# File types that hold prose or data and no code comments. The gate skips them without a report.
SKIPPED = frozenset(
    ".md .markdown .rst .txt .adoc .json .lock .sum .csv .tsv .svg .png .jpg .jpeg .gif .ico .pdf .snap .golden".split()
)


def family_for(path: str) -> Optional[Family]:
    name = os.path.basename(path)
    if name in FILENAMES:
        return FILENAMES[name]
    return EXTENSIONS.get(os.path.splitext(name)[1].lower())


def is_skipped(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SKIPPED


@dataclass(frozen=True)
class Block:
    line: int
    text: Tuple[str, ...]
    anchor: str

    @property
    def length(self) -> int:
        return len(self.text)


_LETTERS = re.compile(r"^[A-Za-z]*")


def _prefix_length(stripped: str, family: Family) -> int:
    """The length of the string-literal prefix (r, b, f, ...) before a doc-position delimiter."""
    return len(_LETTERS.match(stripped).group()) if family.doc_position_only else 0


def _opening(stripped: str, family: Family) -> Optional[Tuple[str, str]]:
    body = stripped[_prefix_length(stripped, family):]
    for opening, closing in family.delimiters:
        if body.startswith(opening):
            return opening, closing
    return None


def _is_doc_position(lines: Sequence[str], index: int) -> bool:
    """True at the first statement of the file, or right after a line ending with ':'."""
    previous = index - 1
    while previous >= 0 and not lines[previous].strip():
        previous -= 1
    return previous < 0 or lines[previous].strip().endswith(":")


def _string_open(stripped: str, family: Family) -> Optional[Tuple[str, str]]:
    """Returns (closing token, remainder after it opens) for a string stripped opens but does not close, or None."""
    earliest: Optional[Tuple[int, str, str]] = None
    for opening, closing in family.delimiters:
        at = stripped.find(opening)
        if at == -1:
            continue
        rest = stripped[at + len(opening):]
        if closing in rest:
            continue
        if earliest is None or at < earliest[0]:
            earliest = (at, closing, rest)
    return (earliest[1], earliest[2]) if earliest else None


def _is_line_comment(stripped: str, family: Family) -> bool:
    if _opening(stripped, family) is not None:
        return False
    return any(stripped.startswith(marker) for marker in family.line_markers)


def _spans(lines: Sequence[str], family: Family) -> Tuple[List[Tuple[int, int, str]], set]:
    spans: List[Tuple[int, int, str]] = []
    # Lines that a plain string literal occupies. A doc-position family can
    # open one on a code line; those lines are not a comment and not an anchor.
    excluded: set = set()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        delimiter = _opening(stripped, family)
        if delimiter is not None and (not family.doc_position_only or _is_doc_position(lines, index)):
            opening, closing = delimiter
            end = index
            rest = stripped[_prefix_length(stripped, family) + len(opening):]
            while closing not in rest and end + 1 < len(lines):
                end += 1
                rest = lines[end]
            spans.append((index, end, family.delimited_anchor))
            index = end + 1
        elif _is_line_comment(stripped, family):
            end = index
            while end + 1 < len(lines) and _is_line_comment(lines[end + 1].strip(), family):
                end += 1
            spans.append((index, end, AFTER))
            index = end + 1
        else:
            opened = _string_open(stripped, family) if family.doc_position_only else None
            if opened is None:
                index += 1
            else:
                closing, rest = opened
                end = index
                while closing not in rest and end + 1 < len(lines):
                    end += 1
                    rest = lines[end]
                excluded.update(range(index, end + 1))
                index = end + 1
    return spans, excluded


def scan(source: str, family: Family) -> List[Block]:
    """Returns the comment blocks of source, in source order."""
    lines = source.splitlines()
    spans, excluded = _spans(lines, family)
    commented = set(excluded)
    for start, end, _ in spans:
        commented.update(range(start, end + 1))

    def anchor(start: int, end: int, side: str) -> str:
        candidates = range(end + 1, len(lines)) if side == AFTER else range(start - 1, -1, -1)
        for index in candidates:
            if index not in commented and lines[index].strip():
                return lines[index].strip()
        return ""

    return [
        Block(start + 1, tuple(line.strip() for line in lines[start : end + 1]), anchor(start, end, side))
        for start, end, side in spans
    ]


ADDED = "ADDED"
CHANGED = "CHANGED"
GREW = "GREW"
REMOVED = "REMOVED"

# Two anchor lines at or above this ratio are the same declaration after an edit.
SIMILAR_ANCHOR = 0.6

_WORDS = re.compile(r"\w+")


def _kept(old: Block, new: Block) -> float:
    """The share of the words of old that new keeps, in order. A block that grew keeps all of them."""
    words = _WORDS.findall(" ".join(old.text).lower())
    if not words:
        return 1.0
    matcher = difflib.SequenceMatcher(None, words, _WORDS.findall(" ".join(new.text).lower()), autojunk=False)
    return sum(match.size for match in matcher.get_matching_blocks()) / len(words)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    status: str
    old_length: int
    new_length: int
    anchor: str
    flagged: bool
    user_facing: bool = False


def pair(old: Sequence[Block], new: Sequence[Block]) -> Tuple[Dict[int, Optional[Block]], Tuple[Block, ...]]:
    """Maps the index of each changed or added block of new to its block in old (or to None), and lists the
    blocks of old that have no partner in new."""
    # (order, block) for each block of old not yet claimed by an unchanged match.
    free: List[Tuple[int, Block]] = list(enumerate(old))
    open_indexes: List[int] = []
    for index, block in enumerate(new):
        same = next(((order, b) for order, b in free if b.anchor == block.anchor and b.text == block.text), None)
        if same is None:
            open_indexes.append(index)
        else:
            free.remove(same)

    # Every candidate pairing of one open block of new with one free block of
    # old, so the best match anywhere in the file is assigned before a
    # weaker match elsewhere can claim the same block first. The anchor
    # decides whether two blocks can pair; the kept words of the comment
    # decide between a grown block and a new sibling above a similar anchor.
    candidates: List[Tuple[float, int, int, int]] = []
    for index in open_indexes:
        block = new[index]
        for order, candidate in free:
            similarity = 1.0 if candidate.anchor == block.anchor else difflib.SequenceMatcher(
                None, candidate.anchor, block.anchor
            ).ratio()
            if similarity >= SIMILAR_ANCHOR:
                candidates.append((similarity + _kept(candidate, block), abs(order - index), index, order))
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))

    pairs: Dict[int, Optional[Block]] = {index: None for index in open_indexes}
    claimed_new = set()
    claimed_old = set()
    for score, distance, index, order in candidates:
        if index in claimed_new or order in claimed_old:
            continue
        pairs[index] = old[order]
        claimed_new.add(index)
        claimed_old.add(order)

    removed = tuple(block for order, block in free if order not in claimed_old)
    return pairs, removed


def compare(path: str, old_source: str, new_source: str, family: Family) -> List[Finding]:
    old = scan(old_source, family)
    new = scan(new_source, family)
    pairs, removed = pair(old, new)
    findings = []
    for index, base in sorted(pairs.items()):
        block = new[index]
        if base is None:
            findings.append(Finding(path, block.line, ADDED, 0, block.length, block.anchor, False))
        elif block.length > base.length:
            findings.append(Finding(path, block.line, GREW, base.length, block.length, block.anchor, True))
        else:
            findings.append(Finding(path, block.line, CHANGED, base.length, block.length, block.anchor, False))
    for block in removed:
        findings.append(Finding(path, block.line, REMOVED, block.length, 0, block.anchor, False))
    return findings


class GitError(Exception):
    pass


def git(cwd: str, *args: str) -> str:
    # Ignore a repository location inherited from the shell (for example
    # from a git hook), so the command always resolves against cwd.
    env = dict(os.environ)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)
    try:
        result = subprocess.run(["git", *args], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as error:
        raise GitError("cannot run git: %s" % error)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(message or "git " + " ".join(args) + " failed")
    return result.stdout.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Change:
    path: str
    base_path: Optional[str]


def changed_files(top: str, merge_base: str) -> List[Change]:
    """Lists the files that differ from merge_base in the working tree, untracked files included."""
    fields = git(top, "diff", "--name-status", "-M", "-z", merge_base).split("\0")
    changes = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index][0]
        if status in "RC":
            changes.append(Change(fields[index + 2], fields[index + 1]))
            index += 3
            continue
        if status == "A":
            changes.append(Change(fields[index + 1], None))
        else:
            changes.append(Change(fields[index + 1], fields[index + 1]))
        index += 2
    for path in git(top, "ls-files", "--others", "--exclude-standard", "-z").split("\0"):
        if path:
            changes.append(Change(path, None))
    return sorted(changes, key=lambda change: change.path)


@dataclass(frozen=True)
class Report:
    findings: Tuple[Finding, ...]
    not_checked: Tuple[str, ...]

    @property
    def flagged(self) -> bool:
        return any(finding.flagged for finding in self.findings)


def run(cwd: str, base: str, user_facing: Sequence[str] = ()) -> Report:
    top = git(cwd, "rev-parse", "--show-toplevel").strip()
    merge_base = git(top, "merge-base", base, "HEAD").strip()
    findings: List[Finding] = []
    not_checked: List[str] = []
    for change in changed_files(top, merge_base):
        full_path = os.path.join(top, change.path)
        exists = os.path.isfile(full_path)
        if not exists and change.base_path is None:
            continue
        # The file name (CMakeLists.txt, say) can claim a family the
        # extension would otherwise skip, so it is checked first.
        family = family_for(change.path)
        if family is None:
            if not is_skipped(change.path):
                not_checked.append(change.path)
            continue
        if exists:
            try:
                with open(full_path, encoding="utf-8", errors="replace") as handle:
                    new_source = handle.read()
            except OSError as error:
                raise GitError("cannot read %s: %s" % (change.path, error))
        else:
            new_source = ""
        old_source = git(top, "show", merge_base + ":" + change.base_path) if change.base_path else ""
        exempt = any(fnmatch.fnmatchcase(change.path, glob) for glob in user_facing)
        for finding in compare(change.path, old_source, new_source, family):
            if exempt:
                finding = Finding(
                    finding.path, finding.line, finding.status, finding.old_length,
                    finding.new_length, finding.anchor, False, True,
                )
            findings.append(finding)
    return Report(tuple(findings), tuple(not_checked))


def render(report: Report) -> str:
    lines = []
    for finding in report.findings:
        mark = "FLAG" if finding.flagged else "    "
        size = "%d -> %d lines" % (finding.old_length, finding.new_length)
        note = "  (user-facing, not flagged)" if finding.user_facing else ""
        lines.append(
            "%s %s:%d  %s  %s  | %s%s"
            % (mark, finding.path, finding.line, finding.status, size, finding.anchor or "(no anchor)", note)
        )
    for path in report.not_checked:
        lines.append("     %s  NOT CHECKED  unknown file type, read its diff" % path)
    flagged = sum(1 for finding in report.findings if finding.flagged)
    removed = sum(1 for finding in report.findings if finding.status == REMOVED)
    lines.append(
        "%d flagged, %d listed, %d removed, %d not checked"
        % (flagged, len(report.findings), removed, len(report.not_checked))
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="comment_growth.py",
        description="List the comment blocks that changed since BASE and flag the ones that grew.",
    )
    parser.add_argument("base", nargs="?", default="origin/main", help="ref to compare with (default: origin/main)")
    parser.add_argument(
        "--user-facing", action="append", default=[], metavar="GLOB",
        help="path pattern whose comments ship to users; listed, never flagged. Repeat for more patterns.",
    )
    args = parser.parse_args(argv)
    try:
        report = run(os.getcwd(), args.base, args.user_facing)
    except GitError as error:
        print("comment_growth: %s" % error, file=sys.stderr)
        return 2
    print(render(report))
    return 1 if report.flagged else 0

if __name__ == "__main__":
    sys.exit(main())
