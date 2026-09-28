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
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
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
    # line whose code ends with ':'. Elsewhere it is a string a code line opens.
    doc_position_only: bool = False
    # The quote characters of a one-line string, read only for a doc-position family.
    quotes: str = ""


SLASH = Family("slash", ("//",), (("/*", "*/"),), AFTER)
HASH = Family("hash", ("#",), (), AFTER)
HASH_DOCSTRING = Family("hash-docstring", ("#",), (('"""', '"""'), ("'''", "'''")), BEFORE, doc_position_only=True, quotes="'\"")
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


def _read_code(stripped: str, family: Family) -> Tuple[str, Optional[Tuple[str, str]]]:
    """Returns the code of stripped before a trailing line comment, and (closing token, remainder after it
    opens) for a string stripped opens but does not close, or None.

    A delimiter or a line marker inside a one-line string, and a delimiter after a line marker, count for nothing.
    """
    at = 0
    while at < len(stripped):
        if any(stripped.startswith(marker, at) for marker in family.line_markers):
            return stripped[:at].rstrip(), None
        delimiter = next(((o, c) for o, c in family.delimiters if stripped.startswith(o, at)), None)
        if delimiter is not None:
            opening, closing = delimiter
            end = stripped.find(closing, at + len(opening))
            if end == -1:
                return stripped, (closing, stripped[at + len(opening):])
            at = end + len(closing)
        elif stripped[at] in family.quotes:
            quote = stripped[at]
            at += 1
            while at < len(stripped) and stripped[at] != quote:
                at += 2 if stripped[at] == "\\" else 1
            at += 1
        else:
            at += 1
    return stripped, None


def _is_doc_position(lines: Sequence[str], index: int, family: Family) -> bool:
    """True at the first statement of the file, or right after a line whose code ends with ':'. Blank lines
    and comment lines in between do not count, as they do not count in the language."""
    for previous in range(index - 1, -1, -1):
        code, _ = _read_code(lines[previous].strip(), family)
        if code:
            return code.endswith(":")
    return True


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
        if delimiter is not None and (not family.doc_position_only or _is_doc_position(lines, index, family)):
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
            opened = _read_code(stripped, family)[1] if family.doc_position_only else None
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
# Across files a pair must also keep this share of the old words, since a
# common anchor (a return, an error check, no anchor at all) repeats in every file.
KEPT_ACROSS_FILES = 0.5
# The most pairs of blocks the pairing across files scores. Past it the
# pairing across files does not run, so its time stays bounded, and the report says so.
MOST_PAIRS_ACROSS_FILES = 150000

_WORDS = re.compile(r"\w+")


class TooManyPairs(Exception):
    pass


def _words(block: Block) -> List[str]:
    return _WORDS.findall(" ".join(block.text).lower())


def _kept(old_words: Sequence[str], new_words: Sequence[str]) -> float:
    """The share of old_words that new_words keeps, in order. A block that grew keeps all of them."""
    if not old_words:
        return 1.0
    matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    return sum(match.size for match in matcher.get_matching_blocks()) / len(old_words)


def _similarity(old_anchor: str, new_anchor: str) -> float:
    """The ratio of two anchor lines, or 0.0 when a quick upper bound of it is already below SIMILAR_ANCHOR."""
    if old_anchor == new_anchor:
        return 1.0
    matcher = difflib.SequenceMatcher(None, old_anchor, new_anchor)
    if matcher.real_quick_ratio() < SIMILAR_ANCHOR or matcher.quick_ratio() < SIMILAR_ANCHOR:
        return 0.0
    return matcher.ratio()


def _reach(old_words: Sequence[str], postings: Dict[str, List[int]], indexes: List[int], min_kept: float) -> List[int]:
    """The blocks among indexes that can keep min_kept of old_words. With a share to keep, a block with no
    words has none to share and reaches no block."""
    if min_kept <= 0:
        return indexes
    if not old_words:
        return []
    # To keep `need` of the words, a block holds a word from each set of
    # len - need + 1 positions, so the rarest such set names every candidate.
    need = math.ceil(min_kept * len(old_words))
    rarest = sorted(old_words, key=lambda word: len(postings.get(word, ())))[: len(old_words) - need + 1]
    return sorted(set().union(*(postings.get(word, ()) for word in rarest)))


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
    # (path, line) of the block in the old file, for a block paired with one of another file.
    moved_from: Optional[Tuple[str, int]] = None


