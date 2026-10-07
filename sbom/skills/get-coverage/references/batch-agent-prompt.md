# Batch agent prompt

Send one subagent (`general-purpose`) per batch in `.sbom-coverage/plan.json`, all in a
single message so they run in parallel, with `run_in_background: true`. Substitute:
- `{{N}}`: the number of projects in the batch
- `{{FACTS}}`: the batch's absolute `facts` path
- `{{OUT}}`: the absolute `products` path
- `{{LIST_PRODUCTS}}`: the absolute path of the sibling `../list-products/SKILL.md`
- `{{RULES}}`: the absolute path of this skill's `references/product-rules.md`

---

Your task: decide which products each of {{N}} Eclipse Foundation projects ships, and write
the result to a JSON file. A "product" is a distinct deliverable that needs its own SBOM.

## Inputs (read these first)

1. Base rules: `{{LIST_PRODUCTS}}`, sections "1. Classify each repo: does it ship?" and
   "2. Group repos into logical products" only. Ignore the rest: do NOT write report.json,
   validate a schema, ask for confirmation, or record evidence, confidence or ecosystems.
2. Coverage-specific additions: `{{RULES}}`. They add to the base rules and never replace
   them. Follow both exactly.
3. Facts: `{{FACTS}}`, keyed by project display name. Each entry has `project_id`, `short_id`,
   `state`, `top_level_project`, `summary`, `github_orgs` and `repos` (per-repo GitHub
   facts: description, topics, languages, releases, tags, the build manifests in the tree,
   workflow names, Jenkinsfile, parsed root pom.xml, package.json, Cargo.toml and
   pyproject.toml). Read it with Python project by project, because it can be large.

Base the analysis on the facts. Look things up only when the facts can't settle a
question, using the sources and blind spots listed in the rules file.

## Output

Write ONLY your {{N}} projects to `{{OUT}}` with Python
`json.dump(..., indent=2, ensure_ascii=False)`. Don't touch any other file, because other
agents run in parallel. The format:

```json
{
  "Eclipse Example": {
    "example-core": {"repos": ["https://github.com/eclipse-example/core"]},
    "example-server-image": {"repos": ["https://github.com/eclipse-example/core"],
                             "image": "ghcr.io/eclipse-example/server"}
  },
  "Eclipse Docs Only Project": {}
}
```

- Use the project names exactly as they appear in the facts file, including any trailing
  spaces. Include every project; use `{}` for one that ships nothing.
- Use repo URLs exactly as they appear in the facts file, and check every URL against it
  before finishing.
- Every `-image` product has an `"image"` registry reference with no tag.

## Report back (brief)

1. Per project: the product count, plus one line of reasoning for any non-obvious call.
2. Uncertain calls a human should double-check, including any "undecided" kinds of
   product from the rules file that you included.
3. The number of extra lookups beyond the facts file, and what they were for.
