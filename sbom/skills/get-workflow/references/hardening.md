# Workflow skeleton and the emit-time audit

Every generated workflow has this shape.

## The skeleton

```yaml
# SBOMs for: <upload names, comma-separated>
# Generated with the help of the Eclipse CSI sbom plugin (https://github.com/eclipse-csi/skills).
# The SBOMs are uploaded to the Eclipse Foundation SBOM Registry (https://sbom.eclipse.org).
# To view or download them, see https://csi.eclipse.dev/security-handbook/sbom/registry.html
# Not covered: <only when a gap is recorded — one line, plain language>
# Needs secrets: <only when the build needs any — NAME (what for), ...>
name: sbom-<product>

env:
  CYCLONEDX_SPEC_VERSION: "1.6"     # CycloneDX version of the generated SBOMs
  <TOOL>_VERSION: "<x.y.z>"         # <tool>, pinned exactly; one line per tool the workflow installs

on:
  release:
    types: [published]
  workflow_dispatch:          # regenerate for an older release without re-tagging
    inputs:
      ref:
        description: "Tag or ref to build the SBOM for"
        required: true
        type: string

permissions:
  contents: read              # elevate per job only where a job genuinely needs more

jobs:
  sbom:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write         # the OIDC token PIA authenticates the upload with
    steps:
      - uses: actions/checkout@<40-hex-sha> # v<x.y.z>
        with:
          ref: ${{ inputs.ref || github.ref }}
          persist-credentials: false

      - uses: actions/setup-<lang>@<40-hex-sha> # v<x.y.z>
        with:
          <lang>-version: '<from build.toolchain — the version the RELEASE used>'
          <caching off, written the way this action expects — see "Disable dependency caching">
          # e.g. setup-go: "cache: false"; setup-java / setup-python: no cache input at all

      - name: Determine product version
        id: version
        env:
          # the source depends on what defines a release (SKILL.md, "Product version");
          # this is the GitHub-release case
          VERSION: ${{ inputs.ref || github.event.release.tag_name }}
        run: |
          set -euo pipefail
          [[ "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z._+/-]{0,127}$ ]] || { echo "::error::unexpected version: $VERSION"; exit 1; }
          echo "version=$VERSION" >> "$GITHUB_OUTPUT"

      - name: Generate CycloneDX SBOM
        env:
          SBOM: sbom.cdx.json
          # every dynamic value is bound here and referenced as a shell variable;
          # ${{ }} must never appear inside the run: block below
        run: |
          set -euo pipefail
          <install the generator at "$<TOOL>_VERSION">
          <invocation from references/tool_selection.md §3, writing "$SBOM", with the spec
           version given as "$CYCLONEDX_SPEC_VERSION">

      # Fails until the Eclipse Foundation authorizes uploads from this repository.
      - name: Upload SBOM to sbom.eclipse.org
        uses: eclipse-csi/workflows/upload-sbom@<40-hex-sha> # main (<YYYY-MM-DD>)
        with:
          sbom-file: sbom.cdx.json
          product-name: <upload name>
          product-version: ${{ steps.version.outputs.version }}
```

There is no second, BSI-enriched document to upload: enrichment is out of scope for now
(`SKILL.md` §7), so the generator's own output is the only document a run produces. Nor is
there a step checking that document: it is uploaded exactly as the generator wrote it
(`SKILL.md` §7).

The header comment stays this short. The products line lists every upload name, exactly as
recorded in `pipeline.upload_names`. The "Not covered" and "Needs secrets" lines appear only
when they apply, one line each. Nothing else goes in it: no date, no routing-table revision,
no scores, no enrichment or permission-request text. Those belong in the report.

## Rule-by-rule

### Versions in one place

The CycloneDX spec version and the version of every tool the workflow installs (each
generator, `cyclonedx-cli` for a convert or merge step) are set once, in the workflow-level
`env:` block under the header, and every step reads them from there:

