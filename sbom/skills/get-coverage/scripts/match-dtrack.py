#!/usr/bin/env python3
"""Set the sbom_uploaded flag on products that have an SBOM in Dependency-Track.

Reads dt-projects.json (from dump-dtrack-projects.py), github-products.json,
github-projects.json and github-repo-facts.json. Every Dependency-Track project with an
uploaded SBOM (lastBomImport set) is matched to a product. The result depends only on
those files and dtrack-decisions.json, so the same inputs always give the same matches.

  1. decision: dtrack-decisions.json in the working directory, the judgement calls
     recorded for names the rules below cannot settle (exact names, name prefixes,
     ignored names). Decisions win over the rules.
  2. repo: a GitHub repo named by the project's external references or the vcs_url in
     its purl (any github.com/<org>/<repo>/... or maven.pkg.github.com/<org>/<repo> URL).
  3. coordinates: the purl's package matches a repo's root manifest (Maven
     groupId/artifactId, npm, PyPI or Cargo name), or a Go module path names the repo.
  4. name: the normalised project name ("Sirius Web - Backend" -> sirius-web-backend)
     is a product name, or the only product ending in "-<name>" (unless the name is a
     generic word such as "backend"), or a repo name, or a project short id.

Steps 2-4 each give candidate products. Several candidates are narrowed in order by the
classifier (CONTAINER keeps image products, anything else non-image ones) and by the
name; a step matches only when exactly one candidate is left. Ties are never broken by
guessing: the name is reported in .sbom-coverage/dtrack-unmatched.json with its
evidence, to be settled by a decision. Writes the flags into github-products.json and the
covered products, with the step that matched each, to products-with-sboms.json.
"""

import collections
import datetime
import json
import os
import re
import sys
import urllib.parse

STATE_DIR = ".sbom-coverage"
DECISIONS = "dtrack-decisions.json"
GITHUB_RE = re.compile(r"github\.com[/:]([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9._-]+)")
PURL_TYPE_RE = re.compile(r"[a-z]+")
# Too generic to match on a "-<name>" suffix alone, however unique the suffix is today.
GENERIC = {"api", "app", "backend", "cli", "client", "core", "docs", "frontend", "image",
           "library", "sdk", "server", "service", "ui", "web", "webui"}


def slug(text: str) -> str:
    """Normalise a name for comparison: 'Sirius Web - Backend' -> 'sirius-web-backend'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def repo_url(owner: str, name: str) -> str:
    """Canonical lowercased GitHub repo URL."""
    name = name[:-4] if name.endswith(".git") else name
    return f"https://github.com/{owner}/{name}".lower()


def parse_purl(purl: str):
    """(type, namespace-and-name) of a purl, without version and qualifiers."""
    if not (purl or "").startswith("pkg:"):
        return None, None
    kind, _, rest = purl[4:].partition("/")
    if not PURL_TYPE_RE.fullmatch(kind) or not rest:
        return None, None
    # The name ends at the version ("@") or the qualifiers/subpath ("?", "#"); it is never empty.
    end = next((i for i, ch in enumerate(rest) if i and ch in "@?#"), len(rest))
    return kind, urllib.parse.unquote(rest[:end])


def vcs_repos(project: dict) -> set:
    """GitHub repo URLs named by a Dependency-Track project's references or purl."""
    urls = [e.get("url") or "" for e in project.get("externalReferences") or []]
    purl = project.get("purl") or ""
    if "vcs_url=" in purl:
        urls.append(urllib.parse.unquote(purl.split("vcs_url=", 1)[1].split("&", 1)[0]))
    return {repo_url(*m.groups()) for url in urls for m in [GITHUB_RE.search(url)] if m}


def load(path: str, default=None):
    """Read a JSON file; the default when it is absent and a default is given."""
    if not os.path.exists(path):
        if default is not None:
            return default
        sys.exit(f"error: {path} not found")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Matcher:
    """Deterministic rules from a Dependency-Track project to one (project, product)."""

    def __init__(self, products: dict, projects: dict, facts: dict):
        self.by_repo = collections.defaultdict(set)
        self.by_name = {}
        self.by_short_id = collections.defaultdict(set)
        self.by_repo_name = collections.defaultdict(set)
        self.by_coords = collections.defaultdict(set)
        for project, prods in products.items():
            short_id = (projects.get(project) or {}).get("short_id")
            for name, entry in prods.items():
                self.by_name[name] = (project, name)
                if short_id:
                    self.by_short_id[short_id.lower()].add((project, name))
                for url in entry["repos"]:
                    self.by_repo[url.lower()].add((project, name))
                    self.by_repo_name[url.rstrip("/").rsplit("/", 1)[-1].lower()].add(url.lower())
        for url, fact in facts.items():
            pom = fact.get("root_pom") or {}
            if pom.get("group_id") and pom.get("artifact_id"):
                self.by_coords[("maven", f"{pom['group_id']}/{pom['artifact_id']}")].add(url.lower())
            for kind, key in (("npm", "root_package_json"), ("pypi", "root_pyproject"),
                              ("cargo", "root_cargo")):
                pkg_name = (fact.get(key) or {}).get("name")
                if pkg_name:
                    self.by_coords[(kind, pkg_name.lower())].add(url.lower())

    def from_repos(self, repos) -> set:
        """Products fed by any of the repos."""
        return {t for repo in repos for t in self.by_repo.get(repo, ())}

    def narrow(self, candidates: set, project: dict) -> list:
        """Narrow several candidates by classifier, then by name; sorted."""
        candidates = sorted(candidates)
        if len(candidates) > 1:
            want_image = project.get("classifier") == "CONTAINER"
            candidates = [t for t in candidates if t[1].endswith("-image") == want_image]
        if len(candidates) > 1:
            name = slug(project["name"])
            exact = [t for t in candidates
                     if t[1] in (name, name + "-image") or t[1].endswith("-" + name)]
            candidates = exact or candidates
        return candidates

    def name_candidates(self, project: dict) -> set:
        """Products the project's name points at, most specific form first."""
        name = slug(project["name"])
        forms = [name + "-image", name] if project.get("classifier") == "CONTAINER" else [name]
        for form in forms:
            if form in self.by_name:
                return {self.by_name[form]}
        for form in forms if name not in GENERIC else ():
            suffixed = {t for t in self.by_name.values() if t[1].endswith("-" + form)}
            if len(suffixed) == 1:
                return suffixed
        if name in self.by_repo_name:
            return self.from_repos(self.by_repo_name[name])
        return set(self.by_short_id.get(name, ()))

    def match(self, project: dict):
        """(rule, (project, product)) for the first rule left with one candidate, else None."""
        kind, pkg = parse_purl(project.get("purl"))
        coords = set()
        if kind == "golang" and pkg.startswith("github.com/"):
            coords = {repo_url(*pkg.split("/")[1:3])} if pkg.count("/") >= 2 else set()
        elif kind:
            coords = set(self.by_coords.get((kind, pkg if kind == "maven" else pkg.lower()), ()))
        for rule, candidates in (("repo", self.from_repos(vcs_repos(project))),
                                 ("coordinates", self.from_repos(coords)),
                                 ("name", self.name_candidates(project))):
            left = self.narrow(candidates, project)
            if len(left) == 1:
                return rule, left[0]
        return None


