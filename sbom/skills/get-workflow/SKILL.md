---
name: get-workflow
description: >-
  For a product whose release mechanism is already recorded, choose the SBOM
  generator each of its build roots needs, then write a hardened GitHub Actions
  workflow that produces a CycloneDX 1.6 SBOM on every release and uploads it to
  the Eclipse SBOM registry, plus a draft HelpDesk ticket requesting upload
  permission. Records both in ./report.json and prints them;
  writes no workflow file, never modifies a project repository and never opens a
  pull request. Takes a product name, or runs over every product in
  ./report.json. Use after get-metadata, or standalone when asked which SBOM
  tool a project should use or what its SBOM workflow should look like.
argument-hint: "[product-name] — or (none) to run over every product in ./report.json"
---

# Generate the SBOM workflow

Five things are returned. Nothing else is in scope:

| # | Output | Scope |
|---|---|---|
| 1 | **Generator choice** — which tool, and the rule that picked it | per source |
| 2 | **A hardened workflow** — CycloneDX 1.6, fully pinned. Recorded in `pipeline.workflow` and printed in the reply, with the path it belongs at | product |
| 3 | **`generator` and `pipeline` in `./report.json`** | product |
| 4 | **The coverage-gap register** — what will not be covered, and why | project |
| 5 | **The upload-permission request** — a draft HelpDesk ticket and a link that opens it pre-filled (§12) | project |

**This skill writes exactly one file: `./report.json`.** The workflow it generates is not
written to disk anywhere — it goes inline into `pipeline.workflow.content`, and into your
reply, alongside the path inside the target repo it is meant to occupy. Nothing else is
produced: no staging tree, no sidecar data file, no install document, no index.

Beyond that: never write into a checkout of a project repository, never run `git add`,
`commit` or `push`, never run `gh pr create`, and **do not offer to install the workflow
or take any further action with it**. Generating it and showing it is the whole job. The
maintainer reads it in your reply and copies it in themselves, or has `/write-workflow`
write it into a local clone after a dry run they agree to — a separate step, also run by
`/onboard --write`, never this one. The design rests on a human reviewing the change
before it runs in their repo.

**Every generated workflow uploads its SBOM to the Eclipse SBOM registry**
(sbom.eclipse.org) through the Project Identity Authority (PIA), with the
`eclipse-csi/workflows/upload-sbom` action — see
[`hardening.md`](references/hardening.md) "Upload through PIA". PIA authenticates the
workflow by its own GitHub OIDC identity, so there is no secret to set up, but upload
permission is granted **per product name and repository** by the Eclipse Foundation
Security Team. §12 drafts the HelpDesk ticket that requests it. Until it is granted, the
upload step fails, visibly. The upload cannot be tried from here: it first runs in the
project's own GitHub Actions, once a maintainer has added the workflow.

## Input

**With an argument** — the product name, which must already exist under `products` in
`./report.json`. Run for that product only.

**With no arguments** — run for every key under `products`.

Either way, a product needs a `release` block before this skill can do anything: the
trigger, the hook strategy and the build inputs all come from there. If `release` is
absent, say to run `/get-metadata` first and stop for that product.

**Only ever write to a product that already exists under `products`.** A `pipeline` block
with no product entry to hang from is not a valid report, and deciding that a product
exists is `/list-products`' job. If you are handed a product name that is not in the
report, return your findings in the reply and write nothing.

## 1. Refuse before you generate

Work through this list **before** choosing any tool. Each condition stops generation for
that product and is recorded, not worked around.

| Condition | Why it stops you |
|---|---|
| A `needs_review` entry that is a **directive** — "re-run `/list-products` to split these", "confirm this split with maintainers" | An earlier skill deliberately withheld a decision. Generating anyway converts an open question into a committed answer, and the resulting file looks exactly like one that was reviewed |
| `confidence.level` is `low` and nothing records a human reviewing it | Low confidence means the product boundary itself is a guess. A workflow is the wrong artifact to attach to a guess |
| `hook.immutable_input` is `none` but `hook.strategy` is `new-workflow` | `get-metadata` §4 says nothing immutable forces `extend-existing`. A standalone workflow here re-resolves against whatever `HEAD` happens to be |
| `hook.strategy` is `extend-existing` with no `hook.target` | Nothing says which pipeline to patch |
| `hook.fidelity_risk` is `null` and `immutable_input` is not `oci-digest` | Only a digest describes the shipped bytes. A null risk anywhere else claims a guarantee the approach does not give |
| A `ships: true` repo appears in no product's `sources` | See §3 — this is a project-level gap, recorded rather than generated around |