- `CYCLONEDX_SPEC_VERSION` is `"1.6"` for now, the version the registry accepts. Steps pass
  `"$CYCLONEDX_SPEC_VERSION"` wherever the tool takes the spec version, in the form the tool
  expects (`cyclonedx-json@$CYCLONEDX_SPEC_VERSION` for Syft's `-o`, `v${CYCLONEDX_SPEC_VERSION/./_}`
  for `cyclonedx-cli --output-version`). The literal `1.6` never appears in a step.
- One `<TOOL>_VERSION` per installed tool, named after it (`SYFT_VERSION`,
  `CYCLONEDX_MAVEN_PLUGIN_VERSION`, `CYCLONEDX_CLI_VERSION`), pinned to an exact version
  with a comment naming the tool.
- Actions are the exception: a `uses:` line cannot read a variable, so actions stay pinned
  by commit SHA as below.

A maintainer then updates a version by changing one visible line, rather than finding it
inside a command. In an `extend-existing` patch the block goes into the `env:` of the job
the SBOM steps are inserted into, not the existing workflow's top level (`SKILL.md` §4).

### Full-SHA pins

```yaml
uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

40 hex characters, plus a comment naming the tag **actually resolved** at generation time.
A tag can be reassigned to a different commit; a SHA cannot. Resolve them fresh — see
SKILL.md §6 — and never copy one out of a reference document, where it is only ever an
illustration of the shape.

An action published without releases or tags — `eclipse-csi/workflows/upload-sbom` is one —
is pinned to the commit its default branch pointed at, with a comment naming the branch and
the date it was resolved: `# main (2026-10-13)`.

### `persist-credentials: false`

On every `actions/checkout`. Without it the job's token is written into
`.git/config`, where any later step — including anything a dependency's install script
runs — can read it.

### No `${{ }}` inside `run:`

```yaml
#  WRONG — the expression is substituted into the shell source before it runs
run: echo "Building ${{ github.event.release.tag_name }}"

#  RIGHT — the value arrives as an environment variable the shell reads
env:
  TAG: ${{ github.event.release.tag_name }}
run: |
  set -euo pipefail
  echo "Building $TAG"
```

A release tag, a branch name, and a `workflow_dispatch` input are all attacker-influencable
in some repositories. The wrong form lets their content become shell source.

### Validate every dispatch input

Binding to `env:` stops injection; it does not make the value *correct*. Assert the shape:

```yaml
env:
  IMAGE_DIGEST: ${{ inputs.image_digest }}
run: |
  set -euo pipefail
  [[ "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "::error::not a digest"; exit 1; }
```

### Upload through PIA

