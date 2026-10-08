---
name: get-coverage
description: >-
  Regenerate the Eclipse Foundation SBOM coverage data and dashboard: list every Regular and
  Incubating project's GitHub repos, collect repo facts, identify the shippable products
  (packages, plugins, container images) with parallel subagents, verify images against
  their registries, match products to SBOMs already in Dependency-Track, and rebuild and
  republish the adoption dashboard. Incremental: only projects whose repos changed are
  re-analysed. Use when asked to refresh, regenerate or rebuild github-products.json, SBOM
  coverage stats, or the SBOM adoption dashboard.
argument-hint: "[--full] — re-analyse every project instead of only changed ones"
---

# SBOM coverage

Run every command from a working directory of your choice (not inside the skill); it produces there:

| File | What it is |
|---|---|
| `github-repos.json`, `github-projects.json` | projects → GitHub orgs → repos, and project metadata |
| `github-repo-facts.json` | per-repo GitHub facts (manifests, releases, tags, CI, release triggers and publish steps of each workflow) |
| `github-products.json` | project → product → `{repos, image?, sbom_uploaded}`, **the main output** |
| `products-with-sboms.json` | products that have an SBOM in Dependency-Track |
| `sbom-adoption.html` | the dashboard, also published as an artifact |
| `dtrack-decisions.json` | your decisions for Dependency-Track names the rules cannot match (step 7); keep it |
| `.sbom-coverage/` | pipeline state: cache, batches, candidate, reports, `state.json` |

`S=<this skill's base directory>/scripts` below. Every script uses only the Python
standard library (Python 3.10+).

**Requirements**
- A GitHub token in `GH_TOKEN` or `GITHUB_TOKEN` with read access to public repositories
  (GraphQL needs one). `read:packages` additionally lets agents list ghcr.io packages.
- For SBOM status: a Dependency-Track API key with `VIEW_PORTFOLIO` (step 7).
- The sibling `list-products` skill from this plugin.

The rules for what counts as a product live in two places, both required: sections 1–2 of
the sibling `../list-products/SKILL.md` (the base rules, shared with onboarding) and
`references/product-rules.md` (what is specific to the coverage run). Never restate those
rules in prompts. Point agents at the files.

**Trial run.** To try the pipeline cheaply, start step 1 with `--limit 10`: only the first
ten projects go through every later step.

## Steps

Run them in order. Tell the user briefly what each step is doing, because full runs take a while.

### 1. List projects and repos
```sh
python3 $S/list-all-github-repos.py
```

