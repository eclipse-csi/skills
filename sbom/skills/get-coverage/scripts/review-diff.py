#!/usr/bin/env python3
"""Compare the candidate product list with github-products.json, and apply it after review.

Without --apply: writes .sbom-coverage/diff.md listing, per project, the products that
were added or removed and those whose repos changed, and prints a summary. Nothing else
is modified.

With --apply: copies the candidate to github-products.json (keeping the previous file as
github-products.previous.json) and updates .sbom-coverage/cache.json, so unchanged
projects are skipped on the next run. Run match-dtrack.py afterwards to set the
sbom_uploaded flags.
"""

import argparse
import json
import os
import shutil
import sys

STATE_DIR = ".sbom-coverage"
PRODUCTS = "github-products.json"


def load(path, default=None):
    """Load a JSON file, or return default when it does not exist."""
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def repos_of(entry):
    """Return the sorted repo list of a product in either the list or object form."""
    return sorted(entry["repos"] if isinstance(entry, dict) else entry)


def main() -> int:
    """Write the diff report, or apply the candidate when --apply is given."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="replace github-products.json with the candidate and update the cache")
    args = parser.parse_args()

    candidate = load(os.path.join(STATE_DIR, "candidate.json"))
    if candidate is None:
        sys.exit("error: run merge-products.py (and verify-images.py) first")
    current = load(PRODUCTS, {})

    lines, added, removed, changed, touched = [], 0, 0, 0, 0
    for name in list(candidate) + [n for n in current if n not in candidate]:
        new, old = candidate.get(name, {}), current.get(name, {})
        plus = sorted(set(new) - set(old))
        minus = sorted(set(old) - set(new))
        moved = sorted(k for k in set(new) & set(old) if repos_of(new[k]) != repos_of(old[k]))
        if not (plus or minus or moved):
            continue
        touched += 1
        added, removed, changed = added + len(plus), removed + len(minus), changed + len(moved)
        lines.append(f"### {name}  ({len(old)} → {len(new)} products)")
        lines += [f"- ➕ `{k}` ← {', '.join(repos_of(new[k]))}" for k in plus]
        lines += [f"- ➖ `{k}`" for k in minus]
        lines += [f"- ✏️ `{k}` repos: {', '.join(repos_of(new[k]))}" for k in moved]
        lines.append("")

    old_total = sum(len(v) for v in current.values())
    new_total = sum(len(v) for v in candidate.values())
    header = ["# Product changes", "",
              f"Products: {old_total} → {new_total}. Projects changed: {touched}. "
              f"Added {added}, removed {removed}, repos changed {changed}.", ""]
    report = "\n".join(header + (lines or ["No changes."])) + "\n"
    with open(os.path.join(STATE_DIR, "diff.md"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print(header[2], file=sys.stderr)

    if args.apply:
        if os.path.exists(PRODUCTS):
            shutil.copyfile(PRODUCTS, "github-products.previous.json")
        with open(PRODUCTS, "w", encoding="utf-8") as fh:
            json.dump(candidate, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        fingerprints = load(os.path.join(STATE_DIR, "fingerprints.json"), {})
        cache = {name: {"fingerprint": fingerprints[name], "products": candidate[name]}
                 for name in candidate if name in fingerprints}
        with open(os.path.join(STATE_DIR, "cache.json"), "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=1, ensure_ascii=False)
        print(f"applied: github-products.json updated ({new_total} products), cache "
              f"refreshed ({len(cache)} projects)", file=sys.stderr)
    else:
        print(f"review {STATE_DIR}/diff.md, then run with --apply", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