The SBOM is uploaded to the Eclipse SBOM registry by
[`eclipse-csi/workflows/upload-sbom`](https://github.com/eclipse-csi/workflows#upload-sbom),
which authenticates with the job's own GitHub OIDC token through the Project Identity
Authority (PIA). There is no secret to store.

- **`id-token: write` on the uploading job only**, never at the top level. A job-level
  `permissions:` block replaces the top-level one, so it lists `contents: read` as well.
- **The upload comes right after the generation step, in the same job**, and sends the
  document as generated. Nothing checks it first (`SKILL.md` §7).
- **`product-name` is a literal**: the product's upload name as recorded in
  `pipeline.upload_names` and listed in the HelpDesk ticket. Permission is granted per name,
  so it is never computed from an input.
- **`product-version` comes from the "Determine product version" step**, bound through
  `env:` and shape-checked there like any dispatch input.
- **No `if:` and no `continue-on-error:` on the upload in a standalone workflow.** Until
  upload permission is granted the step fails, visibly, and the one-line comment on the
  step says why.
  An `extend-existing` patch follows SKILL.md §4 instead, so it cannot break a release.
- **No `upload-artifact`.** The registry is where the SBOM is kept.

### Never `workflow_run`

Chaining the SBOM job off the release workflow's completion is the obvious-looking design
and it is wrong: `workflow_run` runs in the context of the **default branch** with a
token that can be more privileged than the triggering run. A standalone workflow listens
for the same event the release listens for.

### `set -euo pipefail`

First line of every multi-line `run:`. Without it a failed command mid-block leaves the
step green, and the SBOM job "succeeds" having produced nothing.

### Disable dependency caching

```yaml
- uses: actions/setup-go@<sha> # v7.0.0
  with:
    go-version: '1.25'
    cache: false
```

`cache-poisoning` is a **High**-severity finding in any workflow triggered by
`release: published` or a tag push: such a job can restore a cache entry that an earlier,
lower-privilege run wrote.

For an SBOM workflow the trade is entirely one-sided:

- The cache holds what a *previous* run resolved. The SBOM must describe what **this**
  release resolves — a restored cache is a way to describe the wrong dependency set.
- The saving is seconds, on a job that runs once per release.

So dependency caching is off on every setup action, always. **How you turn it off depends
on the action**, because their `cache` inputs mean different things:

| Action | Caches by default? | Write |
|---|---|---|
| `actions/setup-go` | **Yes** (`cache` is a boolean, default `true`) | `cache: false` |
| `actions/setup-java` | No: `cache` names a build tool (`maven`, `gradle`, `sbt`), empty by default | **No `cache` input at all** |
| `actions/setup-python` | No: `cache` names a package manager (`pip`, `pipenv`, `poetry`), empty by default | **No `cache` input at all** |
| `actions/setup-node` | **Yes, for npm projects**: `package-manager-cache` defaults to `true`; `cache` is an opt-in package-manager name | `package-manager-cache: false`, and no `cache` input |
| `actions/setup-dotnet` | No (`cache` is a boolean, default `false`) | No `cache` input |
| `gradle/actions/setup-gradle` | **Yes** | `cache-disabled: true` |

**Never write `cache: false` where `cache` takes a name** (`setup-java`, `setup-python`,
`setup-node`). The action reads `false` as a build-tool or package-manager name, and
`zizmor` reports it as caching turned on: a High finding. With these settings every action
above audits clean, so no `cache-poisoning` suppression is needed.

Checked 2026-10-21 against each action's `action.yml` (setup-go v7.0.0, setup-java v6.1.0,
setup-python v7.0.0, setup-node v7.1.0, setup-dotnet v6.0.0, gradle/actions v6.4.0) and
`zizmor` v1.30.1. For an action not in the table, read its `action.yml` at the version you
pin and run `zizmor` over the result; defaults like these change between major versions.

```yaml
- uses: actions/setup-node@<sha> # v7.1.0
  with:
    node-version: '22'
    package-manager-cache: false
```

### Suppressions

A High finding blocks — **unless it is individually suppressed with a written
justification**, and the suppression is stated in the report so it is reviewable there
rather than buried in YAML.

The comment must be attached to the **step**, not placed inside the `run:` block, where it
has no effect:

```yaml
#  WRONG — inside run:, zizmor never sees it
run: |
  # zizmor: ignore[adhoc-packages]
  npm install -g "pkg@1.2.3"

#  RIGHT — on the step
- name: Generate SBOM # zizmor: ignore[adhoc-packages]
```

Only one suppression is justified in generated workflows:

| Finding | Where | Justification |
|---|---|---|
| `adhoc-packages` | Installing the generator itself | **The SBOM generator cannot come from the project's own lockfile** — it is not one of the project's dependencies. The version is pinned exactly and `--ignore-scripts` blocks install-time code execution, which is the risk the audit targets |

**Anything else is a real finding.** Do not suppress to make output pass; regenerate.

Note that `go install pkg@version` and a version-pinned `curl | sh` of a release binary
are *not* flagged, while `npm install -g` is. Prefer the un-flagged form where the tool
offers one.

## Matrix

Each matrix entry is its own document and is uploaded under its own name,
`<product>-<target>`. Every entry carries its upload name literally, and each one is listed
in the HelpDesk ticket:

