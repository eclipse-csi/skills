#!/usr/bin/env python3
"""
Locate the ADR log in a repository, list existing ADRs, detect the conventions
they use, and suggest the number + filename for the next ADR.

Usage:
    python find_adrs.py [--root .] [--dir docs/decisions] [--title "Use Vitest for unit tests"]
                        [--category backend] [--json]

With no ADR directory found, it suggests docs/decisions/ (the MADR default).
Pure standard library.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ADR_FILE_RE = re.compile(r"^(\d{3,5})-(.+)\.md$")
PREFERRED_DIRS = [
    "docs/decisions", "docs/adr", "docs/adrs", "doc/adr", "doc/decisions",
    "docs/architecture/decisions", "docs/architecture-decisions", "architecture/decisions",
    "adr", "adrs", "decisions",
]
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target", ".venv", "venv",
             "__pycache__", ".next", ".idea", ".vscode", "coverage"}
MAX_DEPTH = 6


def slugify(title):
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return re.sub(r"-{2,}", "-", t) or "untitled-decision"


def read_meta(path):
    """Extract title, status, and style hints from one ADR file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    lines = text.splitlines()
    meta = {"front_matter": False, "fm_keys": [], "status": None, "title": None,
            "numbered_title": False, "markers": set(), "jtd": False, "nygard": False}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                meta["front_matter"] = True
                body_start = i + 1
                break
            m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", lines[i])
            if m:
                key = m.group(1).lower()
                meta["fm_keys"].append(key)
                if key == "status":
                    meta["status"] = m.group(2).strip().strip("\"'") or None
                if key in {"parent", "nav_order"}:
                    meta["jtd"] = True
    in_code = False
    for i in range(body_start, len(lines)):
        line = lines[i]
        if re.match(r"^\s{0,3}(```|~~~)", line):
            in_code = not in_code
            continue
        if in_code:
            continue
        if meta["title"] is None:
            m = re.match(r"^#\s+(.*?)\s*#*\s*$", line)
            if m:
                raw = m.group(1)
                if re.match(r"^(adr[-\s]?)?\d+\s*[.:)\-–]\s*", raw, re.I):
                    meta["numbered_title"] = True
                meta["title"] = re.sub(r"^(adr[-\s]?)?\d+\s*[.:)\-–]\s*", "", raw, flags=re.I)
        if re.match(r"^##\s+(status|decision|context)\s*$", line, re.I):
            meta["nygard"] = True
        if meta["status"] is None:
            m = re.match(r"^\s*\**status\**\s*:\s*\**(.+?)\**\s*$", line, re.I)
            if m:
                meta["status"] = m.group(1).strip()
            elif re.match(r"^##\s+status\s*$", line, re.I):
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip():
                        meta["status"] = lines[j].strip().strip("*_")
                        break
        m = re.match(r"^([*+-])\s+\S", line)
        if m:
            meta["markers"].add(m.group(1))
    return meta


def adr_files(d):
    return sorted(f for f in d.iterdir() if f.is_file() and ADR_FILE_RE.match(f.name))


def discover(root):
    """Return candidate ADR directories: list of (path, count)."""
    found = {}
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if len(rel.parts) >= MAX_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        n = sum(1 for f in filenames if ADR_FILE_RE.match(f))
        if n:
            found[Path(dirpath)] = n
    # Existing-but-empty preferred dirs (e.g. freshly initialised docs/decisions with templates)
    for pd in PREFERRED_DIRS:
        p = root / pd
        if p.is_dir() and p not in found:
            found[p] = 0
    return found


def rank(root, candidates):
    def score(item):
        path, count = item
        rel = path.relative_to(root.resolve()).as_posix()
        pref = PREFERRED_DIRS.index(rel) if rel in PREFERRED_DIRS else len(PREFERRED_DIRS)
        name_hint = 0 if re.search(r"(adr|decision)", rel, re.I) else 1
        return (name_hint, -count, pref, len(rel))
    return sorted(candidates.items(), key=score)


