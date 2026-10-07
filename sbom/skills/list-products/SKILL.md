---
name: list-products
description: >-
  Given the repositories a project owns, classify which ones actually ship something
  and compile the distinct logical products an SBOM must be generated for, along with
  each product's language ecosystem. Takes either a ./report.json written by
  /list-repositories, or a list of GitHub repository links given directly by the user,
  so it does not require list-repositories to have run. Use before get-metadata.
  Also use when asked what products a project ships.
argument-hint: "(none) — reads ./report.json, or accepts GitHub repo links"
---

# Compile the product list

A repo is not a product. One repo may ship several products; one product may span
several repos; many repos ship nothing at all. Never collapse this silently — the
output is a *proposal* for a human to correct.

## Input

There are exactly two ways in:

**A. `./report.json` written by `/list-repositories`.** Read it and take
`project.repos`. Everything else it holds is PMI identity (`project.id`,
`project.short_id`, `project.name`, `project.github_orgs`) — useful for naming, but
not required.

**B. GitHub repository links given by the user**, in the prompt or in answer to your
question. Accept either full `https://github.com/<org>/<repo>` URLs (with or without
a trailing `/`, `.git`, or `#`/`?` fragment) or bare `org/repo`, one per line, and
normalize both to `org/repo`
(`^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$` — the repo half may start with a dot,
as `eclipse-csi/.github` does). Anything that is not a GitHub repository link — an
org-only URL, another host, a deep link to a file or branch — is not valid input:
name it and ask, do not guess at it. Verify each repo exists before classifying it,
and report any that don't. Then write the list to `./report.json` as `project.repos`
yourself, creating the file if needed.

If `./report.json` has no usable `project.repos` — missing file, absent key, or empty
list — fall back to B rather than stopping, mentioning that for an Eclipse project
`/list-repositories "Eclipse <name>"` will produce the report instead.

Work from the resulting repo list as given. Do not re-enumerate repositories
yourself, and do not add repos the user didn't name — that's whatever produced the
list's job, not this skill's.

## 1. Classify each repo: does it ship?

For each repo in `project.repos`, look for build manifests and publication evidence.

**Ecosystem signals** — presence and location of:

An ecosystem value names the **resolver**, because that is what determines which SBOM
generator applies. Record the most specific value the evidence supports; never use a
broader value as a catch-all.

| Ecosystem | Signals |
|---|---|
| maven | `pom.xml` |
| maven-tycho | `pom.xml` with `tycho` / `eclipse-plugin` / `eclipse-feature` packaging, `*.target`, `feature.xml` |
| gradle | `build.gradle`, `build.gradle.kts`, `settings.gradle*` |
| sbt | `build.sbt`, `project/build.properties` |
| mill | `build.mill`, `build.sc` |
| clojure | `deps.edn`, `project.clj` |
| npm | `package.json` + `package-lock.json` |
| yarn | `package.json` + `yarn.lock` (berry also has `.yarnrc.yml`) |
| pnpm | `package.json` + `pnpm-lock.yaml` |
| python | `pyproject.toml`, `setup.py`, `requirements*.txt`, `poetry.lock`, `uv.lock`, `pdm.lock` |
| conda | `environment.yml`, `meta.yaml` recipe, a shipped `conda-meta/` prefix |
| go | `go.mod` |
| rust | `Cargo.toml` with `[package]` |
| dotnet | `*.csproj`, `*.fsproj`, `*.vbproj`, `*.sln` |
| php | `composer.json` + `composer.lock` |
| ruby | `Gemfile` + `Gemfile.lock`, `*.gemspec` |
| elixir | `mix.exs`, `mix.lock` |
| erlang | `rebar.config`, `rebar.lock` |
| swift | `Package.swift` + `Package.resolved`; `Podfile` + `Podfile.lock` |
| dart | `pubspec.yaml` + `pubspec.lock` |
| perl | `cpanfile`, `META.json`, `Makefile.PL`, `dist.ini` |
| ocaml | `*.opam`, `dune-project`, `*.opam.locked` |
| haskell | `*.cabal`, `cabal.project.freeze`, `stack.yaml` |
| lua | `*.rockspec` |
| r | `DESCRIPTION`, `renv.lock` |
| nix | `flake.nix` + `flake.lock`, `default.nix` |
| conan | `conanfile.txt`, `conanfile.py`, `conan.lock` |
| vcpkg | `vcpkg.json`, `vcpkg-configuration.json` |
| cpp-unmanaged | `CMakeLists.txt`, `Makefile`, `meson.build` **with no** conan or vcpkg manifest |
| container | `Dockerfile`, `Containerfile`, `docker-bake.hcl` |
| deb / rpm / apk | `debian/control` / `*.spec` / `APKBUILD` — only when the product itself ships OS packages or a root filesystem |
| terraform | `*.tf`, `.terraform.lock.hcl` |

