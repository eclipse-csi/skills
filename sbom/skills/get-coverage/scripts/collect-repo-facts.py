#!/usr/bin/env python3
"""Collect GitHub facts for every repository listed in github-repos.json.

Reads github-repos.json (as written by list-all-github-repos.py) from the
current directory and writes github-repo-facts.json, keyed by repository URL.
The facts are the signals needed to decide whether a repository ships
something and how repositories group into products:

- metadata: description, topics, languages, homepage, template flag, last push
- release history: GitHub release count and latest release, tag count
- build manifests found anywhere in the tree (per manifest type: count and the
  shallowest paths), ignoring vendored, test, example and doc directories
- CI: GitHub workflow file names, Jenkinsfile presence
- parsed root manifests: pom.xml, package.json, Cargo.toml, pyproject.toml

Metadata and root manifests come from the GraphQL API in batches; file trees
come from the REST API, one call per repository, run concurrently.

A GitHub token is read from GH_TOKEN or GITHUB_TOKEN (GraphQL requires one).
"""

import argparse
import fnmatch
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

REPOS_FILE = "github-repos.json"
FACTS_FILE = "github-repo-facts.json"
GITHUB_API = "https://api.github.com"
GRAPHQL_URL = f"{GITHUB_API}/graphql"

# Build manifests by exact file name, following the ecosystem signal table of
# the list-products skill (../../list-products/SKILL.md).
MANIFEST_NAMES = {
    "pom.xml", "feature.xml", "category.xml",
    "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "build.sbt", "build.mill", "build.sc", "deps.edn", "project.clj",
    "package.json", "package-lock.json", "yarn.lock", ".yarnrc.yml", "pnpm-lock.yaml",
    "pyproject.toml", "setup.py", "setup.cfg", "poetry.lock", "uv.lock", "pdm.lock",
    "environment.yml", "meta.yaml",
    "go.mod", "Cargo.toml", "Cargo.lock",
    "composer.json", "composer.lock", "Gemfile", "Gemfile.lock",
    "mix.exs", "mix.lock", "rebar.config", "rebar.lock",
    "Package.swift", "Package.resolved", "Podfile", "Podfile.lock", "Cartfile",
    "pubspec.yaml", "pubspec.lock",
    "cpanfile", "META.json", "Makefile.PL", "dist.ini",
    "dune-project", "cabal.project.freeze", "stack.yaml",
    "DESCRIPTION", "renv.lock", "flake.nix", "flake.lock", "default.nix",
    "conanfile.txt", "conanfile.py", "conan.lock", "vcpkg.json", "vcpkg-configuration.json",
    "CMakeLists.txt", "Makefile", "meson.build",
    "Dockerfile", "Containerfile", "docker-bake.hcl",
    "APKBUILD", ".terraform.lock.hcl", "Jenkinsfile",
}
# Build manifests by file name pattern.
MANIFEST_PATTERNS = [
    "requirements*.txt", "*.csproj", "*.fsproj", "*.vbproj", "*.sln", "*.gemspec",
    "*.opam", "*.cabal", "*.rockspec", "*.target", "*.tf", "Dockerfile.*", "Dockerfile-*",
    "*.Dockerfile", "*.dockerfile", "Containerfile.*",
]
# Directories whose manifests do not indicate a shipped product.
IGNORED_DIRS = {
    "node_modules", "vendor", "bower_components", "third_party", "thirdparty", "3rdparty",
    "test", "tests", "testing", "testdata", "test-data", "fixtures", "it",
    "example", "examples", "sample", "samples", "demo", "demos",
    "doc", "docs", "documentation", "website", "site",
}
MAX_PATHS_PER_MANIFEST = 20

REPO_FIELDS = """
  nameWithOwner url description homepageUrl isArchived isFork isPrivate isTemplate
  isEmpty pushedAt
  defaultBranchRef { name }
  primaryLanguage { name }
  languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
    edges { size node { name } }
  }
  repositoryTopics(first: 20) { nodes { topic { name } } }
  releases { totalCount }
  latestRelease { tagName publishedAt }
  tags: refs(refPrefix: "refs/tags/", first: 1) { totalCount }
  pom: object(expression: "HEAD:pom.xml") { ... on Blob { text } }
  packageJson: object(expression: "HEAD:package.json") { ... on Blob { text } }
  cargo: object(expression: "HEAD:Cargo.toml") { ... on Blob { text } }
  pyproject: object(expression: "HEAD:pyproject.toml") { ... on Blob { text } }
"""