Set `pipeline.status` to `blocked` and put the specific question in the product's
`confidence.needs_review`. **Generate no workflow for that product**, and leave
`pipeline.workflow` absent — the schema refuses a refusal that carries one.

`/list-products` and `/get-metadata` write these `needs_review` entries deliberately,
at a cost — they stopped and asked rather than guessing. Treating them as advisory throws
that away.

### A pipeline that already emits an SBOM

When a release pipeline's `emits_sbom` (recorded by `/get-metadata`) shows it already
produces a CycloneDX 1.6 SBOM, leave it alone: `status: already-conformant`, no workflow.
Replacing working SBOM generation is the maintainer's decision.

If that pipeline still uploads through the deprecated `store-sbom-data` workflow
(`emits_sbom.upload` is `store-sbom-data`), record it in `pipeline.deprecated_upload` and
say so in your report: the handbook asks projects to
[migrate to the PIA upload](https://eclipse-csi.github.io/security-handbook/sbom/howto.html#deprecated-upload-via-store-sbom-data).
Do not generate a migration and do not add the product to the upload-permission request;
migrating is the maintainer's call.

## 2. Choose a generator

Three gates, in order. The routing authority is
[`references/tool_selection.md`](references/tool_selection.md) — §1 triage, §2 ecosystem
routing, §3 the matrix with the exact invocation and how 1.6 is obtained from each tool,
§3.2 the routes that must never be taken. **Record which dated revision of it you used**,
in `pipeline.tool_selection_revision`.

### Gate A — is this in scope at all? (product scope)

Out of scope **only** when `hook.strategy` is `extend-existing` **and** the pipeline named
in `hook.target` has `ci_system` other than `github-actions`. This skill generates GitHub
Actions workflows only. Jenkins can upload through PIA too — the handbook's
[Jenkins section](https://eclipse-csi.github.io/security-handbook/sbom/howto.html#jenkins)
shows how — but generating Jenkins pipelines is not covered here, and the handbook
documents no upload for GitLab CI.

**"Releases from Jenkins" is not the same fact as "out of scope."** A product whose stable
release runs on a Jenkins job can still have a standalone workflow triggered by the same
git tag — and `get-metadata` will have recorded `strategy: new-workflow` when it can.
Say this explicitly in your report, or a maintainer reads a fixable product as hopeless.

→ `status: out-of-scope`, no workflow generated, reason recorded verbatim.

### Gate B — route to a generator

Take the first branch that matches.

**B1 — the artifact *is* the thing described (per source).** For an image or a root
filesystem a scanner is the correct tool, not a fallback.

| `ecosystems` contains | Tool | Notes |
|---|---|---|
| `container` | **Syft** | `-o cyclonedx-json@1.6`. Scan the **published digest**, not a rebuilt image. One run per `build.matrix` entry |
| `deb`, `rpm`, `apk` | **Syft** | Best-verified licence coverage of the routes assessed |
| `deb` **and** source packages required | **debsbom** | `-t cdx --with-licenses`. Record the licence gap: a verified run left 813 of 1,194 components unlicensed |

**The one case needing two generators for one source:** `container` together with
`build.archetype == "shaded-uber-artifact"` (or a build command showing
`maven-shade-plugin`, `maven-assembly-plugin`, an uber-jar package type). Record **two**
`generator` entries — Syft as `role: primary` over the published digest, plus the
ecosystem-native resolver as `role: supplement` over the same tag.

A container scanner cannot decompose a shaded jar. It sees one file where the resolver
sees two hundred components. Shipping only the image scan is not a smaller SBOM, it is a
wrong one. Do **not** merge the two automatically — combining a resolved build graph into
an image scan changes what the document claims to be, and that is the maintainer's call.

**B2 — three or more ecosystems under one checkout (product scope) → ORT.** Count the
distinct non-artifact ecosystems across sources that share a `repo`. One job: `analyze` →
`report`. **Never `ort advise`** — the CycloneDX reporter calls `addVulnerabilities(...)`,
and BSI TR-03183-2 forbids vulnerability data in an SBOM. Pin the ORT container **by
digest**; a tag is mutable, and one floating reference in an otherwise SHA-pinned workflow
is the gap an attacker uses.

**Ecosystems in different repos do not aggregate.** ORT analyses a directory tree; it
cannot span checkouts. Maven in one repo and npm in another is two generators plus
`hook.multi_source`, not one ORT run.

**B3 — one or two ecosystems → route per source** via
[`tool_selection.md`](references/tool_selection.md) §3, which gives the tool, the `Control`
value (how 1.6 is obtained), the non-negotiable invocation, and the gap to record. Below
three ecosystems the native generators do as well or better with far less operational
weight.

**Five ecosystem values route to more than one tool**, and the tiebreaker is always in
`sources[].build`, never in the ecosystem name:

| Ecosystem | Read | Routes to |
|---|---|---|
| `yarn` | `build.toolchain.yarn`; `.yarnrc.yml`; the `yarn.lock` header (`__metadata:` = berry, `# yarn lockfile v1` = classic); `package.json` `packageManager` / `engines.yarn` | **berry ≥4** → `yarn-plugin-cyclonedx`. **classic 1.x** → no native generator exists; see §3 of the matrix |
| `gradle` | `build.archetype`, `build.resolution_flags.includeConfigs`, an Android plugin in the build file | **plain JVM** → `cyclonedx-gradle-plugin`. **Android** → same plugin with `includeConfigs` pinned to the shipping variant |
| `python` | `build.lockfiles`, `build.resolution_flags` | **resolved venv** → `cyclonedx-py environment`. **manifest only** → `requirements` mode, a documented gap |
| `maven` | `build.archetype == "shaded-uber-artifact"` | The plugin is still right, but a `coverage_gap` is **mandatory**: relocated classes are invisible to a resolver |
| `swift` | — | `cdxgen -t swift` / `-t cocoapods` |

**Never route from the ecosystem value alone where this table has a row.** Yarn bites
hardest: classic 1.x is still widespread, the `yarn` enum value cannot express the split,
and routing a classic repo to the berry plugin produces a workflow that fails on every
single run — visibly broken, but only after a maintainer has installed it.

If the disambiguating evidence is absent, that is `needs-input`. It is not a default.

### Gate C — can the workflow actually resolve?

**Resolution inputs.** Some tools have an input without which they resolve a *different
graph* than the release did: `GOOS`/`GOARCH` for Go, TFM/RID/Configuration for .NET,
`includeConfigs` for Gradle, `--only prod` for Elixir, `--omit=dev` for Composer,
`--without development:test` for Bundler, `CARGO_BUILD_TARGET` for Rust.

If `build.resolution_flags` and `build.toolchain` do not supply it, **do not fill it in
from what the ecosystem usually needs.** Write the step with a `TODO(resolution)` marker
in its `env:` block, set `status: needs-input`, and put the specific question in
`needs_review`. The generated workflow would still run, still upload, and still be wrong.

**Credentials.** Each entry in `build.credentials_required` needed to *resolve*
dependencies (not merely to publish) is wired into the job as `env:` from `secrets.*`,
named in the header's one-line "Needs secrets" note, and repeated in your report. If a
required credential cannot exist in GitHub Actions — a Jenkins-managed SSH key, an
on-prem-only token — set `status: blocked`.

**Never emit a workflow that cannot succeed.** A red X on every release teaches
maintainers to ignore the SBOM job, which is worse than not having one.

### What the routing verdict means

Each `generator` entry records `assessment`:

| `assessment` | What to do | `status` |
|---|---|---|
| `ok` | Generate the workflow | `generated` |
| `documented-gap`, something generable | Generate one, `install_as` naming `sbom-<product>-partial.yml`. The header's one-line "Not covered" note says what it does not cover; a `::warning::` step at runtime; `coverage_gap` **required** on the entry | `partial` |
| No tool at all | Generate nothing. Record the gap and what would close it | `no-path` |

Two calls worth stating outright:

- **Yarn classic → `partial`, not `no-path`.** `tool_selection.md` offers "migrate to
  berry, or scanner + gap"; route to `cdxgen -t js --spec-version 1.6` and set the
  remediation to *"migrate to Yarn ≥ 4 and re-run"*. Documented partial coverage beats
  nothing, which is what `CLAUDE.md` asks for.
- **`snap`, Carthage, CMake/Make-only C/C++ → `no-path`.** No assessed generator covers
  them, so no re-run helps. Say so plainly rather than generating something that produces
  an empty document.

## 3. Reconcile what ships against what has a product

Diff every `project.repos[]` entry with `ships: true` against every
`products[].sources[].repo`. Each uncovered repo goes in `project.coverage_gaps` with the
stage that has to change:

- The ecosystem enum has no value for what it ships (e.g. a snap) →
  `blocking_stage: list-products`, remediation *"re-run `/list-products` now that `snap`
  exists in the enum"*.
- It ships only Helm charts → **not a gap**: Helm charts are not products (see
  `/list-products`), so the repo needs no SBOM and no `coverage_gaps` entry.
- It ships something no generator covers → `blocking_stage: no-tool-exists`.

**Never invent a product to fill the gap.** Deciding that a product exists is
`/list-products`' job, and a `pipeline` block cannot hang from an entry that does not
exist. Report it, record it, name the skill to re-run.

## 4. Shape the workflow

### Trigger

Read `hook.on` and use the trigger the existing release actually uses:

| `hook.on` | `on:` block |
|---|---|
| `github-release` | `release: types: [published]` |
| `tag` | `push: tags: [<hook.tag_pattern>]` |
| `manual` | `workflow_dispatch` with a typed, validated input |

**Never `workflow_run`.** Chaining off the release run is the obvious-looking build and it
is wrong — it was a High-severity finding in the earlier prototypes. A standalone workflow
listens for the same event the release listens for, not for the release workflow.

Add `workflow_dispatch` alongside an automatic trigger so a maintainer can regenerate an
SBOM for an older release without re-tagging.

For a `manual` product, say plainly in the header's "Not covered" note and in your report:
**SBOM generation is not automatic for this product; it fires when someone remembers.**
Record it as a coverage gap. A manual workflow that nobody runs is not onboarding.

### Product version

Every upload carries a version, set by a "Determine product version" step (the skeleton in
[`hardening.md`](references/hardening.md)). Take it from what defines a release for this
product, `release.versioning.defines_release`:

| `defines_release` | `product-version` |
|---|---|
| `github-release` | `${{ inputs.ref \|\| github.event.release.tag_name }}`: the release tag, as published |
| `git-tag` | `${{ inputs.ref \|\| github.ref_name }}`: the tag that was pushed |
| `registry-version` | The tag, when `versioning` records that the registry version is the tag; otherwise as `manifest-version` |
| `manifest-version` | Read from the manifest at the checked-out ref, after the toolchain is set up — e.g. `1.2.0-SNAPSHOT` |
| `none-found` | No version to upload under: `status: needs-input`, with the question in `needs_review` |

Reading a manifest version, one command per ecosystem, run inside the version step:

| Ecosystem | Command |
|---|---|
| Maven, Maven/Tycho | `mvn -B -q -DforceStdout help:evaluate -Dexpression=project.version` |
| npm, Yarn, pnpm | `node -p "require('./package.json').version"` |
| Python | `python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'` |
| Rust | `cargo metadata --no-deps --format-version 1 \| jq -r '.packages[0].version'` |

Anything else, or a manifest that computes its version at build time, is `needs-input`.
Whichever source, the value is bound through `env:` or captured in a shell variable,
shape-checked, and written to the step output; it never reaches `product-version`
unchecked.

### Upload names

Upload permission is granted per name, so every document a workflow uploads has its own,
written literally in the workflow:

- **One document** — the product key.
- **A matrix** — one name per entry, `<product>-<target>` (e.g. `foo-cli-linux-amd64`),
  carried in the matrix entry as `upload-name`.
- **`merge`** — only the merged document is uploaded, under the product key.
- **`link`** — the primary document under the product key, each linked document under
  `<product>-<source>`, where `<source>` is the source's repo name.

Record them all in `pipeline.upload_names`; the §12 ticket lists exactly these. Names must
be unique across the whole registry — Dependency-Track allows no two entries with the same
name — which the `<short_id>-<component>` naming from `/list-products` is there to ensure.

### Matrixed build roots

`build.matrix` becomes `strategy.matrix` with `fail-fast: false`, one SBOM per entry, each
uploaded under its own name (see "Upload names"). The generation and the upload run per
entry, so a failed entry shows as a failed job; there is no separate count job.

Map `runs-on` from each target where a GitHub-hosted runner exists. Where none does — a
macOS or Windows target built on self-hosted agents — **record it as a documented gap
rather than resolving it on Linux anyway**. Four platform installers described by one
Linux-resolved SBOM is a document describing something nobody shipped.

### Multi-source products

| `hook.multi_source.strategy` | Build |
|---|---|
| `single` | One job. The other sources are build-time only |
| `merge` | One job per source → a merge job running a pinned `cyclonedx-cli merge`. Upload only the merged document, under the product key |
| `link` | No merge job. Each document uploaded under its own name (see "Upload names"); the primary carries `externalReferences[]` of `type: bom` pointing at the others |

A merge can drop the dependency roots and turn two properly graphed inputs into one flat
component list. Nothing in the workflow checks for that (§7).

For `link`, say why it is only conditionally conformant: BSI TR-03183-2 permits linked
SBOMs when each linked document is itself conformant *and* the referencing creator
guarantees their availability. Availability rests on every linked document being uploaded,
so it holds only once upload permission is granted for each of their names.

The workflow lives in `hook.multi_source.host_repo`. Name that choice in your report — for
a multi-repo product it is a judgment call, not a default.

### `extend-existing`

There is no new workflow to generate here. Patch the existing one named by `hook.target`,
and record the **whole patched file** in the same `pipeline.workflow` field, with
`kind: patch`. A whole file, not a step block, is what makes the file a maintainer installs
byte-for-byte the one you audited.

1. Read the existing workflow as `/get-metadata` read it. Its entry in `release.pipelines`
   — the one `hook.target` names — links to the exact version that was analysed:
   `https://github.com/<org>/<repo>/blob/<sha>/<path>`. `<sha>` becomes `base_ref` and
   `<path>` becomes `install_as`. Download that version into the temporary folder (§10):

   ```sh
   gh api -H "Accept: application/vnd.github.raw" \
     "repos/<org>/<repo>/contents/<path>?ref=<sha>" > "<tmp>/<product>.base.yml"
   ```

   If that link is not pinned to a 40-character commit, or points at another repository
   than `pipeline.host_repo`, re-run `/get-metadata` for the product rather than reading
   some other version: the patch must be made to the file whose release facts are recorded.

2. Copy it to `<tmp>/<product>.yml` and edit only the copy, changing nothing else:
   - Insert the version step, the SBOM generation and the upload into the
     job that builds the release, after the build steps the SBOM must describe. Open the
     inserted block with the same short comment as a new workflow's header
     ([`hardening.md`](references/hardening.md)), give the upload step its one-line
     authorization comment, and add the version variables (`CYCLONEDX_SPEC_VERSION` and
     each `<TOOL>_VERSION`) to that job's `env:`, not to the workflow's top level.
     `continue-on-error: true` on the inserted steps unless `hook.blocks_release` is true.
   - Add `id-token: write` to that job's `permissions:`, keeping everything it already
     has; without it the upload cannot get its OIDC token. A job with no `permissions:`
     block gets one listing the workflow-level permissions plus `id-token: write`, because
     a job-level block replaces the workflow-level one. When neither declares any, the job
     runs with the repository's default token permissions, which the file does not show:
     `status: needs-input`, asking which permissions the job needs.
3. Audit the copy (§10). Record (§11) the copy verbatim as `content`, its hash as `sha256`,
   the hash of `<product>.base.yml` as `base_sha256`, and the commit as `base_ref`:

   ```sh
   python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' <file>
   ```

4. Print the change as a diff, not the whole file —
   `diff -u <product>.base.yml <product>.yml`, headed by the path and `base_ref` — with a
   bolded warning that this edits the pipeline that ships their software, which is the
   higher-stakes change.

Set `workflow.install_as` to the existing workflow's path, and say in your report that this
replaces a file that already exists. The recorded content stands in for that file only
while it is still the version `base_sha256` names: `/write-workflow` refuses any other, and
a maintainer applying it by hand should apply the diff, not copy the file over a newer one.

If their existing workflow has hardening problems, **note them and stop there**. Fixing
someone's release pipeline is not what they asked for, and a patch that also rewrites
their checkout steps will not get applied.

→ `status: patch-proposed`.

## 5. The hardening contract

[`references/hardening.md`](references/hardening.md) is the single source for the skeleton,
the rule-by-rule detail, the one justified suppression, and the emit-time audit. Every
workflow you generate satisfies it in full. The rules, in brief — each one a finding class
from the `zizmor` audit of the earlier prototypes:

full-SHA action pins · top-level `permissions: contents: read` · `id-token: write` on the
uploading job only · `persist-credentials: false` on every checkout · no `${{ }}` inside
`run:` · no `workflow_run` · `set -euo pipefail` · dependency caching off on every setup
action, written the way that action expects (`cache: false` is wrong for some of them).

Two standing preferences:

- **Keep the action surface small.** Prefer installing a generator at a pinned version
  inside a `run:` block over adding another action. Every action is another SHA someone
  has to keep fresh; 3–4 per workflow stays maintainable, fifteen does not.
- **Do not add `harden-runner` or similar.** It introduces a third-party action and a
  network-egress dependency to satisfy no requirement anyone stated.

## 6. Pin at generation time

**Never copy a SHA out of a reference document.** Any SHA written down here was resolved
on some past date; reference files show the *shape* of a snippet, not a current pin.
Resolve fresh, per action:

```sh
tag=$(gh api repos/<owner>/<repo>/releases/latest --jq .tag_name)
sha=$(gh api repos/<owner>/<repo>/commits/"$tag" --jq .sha)
gh api repos/<owner>/<repo> --jq '.archived, .full_name'
```

`commits/<tag>` dereferences an annotated tag to a commit in one call. Assert the SHA is
40 hex; write the `# <tag>` comment to match the tag you actually resolved. Check
`archived` and `full_name` — repositories move (`CycloneDX/cdxgen` → `cdxgen/cdxgen`
already happened), and a rename redirect resolves for a while and then stops.

An action published **without releases or tags** — `eclipse-csi/workflows`, which holds
`upload-sbom`, is one — is pinned to the commit its default branch points at, with the
branch and the date in the comment:

```sh
sha=$(gh api repos/eclipse-csi/workflows/commits/main --jq .sha)   # → @<sha> # main (YYYY-MM-DD)
```

Pin non-actions the same way: generator versions, CLI versions, container images **by
digest**. Tool versions go in the workflow's `env:` block as `<TOOL>_VERSION`, beside
`CYCLONEDX_SPEC_VERSION` (`hardening.md`, "Versions in one place"), never inside a command.

**If `gh` is unavailable or unauthenticated, stop.** Do not fall back to a SHA written in
any reference file, and do not emit a floating tag — a floating tag is itself a hardening
violation, so generating one is worse than generating nothing. Offer the user the choice:
authenticate, or generate with `# PIN-REQUIRED` placeholders and `status: needs-input`.

## 7. What the workflow does not do

### The SBOM is not checked

**Generate no step that checks the SBOM.** The workflow uploads the document exactly as
the generator wrote it, so its correctness and completeness are not checked: not its spec
version, not that it lists components and dependencies, not that it carries no
vulnerability data. Say so in your report; the workflow's header comment stays short and
does not repeat it.

What still guards those properties is the generator configuration from
[`tool_selection.md`](references/tool_selection.md): the pinned spec version and the
flags of each invocation. What nothing catches any more, and the report should not imply
otherwise: a generator update that changes its default spec version, a flat component
list with no dependency graph, an empty document from a resolution that silently failed
(often a missing credential), and vulnerability data from a tool that adds it.

### Enrichment is out of scope, for now

**Do not generate a BSI enrichment step, and do not generate a sidecar data file.** The
enrichment step existed to read project facts from a sidecar that is no longer produced,
and an enrichment step without its data file is a step that warns on every run.

State the consequence rather than leaving it implied, in your report (not in the workflow's
header comment): **the generated workflow tops out at what the generator itself emits.**
BSI TR-03183-2 required fields 3, 6, 9, 10, 11 and 12 are properties of *delivered files*
— a shipped filename, the digest of the published artifact, whether a component is an
executable or an archive — not properties of resolved coordinates, so no dependency
resolver produces them and no choice of generator closes the gap.

## 8. Confirm before generating

Stop here and present the plan, **before** generating any workflow:

| Product | Generator | Assessment | Status | Install path | Upload names | Gaps | Secrets |
|---|---|---|---|---|---|---|---|

Then ask:

1. Is any product routed to the wrong tool?
2. Are the recorded coverage gaps acceptable, or should a product be deferred?
3. For multi-repo products — is the host repo right?
4. Are the upload names right? Permission is granted per name, and a name is hard to
   change once SBOMs have been uploaded under it.

One table is a smaller ask than several hundred lines of YAML someone has to read to
discover a product was routed wrong — and the last cheap place to catch it before a
maintainer copies that workflow in.

## 9. Produce the workflow

There is **no staging tree and no file output.** For each product, determine the path the
workflow would occupy inside the target repo, generate the YAML, and carry both into §10.
The path is a label on the content, not a file that exists:

```
<host_repo>/.github/workflows/sbom-<product-key>.yml
```

- One workflow per product. Product keys are already registry-unique, so several products
  can name a path in the same repo without colliding. A matrix lives inside the YAML; a
  multi-source product gets one job per source.
- `partial` coverage appends `-partial` to the filename in that path, so the status stays
  visible in the repo's Actions list once installed, not only in a comment.
- For `extend-existing`, the path is the **existing** workflow being edited, and the content
  is that whole workflow with the SBOM steps added — see §4.
- The workflow's header comment is short, in the form of the skeleton in
  [`hardening.md`](references/hardening.md): the products it makes SBOMs for (its upload
  names), that it was generated with the help of the Eclipse CSI sbom plugin, and where the
  SBOMs are uploaded and how to view them. Then, only when they apply, one line naming what
  is not covered and one naming the secrets the build needs. No date, routing-table
  revision, score, enrichment note or permission-request text: those go in your report.
  Under the header, the `env:` block holds `CYCLONEDX_SPEC_VERSION` and every tool version,
  and the upload step carries a one-line comment that it fails until uploads are
  authorized.

## 10. Self-audit before recording

Audit every workflow you generated **before** writing `report.json`. A failure means
regenerate, not record.

**Producing no file is not an exemption.** An unaudited workflow pasted out of a reply is
exactly as installable as one staged in a tree, and the hardening contract is what makes
it safe to install. The auditors read files, so audit a copy in a temporary folder of its
own, outside the working directory and outside any clone. Create it with:

```sh
python3 -c 'import tempfile; print(tempfile.mkdtemp(prefix="sbom-"))'
```

It prints the folder's path, `<tmp>` below; write that path into each later command, since
a shell variable may not survive from one command to the next. Write each workflow there,
audit it, and delete the folder once the findings are recorded:

```sh
python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1])' "<tmp>"
```

That copy is how `zizmor` gets run, never output to hand over and never something to leave
where it would look installable. If the folder cannot be created — a sandbox that allows
writing only in the working directory — say so and stop; never put these files in the
working directory or in a clone.

Run the structural checks and the auditors from
[`hardening.md`](references/hardening.md) §"Emit-time audit" over the scratch copy. A High
finding blocks unless it is individually suppressed with a written justification, stated in
your report — **exactly two** are justified, both set out there. **Anything else is a real
finding: regenerate, do not suppress.**

For a patch, run the same checks over the base file too. A failure or finding the base
already has is the maintainer's existing problem — note it and do not fix it (§4); only
what the patch introduces blocks.

## 11. Record

Two writes per product, plus two at project scope. Set `_meta.schema_version` to `1`, and
**never lower it** — a report already at a higher number stays there.

1. `generator` — an array on the product entry. One entry per (source, tool) pair; ORT
   gets one entry with no `source` pointer; a supplement generator gets its own entry with
   `role: "supplement"`.
2. `pipeline` — a sibling of `sources`, `evidence`, `confidence`, `release`. Written for
   **every product you considered**, including those you refused. A product with no
   `pipeline` key is one you never looked at, which is a different fact from one you
   declined.
3. `project.coverage_gaps` — from §3.
4. `project.upload_request` — written by the §12 script, never by hand.

`pipeline.workflow` is where the generated YAML lives, and `report.json` is the only place
it exists — `install_as` for the path it belongs at, `content` for the complete file
verbatim, `kind` for whether it is a new file or an `extend-existing` patch (with
`base_sha256` and `base_ref`, §4), and `sha256`, the hash of the scratch file you audited.
Write the content **exactly as you audited and printed it**; a report whose recorded
workflow differs from the one the maintainer read is worse than no record, because both
look authoritative. The validator warns when `content` does not match `sha256`: re-record
the content from the audited file until it does not, or `/write-workflow` will flag it as
edited since the audit.

`pipeline.upload_names` lists every name the workflow uploads under (see "Upload names"),
for every product whose workflow uploads. For an `already-conformant` product still on the
deprecated `store-sbom-data` upload, `pipeline.deprecated_upload` says so (§1).

Record `pipeline.tool_selection_revision` as the dated revision of `tool_selection.md` you
routed from. The workflow is only justified by that revision: when the routing table is
later revised, this field is what names the generated workflows the change invalidates.

There is **one** `confidence` per product, written by `/list-products` and extended by each
later skill. Do not add a second one under `pipeline`. Use `high` only when you resolved
every pin, ran the auditors, and observed every mandatory resolution input. Everything you
could not observe belongs in `needs_review` as a specific question.

## 12. Request upload permission

Upload permission is requested once per project, with an issue in the Eclipse Foundation
[HelpDesk](https://gitlab.eclipse.org/eclipsefdn/helpdesk/-/issues), as the
[handbook](https://eclipse-csi.github.io/security-handbook/sbom/howto.html#prerequisite-request-upload-permission)
describes. Draft it with the script next to this skill. It reads `./report.json`, writes
`project.upload_request`, and prints the draft ticket and a link that opens it pre-filled:

```sh
# Substitute the quoted "Base directory for this skill" from your context; `python` if no `python3`.
python3 "<skill base directory>/scripts/upload-request.py"
```

The ticket covers every product whose workflow uploads (`status` `generated`, `partial` or
`patch-proposed`): its title names the project, and its body gives the project id and each
upload name with the repository that runs the upload (`pipeline.host_repo`), and asks for
the labels `service:dependencytrack` and `team:security`. **Do not write the ticket or the
link by hand**: the script keeps both deterministic and the link correctly encoded. When the
link would be too long for a browser, it opens the issue with the title only and the script
says to paste the description.

Do not file the ticket yourself. Filing it is the maintainer's to do.

Finish by validating:

```sh
python3 "<skill base directory>/../validate-report.py"
```

## 13. Report and stop

Print the workflow. For every product you generated one for, the reply contains the full
YAML in a fenced block, headed by the path it belongs at — that reply is the only rendering
of it a maintainer gets, so a truncated or elided one leaves them nothing to copy. For a
patch, print the full diff from §4 instead.

Alongside each, per product: generator and assessment, status, the trigger, and the
coverage gaps in prose.

Flag explicitly:

- **Every product with `status` other than `generated`**, and what would change it.
- **Every `partial`** — what the SBOM will not contain, in terms of what is missing rather
  than "limited support".
- **Every `manual` trigger** — SBOM generation is not automatic for that product.
- **Every product needing secrets**, and that the workflow fails until they exist.
- **Every matrixed product**, and the upload names it therefore needs.
- **Any target with no GitHub-hosted runner**, and that its platform is uncovered.
- **Any auditor that was not installed**, and that the audit therefore did not run.
- **No BSI enrichment** — uniform across every product, and the ceiling it imposes (§7).
- **`project.coverage_gaps`** — which shipping repos still have no SBOM, and the skill to
  re-run for each.
- **Every `already-conformant` product still on the deprecated `store-sbom-data` upload**,
  and the handbook's migration note.

End with the upload-permission request from §12: the draft ticket and the link, exactly as
the script printed them, and say that every upload fails until the ticket is resolved.

Then say which path each workflow belongs at, and **stop there**. Do not write it to a
file, do not install it, do not offer to open a pull request, and do not propose a next
action for it. The workflow in the reply and in `report.json` is the deliverable — anything
further with it is the maintainer's to do.
