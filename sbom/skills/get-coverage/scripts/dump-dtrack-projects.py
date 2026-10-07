#!/usr/bin/env python3
"""Dump all Dependency-Track projects to dt-projects.json.

Pages through the Dependency-Track REST API (/api/v1/project), including
inactive projects, and writes the full project objects to a JSON array in the
current directory. Each project carries its `parent` reference (so nested
hierarchies can be rebuilt), `lastBomImport` (set once an SBOM was uploaded),
`classifier`, `tags`, `purl` and `externalReferences`.

Configuration comes from the environment:
  DT_URL      base URL of the Dependency-Track API server, e.g. https://dtrack.example.org
  DT_API_KEY  API key of a team with the VIEW_PORTFOLIO permission

With portfolio access control enabled, only projects visible to that team are
returned.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

OUTPUT = "dt-projects.json"
PAGE_SIZE = 500


def fetch_page(base_url: str, api_key: str, page: int) -> list:
    """Return one page of projects from the Dependency-Track API."""
    query = urllib.parse.urlencode(
        {"pageSize": PAGE_SIZE, "pageNumber": page, "excludeInactive": "false"})
    request = urllib.request.Request(
        f"{base_url}/api/v1/project?{query}",
        headers={"X-Api-Key": api_key, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def fetch_all_projects(base_url: str, api_key: str) -> list:
    """Page through /api/v1/project until an empty page is returned."""
    projects = []
    page = 1
    while True:
        batch = fetch_page(base_url, api_key, page)
        if not batch:
            return projects
        projects.extend(batch)
        print(f"page {page}: {len(projects)} projects", file=sys.stderr)
        if len(batch) < PAGE_SIZE:
            return projects
        page += 1


def main() -> int:
    """Read configuration, dump all projects and write them to a JSON file."""
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()

    base_url = os.environ.get("DT_URL", "").rstrip("/")
    api_key = os.environ.get("DT_API_KEY", "")
    if not base_url or not api_key:
        print("error: set DT_URL and DT_API_KEY", file=sys.stderr)
        return 1

    try:
        projects = fetch_all_projects(base_url, api_key)
    except urllib.error.HTTPError as err:
        hint = " (check the API key and its VIEW_PORTFOLIO permission)" if err.code in (401, 403) else ""
        print(f"error: HTTP {err.code} from {err.url}{hint}", file=sys.stderr)
        return 1
    except urllib.error.URLError as err:
        print(f"error: cannot reach {base_url}: {err.reason}", file=sys.stderr)
        return 1

    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(projects, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    with_bom = sum(1 for p in projects if p.get("lastBomImport"))
    children = sum(1 for p in projects if p.get("parent"))
    print(f"Wrote {len(projects)} projects ({with_bom} with an uploaded SBOM, "
          f"{children} nested under a parent) to {OUTPUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