class GitHub:
    """Minimal GitHub REST and GraphQL client with rate-limit handling."""

    def __init__(self, token: Optional[str]):
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def request(self, url: str, body: Optional[dict] = None, retries: int = 5):
        """Send a GET (or POST when body is given) and return parsed JSON, or None on 404."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self.headers)
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    return json.load(response)
            except urllib.error.HTTPError as err:
                if err.code in (404, 409):  # 409: empty repository
                    return None
                if err.code in (403, 429):
                    wait = self._rate_limit_wait(err)
                    if wait is not None:
                        print(f"rate limited, sleeping {wait}s", file=sys.stderr)
                        time.sleep(wait)
                        continue
                if err.code >= 500 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError):
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")

    @staticmethod
    def _rate_limit_wait(err: urllib.error.HTTPError) -> Optional[int]:
        """Return seconds to wait for a primary or secondary rate limit, else None."""
        if err.headers.get("Retry-After"):
            return int(err.headers["Retry-After"]) + 1
        if err.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(err.headers.get("X-RateLimit-Reset", time.time() + 60))
            return max(reset - int(time.time()), 1) + 1
        return None

    def graphql(self, query: str) -> dict:
        """Run a GraphQL query; per-field errors (e.g. NOT_FOUND) are tolerated."""
        result = self.request(GRAPHQL_URL, {"query": query}) or {}
        for error in result.get("errors") or []:
            if error.get("type") != "NOT_FOUND":
                print(f"warning: GraphQL error: {error.get('message')}", file=sys.stderr)
        return result.get("data") or {}

    def tree(self, full_name: str, branch: str) -> Optional[dict]:
        """Return the recursive git tree of a branch."""
        ref = urllib.parse.quote(branch, safe="")
        return self.request(f"{GITHUB_API}/repos/{full_name}/git/trees/{ref}?recursive=1")


WORKFLOW_FIELDS = """
  nameWithOwner
  wf: object(expression: "HEAD:.github/workflows") {
    ... on Tree { entries { name object { ... on Blob { text } } } }
  }
"""

# Steps that publish a release artifact, by kind.
PUBLISH_PATTERNS = {
    "maven": r"mvn[^\n]*\bdeploy\b|central-publishing|nexus-staging|maven-publish|publishToSonatype"
             r"|gradle[^\n]*\bpublish|\bpublish(ToMavenLocal)?\b[^\n]*gradle",
    "npm": r"\bnpm\s+publish|\byarn\s+(npm\s+)?publish|\bpnpm\s+publish|changesets/action"
           r"|semantic-release|JS-DevTools/npm-publish|\blerna\s+publish",
    "pypi": r"pypa/gh-action-pypi-publish|twine\s+upload|\buv\s+publish|\bpoetry\s+publish"
            r"|\bflit\s+publish|\bhatch\s+publish",
    "crates": r"\bcargo\s+publish|release-plz",
    "image": r"docker/build-push-action|\bdocker\s+push\b|buildx\b[^\n]*--push|\bjib\b|\bko\s+(build|publish)"
             r"|redhat-actions/push-to-registry|\bpodman\s+push\b|bootBuildImage|spring-boot:build-image",
    "github-release": r"softprops/action-gh-release|ncipollo/release-action|\bgh\s+release\s+(create|upload)"
                      r"|actions/create-release|goreleaser|svenstaro/upload-release-action",
    "p2/download": r"download\.eclipse\.org|projects-storage\.eclipse\.org",
}
PUBLISH_RES = {kind: re.compile(p, re.I) for kind, p in PUBLISH_PATTERNS.items()}


def workflow_triggers(text: str) -> list:
    """Return the events a GitHub Actions workflow is triggered by (best-effort, no YAML lib)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"""^(on|"on"|'on'|true)\s*:(.*)$""", line)
        if not match:
            continue
        inline = match.group(2).split("#")[0].strip()
        if inline:
            return sorted(set(re.findall(r"[a-z_]+", inline)))
        block = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt.startswith((" ", "\t", "#")):
                break
            block.append(nxt)
        events = set(re.findall(r"^\s{1,8}([a-z_]+)\s*:", "\n".join(block), re.M))
        events |= set(re.findall(r"^\s{1,8}-\s*([a-z_]+)\s*$", "\n".join(block), re.M))
        text_block = "\n".join(block)
        if "push" in events and re.search(r"^\s+tags\s*:", text_block, re.M):
            events.add("push_tags")
        return sorted(events & {"push", "push_tags", "release", "workflow_dispatch", "schedule",
                                "pull_request", "pull_request_target", "workflow_call",
                                "workflow_run", "repository_dispatch"})
    return []


