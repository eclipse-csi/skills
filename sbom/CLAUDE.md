# sbom

Agent plugin that gets an open source project onto automated SBOM generation (every
release of every product it ships produces a CycloneDX 1.6 SBOM) and measures SBOM
coverage across all Eclipse projects. Driver: the EU Cyber
Resilience Act, with BSI TR-03183-2 v2.1.0 as the field-level requirement.

**[`README.md`](README.md) is the human-facing document** — what the chain does, what it
deliberately will not do, and how generator choice is made. Read it first; this file
carries only what is needed to *work on* the repo.

## Layout

- `skills/` holds every skill. `.claude-plugin/plugin.json` is the plugin manifest; the
  repository-root marketplace (`../.claude-plugin/marketplace.json`) lists it.
- Four chained onboarding skills — `list-repositories` → `list-products` →
  `get-metadata` → `get-workflow` — plus `onboard`, which runs them in order.
  `list-repositories` is the only Eclipse-specific one of these; every other skill works
  from whatever repo or product list it is handed.
- `get-coverage` runs product identification at scale over every Eclipse project on
  GitHub and builds the adoption dashboard. It does not use `report.json`; it writes its
  own files into the current directory (see its SKILL.md).
- **Product rules have one home: sections 1–2 of `list-products`.** `get-coverage` reads
  them from the sibling skill and adds only coverage-specific rules in
  `skills/get-coverage/references/product-rules.md`. A rule that applies to onboarding
  too belongs in `list-products`, never in both.
- Routing lives in
  [`skills/get-workflow/references/tool_selection.md`](skills/get-workflow/references/tool_selection.md),
  hardening in
  [`skills/get-workflow/references/hardening.md`](skills/get-workflow/references/hardening.md).
  Each is the **single source** for its subject — when a SKILL.md restates one of them,
  delete the restatement rather than keeping both in step.

## report.json

Every skill's output conforms to [`skills/schema.json`](skills/schema.json) and is written
to `report.json` in the current directory, enriched stage by stage. All five onboarding
skills validate before finishing:

```sh
python3 "<skill base directory>/../validate-report.py"
```

**Layout invariant:** `validate-report.py` and `schema.json` sit one level *above* the
skill directories, so `../validate-report.py` resolves from any skill's own base
directory — which Claude Code states at the top of every skill invocation. That is the
only locator that works in every install form (plugin, `.claude/skills`, a bare clone),
because `CLAUDE_PLUGIN_ROOT` is set for MCP servers and hooks but **not** for the Bash
tool. Moving either file into a skill directory, or the skills up a level, breaks all
five call sites at once.

The script finds `schema.json` relative to itself, so the cwd never matters. Without
`jsonschema` installed it reports `PARTIAL` and exits non-zero — the cross-field rules
still run, but a skipped structural check is never reported as a pass.

Objects are closed, so an unvalidated write loses a misspelled field silently. The
validator also enforces the cross-field rules the schema cannot express
(`immutable_input: none` ⇒ `extend-existing`, and similar).

Facts are recorded at the scope at which they vary: `sources[].build` per build root,
`release` per product, `generator` per (source, tool) pair. There is **one** `evidence`
and **one** `confidence` per product — do not add a second pair under `release` or
`pipeline`. `_meta.schema_version` is `1` and is never lowered.

A real project's run output is never a test input and is never committed — see
`.gitignore`.

## Non-negotiables

These are the rules the whole repo exists to enforce. Everything else is negotiable.

- **CycloneDX 1.6, JSON, pinned explicitly.** 1.6 is a registry-compatibility floor, not a
  tooling ceiling: several generators now default to 1.7, and Trivy and osv-scalibr emit
  1.7 with no selector flag at all. Every generated workflow pins the spec version *and*
  asserts `jq -e '.specVersion == "1.6"'`. This has drifted before and will drift again.
- **No vulnerability data in an SBOM** (BSI TR-03183-2). VEX is a separate artifact.
- **Ecosystem-native generators over universal scanners** — native tools resolve the build
  graph and emit the dependency relationships BSI requires. Syft and cdxgen are for
  container images and for ecosystems with no viable native generator.
- **A repository is not a product.** One repo may ship several, one product may span
  several, many ship nothing. Product identification is proposed for human confirmation,
  never resolved silently.
- **Coverage gaps are reported, not papered over.** An SBOM omitting a significant portion
  of a product's dependencies is less useful than a documented gap.
- **The onboarding chain writes exactly one file, `report.json`.** No workflow is staged
  on disk, no project repository is modified, and no skill runs `git commit`, `git push`
  or `gh pr create`.
- **`get-coverage` writes only into the current working directory:** `github-repos.json`,
  `github-projects.json`, `github-repo-facts.json`, `github-products.json` (previous version
  kept as `github-products.previous.json`), `products-with-sboms.json`, `sbom-adoption.html`
  and its pipeline state in `.sbom-coverage/`. It reads `dt-projects.json`, which the user
  exports, and `dtrack-decisions.json`, which holds the user's matching decisions. It never
  modifies a project repository and never runs `git commit`, `git push` or `gh pr create`.
  The dashboard is published as a private artifact when the Artifact tool is available.
- **Verify tool behaviour and versions against primary sources**, not from memory.
  Published guidance in this area is frequently out of date.

## Out of scope, deliberately

Record the affected products and state the exclusion; never partially implement one.

- **Upload to an SBOM registry** — output stops at a validated SBOM published as a
  workflow artifact with a `TODO(upload)` marker.
- **Jenkins and GitLab CI** — the assumed upload step needs a GitHub Actions OIDC token.
- **BSI enrichment** — the post-processing step supplying BSI fields 3, 6, 9, 10, 11 and
  12 read a sidecar that is no longer produced, so generated workflows top out at what the
  generator itself emits.
- **Signing and attestation.**

## get-coverage dashboard

The dashboard is generated: design in `skills/get-coverage/assets/dashboard.template.html`,
derived per-product fields in `skills/get-coverage/scripts/build-dashboard.py`. Change
those, rebuild, and load the page once in a headless DOM to check for script errors
before publishing — one broken function stops every chart. Never hand-edit a generated
`sbom-adoption.html`.