def pair(
    old: Sequence[Block], new: Sequence[Block], min_kept: float = 0.0, most: Optional[int] = None,
    one_file: bool = True,
) -> Tuple[Dict[int, Optional[int]], Tuple[int, ...]]:
    """Maps the index of each changed or added block of new to the index of its block in old (or to None), and
    lists the indexes of the blocks of old that have no partner in new. A pair keeps at least min_kept of the
    old words. Raises TooManyPairs when more than most pairs of blocks would need a score. Only in one_file does
    an identical copy leave its old block free for a longer block, and a longer block share an old block."""
    old_words = [_words(block) for block in old]
    new_words = [_words(block) for block in new]
    # The orders of the blocks of old not yet claimed by an unchanged match, by (anchor, text).
    unchanged: Dict[Tuple[str, Tuple[str, ...]], List[int]] = {}
    for order, block in enumerate(old):
        unchanged.setdefault((block.anchor, block.text), []).append(order)
    fresh = [index for index, block in enumerate(new) if (block.anchor, block.text) not in unchanged]
    open_indexes: List[int] = []
    # The block of old that each identical copy in new leaves free for a longer block that keeps all its words.
    copies: Dict[int, int] = {}
    # The longer blocks each block of old was left free for; only they can pair with it.
    freed_for: Dict[int, set] = {}
    for index, block in enumerate(new):
        orders = unchanged.get((block.anchor, block.text))
        if not orders:
            open_indexes.append(index)
            continue
        words = old_words[orders[0]]
        longer = {
            other
            for other in (fresh if one_file and words else ())
            if new[other].length > block.length
            and _similarity(block.anchor, new[other].anchor) >= SIMILAR_ANCHOR
            and _kept(words, new_words[other]) == 1.0
        }
        if longer:
            copies[index] = orders[0]
            freed_for.setdefault(orders[0], set()).update(longer)
        else:
            orders.pop(0)
    free = sorted(order for orders in unchanged.values() for order in orders)

    # Each word, mapped to the open blocks of new that hold it.
    postings: Dict[str, List[int]] = {}
    for index in open_indexes:
        for word in set(new_words[index]):
            postings.setdefault(word, []).append(index)
    reach: Dict[int, List[int]] = {}
    for order in free:
        reach[order] = _reach(old_words[order], postings, open_indexes, min_kept)
        if order in freed_for:
            reach[order] = [index for index in reach[order] if index in freed_for[order]]
    if most is not None and sum(len(indexes) for indexes in reach.values()) > most:
        raise TooManyPairs()
    new_sets = {index: set(new_words[index]) for index in open_indexes}

    # Every candidate pairing of one open block of new with one free block of
    # old, so the best match anywhere in the file is assigned before a
    # weaker match elsewhere can claim the same block first. The anchor
    # decides whether two blocks can pair; the kept words of the comment
    # decide between a grown block and a new sibling above a similar anchor.
    candidates: List[Tuple[float, int, int, int]] = []
    for order in free:
        words = old_words[order]
        for index in reach[order]:
            # An upper bound of the kept share, cheap next to the two ratios below.
            if min_kept and words and sum(1 for word in words if word in new_sets[index]) < min_kept * len(words):
                continue
            similarity = _similarity(old[order].anchor, new[index].anchor)
            if similarity >= SIMILAR_ANCHOR:
                kept = _kept(words, new_words[index])
                if kept >= min_kept:
                    candidates.append((similarity + kept, abs(order - index), index, order))
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1], candidate[2], candidate[3]))

    pairs: Dict[int, Optional[int]] = {index: None for index in open_indexes}
    # The block of new that took each claimed block of old.
    taker: Dict[int, int] = {}
    for score, distance, index, order in candidates:
        if pairs[index] is None and order not in taker:
            pairs[index] = order
            taker[order] = index
    # A block left without a partner may still be the one that grew, when a
    # sibling that copies the old words took its old block. It shares that
    # block when its anchor is closer to the old anchor than the sibling's, so
    # the growth is flagged rather than missed, and a new block beside a
    # comment changed in place is not.
    for score, distance, index, order in candidates:
        if one_file and pairs[index] is None and new[index].length > old[order].length:
            anchor = old[order].anchor
            if _similarity(anchor, new[index].anchor) > _similarity(anchor, new[taker[order]].anchor):
                pairs[index] = order
    # A copy whose old block no other block took is that block, unchanged.
    for index, order in sorted(copies.items()):
        if order in taker:
            pairs[index] = None
        else:
            taker[order] = index

    return pairs, tuple(order for order in free if order not in taker)


def _findings(
    path: str, base_path: str, new: Sequence[Block], pairs: Dict[int, Optional[Block]], removed: Sequence[Block],
    moved_from: Dict[int, Tuple[str, int]],
) -> List[Finding]:
    findings = []
    for index, base in sorted(pairs.items()):
        block = new[index]
        origin = moved_from.get(index)
        if base is None:
            findings.append(Finding(path, block.line, ADDED, 0, block.length, block.anchor, False))
        elif block.length > base.length:
            findings.append(
                Finding(path, block.line, GREW, base.length, block.length, block.anchor, True, False, origin)
            )
        else:
            findings.append(
                Finding(path, block.line, CHANGED, base.length, block.length, block.anchor, False, False, origin)
            )
    for block in removed:
        findings.append(Finding(base_path, block.line, REMOVED, block.length, 0, block.anchor, False))
    return findings