def summarize_workflows(entries: Optional[list]) -> dict:
    """Summarise a repo's workflows into release signals.

    release_trigger is the strongest release signal found in a workflow that publishes:
      "release"  triggered by a published GitHub release
      "tag"      triggered by pushing a tag
      "manual"   workflow_dispatch only
      "push"     publishes on every push to a branch (snapshots / continuous)
      None       no publishing workflow found
    """
    workflows = []
    for entry in entries or []:
        name = entry.get("name", "")
        if not name.endswith((".yml", ".yaml")):
            continue
        text = ((entry.get("object") or {}).get("text")) or ""
        triggers = workflow_triggers(text)
        publishes = sorted(k for k, rx in PUBLISH_RES.items() if rx.search(text))
        if publishes or {"release", "push_tags"} & set(triggers):
            workflows.append({"name": name, "triggers": triggers, "publishes": publishes})
    order = ["release", "tag", "manual", "push"]
    signal = None
    for wf in workflows:
        if not wf["publishes"]:
            continue
        t = set(wf["triggers"])
        kind = next((k for k, trigger in (("release", "release"), ("tag", "push_tags"),
                                           ("push", "push"), ("manual", "workflow_dispatch"))
                     if trigger in t), None)
        if kind == "push" and "workflow_dispatch" in t and not set(t) - {"push", "workflow_dispatch"}:
            kind = "push"
        if kind and (signal is None or order.index(kind) < order.index(signal)):
            signal = kind
    return {"release_trigger": signal, "release_workflows": workflows}