```yaml
strategy:
  fail-fast: false            # one failing target must not hide the others
  matrix:
    include:
      - {goos: linux,  goarch: amd64, runs-on: ubuntu-latest, upload-name: foo-cli-linux-amd64}
      - {goos: darwin, goarch: arm64, runs-on: macos-latest,  upload-name: foo-cli-darwin-arm64}
...
      # Fails until the Eclipse Foundation authorizes uploads from this repository.
      - name: Upload SBOM to sbom.eclipse.org
        uses: eclipse-csi/workflows/upload-sbom@<40-hex-sha> # main (<YYYY-MM-DD>)
        with:
          sbom-file: sbom.cdx.json
          product-name: ${{ matrix.upload-name }}
          product-version: ${{ steps.version.outputs.version }}
```

There is no count job: with `fail-fast: false` every entry runs its own generation and
upload, and a failed entry shows as a failed job.

Where a target has no GitHub-hosted runner, **do not silently resolve it on Linux** —
record the platform as a coverage gap.

## Running after the release publishes

When the SBOM run needs something a release publishes (`hook.needs_published`), it has to
start after publishing, in the way the user chose (`hook.after_publish.option`,
get-metadata §4). Three of the options add to the release workflow; these are their
shapes. Everything else in this file still applies to them.

### Security rules

These hold for every option. None of them may be relaxed to make a workflow fit.

- **The SBOM never runs in a job that holds publishing secrets.** It is its own job, after
  the publish jobs (`needs:`), never steps inside them: an SBOM generator is third-party
  code, and the publish job holds the registry credentials and signing keys.
- **No secrets are passed to an SBOM job:** no `secrets:` on a call, never
  `secrets: inherit`, no `${{ secrets.* }}` beyond what the build itself needs to resolve
  (`build.credentials_required`).
- **`actions: write` only on a start job**, `start-sbom-<product>`, whose only step starts
  the SBOM workflow with `gh` (preinstalled on the runner): no `uses:` step, no third-party
  code next to that permission.
- **Never `workflow_run`**, and nothing started from another repository: starting a
  workflow across repositories needs a token the default one cannot be.
- **Every value passed on is checked first**, like any dispatch input: the tag against the
  version pattern, a digest against `^sha256:[0-9a-f]{64}$`.
- The added jobs carry `continue-on-error: true` unless `hook.blocks_release` is true, so an
  SBOM failure never turns a finished release red. (A reusable-workflow call cannot carry
  it; that is the trade-off of `release-calls-sbom`, below.)

### The pushed image's digest

For a container product the SBOM scans the image the release pushed, by digest. Each
option runs only after the push job has finished, so the digest is read from the registry
by the tag the release pushed, in a step before generation. The release's own publish job
is not touched:

```yaml
      - name: Find the pushed image's digest
        id: image
        env:
          IMAGE: <registry/org/name, as the release pushes it>
          TAG: ${{ steps.version.outputs.version }}   # the image tag, if the release tags it differently
        run: |
          set -euo pipefail
          digest=$(docker buildx imagetools inspect "$IMAGE:$TAG" --format '{{json .Manifest.Digest}}' | tr -d '"')
          [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "::error::no image digest for $IMAGE:$TAG"; exit 1; }
          echo "digest=$digest" >> "$GITHUB_OUTPUT"
```

The generation step then scans `registry:${IMAGE}@${DIGEST}`. A private registry needs its
login, recorded in `build.credentials_required`.

### `sbom-job-in-release`: an SBOM job in the release workflow

One file, recorded as the `kind: patch` workflow (`SKILL.md` §4, `extend-existing`): the
release workflow with one job added at the end. Its steps are the skeleton's, with the ref
and version taken from the release run itself (`${{ github.ref }}`,
`${{ github.ref_name }}`):