def _pair_blocks(old: Sequence[Block], new: Sequence[Block]) -> Tuple[Dict[int, Optional[Block]], List[Block]]:
    pairs, removed = pair(old, new)
    return {index: None if order is None else old[order] for index, order in pairs.items()}, [old[o] for o in removed]


def compare(path: str, old_source: str, new_source: str, family: Family) -> List[Finding]:
    new = scan(new_source, family)
    return _findings(path, path, new, *_pair_blocks(scan(old_source, family), new), {})


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
    # (removed, added) block counts when the pairing across files did not run.
    not_paired_across_files: Optional[Tuple[int, int]] = None

    @property
    def flagged(self) -> bool:
        return any(finding.flagged for finding in self.findings)


def run(cwd: str, base: str, user_facing: Sequence[str] = ()) -> Report:
    top = git(cwd, "rev-parse", "--show-toplevel").strip()
    merge_base = git(top, "merge-base", base, "HEAD").strip()
    # (change, new blocks, pairs, removed blocks) of each file that was compared.
    files: List[Tuple[Change, List[Block], Dict[int, Optional[Block]], List[Block]]] = []
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
        new = scan(new_source, family)
        files.append((change, new, *_pair_blocks(scan(old_source, family), new)))

    # A block that moved to another file is still free on both sides after
    # the pairing inside each file, so the free blocks pair once more across files.
    # A block moves to one place, so the rules of one file (a copy that leaves
    # its old block free, a longer block that shares one) do not apply here.
    added = [
        (number, index)
        for number, (_, _, pairs, _) in enumerate(files)
        for index, base in sorted(pairs.items())
        if base is None
    ]
    gone = [(number, block) for number, (_, _, _, removed) in enumerate(files) for block in removed]
    not_paired: Optional[Tuple[int, int]] = None
    # For each file, (path, line) in the old file of each block paired across files, by block index.
    moved_from: List[Dict[int, Tuple[str, int]]] = [{} for _ in files]
    try:
        moved, left = pair(
            [block for _, block in gone], [files[number][1][index] for number, index in added],
            KEPT_ACROSS_FILES, MOST_PAIRS_ACROSS_FILES, one_file=False,
        )
    except TooManyPairs:
        not_paired = (len(gone), len(added))
    else:
        for file in files:
            file[3].clear()
        for order in left:
            number, block = gone[order]
            files[number][3].append(block)
        for position, (number, index) in enumerate(added):
            if position not in moved:
                del files[number][2][index]
            elif moved[position] is not None:
                old_number, block = gone[moved[position]]
                files[number][2][index] = block
                old_change = files[old_number][0]
                moved_from[number][index] = (old_change.base_path or old_change.path, block.line)

    findings: List[Finding] = []
    for number, (change, new, pairs, removed) in enumerate(files):
        exempt = any(fnmatch.fnmatchcase(change.path, glob) for glob in user_facing)
        base_path = change.base_path or change.path
        for finding in _findings(change.path, base_path, new, pairs, removed, moved_from[number]):
            if exempt:
                finding = replace(finding, flagged=False, user_facing=True)
            findings.append(finding)
    return Report(tuple(findings), tuple(not_checked), not_paired)


def render(report: Report) -> str:
    lines = []
    for finding in report.findings:
        mark = "FLAG" if finding.flagged else "    "
        size = "%d -> %d lines" % (finding.old_length, finding.new_length)
        note = "  (moved from %s, old line %d)" % finding.moved_from if finding.moved_from else ""
        if finding.user_facing:
            note += "  (user-facing, not flagged)"
        # A removed block has no line in the working tree; its line is one of the file at the base.
        where = "%s (old line %d)" if finding.status == REMOVED else "%s:%d"
        lines.append(
            "%s %s  %s  %s  | %s%s"
            % (mark, where % (finding.path, finding.line), finding.status, size, finding.anchor or "(no anchor)", note)
        )
    for path in report.not_checked:
        lines.append("     %s  NOT CHECKED  unknown file type, read its diff" % path)
    if report.not_paired_across_files:
        lines.append(
            "     %d removed and %d added blocks NOT PAIRED ACROSS FILES, too many to compare; read their diff"
            % report.not_paired_across_files
        )
    flagged = sum(1 for finding in report.findings if finding.flagged)
    removed = sum(1 for finding in report.findings if finding.status == REMOVED)
    summary = "%d flagged, %d listed, %d removed, %d not checked" % (
        flagged, len(report.findings), removed, len(report.not_checked)
    )
    if report.not_paired_across_files:
        summary += ", %d not paired across files" % sum(report.not_paired_across_files)
    lines.append(summary)
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
