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