**Disambiguation rules** — these are the cases that get recorded wrongly:

- **JavaScript: the lockfile decides**, not `package.json`. Three lockfiles mean three
  different generators. If several lockfiles are present, the one the release pipeline
  installs with wins; if that is unclear, say so in `needs_review` rather than guessing.
- **Python vs conda.** `conda` is for a product shipping a conda environment or recipe.
  A Python project that merely *builds* under conda is still `python`.
- **C/C++: `conan` and `vcpkg` are not interchangeable**, and `cpp-unmanaged` is a real,
  distinct value — record it rather than omitting the ecosystem, because it is what marks
  a product as having no viable generator.
- **Swift** covers both SwiftPM and CocoaPods. Carthage (`Cartfile`) is unsupported
  everywhere — record it in `needs_review`, not as an ecosystem.
- **`maven-tycho` is not `maven`.** Tycho resolves OSGi bundles through p2, which the
  Maven resolver does not see, so the generator choice differs. Do not collapse it.
- **A repo's language is not its ecosystem.** Record only ecosystems whose manifests are
  actually present at that build root.

Several of these ecosystems have no generator that meets the target — see
[`tool_selection.md`](../get-workflow/references/tool_selection.md). Record them anyway and let the
downstream skill declare the coverage gap. An unrecorded ecosystem is an
undocumented gap, which is the outcome `CLAUDE.md` rules out.

**Ships-something signals** (a manifest alone is not enough):

- Publishable coordinates: a `pom.xml` with `groupId`/`artifactId` and a
  distribution or central-publishing config; a `package.json` **without**
  `"private": true`; `[package]` in `Cargo.toml`.
- Release history: git tags, GitHub Releases with assets.
- A release pipeline exists (`.github/workflows/*release*`, `Jenkinsfile`).
- **Snapshot-only publishing counts.** A pipeline that deploys snapshots (e.g.
  `mvn deploy` to a snapshot repository on every push) is enough, even without tags
  or releases.
- A publishing pipeline that **cannot work** — missing registry secrets, or pointing
  at a file that does not exist — does not count.

**Ships-nothing signals** — treat as non-shipping unless contradicted: repo named
`.github`, `*-website`, `*.github.io`, `docs`, `examples`, `samples`, `test*`;
archived repos; repos whose only manifests are for the build of docs or CI.

Record `ships: true|false` and a short `note` on each repo entry.

## 2. Group repos into logical products

Apply these in order, and record the reasoning:

1. **Multiple products in one repo (monorepo).** Sibling directories each with
   their own manifest *and* their own publishable coordinates. Distinct ecosystems
   in one repo almost always means distinct products (e.g. a Maven backend plus an
   npm frontend). Each becomes its own product, and each sibling directory is its
   own entry in that product's `sources`.
2. **Multi-module build, one product.** Many `pom.xml` under one aggregator whose
   modules are not independently consumed. This is **one** product with a single
   `sources` entry at the aggregator root. Distinguishing this from case 1 is the
   single most common mistake — check whether modules are published separately.
3. **One product across several repos.** Shared artifact group, coordinated
   version numbers, or a naming family (`foo-core`, `foo-runtime`). One product,
   one `sources` entry per repo — flag it, since the pipeline can only live in one
   of them.
