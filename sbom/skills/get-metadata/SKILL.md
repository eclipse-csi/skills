---
name: get-metadata
description: >-
  For a product, determine how it is versioned and released, which existing
  pipelines perform the release, how each of its build roots resolves dependencies,
  and where SBOM generation should hook in so that every new release produces an
  SBOM — preferring a standalone SBOM workflow over editing
  the release pipeline. Takes a product name and its sources as arguments, or runs
  over every product in ./report.json. Use after list-products, or standalone when
  asked how a product is released, versioned, built, or where to attach SBOM
  generation.
argument-hint: "[product-name] [repo URL or org/repo …] — or (none) to run over every product in ./report.json"
---

# Determine release mechanism, versioning, build inputs and the SBOM hook point

Five things are returned for every product. Nothing else is in scope:

| # | Output | Scope |
|---|---|---|
| 1 | **Versioning mechanism** — how a release is identified and numbered | product |
| 2 | **Link to the source of that versioning** — a URL, not a bare file path | product |
| 3 | **Existing release pipeline links** — every pipeline that publishes, as URLs | product |
| 4 | **How each build root resolves** — archetype, toolchain, lockfiles, resolution flags | **per source** |
| 5 | **SBOM hook suggestion** — where generation attaches, and why | product |

Output 4 exists because the workflow builder cannot produce a correct invocation
without it. This skill reads the release pipeline, so it is the only place in the
chain those facts can come from.

**Record only what you observed.** Every fact in output 4 must be read from a
pipeline file, a build file, or the release history — never inferred from the
ecosystem. A guessed `--omit=dev` or an assumed `GOARCH` yields an SBOM describing
something that was never shipped, which is worse than a recorded gap. Where you
cannot observe a fact, omit the field and add a specific question to the product's
`confidence.needs_review`.

**Non-goal: this skill does not choose a generator** — it records the inputs that
choice needs.

## Input

**With arguments** — the first argument is the product name, the rest are its
sources. Accept `org/repo`, `https://github.com/org/repo`, and a tree URL such as
`https://github.com/org/repo/tree/main/server` (the path after the ref is the
build root; default the build root to `.`). Normalize each to `org/repo` plus a
path before you start, and echo what you resolved. Run for that product only.

**With no arguments** — read `./report.json` and run for every key under the
top-level `products` object. If `products` is absent or empty, say to run
`/list-products` first and stop. Products only ever live under `products`; if a
report has product-shaped keys at the top level it predates that layout, so ask
for a `/list-products` re-run rather than reading them from there.

Either way, if `./report.json` exists and already holds the product under
`products`, write the findings back to its `release` key. If it doesn't hold the
product, return the findings in the reply and **write nothing** — deciding that a
product exists is `/list-products`' job, and a `release` block with no product
entry to hang from is not a valid report.

## 1. Versioning mechanism, with a link

Determine and record, each with a URL a reader can open:

| Mechanism | What to look for |
|---|---|
| `git-tag` | Actual tags in the repo. Record the real pattern: `v1.2.3`, `1.2.3`, `release-1.2.3`, or a per-product prefix like `console-v1.2.3` in a monorepo |
| `github-release` | GitHub Releases with assets — a release may exist per tag, or tags may exist with no releases |
| `registry-version` | The version published to a registry: Maven Central, PyPI, npm, an OCI tag or digest. Record whether it tracks the git tag exactly |
| `manifest-version` | The version of record in a build file: `pom.xml` `<version>`, `package.json` `"version"`, `pyproject.toml`, `gradle.properties` |
| `none-found` | No versioning signal discovered — record and flag |

A product usually has several. Record all of them, then name **which one defines
"released"** for this product — that is the signal the SBOM must be produced for.
Where they disagree (a tag with no GitHub Release, a manifest version ahead of the
registry), say so; the disagreement tells you which signal the project actually
treats as a release.

Also record the scheme (semver, CalVer, Eclipse `major.minor.service`, other) and
the snapshot/dev convention (`-SNAPSHOT`, `.qualifier`, a prerelease suffix).

Every one of these needs a link, in this form:

- Tags: `https://github.com/<org>/<repo>/tags`
- A release: `https://github.com/<org>/<repo>/releases/tag/<tag>`
- A manifest: a **permalink** pinned to a commit SHA, not `blob/main`, so the line
  it refers to doesn't drift — `https://github.com/<org>/<repo>/blob/<sha>/pom.xml`
- A registry: the package page, e.g. `https://pypi.org/project/<name>/`

If `./report.json` has `project.id` set, cross-check against the PMI-declared
releases:

