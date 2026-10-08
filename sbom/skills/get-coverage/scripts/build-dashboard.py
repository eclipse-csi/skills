#!/usr/bin/env python3
"""Build the SBOM adoption dashboard (sbom-adoption.html) from the pipeline outputs.

Reads github-products.json, github-projects.json and github-repo-facts.json, derives per
product:
  - the primary build ecosystem (from root-level build files; images count as their own)
  - the CI platform (GitHub Actions workflows / Jenkinsfile)
  - whether it is active (a push to any of its repos in the 180 days before --as-of)
and embeds the data into assets/dashboard.template.html.
"""

import argparse
import datetime
import json
import os
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "assets", "dashboard.template.html")
OUTPUT = "sbom-adoption.html"
OTHER = "Other / none"


def ecosystem(facts: dict) -> str:
    """Infer the primary build ecosystem, preferring build files at the repo root.

    A monorepo's root build (e.g. CMake + Conan) decides over manifests of sub-directories
    (e.g. a UI's package.json); deeper manifests are used only when the root has none.
    """
    manifests = facts.get("manifests") or {}
    root = {name: v for name, v in manifests.items() if name in set(facts.get("root_files") or [])}
    root.pop("Dockerfile", None)
    result = _ecosystem(root, facts) if root else OTHER
    if result == OTHER:
        return _ecosystem(manifests, facts)
    # Tycho signals (feature.xml, category.xml, *.target) live in sub-directories by design.
    tycho = any(n in manifests for n in ("feature.xml", "category.xml")) \
        or any(n.endswith(".target") for n in manifests)
    return "Maven / Tycho (p2)" if result == "Maven" and tycho else result


def _ecosystem(m: dict, facts: dict) -> str:
    """Classify a set of manifest names into one ecosystem."""
    has = lambda *names: any(n in m for n in names)  # noqa: E731
    if has("feature.xml", "category.xml") or (facts.get("root_pom") or {}).get("tycho") \
            or any(k.endswith(".target") for k in m):
        return "Maven / Tycho (p2)"
    if has("pom.xml"):
        return "Maven"
    if has("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"):
        return "Gradle"
    if has("build.sbt"):
        return "sbt"
    if has("Cargo.toml"):
        return "Rust / Cargo"
    if has("go.mod"):
        return "Go"
    if has("package.json"):
        return "npm / JS"
    if has("pyproject.toml", "setup.py", "setup.cfg", "poetry.lock", "uv.lock") \
            or any(k.startswith("requirements") for k in m):
        return "Python"
    if any(k.endswith((".csproj", ".sln", ".fsproj")) for k in m):
        return ".NET"
    if has("CMakeLists.txt", "Makefile", "meson.build", "conanfile.txt", "conanfile.py", "vcpkg.json"):
        return "C / C++"
    return OTHER


def ci_system(repo_facts: list) -> str:
    """Classify the CI used by a product's repos."""
    gha = any(f.get("workflows") for f in repo_facts)
    jenkins = any(f.get("has_jenkinsfile") for f in repo_facts)
    if gha and jenkins:
        return "GitHub Actions + Jenkins"
    if gha:
        return "GitHub Actions"
    return "Jenkins only" if jenkins else "No CI found"


POPULAR = {"Maven", "Container image", "npm / JS", "Python"}
RELEASE_RANK = {"release": 3, "tag": 3, "manual": 1, "push": 1, None: 0}
RELEASE_LABEL = {"release": "publishes on GitHub release", "tag": "publishes on tag push",
                 "manual": "manual release workflow", "push": "publishes on every push",
                 None: "no release workflow found"}


def best_trigger(repo_facts: list):
    """Strongest release trigger across a set of repos."""
    return max((f.get("release_trigger") for f in repo_facts),
               key=lambda t: RELEASE_RANK.get(t, 0), default=None)


