---
name: list-repositories
description: >-
  Resolve an Eclipse Foundation project from its name (e.g. "Eclipse CSI") or PMI
  project ID, and enumerate the complete list of its GitHub code repositories. Writes
  the project's identity and repo list to ./report.json. Use when starting SBOM
  onboarding for an Eclipse project, or when asked what repositories an Eclipse Foundation project has.
  First step of the SBOM onboarding chain, before list-products.
argument-hint: '"Eclipse <project name>", a short ID, or a dotted PMI project_id'
---

# List repositories

Given an Eclipse project name or ID, resolve the project and enumerate **every**
GitHub repository it owns or declares.

## 1. Resolve the project

Input given: `$1`. This may be a display name (`Eclipse CSI`, or just `CSI`), a
short ID (`csi`), or a dotted PMI `project_id` (`technology.csi`).

Try the fast path first — it only works for a dotted ID:

```sh
curl -sS "https://projects.eclipse.org/api/projects/$1"
```

If that returns a JSON **list with one element**, use it. If it returns
`{"message":"No content with this ID"}`, `$1` was a name or short ID — query
filters are silently ignored by this API, so page through and match client-side:

```sh
# repeat page=0,1,2,... ; pagesize caps at 100
curl -sS "https://projects.eclipse.org/api/projects?pagesize=100&page=0"
```

Match `$1` against, in order: `project_id` (exact), `short_project_id` (exact,
case-insensitive), then `name` (case-insensitive, with or without a leading
`"Eclipse "`). Stop paging once a match is found; report the resolved
`project_id` before continuing. If more than one project matches, list them and
ask which.

Record from the response: `project_id`, `short_project_id`, `name`, `state`. If
`state` is `Archived`, say so and ask whether to continue.

## 2. Enumerate repositories

Collect candidates from **both** PMI fields — they are not redundant. An org
listing catches repos nobody remembered to declare; the explicit list catches
repos that live outside the project's own org.

**From `github.org`** — page through the org's repositories:

```sh
# repeat page=1,2,3,... until a page returns fewer than per_page entries
gh api "orgs/<org>/repos?per_page=100&type=sources&page=1" \
  --jq '.[] | {name: .full_name, archived, fork, empty: (.size == 0)}'
```

Without `gh`, the same endpoint over `curl` needs an explicit token and paging
header:

```sh
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
     -H "X-GitHub-Api-Version: 2022-11-28" \
     "https://api.github.com/orgs/<org>/repos?per_page=100&type=sources&page=1"
```

Three things that will otherwise bite:

- **Page until short.** The API does not tell you the total. A single unpaged
  call silently truncates at 30 and a project quietly loses repositories.
- **`type=sources` excludes forks**, which is what you want: a fork ships
  nothing of the project's own. Record any fork you do encounter with a note
  rather than dropping it silently.
- **Unauthenticated requests are rate-limited to 60/hour** and will fail
  mid-enumeration on a large org. If `gh` is unavailable and no token is set,
  say so before starting rather than producing a partial list.

Record `archived` and whether the repo is empty. Neither is a reason to drop a
repo here — an archived repo can still have shipped a release that needs an SBOM
— but both are facts `/list-products` needs.

**From `github_repos[].url`** — take each URL as given and normalize to
`org/repo`.

Subtract anything matching `github.ignored_repos`. If `gitlab.project_group` is
set, note it and state plainly that GitLab is out of scope.

## 3. Write the report and confirm

Write or update `./report.json`'s `project` block:

```json
{
  "project": {
    "id": "technology.csi",
    "short_id": "csi",
    "name": "Eclipse CSI",
    "github_orgs": ["eclipse-csi"],
    "repos": [
      {"name": "eclipse-csi/csi"},
      {"name": "eclipse-csi/.github", "note": "archived 2024-11"}
    ]
  }
}
```

If `./report.json` already exists ask the user if it can be replaced.

Do not set `ships` on any repo here — that classification, and the product
entries, belong to `/list-products`. Use `note` for facts you observed (archived,
empty, a fork), never for a judgement about whether it ships.

Finish by validating:

```sh
# Substitute the quoted "Base directory for this skill" from your context; `python` if no `python3`.
python3 "<skill base directory>/../validate-report.py"
```

Present the resolved project and the full repo list as a table (repo, source:
`github.org` or `github_repos`, archived/fork notes). Note how many were dropped
via `ignored_repos`, and note the GitLab group if one exists.

Tell the user to run `/list-products` next.