```sh
curl -sS "https://projects.eclipse.org/api/projects/<project.id>/releases"
```

Returns `{"releases":[{name,url,date,type,downloads}]}`. These often lag or differ
from git tags; a mismatch is worth reporting. Skip this entirely when `project.id`
is absent.

## 2. Existing release pipelines, with links

Enumerate every pipeline and classify it. Link each as a permalink
(`https://github.com/<org>/<repo>/blob/<sha>/.github/workflows/<file>`).

- **GitHub Actions** — `.github/workflows/*.y{a,}ml`. Read the `on:` block. Role is
  `release` if it publishes anything, `ci` if it only builds and tests, `nightly`
  if scheduled. Record the trigger verbatim.
- **Jenkins** — `Jenkinsfile`, `Jenkinsfile*`, `.jenkins/`, or a JJB definition.
  Eclipse projects often release from a JIPP on `ci.eclipse.org` even when CI runs
  on GitHub Actions. Say plainly that **these skills generate GitHub Actions
  workflows only**, so `/get-workflow` cannot complete that product. Record it
  anyway.
- **GitLab CI** — `.gitlab-ci.yml`. Out of scope; record and flag.

Record `ci_system` on each pipeline (`github-actions`, `jenkins`, `gitlab-ci`,
`other`) so the builder can see out-of-scope products without re-reading the file.

Note any pipeline that already produces an SBOM. A product may be partly onboarded
already, and replacing working SBOM generation is a decision for the maintainer,
not a default. Record it as an object, not a flag — `{"present": true, "format":
"cyclonedx", "spec_version": "1.4", "tool": "cargo-cyclonedx", "upload": "none"}`. A bare
`true` gives the builder nothing to reason with: an existing SBOM at the wrong spec
version is a different situation from a conformant one. Use `{"present": false}`
when there is none.

`upload` says how that SBOM leaves the pipeline: `upload-sbom` (the
`eclipse-csi/workflows/upload-sbom` action, through PIA), `store-sbom-data` (the deprecated
`eclipse-csi/workflows/.github/workflows/store-sbom-data.yml`), `other`, or `none` (kept as
an artifact, or not kept). `/get-workflow` flags the deprecated one.

## 3. How each build root resolves

For **every entry in the product's `sources`**, work out how that build root
resolves its dependencies, and write a `build` object onto that entry. This is per
source, not per product: a product with a Maven backend and an npm frontend has two
archetypes, two toolchains and two lockfile sets.

Read the release pipeline first — it is the authority on what the release actually
did — then the build root's own files.

| Field | Where to read it | Why the builder needs it |
|---|---|---|
| `archetype` | The build files: an aggregator POM with modules, a shading/assembly plugin, Android variants, a workspace declaration | Decides the goal and flags — `multi-module-aggregate` needs an aggregate goal, `platform-variant` needs `matrix` filled in, `shaded-uber-artifact` is a coverage gap a resolver cannot see |
| `toolchain` | The pipeline's `setup-*` steps; `.tool-versions`, `.nvmrc`, `global.json`, the `go` directive | The SBOM must be resolved on the toolchain the release used, or it resolves a different graph |
| `lockfiles` | The build root; note whether each is **committed** | Selects the tool outright for JavaScript, and the mode for Python. A lockfile generated during the build is not an immutable input |
| `resolution_flags` | The release job's build and publish steps | `GOOS`/`GOARCH`, TFM/RID/`Configuration`, `includeConfigs`, `MIX_ENV`, `--omit=dev`, `--no-dev`, `--without development:test` |
| `matrix` | A `strategy.matrix` in the release job | A matrixed build root needs **one SBOM per target**; several generators bake the target into the output |
| `build_command` | The release job, verbatim | Lets the SBOM workflow mirror the resolution the release performed rather than re-derive it |
| `credentials_required` | `settings.xml`, `.npmrc`, private feed config, secrets referenced by the release job | If resolution needs auth, the workflow fails or silently emits a thin SBOM. An unresolvable build must be reported, not attempted |
| `reproducible` | `project.build.outputTimestamp`, `SOURCE_DATE_EPOCH` | Determines whether two runs are byte-comparable and whether release-to-release diffs are readable |

Omit any field you could not observe and raise it in `needs_review`. Do not fill
`resolution_flags` from what the ecosystem *usually* needs.

## 4. Decide the hook point

**Default to `new-workflow`: a standalone SBOM workflow, separate from the release
pipeline.** Prefer it because it does not touch a working release path — a broken
SBOM step can never fail a release it isn't part of, and a maintainer reviewing one
new file is a much smaller ask than a diff against the pipeline that ships their
software.