### 2. Collect repo facts
```sh
python3 $S/collect-repo-facts.py
```
Three passes: GraphQL metadata and root manifests, the file tree per repo, and every
GitHub Actions workflow file. From the workflow files it records `release_trigger` (the
strongest signal of a publishing workflow: `release`, `tag`, `manual`, `push` or `null`) and
`release_workflows` (each workflow's triggers and publish steps). The dashboard's
"Easy Candidates for New Adopters" filters and ranking use these. To refresh only the workflow signals into an
existing facts file, add `--release-signals-only`.

### 3. Plan the analysis
```sh
python3 $S/prepare-batches.py          # add --full when the user asked for it
```
Read `.sbom-coverage/plan.json`. If it has no batches, every project is unchanged: skip to
step 5, then continue from step 6.

Before sending agents, tell the user how many projects and batches will be analysed and
roughly what it costs, then proceed. A batch takes an agent 1–5 minutes and about
50k–120k tokens; multiply by the number of batches in the plan.

### 4. Identify products: one subagent per batch
Use the prompt in `references/batch-agent-prompt.md`, filled in for each batch in the plan.
Send up to ~20 agents at a time in one message, in the background. As each finishes,
relay its uncertain calls to the user in one or two lines. Don't wait on them silently.
Once all are done, check that every batch's `products` file exists; re-send any that failed.

### 5. Merge, verify images, review
```sh
python3 $S/merge-products.py     # -> .sbom-coverage/candidate.json; exits 1 on errors
python3 $S/verify-images.py      # drops images not found in their registry
python3 $S/review-diff.py        # -> .sbom-coverage/diff.md
```
- If merge reports errors (a missing project, or a URL outside the project), fix the batch
  output by re-sending that batch's agent, then re-run the merge.
- **Stop here and show the user the result for approval:** the summary line, the notable
  changes from `diff.md`, the `NOT_FOUND`, `UNVERIFIABLE` and `NO_REF` counts from
  `.sbom-coverage/image-report.json`, and the uncertain calls the agents reported.
  Do not apply until the user approves.

### 6. Apply (after approval)
```sh
python3 $S/review-diff.py --apply   # github-products.json updated; previous kept as .previous.json
```

### 7. Dependency-Track status
The user exports Dependency-Track projects in their own terminal, so the API key stays out
of the conversation:
```sh
DT_URL=… DT_API_KEY=… python3 $S/dump-dtrack-projects.py
```
Ask whether `dt-projects.json` is current. When it is:
```sh
python3 $S/match-dtrack.py
```
The match is rule-based and deterministic: the same `dt-projects.json` and products give the
same result. Rules try, in order, the repo named by the project's references, its package
coordinates, then its name; a tie is never guessed (see the script's docstring).
`products-with-sboms.json` records which rule matched each product (`matched_by`).

Names the rules cannot settle are listed, with their purls, repos and candidate products, in
`.sbom-coverage/dtrack-unmatched.json`. For each one, propose the product (or that it is
not a product) with a one-line reason, show the proposals to the user and record only what
they confirm in `dtrack-decisions.json` in the working directory, then re-run:
```json
{
  "names":    {"<DT name>": {"project": "Eclipse …", "product": "…", "reason": "…"}},
  "prefixes": [{"prefix": "<DT name prefix>", "project": "Eclipse …", "product": "…", "reason": "…"}],
  "ignore":   {"<DT name>": "<why it is not a product>"}
}
```
Decisions win over the rules and are reused on every later run, so only new names ever need
a decision. Keep the file: it is the record of those judgement calls. Each
`decision_targets_missing` entry is a decision whose product no longer exists; fix it.

### 8. Dashboard
```sh
python3 $S/build-dashboard.py      # -> sbom-adoption.html
```
`sbom-adoption.html` is a self-contained page; open it locally or share the file. If the
Artifact tool is available, publish it: when `.sbom-coverage/state.json` has a
`dashboard_url`, pass it as `url` to update the existing page; otherwise publish a new one
with `icon: "chart"` and save the returned URL to `state.json` as
`{"dashboard_url": "…"}`. The page design lives in
`assets/dashboard.template.html`; change the design there, not in the generated file.

**Dashboard changes always go through this skill.** When asked to change the dashboard, even a
small wording tweak, edit `assets/dashboard.template.html` (layout, text, charts, client-side
filters) or `scripts/build-dashboard.py` (derived per-product fields: ecosystem, CI platform,
days since last push, release trigger, easy-candidate scoring). Then rebuild with
`build-dashboard.py` and publish that output. Never hand-edit `sbom-adoption.html` or the
published copy: the next refresh would silently undo it. Before publishing, load the page once
in a headless DOM (e.g. jsdom) to check that there are no script errors and the changed controls
work, because one broken function stops every chart on the page.

### 9. Report
Summarise: products total and change, coverage (products and projects with SBOMs),
anything left for review, and the dashboard link.

## Notes

- **Cache.** `.sbom-coverage/cache.json` keeps each project's products with a fingerprint of
  its facts and the rules. Editing `product-rules.md`, or sections 1–2 of list-products,
  invalidates every project.
- **Borderline kinds** (test suites, CI/base images, GitHub Actions, Ansible roles) are
  defined in `list-products`; Helm charts are not products. When the user decides one,
  record it in `list-products` so onboarding and coverage stay consistent.