def candidate_signals(rows: list, products: dict, facts: dict, projects: dict) -> list:
    """Per-project signals for the "Easy Candidates for New Adopters" table.

    The page applies the conditions (no SBOM yet, active, GitHub Actions, not C/C++ or
    Tycho/p2, GitHub Releases, clear release trigger) as user-toggled filters; this only
    provides each project's facts and a priority score: popular ecosystems, GitHub Actions
    only, a clear release trigger and GitHub Releases present.
    """
    by_project = {}
    for r in rows:
        by_project.setdefault(r["p"], []).append(r)
    out = []
    for name, prs in by_project.items():
        ecos = {r["eco"] for r in prs}
        repos = sorted({u for e in products[name].values() for u in e["repos"]})
        repo_facts = [facts.get(u, {}) for u in repos]
        trigger = best_trigger(repo_facts)
        has_releases = any((f.get("releases") or {}).get("count") for f in repo_facts)
        gha_only = all(r["ci"] == "GitHub Actions" for r in prs)
        if ecos <= POPULAR:
            popular = 3
        else:
            popular = 1 if ecos & POPULAR else 0
        score = popular + (2 if gha_only else 0) + RELEASE_RANK.get(trigger, 0) + (1 if has_releases else 0)
        meta = projects.get(name, {})
        out.append({"p": name, "tl": meta.get("top_level_project") or "?", "st": meta.get("state") or "?",
                    "n": len(prs), "sb": sum(r["sb"] for r in prs), "wf": len(repos), "eco": sorted(ecos),
                    "gha_only": gha_only, "release": RELEASE_LABEL[trigger],
                    "rel_ok": RELEASE_RANK.get(trigger, 0) >= 3, "releases": has_releases,
                    "popular": popular == 3, "score": score})
    out.sort(key=lambda e: (-e["score"], e["wf"], e["n"], e["p"].lower()))
    return out


def main() -> int:
    """Compute the dashboard dataset and render the HTML."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--as-of", default=datetime.date.today().isoformat(),
                        help="reference date for 'active' and the page header (default: today)")
    args = parser.parse_args()

    load = lambda p: json.load(open(p, encoding="utf-8"))  # noqa: E731
    products = load("github-products.json")
    projects = load("github-projects.json")
    facts = load("github-repo-facts.json")
    repos = load("github-repos.json")
    as_of = datetime.datetime.fromisoformat(args.as_of).replace(tzinfo=datetime.timezone.utc)

    def days_since_push(urls):
        """Days between the latest push to any of the repos and --as-of (None if unknown)."""
        pushes = [facts.get(u, {}).get("pushed_at") for u in urls]
        pushes = [datetime.datetime.fromisoformat(p.replace("Z", "+00:00")) for p in pushes if p]
        return (as_of - max(pushes)).days if pushes else None

    def active(urls):
        age = days_since_push(urls)
        return age is not None and age <= 180

    rows, unverified = [], 0
    for name, prods in products.items():
        meta = projects.get(name, {})
        for product, entry in prods.items():
            is_image = product.endswith("-image")
            unverified += is_image and entry.get("image_status", "NO_REF") != "PUSHED"
            rows.append({
                "p": name, "k": product, "tl": meta.get("top_level_project") or "?",
                "st": meta.get("state") or "?", "img": is_image,
                "eco": "Container image" if is_image else ecosystem(facts.get(entry["repos"][0], {})),
                "ci": ci_system([facts.get(u, {}) for u in entry["repos"]]),
                "act": active(entry["repos"]), "age": days_since_push(entry["repos"]),
                "sb": bool(entry.get("sbom_uploaded")),
                "rel": RELEASE_LABEL[best_trigger([facts.get(u, {}) for u in entry["repos"]])],
                "nr": len(entry["repos"])})
    project_rows = [{"p": n, "tl": projects.get(n, {}).get("top_level_project") or "?",
                     "st": projects.get(n, {}).get("state") or "?", "n": len(v),
                     "sb": sum(bool(e.get("sbom_uploaded")) for e in v.values())}
                    for n, v in products.items()]

    easy = candidate_signals(rows, products, facts, projects)
    data = json.dumps({"products": rows, "projects": project_rows, "easy": easy},
                      separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    repo_count = sum(len(u) for orgs in repos.values() for u in orgs.values())
    with open(TEMPLATE, encoding="utf-8") as fh:
        html = fh.read()
    for key, value in {"__DATA__": data, "__AS_OF__": args.as_of,
                       "__REPO_COUNT__": f"{repo_count:,}", "__PROJECT_COUNT__": f"{len(products):,}",
                       "__IMG_UNVERIFIED__": f"{unverified:,}"}.items():
        html = html.replace(key, value)
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {OUTPUT}: {len(rows)} products, "
          f"{sum(r['sb'] for r in rows)} with SBOMs ({len(html) // 1024} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