A standalone workflow is only trustworthy when it can rebuild from an **immutable
input**. Check for one, in this order:

| `immutable_input` | Input available | Approach | Fidelity |
|---|---|---|---|
| `oci-digest` | Published OCI image | Pull by **digest** and scan the published image | Highest — the SBOM describes exactly the shipped bytes |
| `tag-and-lockfile` | Release tag + a **committed** lockfile from step 3 | Check out the tag, resolve from the lockfile | High — resolution is pinned |
| `tag-only` | Release tag, no lockfile | Check out the tag and resolve | Adequate, but record the drift risk: version ranges and `-SNAPSHOT` dependencies can resolve differently than they did at release |
| `none` | Nothing immutable — version computed at release time, artifact assembled from release-job-only state | `extend-existing` | Only the release job holds the truth |

Read the lockfile row off `build.lockfiles` from step 3, and only count lockfiles
marked `committed` — one generated during the build is not an immutable input.

Choose `extend-existing` — SBOM steps inside the existing release pipeline — only
when the last row applies, or when the maintainer asks for it. When you do, note
that generation must not block publication, and that editing a working release
pipeline is the higher-stakes change.

Whichever you choose, **state the fidelity risk explicitly**. A standalone
workflow that re-resolves dependencies can produce an SBOM that does not match the
released artifact; that is the cost of not touching the release path, and it must
be recorded rather than glossed over.

### Trigger

Use the trigger the **existing release actually uses**:

| Existing release trigger | `hook.on` |
|---|---|
| `release: published` | `github-release` |
| `push: tags:` | `tag` (record the pattern) |
| Manual dispatch, or driven from Jenkins/externally | `manual` |

**Never `workflow_run`.** Chaining a standalone workflow off the release run is the
obvious-looking way to build this and it is wrong: `workflow_run` was a
High-severity finding in earlier prototype SBOM workflows. A standalone workflow
listens for the same event the release listens for; it does not listen for the
release workflow.

Check the recorded trigger and tag pattern against **actual past releases**, not
just the pipeline's `on:` block — a workflow can listen for a pattern the project
stopped using. Set `verified_against_history` to record whether you did.

If a product's release is `manual`, say clearly that SBOM generation will not be
automatic for it, and that this is a coverage gap.

### When the SBOM needs something the release publishes

A standalone SBOM workflow listens for the same event as the release, so both start at
the same moment. It can therefore not count on anything the release publishes: an image
is not pushed yet, a package is not on its registry yet (Maven Central can take an hour or
more after upload). Work out, per product, whether the SBOM run needs anything published,
and record each thing in `hook.needs_published`:

- **A container image to scan** (`what: image`, `why: scan-published-image`). Always, for
  a container product: the SBOM describes the pushed image, by digest. `published_by` is
  the workflow that pushes it.
- **A part of the project that is not built in the same run** (`what: package`,
  `why: sibling-not-built`). Read the build files: a dependency on the project's own
  modules or packages, at the release version, that is not part of this build root (not a
  module of the Maven build, not a workspace member, not in the checkout). `published_by`
  is the workflow in this repo that publishes it, or `org/repo` when another repository
  does. For another repository, set `release_needs_it: true` when this product's own
  release build already resolves it: then it is published before this release can run.