def fetch_workflows(github: "GitHub", full_names: list, batch_size: int = 10) -> dict:
    """Fetch every repo's workflow files in GraphQL batches; return name -> summary."""
    results, pending = {}, list(full_names)
    while pending:
        batch, pending = pending[:batch_size], pending[batch_size:]
        aliases = []
        for i, name in enumerate(batch):
            owner, repo = name.split("/")
            aliases.append(f'r{i}: repository(owner: {json.dumps(owner)}, '
                           f'name: {json.dumps(repo)}) {{ {WORKFLOW_FIELDS} }}')
        try:
            data = github.graphql("query {\n" + "\n".join(aliases) + "\n}")
        except (urllib.error.URLError, RuntimeError, TimeoutError,
                http.client.HTTPException, ConnectionError):
            if batch_size == 1:
                print(f"warning: workflow fetch failed for {batch[0]}", file=sys.stderr)
                results[batch[0]] = summarize_workflows(None)
                continue
            batch_size = max(batch_size // 2, 1)
            pending = batch + pending
            continue
        for i, name in enumerate(batch):
            node = (data.get(f"r{i}") or {}).get("wf") or {}
            results[name] = summarize_workflows(node.get("entries"))
        print(f"workflows: {len(results)}/{len(full_names)}", file=sys.stderr)
    return results


def full_name_from_url(url: str) -> str:
    """Turn https://github.com/<owner>/<repo> into <owner>/<repo>."""
    return "/".join(url.rstrip("/").split("/")[-2:])


def fetch_metadata(github: GitHub, full_names: list, batch_size: int) -> dict:
    """Fetch GraphQL metadata for all repos, halving the batch size on failure."""
    results = {}
    pending = list(full_names)
    while pending:
        batch, pending = pending[:batch_size], pending[batch_size:]
        aliases = []
        for i, name in enumerate(batch):
            owner, repo = name.split("/")
            aliases.append(f'r{i}: repository(owner: {json.dumps(owner)}, '
                           f'name: {json.dumps(repo)}) {{ {REPO_FIELDS} }}')
        try:
            data = github.graphql("query {\n" + "\n".join(aliases) + "\n}")
        except (urllib.error.URLError, RuntimeError, TimeoutError,
                http.client.HTTPException, ConnectionError):
            if batch_size == 1:
                print(f"warning: metadata fetch failed for {batch[0]}", file=sys.stderr)
                continue
            batch_size = max(batch_size // 2, 1)
            print(f"GraphQL batch failed, retrying with batch size {batch_size}",
                  file=sys.stderr)
            pending = batch + pending
            continue
        for i, name in enumerate(batch):
            results[name] = data.get(f"r{i}")
        print(f"metadata: {len(results)}/{len(full_names)}", file=sys.stderr)
    return results


def blob_text(node: Optional[dict]) -> Optional[str]:
    """Return a GraphQL Blob's text, or None when absent or binary."""
    return (node or {}).get("text")


def xml_tag(text: str, tag: str) -> Optional[str]:
    """Return the first <tag> value outside <parent>, <dependencies> and <build>."""
    stripped = re.sub(r"<(parent|dependencies|dependencyManagement|build|profiles)>.*?</\1>",
                      "", text, flags=re.S)
    match = re.search(rf"<{tag}>\s*([^<]+?)\s*</{tag}>", stripped)
    return match.group(1) if match else None


def parse_pom(text: Optional[str]) -> Optional[dict]:
    """Extract product-relevant signals from a root pom.xml."""
    if not text:
        return None
    parent_group = re.search(r"<parent>.*?<groupId>([^<]+)</groupId>", text, re.S)
    parent_group_id = parent_group.group(1).strip() if parent_group else None
    modules = re.search(r"<modules>(.*?)</modules>", text, re.S)
    return {
        "group_id": xml_tag(text, "groupId") or parent_group_id or None,
        "artifact_id": xml_tag(text, "artifactId"),
        "packaging": xml_tag(text, "packaging") or "jar",
        "modules": len(re.findall(r"<module>", modules.group(1))) if modules else 0,
        "tycho": "tycho" in text,
        "distribution_management": "<distributionManagement>" in text,
        "central_publishing": bool(re.search(
            r"central-publishing-maven-plugin|nexus-staging-maven-plugin", text)),
    }


def parse_package_json(text: Optional[str]) -> Optional[dict]:
    """Extract product-relevant signals from a root package.json."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"parse_error": True}
    if not isinstance(data, dict):
        return {"parse_error": True}
    return {
        "name": data.get("name"),
        "private": bool(data.get("private")),
        "workspaces": bool(data.get("workspaces")),
        "publish_config": "publishConfig" in data,
    }


def parse_cargo(text: Optional[str]) -> Optional[dict]:
    """Extract product-relevant signals from a root Cargo.toml."""
    if not text:
        return None
    name = re.search(r'^\[package\].*?^name\s*=\s*"([^"]+)"', text, re.S | re.M)
    return {
        "package": bool(re.search(r"^\[package\]", text, re.M)),
        "workspace": bool(re.search(r"^\[workspace\]", text, re.M)),
        "name": name.group(1) if name else None,
    }


def parse_pyproject(text: Optional[str]) -> Optional[dict]:
    """Extract product-relevant signals from a root pyproject.toml."""
    if not text:
        return None
    name = re.search(r'^\[(?:project|tool\.poetry)\].*?^name\s*=\s*"([^"]+)"', text, re.S | re.M)
    return {"name": name.group(1) if name else None}


def is_manifest(filename: str) -> bool:
    """Whether a file name is a build or packaging manifest."""
    return filename in MANIFEST_NAMES or any(
        fnmatch.fnmatchcase(filename, p) for p in MANIFEST_PATTERNS)


def summarize_tree(tree: Optional[dict]) -> dict:
    """Summarize a recursive git tree into manifests, root files and CI signals."""
    if not tree:
        return {"tree_available": False}
    paths = [e["path"] for e in tree.get("tree", []) if e.get("type") == "blob"]
    manifests: dict = {}
    for path in paths:
        parts = path.split("/")
        filename = parts[-1]
        if path == "debian/control" or path.endswith("/debian/control"):
            filename = "debian/control"
        elif not is_manifest(filename):
            continue
        if any(part.lower() in IGNORED_DIRS for part in parts[:-1]):
            continue
        manifests.setdefault(filename, []).append(path)
    workflows = sorted(p.split("/")[-1] for p in paths
                       if re.match(r"\.github/workflows/[^/]+\.ya?ml$", p))
    return {
        "tree_available": True,
        "tree_truncated": bool(tree.get("truncated")),
        "file_count": len(paths),
        "root_files": sorted(p for p in paths if "/" not in p),
        "manifests": {
            name: {
                "count": len(found),
                "paths": sorted(found, key=lambda p: (p.count("/"), p))[:MAX_PATHS_PER_MANIFEST],
            }
            for name, found in sorted(manifests.items())
        },
        "workflows": workflows,
        "has_jenkinsfile": any(p.split("/")[-1] == "Jenkinsfile" for p in paths),
    }


def build_facts(url: str, meta: Optional[dict], tree_summary: dict) -> dict:
    """Combine GraphQL metadata and tree summary into one repo facts entry."""
    if not meta:
        return {"url": url, "found": False}
    latest = meta.get("latestRelease") or {}
    return {
        "url": meta["url"],
        "found": True,
        "full_name": meta["nameWithOwner"],
        "description": meta.get("description"),
        "homepage": meta.get("homepageUrl") or None,
        "topics": [n["topic"]["name"] for n in meta["repositoryTopics"]["nodes"]],
        "primary_language": (meta.get("primaryLanguage") or {}).get("name"),
        "languages": {e["node"]["name"]: e["size"] for e in meta["languages"]["edges"]},
        "archived": meta["isArchived"],
        "fork": meta["isFork"],
        "private": meta["isPrivate"],
        "template": meta["isTemplate"],
        "empty": meta["isEmpty"],
        "pushed_at": meta.get("pushedAt"),
        "default_branch": (meta.get("defaultBranchRef") or {}).get("name"),
        "releases": {
            "count": meta["releases"]["totalCount"],
            "latest_tag": latest.get("tagName"),
            "latest_published_at": latest.get("publishedAt"),
        },
        "tag_count": meta["tags"]["totalCount"],
        "root_pom": parse_pom(blob_text(meta.get("pom"))),
        "root_package_json": parse_package_json(blob_text(meta.get("packageJson"))),
        "root_cargo": parse_cargo(blob_text(meta.get("cargo"))),
        "root_pyproject": parse_pyproject(blob_text(meta.get("pyproject"))),
        **tree_summary,
    }


def main() -> int:
    """Read github-repos.json, collect facts for each repo and write them."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=50,
                        help="repositories per GraphQL query (default: %(default)s)")
    parser.add_argument("--workers", type=int, default=8,
                        help="concurrent file tree requests (default: %(default)s)")
    parser.add_argument("--release-signals-only", action="store_true",
                        help=f"only (re)collect workflow release signals into an existing {FACTS_FILE}")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("error: GH_TOKEN or GITHUB_TOKEN is required for the GraphQL API",
              file=sys.stderr)
        return 1
    github = GitHub(token)

    with open(REPOS_FILE, encoding="utf-8") as fh:
        projects = json.load(fh)
    urls = sorted({url for orgs in projects.values() for repos in orgs.values()
                   for url in repos})
    by_name = {full_name_from_url(url): url for url in urls}

    if args.release_signals_only:
        with open(FACTS_FILE, encoding="utf-8") as fh:
            facts = json.load(fh)
        names = [n for n, u in by_name.items() if facts.get(u, {}).get("found")]
        signals = fetch_workflows(github, names)
        for name, summary in signals.items():
            facts[by_name[name]].update(summary)
        with open(FACTS_FILE, "w", encoding="utf-8") as fh:
            json.dump(facts, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"Updated release signals for {len(signals)} repositories in {FACTS_FILE}",
              file=sys.stderr)
        return 0

    print(f"Collecting facts for {len(by_name)} repositories", file=sys.stderr)

    metadata = fetch_metadata(github, list(by_name), args.batch_size)

    def tree_for(name: str) -> tuple:
        meta = metadata.get(name) or {}
        branch = (meta.get("defaultBranchRef") or {}).get("name")
        if not branch or meta.get("isEmpty"):
            return name, summarize_tree(None)
        return name, summarize_tree(github.tree(meta["nameWithOwner"], branch))

    trees = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (name, summary) in enumerate(pool.map(tree_for, by_name), 1):
            trees[name] = summary
            if i % 100 == 0 or i == len(by_name):
                print(f"trees: {i}/{len(by_name)}", file=sys.stderr)

    found = [n for n in by_name if metadata.get(n)]
    signals = fetch_workflows(github, found)
    facts = {url: build_facts(url, metadata.get(name), {**trees[name], **signals.get(name, {})})
             for name, url in by_name.items()}
    missing = [url for url, f in facts.items() if not f["found"]]
    for url in missing:
        print(f"warning: repository not found: {url}", file=sys.stderr)

    with open(FACTS_FILE, "w", encoding="utf-8") as fh:
        json.dump(facts, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote facts for {len(facts)} repositories ({len(missing)} not found) "
          f"to {FACTS_FILE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
