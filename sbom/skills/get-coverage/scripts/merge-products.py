#!/usr/bin/env python3
"""Merge batch results and cached projects into a candidate product list.

Reads .sbom-coverage/plan.json (from prepare-batches.py), every batch's products file and
the cache, validates each repo URL against github-repos.json, and writes
.sbom-coverage/candidate.json in the github-products.json format:

    {project: {product: {"repos": [url, ...], "image": "ghcr.io/org/name" (images only),
                         "sbom_uploaded": false}}}

It never touches github-products.json; review-diff.py --apply does that after review.
"""

import json
import os
import sys

STATE_DIR = ".sbom-coverage"
BATCH_DIR = os.path.join(STATE_DIR, "batches")


def load(path, default=None):
    """Load a JSON file, or return default when it does not exist."""
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def normalise(products: dict) -> dict:
    """Accept product values as a URL list or an object; return the object form."""
    out = {}
    for name, value in products.items():
        entry = {"repos": value} if isinstance(value, list) else dict(value)
        entry.setdefault("repos", [])
        entry["sbom_uploaded"] = False
        out[name] = entry
    return out


def main() -> int:
    """Combine batches with the cache, validate and write the candidate file."""
    plan = load(os.path.join(STATE_DIR, "plan.json"))
    repos = load("github-repos.json")
    if plan is None or repos is None:
        sys.exit("error: run prepare-batches.py first")
    cache = load(os.path.join(STATE_DIR, "cache.json"), {})

    candidate, fingerprints, problems = {}, {}, []
    for name in plan["cached_projects"]:
        candidate[name] = normalise(cache[name]["products"])
        fingerprints[name] = cache[name]["fingerprint"]
    for i, batch in enumerate(plan["batches"], 1):
        # The same file names prepare-batches.py gives batch i.
        facts = load(os.path.join(BATCH_DIR, f"b{i:03d}-facts.json"))
        products_path = os.path.join(BATCH_DIR, f"b{i:03d}-products.json")
        result = load(products_path)
        if result is None:
            problems.append(f"missing batch result: {products_path}")
            continue
        for name in batch["projects"]:
            if name not in result:
                problems.append(f"{products_path}: project missing: {name!r}")
                continue
            candidate[name] = normalise(result[name])
            fingerprints[name] = facts[name]["fingerprint"]
        for extra in set(result) - set(batch["projects"]):
            problems.append(f"{products_path}: unexpected project {extra!r}")

    no_ref = 0
    for name, products in candidate.items():
        valid = {u for org_urls in repos.get(name, {}).values() for u in org_urls}
        for product, entry in products.items():
            if not entry["repos"]:
                problems.append(f"{name} / {product}: no repos")
            for url in entry["repos"]:
                if url not in valid:
                    problems.append(f"{name} / {product}: repo not in project: {url}")
            if product.endswith("-image") and not entry.get("image"):
                no_ref += 1

    ordered = {name: candidate[name] for name in repos if name in candidate}
    for name in repos:
        if name not in candidate:
            problems.append(f"project not analysed: {name!r}")
    with open(os.path.join(STATE_DIR, "candidate.json"), "w", encoding="utf-8") as fh:
        json.dump(ordered, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(os.path.join(STATE_DIR, "fingerprints.json"), "w", encoding="utf-8") as fh:
        json.dump(fingerprints, fh, indent=1)

    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if no_ref:
        print(f"warning: {no_ref} image products have no 'image' reference; "
              "verify-images.py can't check them", file=sys.stderr)
    total = sum(len(v) for v in ordered.values())
    print(f"candidate: {len(ordered)} projects, {total} products -> {STATE_DIR}/candidate.json "
          f"({len(problems)} errors)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