- **Siblings in the same checkout are never a need.** The generated workflow builds them in
  the same run (`/get-workflow`'s `tool_selection.md` §5, rule 5).

For each entry also record `promotion` and `miss`:
- `promotion: manual` when publishing ends in a human step: Maven Central with manual
  publishing (`autoPublish` false, `USER_MANAGED`), a staging repository released by hand,
  an image pushed to a staging tag and retagged later. Otherwise `automatic`.
- `miss: silent` when the SBOM run would still succeed without it, with a thinner SBOM.
  Maven does this: it warns that the POM is missing and drops that part's dependencies.
  `miss: fails` when the run fails instead, which is usual for images, npm, pip, NuGet and
  Cargo.

**Then offer the options that fit, and only those.** None of them adds a security risk,
and none waits by polling a registry:

| Situation | Options to offer |
|---|---|
| An image, or a sibling, published by a workflow in this repo, automatically | `sbom-job-in-release`, `release-starts-sbom`, `release-calls-sbom`, `manual` |
| A sibling from another repo that this release itself needs (`release_needs_it`) | `not-needed`, `manual` |
| A sibling from another repo that this release does not need | `manual` only: nothing in this repository knows when the other one has published |
| Publishing ends in a human step (`promotion: manual`) | `manual`. If the promotion is itself a workflow in this repo, also the three options above, attached to that workflow |
| The release workflow does not run on a tag or a GitHub release (it creates its tag during the run) | `manual`, with the question of how the tag is known in `needs_review` |

Never offer, whatever the situation: `workflow_run`; starting a workflow in another
repository (the default token cannot, and another token is a secret to manage); SBOM
steps inside a job that publishes and holds secrets; passing secrets to the SBOM job.
Where a product needs nothing published, ask nothing and keep the trigger above.

**Ask the user**, with your question tool, one question per product. Products that follow
the same release workflow can share one question. Explain first, in plain words: what the
SBOM needs, who publishes it, and that without this the SBOM run races the release. Then
offer each fitting option with what it means for the project:

- **SBOM job in the release workflow** (`sbom-job-in-release`). One file changes: their
  release workflow gets one job at the end, after the publish jobs. It runs with no secrets
  and never turns a finished release red.
- **Release starts the SBOM workflow** (`release-starts-sbom`). Two files: a new SBOM
  workflow, and one small job at the end of the release workflow that starts it as its own
  run. Only that job gets the `actions: write` permission, and it runs no third-party code.
  A failing SBOM never affects the release run.
- **Release calls the SBOM workflow** (`release-calls-sbom`). Two files, as above, but the
  SBOM runs inside the release run as a reusable workflow. No extra permission, but a
  failing SBOM marks the release run as failed, which cannot be switched off.
- **Manual** (`manual`). A maintainer runs the SBOM workflow by hand once the release is
  public. Not automatic, so it is a coverage gap.
- **Nothing to wait for** (`not-needed`), when it applies: say why, for example that the
  release build itself needs the sibling.

Record the answer in `hook.after_publish`: `option`, `offered` (every option you offered),
`reason`, and for the three options that change the release workflow, `workflow` (its path)
and `after_jobs` (the ids of the jobs that publish what the SBOM needs, read from that
workflow). The option sets the rest of the hook:

| `after_publish.option` | `hook.strategy` | `hook.on` |
|---|---|---|
| `sbom-job-in-release` | `extend-existing`, `target` = `after_publish.workflow` | the release's trigger, as above |
| `release-starts-sbom` | `new-workflow` | `release-dispatch` |
| `release-calls-sbom` | `new-workflow` | `release-call` |
| `manual` | `new-workflow` | `manual`, a coverage gap |
| `not-needed` | unchanged | unchanged |

### Multi-source products

When a product has more than one `sources` entry it produces more than one SBOM, so
record `hook.multi_source`:

- `merge` — combine the per-source SBOMs into one document for the product.
- `link` — keep them as separate component SBOMs referenced from the primary. BSI
  TR-03183-2 permits this when each linked SBOM is itself conformant, and the
  referencing creator is responsible for their availability.
- `single` — only one source actually ships; the others are build-time only.

Also set `host_repo`: a multi-repo product's workflow can only live in one
repository, and which one is a decision worth stating rather than defaulting.

## 5. Record

Two writes. Only write when the product already exists in `./report.json` under
`products`.

1. `build` on **each** entry of that product's `sources` — alongside the `repo`,
   `path` and `ecosystems` that `/list-products` wrote. Do not touch those three.
2. `release` on the product entry, a sibling of `sources`, `evidence`,
   `confidence`.

Set `_meta.schema_version` to `1`; **never lower it** — a higher number means a later
skill wrote data this one does not know about, and lowering it claims that work away.

There is **one** `evidence` and **one** `confidence` per product, written by
`/list-products`. Extend them with what you observed here; do not add a second pair
inside `release`.

```json
{
  "products": {
    "codesign-tools": {
      "sources": [
        {
          "repo": "eclipse-csi/codesign-tools",
          "path": ".",
          "ecosystems": ["maven"],
          "build": {
            "archetype": "multi-module-aggregate",
            "toolchain": {"java": "21", "maven": "3.9.6"},
            "lockfiles": [],
            "resolution_flags": {"Configuration": "Release"},
            "build_command": "mvn -B -ntp deploy -DskipTests",
            "credentials_required": ["settings.xml for repo.eclipse.org"],
            "reproducible": {"mechanism": "maven-output-timestamp"}
          }
        }
      ],
      "release": {
        "mechanism": ["maven-central", "github-release"],
        "versioning": {
          "defines_release": "git-tag",
          "scheme": "semver",
          "tag_pattern": "v*",
          "snapshot_suffix": "-SNAPSHOT",
          "version_of_record": "pom.xml <version>",
          "links": [
            "https://github.com/eclipse-csi/codesign-tools/tags",
            "https://github.com/eclipse-csi/codesign-tools/blob/<sha>/pom.xml"
          ]
        },
        "pipelines": [
          {
            "file": ".github/workflows/release.yml",
            "url": "https://github.com/eclipse-csi/codesign-tools/blob/<sha>/.github/workflows/release.yml",
            "trigger": "push tags v*",
            "role": "release",
            "ci_system": "github-actions",
            "emits_sbom": {"present": false}
          }
        ],
        "hook": {
          "strategy": "new-workflow",
          "on": "tag",
          "tag_pattern": "v*",
          "verified_against_history": true,
          "immutable_input": "tag-only",
          "rationale": "the release pipeline signs and publishes; a separate workflow checking out the tag reproduces the dependency graph without touching it",
          "fidelity_risk": "no lockfile, so a dependency version range could resolve differently than at release time",
          "blocks_release": false,
          "multi_source": {"strategy": "single", "host_repo": "eclipse-csi/codesign-tools"}
        }
      },
      "evidence": [
        {"type": "pipeline-file", "locator": ".github/workflows/release.yml", "note": "publish step and toolchain versions read here"},
        {"type": "release-history", "locator": "https://github.com/eclipse-csi/codesign-tools/releases", "note": "tag pattern confirmed across the last 6 releases"}
      ],
      "confidence": {
        "level": "medium",
        "reasons": ["release workflow read directly", "tag pattern consistent across history"],
        "needs_review": ["no lockfile committed, so the resolved graph at tag time is not pinned"]
      },
      "_meta": {"schema_version": 1}
    }
  }
}
```

Finish by validating, since the product object rejects unmodelled keys and a
misspelled field would otherwise be silently lost:

```sh
# Substitute the quoted "Base directory for this skill" from your context; `python` if no `python3`.
python3 "<skill base directory>/../validate-report.py"
```

`hook.strategy` is `new-workflow` (default) or `extend-existing`; `hook.target` is
required for `extend-existing` and omitted otherwise; `hook.on` is
`github-release`, `tag`, or `manual`, or `release-dispatch` / `release-call` when the
release workflow starts the SBOM; `hook.fidelity_risk` is `null` only when
`immutable_input` is `oci-digest`; `hook.blocks_release` is `false` unless a failed
SBOM step should fail the release too. `hook.needs_published` and `hook.after_publish` are
present only for a product whose SBOM run needs something published (§4). A container
product, for example, records:

```json
"needs_published": [
  {"what": "image", "name": "ghcr.io/example/app", "registry": "ghcr.io",
   "why": "scan-published-image", "published_by": ".github/workflows/release.yml",
   "promotion": "automatic", "miss": "fails"}
],
"after_publish": {
  "option": "release-starts-sbom",
  "offered": ["sbom-job-in-release", "release-starts-sbom", "release-calls-sbom", "manual"],
  "workflow": ".github/workflows/release.yml",
  "after_jobs": ["image"],
  "reason": "the user chose a separate SBOM run so the release run is never affected"
}
```

`confidence` is not decorative — it is how the builder tells a verified fact from an
inference. Use `high` only when the release pipeline and the release history were both
read. Every field you could not observe belongs in `needs_review` as a specific
question, not as a silent omission.

## 6. Report

Return, per product, a table of the five outputs — versioning mechanism, its link,
release pipeline links, per-source build summary, hook suggestion — then the
rationale and the fidelity risk in prose. Say whether
`./report.json` was written or not, and why.

Flag explicitly:

- Products whose release mechanism you could not determine.
- Products released from Jenkins or GitLab CI (out of scope for these skills).
- Products where the tag pattern is inconsistent across history.
- Products already emitting an SBOM from an existing pipeline, and at what spec version.
- Multi-repo products — say which repo you propose to host the workflow and why.
- Any product where `extend-existing` was chosen, and what forced it.
- **Any product whose SBOM run needs something published first**: what, who publishes it,
  the option the user chose, and whether the release workflow will change.
- **Any build root whose resolution flags or toolchain you could not observe** — the
  builder will otherwise generate a plausible-looking workflow that resolves a
  different graph than the release did.
- **Any build root needing credentials** to resolve, since the generated workflow
  cannot succeed without them.
- **Any matrixed build root**, and how many SBOMs it therefore requires.

Stop. Tell the user to run `/get-workflow` next.
