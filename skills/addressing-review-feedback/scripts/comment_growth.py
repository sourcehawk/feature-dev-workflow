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


SLASH = Family("slash", ("//",), (("/*", "*/"),), AFTER)
HASH = Family("hash", ("#",), (), AFTER)
HASH_DOCSTRING = Family("hash-docstring", ("#",), (('"""', '"""'), ("'''", "'''")), BEFORE)
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


def _opening(stripped: str, family: Family) -> Optional[Tuple[str, str]]:
    for opening, closing in family.delimiters:
        if stripped.startswith(opening):
            return opening, closing
    return None


def _is_line_comment(stripped: str, family: Family) -> bool:
    if _opening(stripped, family) is not None:
        return False
    return any(stripped.startswith(marker) for marker in family.line_markers)


def _spans(lines: Sequence[str], family: Family) -> List[Tuple[int, int, str]]:
    spans: List[Tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        delimiter = _opening(stripped, family)
        if delimiter is not None:
            opening, closing = delimiter
            end = index
            rest = stripped[len(opening):]
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
            index += 1
    return spans


def scan(source: str, family: Family) -> List[Block]:
    """Returns the comment blocks of source, in source order."""
    lines = source.splitlines()
    spans = _spans(lines, family)
    commented = set()
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

# Two anchor lines at or above this ratio are the same declaration after an edit.
SIMILAR_ANCHOR = 0.6


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


def pair(old: Sequence[Block], new: Sequence[Block]) -> Dict[int, Optional[Block]]:
    """Maps the index of each changed or added block of new to its block in old, or to None."""
    free = list(old)
    open_indexes: List[int] = []
    for index, block in enumerate(new):
        same = next((b for b in free if b.anchor == block.anchor and b.text == block.text), None)
        if same is None:
            open_indexes.append(index)
        else:
            free.remove(same)

    pairs: Dict[int, Optional[Block]] = {}
    for index in open_indexes:
        match = next((b for b in free if b.anchor and b.anchor == new[index].anchor), None)
        pairs[index] = match
        if match is not None:
            free.remove(match)

    for index in open_indexes:
        if pairs[index] is not None or not new[index].anchor:
            continue
        best: Optional[Block] = None
        best_rank: Tuple[float, int] = (0.0, 0)
        for candidate in free:
            if not candidate.anchor:
                continue
            ratio = difflib.SequenceMatcher(None, candidate.anchor, new[index].anchor).ratio()
            rank = (ratio, -abs(candidate.line - new[index].line))
            if ratio >= SIMILAR_ANCHOR and (best is None or rank > best_rank):
                best, best_rank = candidate, rank
        if best is not None:
            pairs[index] = best
            free.remove(best)
    return pairs


def compare(path: str, old_source: str, new_source: str, family: Family) -> List[Finding]:
    old = scan(old_source, family)
    new = scan(new_source, family)
    findings = []
    for index, base in sorted(pair(old, new).items()):
        block = new[index]
        if base is None:
            findings.append(Finding(path, block.line, ADDED, 0, block.length, block.anchor, False))
        elif block.length > base.length:
            findings.append(Finding(path, block.line, GREW, base.length, block.length, block.anchor, True))
        else:
            findings.append(Finding(path, block.line, CHANGED, base.length, block.length, block.anchor, False))
    return findings


class GitError(Exception):
    pass


def git(cwd: str, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
        elif status != "D":
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
        if is_skipped(change.path):
            continue
        full_path = os.path.join(top, change.path)
        if not os.path.isfile(full_path):
            continue
        family = family_for(change.path)
        if family is None:
            not_checked.append(change.path)
            continue
        with open(full_path, encoding="utf-8", errors="replace") as handle:
            new_source = handle.read()
        old_source = git(top, "show", merge_base + ":" + change.base_path) if change.base_path else ""
        exempt = any(fnmatch.fnmatch(change.path, glob) for glob in user_facing)
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
    lines.append(
        "%d flagged, %d listed, %d not checked" % (flagged, len(report.findings), len(report.not_checked))
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
