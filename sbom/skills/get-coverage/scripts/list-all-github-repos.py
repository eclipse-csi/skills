#!/usr/bin/env python3
"""List all GitHub repositories of Eclipse Foundation projects.

Fetches every non-archived project from the Eclipse projects API
(https://projects.eclipse.org/api/projects), resolves its GitHub orgs and
repositories through the GitHub API, and writes a JSON file shaped as:

    {
      "Eclipse Mosquitto": {
        "https://github.com/eclipse-mosquitto": [
          "https://github.com/eclipse-mosquitto/mosquitto",
          ...
        ]
      },
      ...
    }

Repositories that are archived, forks, private, or config repos (names
starting with ".", e.g. ".github", ".eclipsefdn") are excluded. Projects that
end up with no repositories are omitted.

A GitHub token is read from GH_TOKEN or GITHUB_TOKEN if set; unauthenticated
requests are limited to 60 per hour, which is not enough for a full run.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

REPOS_FILE = "github-repos.json"
PROJECTS_FILE = "github-projects.json"
ECLIPSE_PROJECTS_API = "https://projects.eclipse.org/api/projects"
GITHUB_API = "https://api.github.com"
GITHUB_WEB = "https://github.com"
LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def http_get(url: str, headers: Optional[dict] = None, retries: int = 3):
    """GET a URL and return (parsed JSON, next-page URL or None).

    Returns (None, None) on HTTP 404.
    """
    request = urllib.request.Request(url, headers=headers or {})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.load(response)
                match = LINK_NEXT_RE.search(response.headers.get("Link", ""))
                return body, match.group(1) if match else None
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None, None
            if err.code in (403, 429) and err.headers.get("X-RateLimit-Remaining") == "0":
                reset = int(err.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset - int(time.time()), 1) + 1
                print(f"GitHub rate limit reached, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if err.code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def get_all_pages(url: str, headers: Optional[dict] = None) -> Optional[list]:
    """Follow Link: rel="next" pagination and return all items, or None on 404."""
    items = []
    while url:
        page, url = http_get(url, headers)
        if page is None:
            return None if not items else items
        items.extend(page)
    return items


def fetch_eclipse_projects(include_archived: bool = False) -> list:
    """Return all Eclipse projects, excluding archived ones unless requested."""
    projects = get_all_pages(f"{ECLIPSE_PROJECTS_API}?pagesize=100") or []
    if include_archived:
        return projects
    return [p for p in projects if p.get("state") != "Archived"]


class GitHubClient:
    """Minimal GitHub REST client with per-org repository caching."""

    def __init__(self, token: Optional[str]):
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self._org_repos: dict = {}
        self._repos: dict = {}

    def org_repos(self, org: str) -> list:
        """Return all public repos of an org (or user account), cached."""
        key = org.lower()
        if key not in self._org_repos:
            repos = get_all_pages(
                f"{GITHUB_API}/orgs/{org}/repos?type=public&per_page=100", self.headers
            )
            if repos is None:
                repos = get_all_pages(
                    f"{GITHUB_API}/users/{org}/repos?type=owner&per_page=100", self.headers
                )
            if repos is None:
                print(f"warning: GitHub org/user not found: {org}", file=sys.stderr)
                repos = []
            self._org_repos[key] = repos
            for repo in repos:
                self._repos[repo["full_name"].lower()] = repo
        return self._org_repos[key]

    def repo(self, owner: str, name: str) -> Optional[dict]:
        """Return a single repo, using the org cache or the API (follows renames)."""
        self.org_repos(owner)
        key = f"{owner}/{name}".lower()
        if key not in self._repos:
            repo, _ = http_get(f"{GITHUB_API}/repos/{owner}/{name}", self.headers)
            if repo is None:
                print(f"warning: GitHub repo not found: {owner}/{name}", file=sys.stderr)
            self._repos[key] = repo
        return self._repos[key]


def is_wanted(repo: dict) -> bool:
    """Keep only public, non-archived, non-fork, non-config repositories."""
    return not (
        repo.get("private")
        or repo.get("archived")
        or repo.get("fork")
        or repo["name"].startswith(".")
    )


def parse_repo_url(url: str) -> Optional[tuple]:
    """Split a https://github.com/<owner>/<repo> URL into (owner, repo)."""
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    # Some URLs in the Eclipse data contain stray whitespace, e.g. "org /repo".
    return (match.group(1).strip(), match.group(2).strip()) if match else None


def project_repos(project: dict, github: GitHubClient) -> dict:
    """Return {org URL: sorted list of repo URLs} for one Eclipse project."""
    candidates = []

    github_info = project.get("github") or {}
    org = (github_info.get("org") or "").strip().strip("/")
    if org:
        ignored = {r.strip().lower() for r in github_info.get("ignored_repos") or []}
        candidates.extend(
            r for r in github.org_repos(org) if r["full_name"].lower() not in ignored
        )

    for entry in project.get("github_repos") or []:
        parsed = parse_repo_url(entry.get("url", ""))
        if not parsed:
            print(f"warning: unrecognised repo URL in {project['project_id']}: "
                  f"{entry.get('url')}", file=sys.stderr)
            continue
        repo = github.repo(*parsed)
        if repo:
            candidates.append(repo)

    result: dict = {}
    for repo in candidates:
        if not is_wanted(repo):
            continue
        owner = repo["owner"]["login"]
        result.setdefault(f"{GITHUB_WEB}/{owner}", set()).add(repo["html_url"])
    return {org_url: sorted(urls) for org_url, urls in sorted(result.items())}


def main() -> int:
    """Parse arguments, build the project → org → repos mapping and write it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--include-archived", action="store_true",
                        help="also include archived Eclipse projects")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="only process the first N projects (alphabetically), for a quick trial run")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    github = GitHubClient(token)

    projects = fetch_eclipse_projects(args.include_archived)
    print(f"Fetched {len(projects)} Eclipse projects", file=sys.stderr)

    output = {}
    metadata = {}
    projects = sorted(projects, key=lambda p: p["name"].lower())
    if args.limit:
        projects = projects[:args.limit]
    for i, project in enumerate(projects, 1):
        print(f"[{i}/{len(projects)}] {project['name']}", file=sys.stderr)
        repos = project_repos(project, github)
        if repos:
            output[project["name"]] = repos
            metadata[project["name"]] = {
                "project_id": project.get("project_id"),
                "short_id": project.get("short_project_id"),
                "state": project.get("state"),
                "top_level_project": project.get("top_level_project"),
                "summary": (project.get("summary") or "")[:600],
            }

    for path, data in ((REPOS_FILE, output), (PROJECTS_FILE, metadata)):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    total = sum(len(urls) for orgs in output.values() for urls in orgs.values())
    print(f"Wrote {len(output)} projects, {total} repositories to {REPOS_FILE}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
