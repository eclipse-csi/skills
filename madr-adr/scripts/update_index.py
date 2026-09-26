#!/usr/bin/env python3
"""
Create or refresh the ADR index in README.md at the root of the ADR directory.

Usage:
    python update_index.py [--root .] [--dir docs/decisions] [--check]

The index is a table (number, title, status, date) generated between the markers
<!-- adrlog --> and <!-- adrlogstop --> (the same markers the adr-log tool uses).
Everything outside the markers is left untouched, so put intro text there.
Category subfolders get their own table under a "### <category>" heading.

  * README.md missing:          it is created with a heading, a short intro and the index.
  * README.md without markers:  an "## Index" section with the markers is appended.
  * --check:                    write nothing; exit 1 if README.md is missing or out of date.

Pure standard library; reuses the parsing in find_adrs.py.
"""

import argparse
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill directory free of __pycache__
sys.path.insert(0,str(Path(__file__).resolve().parent))
from find_adrs import ADR_FILE_RE, INDEX_END, INDEX_START, adr_files, discover, rank, read_meta  # noqa: E402

DEFAULT_README = """# Architectural Decision Records

This folder records the architecturally significant decisions of this project, one [MADR](https://adr.github.io/madr/) file per decision.
Records are append-only: a changed decision gets a new ADR that supersedes the old one.

{block}
"""


def cell(text):
    return (text or "-").replace("|", "\\|").strip() or "-"


def table(adr_dir, files):
    rows = ["| ADR | Decision | Status | Date |", "| --- | --- | --- | --- |"]
    for f in sorted(files, key=lambda f: int(ADR_FILE_RE.match(f.name).group(1))):
        m = ADR_FILE_RE.match(f.name)
        meta = read_meta(f)
        title = meta.get("title") or m.group(2).replace("-", " ").capitalize()
        link = f.relative_to(adr_dir).as_posix()
        rows.append(f"| [{m.group(1)}]({link}) | {cell(title)} | {cell(meta.get('status'))} | {cell(meta.get('date'))} |")
    return rows


def build_block(adr_dir):
    """Return (block text, number of ADRs indexed)."""
    top = adr_files(adr_dir) if adr_dir.is_dir() else []
    categories = sorted((p for p in adr_dir.iterdir() if p.is_dir() and adr_files(p)), key=lambda p: p.name) if adr_dir.is_dir() else []
    parts, count = [], len(top)
    if top or not categories:
        parts.append("\n".join(table(adr_dir, top)) if top else "_No decisions recorded yet._")
    for cat in categories:
        files = adr_files(cat)
        count += len(files)
        parts.append(f"### {cat.name}\n\n" + "\n".join(table(adr_dir, files)))
    return f"{INDEX_START}\n\n" + "\n\n".join(parts) + f"\n\n{INDEX_END}", count


def render(current, block):
    """Return (new README text, note or None)."""
    if current is None:
        return DEFAULT_README.format(block=block), None
    pattern = re.compile(re.escape(INDEX_START) + r".*?" + re.escape(INDEX_END), re.S)
    if pattern.search(current):
        return pattern.sub(lambda _: block, current, count=1), None
    note = ("README.md had no index markers, so an '## Index' section was appended. "
            "If it already contained a hand-written list of ADRs, remove it in favour of the generated one.")
    return current.rstrip("\n") + f"\n\n## Index\n\n{block}\n", note


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="repository root (default: current directory)")
    ap.add_argument("--dir", help="ADR directory (skips discovery)")
    ap.add_argument("--check", action="store_true", help="only report; exit 1 if the index is missing or stale")
    args = ap.parse_args()

    root = Path(args.root)
    if args.dir:
        adr_dir = root / args.dir
        if not adr_dir.exists():
            adr_dir = Path(args.dir)
    else:
        ranked = rank(root, discover(root))
        adr_dir = ranked[0][0] if ranked else root / "docs" / "decisions"
    if not adr_dir.is_dir():
        print(f"ADR directory not found: {adr_dir}", file=sys.stderr)
        return 1

    readme = adr_dir / "README.md"
    current = readme.read_text(encoding="utf-8") if readme.is_file() else None
    block, count = build_block(adr_dir)
    new, note = render(current, block)

    if new == current:
        print(f"Unchanged {readme} ({count} ADRs)")
        return 0
    if args.check:
        print(f"Out of date: {readme} ({'missing' if current is None else 'index differs'}); run update_index.py")
        return 1
    readme.write_text(new, encoding="utf-8")
    print(f"{'Created' if current is None else 'Updated'} {readme} ({count} ADRs)")
    if note:
        print(f"Note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