4. **Container images: one product per published image.** Every distinct image
   pushed to a registry is its own product; never group several images into one.
   - Variant images from one build (per service, per worker, matrix entries) are
     one product **per image name**.
   - Tag aliases (`:latest`, version tags, `-alpine` variants of one name) and
     multi-arch builds are **not** separate products.
   - An image counts only if it has actually been **pushed**: a registry listing
     with tags, or a push step that demonstrably ran. A push step that never ran,
     Dockerfiles used only for CI, tests or dev containers, and images no current
     workflow pushes do not count.
   - Record the image reference (e.g. `ghcr.io/org/name`, no tag) as
     `registry-listing` evidence on the product.
5. **Package vs image.** If a repo publishes a package or binary independently
   (Maven, npm, PyPI, crates.io, release binaries, p2 site…) **and** an image built
   from it, those are two products. If the package exists only to build the image,
   record only the image product.

**Borderline kinds — do not decide silently.** These are not settled: test suites,
CI/build/base images, GitHub Actions, Ansible roles, fonts and other artifacts with no
dependencies. Include them if they otherwise ship, and name each one in
`confidence.needs_review`. Helm charts are **not** products: note them on the repo
entry instead.

Name each product for the registry it will be uploaded to: prefer
`<project.short_id>-<component>` when `project.short_id` is set (e.g. by
`/list-repositories`), or a short slug derived from the repo/org name otherwise.
Names must be unique within that registry, so avoid generic words like `server`,
`core`, `milestone`. An image product's name ends in `-image` (e.g. `foo-server-image`),
so a package and the image built from it (rule 5) never share a name. A product's name
is its key under `products` in `./report.json` — there is no separate `name` field.

## 3. Write the report and confirm

Update `./report.json`: fill in `ships`/`note` on each `project.repos` entry, and
add one key per identified product under a top-level `products` object. `project`
and `products` are the only top-level keys this skill writes — a product
must never be written as a top-level key of its own. Leave `release` absent
(`/get-metadata` adds it) and `generator`/`pipeline` absent
(`/get-workflow` adds those) as further sibling keys inside the product entry.

The full contract is [`schema.json`](../schema.json), and the product object does
not accept unmodelled keys — a misspelled field is rejected rather than silently
carried, so validate before you finish:

```sh
# Substitute the quoted "Base directory for this skill" from your context; `python` if no `python3`.
python3 "<skill base directory>/../validate-report.py"
```

Write `products` even when it ends up empty: `"products": {}` records that this
skill ran and found nothing shippable, which is a different fact from the key being
absent. Say so plainly in that case rather than leaving it implied.

If you are re-running over a report whose products sit at the top level (the
pre-`products` layout), move them under `products` as you write, preserving any
`release` or `pipeline` keys later skills already added.

Each product entry, in place under `products`:

```json
{
  "products": {
    "jkube": {
      "sources": [
        {"repo": "eclipse-jkube/jkube", "path": ".", "ecosystems": ["maven"]}
      ],
      "evidence": [
        {"type": "build-file", "locator": "pom.xml", "note": "root aggregator POM"},
        {"type": "registry-listing", "locator": "https://central.sonatype.com/artifact/org.eclipse.jkube", "note": "published to Maven Central"}
      ],
      "confidence": {
        "level": "high",
        "reasons": ["single repo", "clear release history", "distinctive Maven coordinates"],
        "needs_review": []
      },
      "_meta": {"schema_version": 1}
    }
  }
}
```

**Never lower `_meta.schema_version`.** Set it only when absent; otherwise leave
whatever is there. This skill re-runs over already-enriched reports, so it will often
meet products carrying `release`, `generator` and `pipeline` from later skills, and a
lower number would claim that enrichment away.

`sources` takes one entry per (repo, build root); a monorepo product with two
ecosystems at the same path lists two entries in `ecosystems` on that one source
rather than two sources. `confidence.needs_review` must be non-empty whenever
`level` isn't `high` — list the specific open question(s) a human must resolve.

Then **stop and present the proposal to the user** as a short table: product,
repo(s), path(s), ecosystem(s), confidence. Ask explicitly:

- Is any product missing, or listed but not actually shipped?
- Should any product be split or merged?
- Are the proposed registry names right?

Do not proceed to the next skill in the chain. Say what to run next
(`/get-metadata`) and let the user decide.

Call out honestly anything you could not determine — an unreadable repo, an
ambiguous monorepo split, a product with no discoverable release history. A
`low` confidence product that a human has not reviewed must never be treated as
settled.
