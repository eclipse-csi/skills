# sbom

Agent plugin that gets an open source project onto automated SBOM generation, so
**every release of every product it ships produces a CycloneDX 1.6 SBOM** — and measures
how far SBOM adoption has got across all Eclipse projects.

You run them yourself, on your own project. Nothing is applied centrally, nothing is
installed on your behalf, and no repository of yours is modified.

The infrastructure is rarely the hard part — for one already-understood project, the
generator and the upload mechanics are well documented. What is missing is a repeatable
path from *"here are our repositories"* to *"every release produces a complete SBOM"*,
without hand-adapting a template, wiring a build path per repo, and re-deciding tool
choice one product at a time.

Driver: the EU Cyber Resilience Act, with BSI TR-03183-2 v2.1.0 as the concrete
field-level requirement.

## Requirements

> **We recommend running all these skills in a sandbox environment**, such as an isolated
> container or virtual machine, rather than directly on your own machine. The skills run
> scripts, call the GitHub and Dependency-Track APIs with your tokens, and let an agent run
> commands on your behalf; a sandbox limits what they can reach.

### Onboarding skills

| | |
|---|---|
| Claude Code | The skills run inside it |
| `gh`, authenticated (or a `GITHUB_TOKEN`) | Repository and release enumeration, and resolving action pins. The skills stop rather than produce a partial list, or a workflow pinned to a floating tag |
| `python3` | Runs the report validator after every stage |
| `pip install jsonschema` | Without it the validator reports `PARTIAL` and exits non-zero rather than implying a pass |
| `zizmor`, `actionlint` | Strongly recommended — every generated workflow is audited with them *before* you see it. Without them, the skills record that the audit **did not run** |

```sh
pip install jsonschema
pipx install zizmor
go install github.com/rhysd/actionlint/cmd/actionlint@latest
```

### get-coverage

| | |
|---|---|
| Claude Code | The skill runs inside it and sends the product analysis to parallel subagents |
| `python3` 3.10+ | Runs the pipeline scripts, which use only the standard library |
| A GitHub token in `GH_TOKEN` or `GITHUB_TOKEN` | Read access to public repositories; the GraphQL API needs a token. `read:packages` also lets agents list ghcr.io packages |
| A Dependency-Track API key with `VIEW_PORTFOLIO` | Optional. Only for SBOM status; you export the projects yourself, so the key never reaches Claude |

The generated workflows also use `jq`, on the runner rather than on your machine.

## Install

From Claude Code, add this repository as a plugin marketplace and install the plugin:

```
/plugin marketplace add eclipse-csi/skills
/plugin install sbom@eclipse-csi
```

Without the plugin system, copy the **whole contents** of `sbom/skills/` into your skills
directory — `~/.claude/skills/` for every project, or `.claude/skills/` inside one
repository:

```sh
git clone https://github.com/eclipse-csi/skills.git
mkdir -p ~/.claude/skills
cp -r skills/sbom/skills/* ~/.claude/skills/
```

Copy everything, not just the skill directories: `validate-report.py` and `schema.json`
have to sit alongside them, because each skill locates the validator at
`../validate-report.py`, relative to itself, and `get-coverage` reads the sibling
`list-products` skill.

Restart Claude Code, and `/onboard` and `/get-coverage` are available.

## Quick start

Run it from the directory you want `report.json` to land in. That is the only file the
chain writes, and it always goes in the current directory:

```
/onboard Eclipse JKube
```

Takes a project name, a PMI project ID such as `technology.csi`, or a list of `org/repo`.

It works through four stages and **stops to ask at each decision point** — which
repositories ship a product, whether a monorepo is one product or three, whether the
routing table picked the right tool. Those stops are the design. A workflow attached to a
product boundary nobody confirmed looks exactly like one that was reviewed.

You can also run any stage on its own:

| Command | Produces |
|---|---|
| `/list-repositories <project>` | Every GitHub repo the project owns (Eclipse projects only) |
| `/list-products` | The distinct products it ships, and their ecosystems |
| `/get-metadata` | How each is versioned, released and built, and where SBOM generation should attach |
| `/get-workflow` | Generator choice, and the generated workflow itself |
| `/get-coverage` | SBOM coverage across all Eclipse projects, as data files and a dashboard (see below) |

Each onboarding stage enriches the `report.json` the last one left, and every stage is
re-runnable and hand-editable in between — if a product is grouped wrong, fix the JSON and
re-run from there. Only `/list-repositories` is Eclipse-specific; the rest work from any
repository or product list you hand them.

## What you get

**`report.json`** — the full record: every repository, every product, how each releases,
which generator was chosen and why, what is not covered, and each generated workflow
verbatim under that product's `pipeline.workflow`.

**A workflow printed in your terminal for each product**, headed by the path it belongs at:

```
eclipse-jkube/jkube/.github/workflows/sbom-jkube.yml
```

Nothing is written to disk for you to install and nothing is staged in a directory tree.
**Copying a workflow into your repository is yours to do** — read it first. Its header
comment lists the secrets it needs, what a first run should produce, the coverage gaps
recorded against it, and a `zizmor` line to audit it yourself before it runs.

## What it will not do

Deliberate exclusions. Each is recorded against the affected products rather than
half-implemented:

- **Modify your repositories.** No commits, no branches, no pull requests, no local files
  staged.
- **Upload to an SBOM registry.** Workflows publish the SBOM as a build artifact with a
  `TODO(upload)` marker where the push belongs. Registry provisioning is a separate
  configuration step, and guessing at it produces a workflow that fails undebuggably.
- **Jenkins or GitLab CI.** The assumed upload step needs a GitHub Actions OIDC token.
  Note that a product whose *release* runs on Jenkins can often still have a standalone
  SBOM workflow on GitHub triggered by the same tag — the skills tell you when that is the
  case, rather than writing the product off.
