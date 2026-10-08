# Product identification rules for coverage stats

The base rules are sections 1 ("Classify each repo: does it ship?") and 2 ("Group repos into
logical products") of the sibling `list-products` skill (`../list-products/SKILL.md`). That
covers shipping signals, snapshot-only publishing, grouping, container images (one product
per pushed image), package vs image, borderline kinds, Helm charts and naming. This file
adds only what is specific to the coverage run. Both files are part of the cache
fingerprint: **editing either re-analyses every project on the next run.**

## Scope

- Only Regular and Incubating Eclipse projects with GitHub repositories. Projects without
  GitHub repos are out of scope; don't raise them.
- Repos listed by `list-all-github-repos.py` are the full input. Archived, forked, private
  and dot-named config repos (`.github`, `.eclipsefdn`, …) are already excluded there.

## Jakarta EE spec projects

The spec-document repo ships nothing; the API jar is a product; a TCK released as its own
artifact or distribution (its own repo, or its own tag series in the API repo) is a
**separate** product (`<id>-tck`). An API jar with release tags ships even when Maven
Central can't be checked.

## Output differences from list-products

- Results go into the batch products file (see `batch-agent-prompt.md`), not `report.json`.
- An image product records its registry reference in an `"image"` field, e.g.
  `"ghcr.io/eclipse-foo/bar"` or `"docker.io/eclipse/bar"` (no tag), which
  `verify-images.py` checks. An image product without one is flagged for review.
- Borderline kinds are named in the batch report so a human sees them.

## Naming

- Keep the existing name of a product that hasn't changed; never rename for style.
- For single-product projects still use `<short_id>-<component>` (e.g. `birt-birt`);
  don't collapse to the bare short_id.
- Names must be unique across all projects.

## Evidence sources

Use the facts file first. Look up more only when the facts can't settle a question, and
keep lookups targeted:

- GitHub API (`gh api …` or `curl https://api.github.com/…` with the GitHub token) and
  raw files (`https://raw.githubusercontent.com/<owner>/<repo>/HEAD/<path>`).
- Registries, all queried anonymously:
  - Docker Hub: `https://hub.docker.com/v2/repositories/<ns>/<name>/`
  - ghcr.io: get a token from `https://ghcr.io/token?scope=repository:<owner>/<name>:pull`,
    then call `/v2/<owner>/<name>/tags/list`
  - quay.io: `https://quay.io/api/v1/repository/<ns>/<name>`
  - npm, PyPI and crates.io.
- Known blind spots:
  - Maven Central (search.maven.org, repo1.maven.org) may be unreachable from restricted
    networks; when it is, judge Maven publishing from the build configuration and tags.
  - Listing an organisation's GitHub packages needs a token with `read:packages`;
    without it, check individual images on ghcr.io anonymously instead.
  - Workflow run history is **not** reliable evidence that an image was never pushed:
    reusable workflows record runs under their caller, and images are often pushed from
    other repos or by hand. Registry evidence decides.
