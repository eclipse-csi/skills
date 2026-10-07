#!/usr/bin/env python3
"""Check that every image product in the candidate list was actually pushed to a registry.

For each product with an "image" reference (e.g. ghcr.io/org/name, docker.io/ns/name,
quay.io/ns/name) the registry is queried anonymously for tags:

  PUSHED        the image exists and has tags -> kept
  NOT_FOUND     the registry answered and the image does not exist -> dropped
  UNVERIFIABLE  unsupported/private registry or the check failed -> kept, listed for review
  NO_REF        image product without an "image" reference -> kept, listed for review

Updates .sbom-coverage/candidate.json in place (sets "image_status", removes NOT_FOUND
products) and writes .sbom-coverage/image-report.json.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

STATE_DIR = ".sbom-coverage"
CANDIDATE = os.path.join(STATE_DIR, "candidate.json")


def get_json(url, headers=None):
    """GET JSON; return (status_code, body or None)."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        return err.code, None


def check(ref: str) -> str:
    """Return PUSHED, NOT_FOUND or UNVERIFIABLE for one image reference."""
    ref = ref.split("@")[0]
    registry, _, path = ref.partition("/")
    if ":" in path.rsplit("/", 1)[-1]:
        path = path.rsplit(":", 1)[0]  # drop a tag
    if "." not in registry and registry != "localhost":
        registry, path = "docker.io", ref  # bare "ns/name" means Docker Hub
    try:
        if registry in ("docker.io", "index.docker.io", "registry-1.docker.io"):
            ns, _, name = path.partition("/")
            if not name:
                ns, name = "library", ns
            code, body = get_json(f"https://hub.docker.com/v2/repositories/{ns}/{name}/tags/?page_size=1")
            if code == 200:
                return "PUSHED" if (body or {}).get("count") else "NOT_FOUND"
            return "NOT_FOUND" if code == 404 else "UNVERIFIABLE"
        if registry == "ghcr.io":
            code, tok = get_json(f"https://ghcr.io/token?scope=repository:{path}:pull")
            if code != 200 or not tok or "token" not in tok:
                return "UNVERIFIABLE"
            code, body = get_json(f"https://ghcr.io/v2/{path}/tags/list",
                                  {"Authorization": f"Bearer {tok['token']}"})
            if code == 200:
                return "PUSHED" if (body or {}).get("tags") else "NOT_FOUND"
            return "NOT_FOUND" if code == 404 else "UNVERIFIABLE"
        if registry == "quay.io":
            code, body = get_json(f"https://quay.io/api/v1/repository/{path}?includeTags=true")
            if code == 200:
                return "PUSHED" if (body or {}).get("tags") else "NOT_FOUND"
            return "NOT_FOUND" if code == 404 else "UNVERIFIABLE"
    except (urllib.error.URLError, TimeoutError, ValueError):
        return "UNVERIFIABLE"
    return "UNVERIFIABLE"


def main() -> int:
    """Verify every image product in the candidate and drop images that were never pushed."""
    if not os.path.exists(CANDIDATE):
        sys.exit("error: run merge-products.py first")
    with open(CANDIDATE, encoding="utf-8") as fh:
        candidate = json.load(fh)

    targets = [(p, name, e) for p, prods in candidate.items() for name, e in prods.items()
               if name.endswith("-image") or e.get("image")]
    refs = sorted({e["image"] for _, _, e in targets if e.get("image")})
    with ThreadPoolExecutor(max_workers=8) as pool:
        status = dict(zip(refs, pool.map(check, refs)))

    report = {"PUSHED": [], "NOT_FOUND": [], "UNVERIFIABLE": [], "NO_REF": []}
    for project, name, entry in targets:
        state = status.get(entry.get("image"), "NO_REF") if entry.get("image") else "NO_REF"
        report[state].append({"project": project, "product": name, "image": entry.get("image")})
        if state == "NOT_FOUND":
            del candidate[project][name]
        else:
            entry["image_status"] = state

    with open(CANDIDATE, "w", encoding="utf-8") as fh:
        json.dump(candidate, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(os.path.join(STATE_DIR, "image-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    print("images: " + ", ".join(f"{k} {len(v)}" for k, v in report.items())
          + f" (NOT_FOUND products removed) -> {STATE_DIR}/image-report.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