```yaml
  # SBOMs for: <upload names>
  # Generated with the help of the Eclipse CSI sbom plugin (https://github.com/eclipse-csi/skills).
  # The SBOMs are uploaded to the Eclipse Foundation SBOM Registry (https://sbom.eclipse.org).
  # To view or download them, see https://csi.eclipse.dev/security-handbook/sbom/registry.html
  sbom-<product>:
    name: SBOM for <product>
    needs: [<after_jobs>]
    runs-on: ubuntu-latest
    continue-on-error: true       # a failing SBOM never fails the release
    permissions:
      contents: read              # check out the release tag
      id-token: write             # the OIDC token PIA authenticates the upload with
    env:
      CYCLONEDX_SPEC_VERSION: "1.6"
      <TOOL>_VERSION: "<x.y.z>"
    steps:
      <checkout at ${{ github.ref }}, version from ${{ github.ref_name }}, the image digest
       when it is an image, generation, upload: as in the skeleton>
```

### `release-starts-sbom`: a start job, the SBOM as its own run

Two files. The SBOM workflow is the skeleton with `workflow_dispatch` as its only trigger,
the release tag as its `ref` input, and a header line saying what starts it:

```yaml
# Started by the release workflow (<after_publish.workflow>) once it has published.
...
on:
  workflow_dispatch:
    inputs:
      ref:
        description: "Release tag to build the SBOM for"
        required: true
        type: string
```

and the release patch (`pipeline.release_patch`) adds one job:

```yaml
  # Starts the SBOM workflow (.github/workflows/sbom-<product>.yml) once the release has published.
  start-sbom-<product>:
    name: Start the SBOM workflow
    needs: [<after_jobs>]
    runs-on: ubuntu-latest
    continue-on-error: true       # a failing start never fails the release
    permissions:
      actions: write              # only to start the SBOM workflow
    steps:
      - name: Start the SBOM workflow for this release
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
          REF: ${{ github.ref_name }}
        run: |
          set -euo pipefail
          [[ "$REF" =~ ^[0-9A-Za-z][0-9A-Za-z._+/-]{0,127}$ ]] || { echo "::error::unexpected ref: $REF"; exit 1; }
          gh workflow run sbom-<product>.yml --ref "$REF" -f ref="$REF"
```

The default token may start a workflow this way (GitHub starts no run from most events it
causes, but `workflow_dispatch` is an exception), so no other token is needed. `--ref` runs
the SBOM workflow as it is at the release tag: it has to be committed before that release
is tagged. Only for a release workflow that runs on a tag or a GitHub release, where
`github.ref_name` is the tag; one that creates its tag during the run is `needs-input`.

### `release-calls-sbom`: the SBOM as a reusable workflow, in the release run

Two files. The SBOM workflow takes `workflow_call` with the same `ref` input, and keeps
`workflow_dispatch` for re-running an older release by hand:

```yaml
# Called by the release workflow (<after_publish.workflow>) once it has published.
...
on:
  workflow_call:
    inputs:
      ref:
        description: "Release tag to build the SBOM for"
        required: true
        type: string
  workflow_dispatch:
    inputs:
      ref:
        description: "Release tag to build the SBOM for"
        required: true
        type: string
```

and the release patch adds the calling job, with no `secrets:`:

```yaml
  # Calls the SBOM workflow (.github/workflows/sbom-<product>.yml) once the release has published.
  sbom-<product>:
    name: SBOM for <product>
    needs: [<after_jobs>]
    permissions:
      contents: read              # check out the release tag
      id-token: write             # the OIDC token PIA authenticates the upload with
    uses: ./.github/workflows/sbom-<product>.yml
    with:
      ref: ${{ github.ref_name }}
```

A job calling a reusable workflow cannot carry `continue-on-error`, so a failing SBOM
marks the release run as failed, after the release has published. Say so when offering
this option. `zizmor` reports a Low `self-repository` note on the `./` path, suggesting a
`$/` form that `actionlint` 1.7.12 rejects: keep `./`; a Low finding does not block.

### Several products after one release workflow

When several products follow the same release workflow (several images pushed by one
release, for example), make **one** release patch that adds every product's job, and record
that same patch on each of them. `/write-workflow` writes it once, and only together with
all their SBOM workflows.

## Emit-time audit