- **BSI field enrichment.** Fields 3, 6, 9, 10, 11 and 12 are properties of *delivered
  files* — a shipped filename, the digest of the published artifact, whether a component is
  an executable or an archive — not of resolved coordinates. No dependency resolver
  produces them and no choice of generator closes the gap, so generated workflows top out
  at what the generator itself emits.
- **Signing and attestation.**

## Coverage across all projects

`/get-coverage` answers *"how many of our products already have an SBOM, and where should
we help next?"* for every Regular and Incubating Eclipse project hosted on GitHub. It
applies the same product rules as `/list-products`, at scale:

1. Lists every project's GitHub repositories and collects facts about each: build files,
   releases, tags, CI platform, and what each release workflow is triggered by and
   publishes.
2. Identifies the products each project ships, with parallel subagents working in
   batches. Only projects whose repositories changed since the last run are re-analysed,
   and nothing is applied until you approve the diff.
3. Checks that every container image product really exists in its registry.
4. Matches products against the SBOMs already uploaded to your Dependency-Track instance.
5. Builds a self-contained dashboard (`sbom-adoption.html`): coverage by project,
   ecosystems, CI platforms, adoption status, and easy candidates for new adopters.

It needs a GitHub token (`GH_TOKEN`/`GITHUB_TOKEN`) and, for SBOM status, a Dependency-Track
API key with `VIEW_PORTFOLIO`. Start with `--limit 10` for a quick trial; a full run over
~380 projects takes a while and is token-heavy, refreshes are much cheaper. Everything is
written to the directory you run it from.

## When there is no good tool

Some ecosystems have no generator that meets the requirement. You get a **named, explained
gap** instead of a plausible-looking workflow producing a thin document:

| Outcome | Meaning |
|---|---|
| `ok` | A generator that satisfies CRA Annex I Part II(1) |
| `documented-gap` | A workflow is still generated, named `-partial`, warning at runtime, with a concrete statement of what its SBOM will be missing — Yarn 1.x classic, Nix, conda |
| `no-path` | Nothing is generated, because no assessed generator covers it and no re-run helps — snap, Carthage, CMake/Make-only C/C++, Terraform |

R, Haskell and Lua sit on the line: a scanner will produce a component list for them, with
no dependency graph at all.

From `CLAUDE.md`:

> An SBOM omitting a significant portion of a product's dependencies is less useful than
> a documented gap.

A workflow will also refuse to appear when the product boundary itself was never confirmed
by a human. **A repository is not a product:** one repo may ship several, one product may
span several repos, and many ship nothing at all.

## How the generator is chosen

Not by preference. By one routing table:
[`tool_selection.md`](skills/get-workflow/references/tool_selection.md) — ecosystem → tool
→ exact invocation → gap to record.

Each route carries the score its tool earned against a 10-dimension rubric, every dimension
traced to a normative CRA or BSI TR-03183-2 requirement. **4 = CRA Annex I Part II(1)
satisfied**; **5 = the observed ceiling**, because no generator reaches full BSI conformance
unaided. Ecosystem-native generators are preferred over universal scanners: a native tool
resolves the build graph, and so emits the dependency relationships BSI requires. Syft and
cdxgen are for container images and for ecosystems with no viable native tool.

Two caveats worth knowing before you rely on a score: they are **derived from verified
structural behaviour, not measured runs**, and the underlying research is dated
**2026-08-05**. Four generators changed their default spec version in the preceding year.
Each report records which revision of the table it routed from, so you can tell which
generated workflows a later revision invalidates.

## Generated workflows are hardened

An audit of earlier prototypes found four High/High `template-injection` findings,
`artipacked` on every checkout, and a High/Medium `dangerous-triggers`. Every workflow this
produces therefore:

- Pins every action to a full commit SHA, resolved fresh at generation time — never copied
  from a reference file.
- Declares `permissions: contents: read` at top level.
- Sets `persist-credentials: false` on every checkout.
- Never puts `${{ }}` inside a `run:` block.
- Never uses `workflow_run`; it listens for the same event the release listens for.
- Asserts the SBOM with `jq -e` before uploading it: spec version is exactly 1.6,
  `components[]` and `dependencies[]` are non-empty, and no vulnerability data is present
  (BSI forbids it in an SBOM; VEX is a separate artifact).

CycloneDX 1.6 is pinned explicitly because it is a registry-compatibility floor, not a
tooling ceiling — several generators now default to 1.7, and two emit it with no selector
flag at all.

Then the skills run `zizmor` and `actionlint` over their own output and require zero High
findings before recording anything. Exactly two suppressions are permitted, both with
written justifications. If those tools are not installed, the report says the audit **did
not run** rather than claiming a pass.

## Working on the skills

`skills/` holds every skill; `.claude-plugin/plugin.json` is the plugin manifest, listed in
the repository's marketplace (`../.claude-plugin/marketplace.json`). To try changes
locally, add your clone as a marketplace (`/plugin marketplace add ./path/to/skills`) and
install `sbom` from it.

Validate `report.json` in the current directory against the schema and the cross-field rules
the schema cannot express:

```sh
python3 skills/validate-report.py                # must pass
python3 skills/validate-report.py --expect-fail  # report.json must fail, e.g. a deliberately broken copy
```

The script locates its own schema, so it runs from any directory, and always checks the
`report.json` in that directory. The skills invoke it as
`"<skill base directory>/../validate-report.py"`, which resolves in every install form —
plugin, `.claude/skills`, or a bare clone. `validate-report.py` and `schema.json` must
therefore stay one level above the skill directories.

A real project's `report.json` is run output, not a test input — it drifts, and it bakes
one project's accidents into the expectations. It is never committed; see `.gitignore`.