def decide(decisions: dict, project: dict):
    """The recorded decision for a project: 'ignored', (project, product), or None."""
    name = project["name"]
    if name in decisions.get("ignore", {}):
        return "ignored"
    target = decisions.get("names", {}).get(name) or next(
        (r for r in decisions.get("prefixes", []) if name.startswith(r["prefix"])), None)
    return (target["project"], target["product"]) if target else None


def main() -> int:
    """Match uploaded SBOMs to products and write the flags."""
    dt = load("dt-projects.json")
    products = load("github-products.json")
    projects = load("github-projects.json", {})
    facts = load("github-repo-facts.json", {})
    decisions = load(DECISIONS, {"names": {}, "prefixes": [], "ignore": {}})
    matcher = Matcher(products, projects, facts)

    covered = collections.defaultdict(
        lambda: {"dt_projects": set(), "versions": 0, "last": 0, "matched_by": set()})
    unmatched = {}
    bad_decision = set()
    for p in sorted(dt, key=lambda p: (p["name"], p.get("version") or "", p.get("uuid") or "")):
        if not p.get("lastBomImport"):
            continue
        target = decide(decisions, p)
        rule = "decision"
        if target == "ignored":
            continue
        if target is None:
            found = matcher.match(p)
            if found is None:
                kind, pkg = parse_purl(p.get("purl"))
                entry = unmatched.setdefault(p["name"], {
                    "versions": 0, "classifier": p.get("classifier"),
                    "purls": set(), "repos": set(), "candidates": set()})
                entry["versions"] += 1
                if kind:
                    entry["purls"].add(f"pkg:{kind}/{pkg}")
                entry["repos"] |= vcs_repos(p)
                entry["candidates"] |= {f"{t[0]} / {t[1]}" for t in
                                        matcher.from_repos(vcs_repos(p)) | matcher.name_candidates(p)}
                continue
            rule, target = found
        if target[0] not in products or target[1] not in products[target[0]]:
            bad_decision.add((p["name"],) + tuple(target))
            continue
        c = covered[tuple(target)]
        c["dt_projects"].add(p["name"])
        c["versions"] += 1
        c["last"] = max(c["last"], p["lastBomImport"])
        c["matched_by"].add(rule)

    for project, prods in products.items():
        for name, entry in prods.items():
            entry["sbom_uploaded"] = (project, name) in covered
    with open("github-products.json", "w", encoding="utf-8") as fh:
        json.dump(products, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    listing = [{"project": k[0], "product": k[1], "dt_projects": sorted(v["dt_projects"]),
                "sbom_versions": v["versions"], "matched_by": sorted(v["matched_by"]),
                "last_upload": datetime.datetime.fromtimestamp(v["last"] / 1000, datetime.timezone.utc)
                .strftime("%Y-%m-%d")} for k, v in sorted(covered.items())]
    with open("products-with-sboms.json", "w", encoding="utf-8") as fh:
        json.dump(listing, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.makedirs(STATE_DIR, exist_ok=True)
    report = {name: {k: sorted(v) if isinstance(v, set) else v for k, v in entry.items()}
              for name, entry in sorted(unmatched.items())}
    with open(os.path.join(STATE_DIR, "dtrack-unmatched.json"), "w", encoding="utf-8") as fh:
        json.dump({"unmatched": report, "decision_targets_missing": sorted(bad_decision)},
                  fh, indent=1, ensure_ascii=False)
        fh.write("\n")

    rules = collections.Counter(r for v in covered.values() for r in v["matched_by"])
    for item in sorted(bad_decision):
        print(f"warning: decision target no longer exists: {item}", file=sys.stderr)
    print(f"{len(listing)} products with SBOMs (by rule: {dict(sorted(rules.items()))}); "
          f"{len(unmatched)} Dependency-Track project names unmatched -> "
          f"{STATE_DIR}/dtrack-unmatched.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