Run over every generated file before writing `report.json`. A failure means regenerate.
Pass `release-patch` as the second argument for a release patch that only starts or calls
the SBOM workflow, which has no upload of its own.

```bash
set -euo pipefail
f="$1"
kind="${2:-}"

# 1. every uses: is a full SHA with a version comment (or "# main (date)" for an
#    action published without releases)
if grep -nE 'uses: [^@]+@' "$f" | grep -vqE '@[0-9a-f]{40} # (v|main \()'; then
  echo "unpinned or uncommented action in $f"; exit 1
fi

# 2. no ${{ }} inside any run: block  (yq may not be installed; parse with Python)
python3 - "$f" <<'PY'
import re, sys
src = open(sys.argv[1]).read().splitlines()
inside, indent = False, 0
for n, line in enumerate(src, 1):
    m = re.match(r'^(\s*)-?\s*run:\s*\|', line)
    if m:
        inside, indent = True, len(m.group(1))
        continue
    if inside:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            inside = False
        elif '${{' in line:
            sys.exit(f"template injection at line {n}: {line.strip()}")
PY

# 3. no workflow_run trigger. (Not "! grep": set -e never stops on a negated command.)
if grep -q 'workflow_run' "$f"; then echo "workflow_run in $f"; exit 1; fi

# 4. one persist-credentials: false per checkout
[ "$(grep -c 'actions/checkout' "$f")" -eq "$(grep -c 'persist-credentials: false' "$f")" ] ||
  { echo "a checkout without persist-credentials: false in $f"; exit 1; }

# 5. top-level permissions are present
grep -q '^permissions:' "$f" || { echo "no top-level permissions: in $f"; exit 1; }

# 6. the PIA upload: id-token: write only at job level, and at least one upload step
#    (none in a release patch that only starts or calls the SBOM workflow)
python3 - "$f" "$kind" <<'PY'
import re, sys
src = open(sys.argv[1]).read().splitlines()
top, uploads = None, 0
for n, line in enumerate(src, 1):
    if re.match(r'^\S', line):
        top = line.split(':')[0]
    if top == 'permissions' and 'id-token' in line:
        sys.exit(f"id-token permission at the top level, line {n}")
    if 'eclipse-csi/workflows/upload-sbom@' in line:
        uploads += 1
if not uploads and sys.argv[2] != 'release-patch':
    sys.exit("no upload-sbom step")
PY

# 7. no secrets handed on wholesale
if grep -qE 'secrets:\s*inherit' "$f"; then echo "secrets: inherit in $f"; exit 1; fi

# 8. actions: write only on a start-sbom-* job, and that job runs no action
python3 - "$f" <<'PY'
import re, sys
src = open(sys.argv[1]).read().splitlines()
job = None
for n, line in enumerate(src, 1):
    m = re.match(r'^  ([A-Za-z0-9_-]+):\s*(#.*)?$', line)
    if m:
        job = m.group(1)
    if re.match(r'^\s+actions:\s*write', line) and not (job or '').startswith('start-sbom-'):
        sys.exit(f"actions: write outside a start-sbom-* job, line {n}")
    if (job or '').startswith('start-sbom-') and re.match(r'^\s+(-\s+)?uses:', line):
        sys.exit(f"a start-sbom-* job must not run an action, line {n}")
PY
```

Then the real auditors. This skill writes no workflow file, so audit a scratch copy
outside the working directory and delete it once the findings are recorded — the scratch
file is how `zizmor` is run, not output to hand over:

```sh
zizmor --persona=regular "$scratch"            # zero High findings required
actionlint "$scratch"
```

High findings block. Medium and Low are reported, not blocking.

**An `extend-existing` patch** is audited as the whole patched workflow, and the checks and
auditors also run over the original it was made from (SKILL.md §10). Only a failure or a
finding the original does not already have blocks; the rest is the maintainer's existing
workflow, noted and left alone.

**If an auditor is not installed, say so explicitly.** An audit that did
not run must never be recorded as one that passed. Suggest `pipx install zizmor`.
