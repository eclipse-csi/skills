#!/usr/bin/env python3
"""Split projects that need (re)analysis into batch fact files for product identification.

Each project's input is fingerprinted: a hash of its repo facts, its PMI metadata and the
product rules (references/product-rules.md plus sections 1-2 of the sibling
list-products skill). A project whose fingerprint matches the cache in
.sbom-coverage/cache.json keeps its cached products and is not re-analysed.

Writes .sbom-coverage/batches/bNNN-facts.json (one per batch) and
.sbom-coverage/plan.json, which lists the batches and the cached projects.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_FILE = os.path.join(SKILL_DIR, "references", "product-rules.md")
LIST_PRODUCTS = os.path.join(os.path.dirname(SKILL_DIR), "list-products", "SKILL.md")
STATE_DIR = ".sbom-coverage"


def rules_text() -> str:
    """Return the rule text that product identification depends on."""
    with open(RULES_FILE, encoding="utf-8") as fh:
        text = fh.read()
    with open(LIST_PRODUCTS, encoding="utf-8") as fh:
        skill = fh.read()
    # Sections "## 1." and "## 2." of list-products are the classification and grouping rules.
    start = re.search(r"^## 1\.", skill, re.M)
    end = start and re.compile(r"^## 3\.", re.M).search(skill, start.start())
    if not end:
        sys.exit(f"error: could not find sections 1-2 in {LIST_PRODUCTS}")
    return text + "\n" + skill[start.start():end.start()]


def fingerprint(*parts) -> str:
    """Stable hash of JSON-serialisable parts."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(json.dumps(part, sort_keys=True, ensure_ascii=False).encode())
    return digest.hexdigest()[:16]


def load(path, default=None):
    """Load a JSON file, or return default when it does not exist."""
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    """Compute fingerprints, reuse cached projects and write batch files for the rest."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=9,
                        help="projects per batch (default: %(default)s)")
    parser.add_argument("--max-repos", type=int, default=120,
                        help="start a new batch once it holds this many repos (default: %(default)s)")
    parser.add_argument("--full", action="store_true",
                        help="ignore the cache and re-analyse every project")
    args = parser.parse_args()

    repos = load("github-repos.json")
    projects = load("github-projects.json")
    facts = load("github-repo-facts.json")
    if repos is None or projects is None or facts is None:
        sys.exit("error: run list-all-github-repos.py and collect-repo-facts.py first")
    cache = {} if args.full else load(os.path.join(STATE_DIR, "cache.json"), {})
    rules_hash = fingerprint(rules_text())

    def project_entry(name):
        urls = [u for org_urls in repos[name].values() for u in org_urls]
        return {**projects.get(name, {}), "github_orgs": list(repos[name]),
                "repos": {u: facts.get(u, {"url": u, "found": False}) for u in urls}}

    todo, cached = [], []
    for name in repos:
        entry = project_entry(name)
        fp = fingerprint(rules_hash, entry)
        if cache.get(name, {}).get("fingerprint") == fp:
            cached.append(name)
        else:
            todo.append((name, entry, fp))

    batch_dir = os.path.join(STATE_DIR, "batches")
    shutil.rmtree(batch_dir, ignore_errors=True)
    os.makedirs(batch_dir)
    batches, current, repo_count = [], {}, 0
    for name, entry, fp in todo:
        if current and (len(current) >= args.batch_size or repo_count + len(entry["repos"]) > args.max_repos):
            batches.append(current)
            current, repo_count = {}, 0
        current[name] = {**entry, "fingerprint": fp}
        repo_count += len(entry["repos"])
    if current:
        batches.append(current)

    plan = {"rules_hash": rules_hash, "cached_projects": cached, "batches": []}
    for i, batch in enumerate(batches, 1):
        path = os.path.join(batch_dir, f"b{i:03d}-facts.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(batch, fh, indent=1, ensure_ascii=False)
        plan["batches"].append({
            "facts": path, "products": path.replace("-facts.json", "-products.json"),
            "projects": list(batch), "repos": sum(len(e["repos"]) for e in batch.values())})
    with open(os.path.join(STATE_DIR, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=1, ensure_ascii=False)

    print(f"{len(cached)} projects unchanged (cached), {len(todo)} to analyse "
          f"in {len(batches)} batches -> {STATE_DIR}/plan.json", file=sys.stderr)


if __name__ == "__main__":
    main()
