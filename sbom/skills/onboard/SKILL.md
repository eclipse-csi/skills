---
name: onboard
description: >-
  Run the whole SBOM onboarding chain for a project, end to end — enumerate its
  repositories, identify the products it ships, determine how each is released,
  and generate a hardened GitHub Actions workflow that produces a CycloneDX 1.6
  SBOM for every release. Stops at each confirmation point rather than deciding
  for the maintainer, and resumes from whatever ./report.json already contains.
  Use when someone wants to get a project onto automated SBOM generation and does
  not want to learn the individual steps.
argument-hint: '"Eclipse <project name>", a PMI project ID, or a list of org/repo'
---

# Onboard a project onto automated SBOM generation

Runs four skills in order, each also usable on its own, sharing state through
`./report.json` in the current directory:

```
/list-repositories  → the project's code repositories
/list-products      → the logical products it ships, and their ecosystems
/get-metadata   → how each releases, and where SBOM generation attaches
/get-workflow      → generator choice, and the generated workflow itself
```

**Everything the chain writes goes in the current directory** — `report.json`, and
nothing else. Run it from wherever you want that file to land; do not create a
working directory for it or write it anywhere but here. No workflow file is staged,
no project repository is modified, no branch is pushed, no pull request is opened.
Each generated workflow reaches the maintainer by being printed and recorded, and the
chain proposes nothing further for it.

## Resume, don't restart

Read `./report.json` first, if one exists, and start at the first stage whose output
is missing:

| Present | Start at |
|---|---|
| Nothing, or no file | `/list-repositories` |
| `project.repos` | `/list-products` |
| `products` with `sources` | `/get-metadata` |
| products with `release` | `/get-workflow` |
| products with `pipeline` | Report what is there; ask what to re-run |

Say which stage you are starting at and why. A maintainer who answered twenty
questions yesterday should not answer them again because a session ended. Re-running
an earlier stage over a fuller report is supported — each skill writes only its own
keys and never lowers `_meta.schema_version`.

## Honour every gate

Each skill stops and asks before handing on. **Those stops are the point, not
friction to smooth over** — product boundaries are proposed for human confirmation
and never resolved silently, because a workflow attached to an unconfirmed boundary
looks exactly like one that was reviewed.

Run one skill, present its findings and its questions, **wait for an answer**, then
run the next. Do not batch the questions to the end, and do not answer them on the
maintainer's behalf. Stop hardest at `/get-workflow`'s pre-emit confirmation, which
presents the full routing table before anything is generated.

If a decision is deferred, carry on with the products that are not blocked and report
the deferred one as an open item. One unresolved product must not stall the rest.

After each skill, validate and report the running state in one line — repos, products,
how many have release metadata, how many have workflows:

```sh
# Substitute the quoted "Base directory for this skill" from your context; `python` if no `python3`.
python3 "<skill base directory>/../validate-report.py"
```

## At the end

Summarise across the whole project, not per skill:

- **Products with a generated workflow** — the path each belongs at. `/get-workflow`
  already printed the YAML; point back to it rather than reprinting.
- **Products with partial coverage** — what their SBOM will not contain, concretely.
- **Products with no workflow** — and what would change that: a confirmation, a
  credential, a toolchain migration, or a tool that does not exist yet.
- **`project.coverage_gaps`** — shipping repositories not covered at all, and which
  skill to re-run for each.
- **No BSI enrichment** — out of scope for now, so every generated workflow tops out
  at what its generator emits. Uniform across products, stated once.
- **What was not verified** — anything an unavailable tool or a blocked network
  request left unchecked.

Then stop. **Report coverage honestly:** a project told it is onboarded when three of
its eight products silently produce nothing is worse off than one handed an accurate
list of five successes and three named gaps — it has stopped looking.