def summarize(root, adr_dir, title, category):
    root = root.resolve()
    adr_dir = adr_dir.resolve()
    target = adr_dir / category if category else adr_dir
    categories = sorted(p.name for p in adr_dir.iterdir() if p.is_dir() and adr_files(p)) if adr_dir.is_dir() else []

    files = adr_files(target) if target.is_dir() else []
    entries, metas = [], []
    for f in files:
        m = ADR_FILE_RE.match(f.name)
        meta = read_meta(f)
        metas.append(meta)
        entries.append({"number": int(m.group(1)), "file": f.relative_to(root).as_posix(),
                        "title": meta.get("title"), "status": meta.get("status")})

    width = max((len(ADR_FILE_RE.match(f.name).group(1)) for f in files), default=4)
    next_num = max((e["number"] for e in entries), default=0) + 1
    numstr = str(next_num).zfill(width)
    suggested = None
    if title:
        suggested = (target / f"{numstr}-{slugify(title)}.md").relative_to(root).as_posix()

    n = len(metas) or 1
    fm_count = sum(1 for m in metas if m.get("front_matter"))
    keys = {}
    for m in metas:
        for k in m.get("fm_keys", []):
            keys[k] = keys.get(k, 0) + 1
    markers = {}
    for m in metas:
        for mk in m.get("markers", set()):
            markers[mk] = markers.get(mk, 0) + 1
    templates = sorted(p.name for p in adr_dir.glob("adr-template*.md")) if adr_dir.is_dir() else []

    return {
        "adr_dir": target.relative_to(root).as_posix(),
        "exists": target.is_dir(),
        "count": len(entries),
        "next_number": numstr,
        "suggested_file": suggested,
        "categories": categories,
        "templates_in_repo": templates,
        "conventions": {
            "front_matter": f"{fm_count}/{len(metas)}" if metas else "n/a",
            "front_matter_keys": dict(sorted(keys.items(), key=lambda kv: -kv[1])),
            "numbered_titles": sum(1 for m in metas if m.get("numbered_title")),
            "just_the_docs_nav": sum(1 for m in metas if m.get("jtd")),
            "nygard_style": sum(1 for m in metas if m.get("nygard")),
            "list_markers": markers,
        },
        "adrs": entries,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="repository root (default: current directory)")
    ap.add_argument("--dir", help="ADR directory to use (skips discovery)")
    ap.add_argument("--title", help="title of the new ADR, used to build the suggested filename")
    ap.add_argument("--category", help="category subfolder inside the ADR directory")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    root = Path(args.root)
    others = []
    if args.dir:
        adr_dir = root / args.dir
        if not adr_dir.exists():
            adr_dir = Path(args.dir)
    else:
        ranked = rank(root, discover(root))
        if ranked:
            adr_dir = ranked[0][0]
            others = [(p.resolve().relative_to(root.resolve()).as_posix(), c) for p, c in ranked[1:]]
        else:
            adr_dir = root / "docs" / "decisions"

    info = summarize(root, adr_dir, args.title, args.category)
    info["other_candidates"] = others

    if args.json:
        print(json.dumps(info, indent=2))
        return 0

    state = "" if info["exists"] else "  (does not exist yet: MADR default, create it)"
    print(f"ADR directory : {info['adr_dir']}{state}")
    print(f"Existing ADRs : {info['count']}")
    print(f"Next number   : {info['next_number']}")
    if info["suggested_file"]:
        print(f"Suggested file: {info['suggested_file']}")
    if info["categories"]:
        print(f"Categories    : {', '.join(info['categories'])} (numbering is per category; pass --category)")
    if info["templates_in_repo"]:
        print(f"Templates     : {', '.join(info['templates_in_repo'])} (repo has its own copy; prefer it)")
    if others:
        print("Other candidate dirs: " + ", ".join(f"{p} ({c})" for p, c in others))
    if info["count"]:
        c = info["conventions"]
        print("\nConventions in existing ADRs (follow these over MADR defaults):")
        print(f"  front matter     : {c['front_matter']}  keys: {', '.join(f'{k}({v})' for k, v in c['front_matter_keys'].items()) or '-'}")
        print(f"  numbered titles  : {c['numbered_titles']}/{info['count']}  (e.g. '# 3. Use X' or '# ADR-003: Use X')")
        print(f"  Just the Docs nav: {c['just_the_docs_nav']}/{info['count']}  (parent / nav_order keys)")
        print(f"  Nygard sections  : {c['nygard_style']}/{info['count']}  (## Status / ## Context / ## Decision)")
        print(f"  list markers     : {', '.join(f'{k!r}({v})' for k, v in c['list_markers'].items()) or '-'}")
        print("\nExisting ADRs:")
        for e in info["adrs"]:
            print(f"  {str(e['number']).zfill(len(info['next_number']))}  {(e['status'] or '-')[:28]:<28}  {e['title'] or '(no title)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
