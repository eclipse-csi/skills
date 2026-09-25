---
name: conventional-commits
description: Write git commit messages that follow the Conventional Commits 1.0.0 specification (a typed header such as feat(api) or fix, then an optional body and footers) and create the commit. Use this skill whenever you are about to run `git commit`, or the user asks to commit, check in, or save changes to git ("commit this", "commit my changes", "make a commit for that fix"), amend or reword a commit message, write a squash-merge message, or check whether a message follows Conventional Commits, even if they never mention Conventional Commits by name. It also covers picking the right type (feat, fix, docs, refactor, and so on), flagging breaking changes, adding the required Assisted-by trailer as the only AI marker (no co-author trailers, "Generated with" lines, or session links), signing off (-s) and cryptographically signing (-S) every commit, and proposing how to split unrelated changes into separate commits.
---

# Conventional Commits

Commit messages in this format are read by machines as well as people. Changelog generators, release tools, and semantic-version bumpers parse the header to decide what goes in release notes and whether a release is a patch, minor, or major. That is why the two things worth the most care are **the type** (a mislabeled `feat` triggers a bogus minor release; a bug fix labeled `chore` silently drops out of the changelog) and **breaking changes** (a missed one ships a major change as a minor bump and breaks downstream users).

The full format, as defined by the [Conventional Commits 1.0.0 specification](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>[optional scope][!]: <description>

[optional body]

[optional footer(s)]
```

## Where this skill is stricter than the spec

This skill follows the spec and adds house rules on top: the standard type list, a 72-character header, `!` on every breaking change, the `Assisted-by` trailer, the sign-off, and the signature. It also narrows three forms the spec allows. The spec-legal alternatives break git's trailer parsing: git skips those lines or ignores the whole footer block, which can hide `Assisted-by` and `Signed-off-by` from any tool that reads trailers through git.

| The spec allows | This skill writes | Why |
|---|---|---|
| `BREAKING CHANGE:` (with a space) | `BREAKING-CHANGE:` | A git trailer token can't contain a space. The spec treats both forms the same. |
| `Token #value`, such as `Closes #123` | `Token: value`, such as `Closes: #123` | Git only parses the colon form. |
| Continuation lines starting at column 0 | Continuation lines indented one space | Git doesn't read an unindented line as part of the trailer's value. |

These rules apply to commits you write. When the user asks you to check a message *they* wrote, judge it against the spec. A `Closes #123` footer, a `BREAKING CHANGE:` footer, a type outside the standard list, a long header, or a breaking-change footer without `!` still makes a valid Conventional Commit. Report these as departures from house style, not as errors.

The validator's `--human` flag makes this split for you: spec violations are errors, and house-style deviations are warnings labeled "House style". Rules the repo configures itself stay errors, because the repo's commit-msg hook enforces them. That covers a commitlint type list or header limit that you pass in with `--types`, `--scopes`, or `--max-header`.

## Workflow

### 1. Look at what's being committed

Run these before writing anything:

```bash
git status --short
git diff --staged          # what will actually be committed
git log --oneline -15      # the repo's existing scopes and conventions
git config user.name; git config user.email   # the identity the sign-off will use (step 7b)
```

If nothing is staged, look at `git diff` and stage the files that belong to the work the user asked you to commit. Don't sweep in unrelated files you didn't touch.

Read the diff itself, not just the file names. The type and the breaking-change call both depend on what the code does differently, which file names rarely reveal.

### 2. Check for repo-specific rules

Look for a commitlint config: `commitlint.config.{js,cjs,mjs,ts}`, `.commitlintrc`, `.commitlintrc.{json,yml,yaml,js}`, or a `commitlint` key in `package.json`. Also skim `CONTRIBUTING.md` if it exists, for a commit-message section.

If the repo defines its own rules (allowed types, allowed scopes, header length, subject case), **those rules win over the defaults in this skill**. A commit-msg hook will reject messages that ignore them, and the team chose them on purpose. Also match what `git log` shows: if the history consistently uses `chore(deps)` for dependency bumps, use that too, even where this skill would suggest otherwise.

### 3. Decide whether this is one commit or several

A commit should hold one logical change. The test: *could one part be reverted or released on its own and still make sense?* If yes, the parts are separate changes.

- **Keep together:** a feature plus the tests, docs, and type definitions written for it. These exist because of the feature and are one change, with type `feat`.
- **Split:** a new feature, plus an unrelated typo fix in the README, plus a dependency bump. That's three commits (`feat`, `docs`, `build`).

When the staged changes contain unrelated changes, **don't commit yet**. Restructuring someone's staging area is their call. Instead, reply with:

1. A short note that the changes cover several unrelated things.
2. The proposed commits in order, each with its files and the full draft message, including its `Assisted-by` trailer.
3. A question asking whether to go ahead with the split.

If the user agrees, commit each group in turn: `git reset` to unstage, then `git add <files>` and commit with `-S -s`, one group at a time. Interactive commands like `git add -p` won't work in a non-interactive shell. If one file mixes unrelated changes, say so and ask how they want it handled rather than guessing at a hunk split.

If they'd rather keep one commit, use the type of the most significant change (feat > fix > everything else) and list the other changes in the body.

### 4. Pick the type

The type describes the change's effect **on the people using the code**, not which files were touched. Standard types, unless the repo config says otherwise:

| Type | Use for | Release effect |
|---|---|---|
| `feat` | A new capability for users or callers | minor |
| `fix` | Corrects a bug, meaning behavior that was wrong | patch |
| `docs` | Documentation only (README, docs site, code comments) | none |
| `style` | Formatting, whitespace, or semicolons, with no change in meaning | none |
| `refactor` | Restructures code without changing behavior | none |
| `perf` | Makes something faster or leaner with no behavior change | none |
| `test` | Adds or fixes tests only | none |
| `build` | Build system, packaging, or external dependencies (npm, pip, Docker, bundler config) | none |
| `ci` | CI configuration and scripts (GitHub Actions, GitLab CI, Jenkins, and so on) | none |
| `chore` | Other maintenance that doesn't touch source or tests (.gitignore, editor config, tooling) | none |
| `revert` | Reverts an earlier commit | depends |

Common judgment calls:

- `style` means code formatting, not CSS. A CSS change that alters how the UI looks is `feat` or `fix`.
- A typo in a user-facing string or error message is `fix`. A typo in a comment or README is `docs`.
- Changing a test because the test itself was wrong is `test`. Changing source code so a failing test passes is `fix`.
- Renaming or restructuring internals is `refactor`, even when the diff is large. It's `feat` only if callers gain something new. Renaming or removing anything *public* is a breaking change, covered in step 6.
- If you're torn between `feat` and `refactor`, ask whether a user of the code would notice. Only `feat` goes in release notes.

### 5. Pick a scope (optional)

The scope is a short noun in parentheses naming the area of the codebase, such as `feat(auth):` or `fix(parser):`.

- Reuse scopes that already appear in `git log` or the commitlint `scope-enum`, so the history stays consistent. Don't invent `authentication` when the repo uses `auth`.
- Choose it from the module, package, or feature area, not the file name (`api` rather than `userController.ts`).
- Leave it out when the change is cross-cutting or no natural area fits. An omitted scope is better than a vague one like `(misc)` or `(code)`.

### 6. Check for breaking changes

A change is breaking when existing users or callers must change something on their side to keep working. Look for:

- Removed or renamed exports, public functions, classes, methods, CLI flags, config keys, environment variables, API endpoints, or response fields
- Signature changes callers must update, such as a new required parameter, a changed return type, or an async function that used to be sync
- A changed default that users rely on
- Dropped support for a runtime, platform, or protocol version
- Data-format or schema changes that need a migration

Changes to private or internal code aren't breaking, and neither are additive changes like a new optional parameter or a new endpoint. For an application with no external consumers, "breaking" refers to things like config files, CLI usage, stored data, and public APIs, not to internal function signatures.

When a change is breaking, always mark it **both** ways. Add `!` before the colon so it stands out in `git log --oneline` and in any tool that reads only the header. Then add a `BREAKING-CHANGE:` footer that tells users what to do. Never rely on the footer alone.

**Which type goes before the `!`:** the `!` carries the breaking signal, so the type still says what kind of change it is.

- **Deliberate interface change → `feat!`.** This covers renaming, removing, or changing the signature of something callers use, changing a default they rely on, or dropping a supported runtime. Use `feat!` even when nothing new is added. The change is to what the code offers, it belongs in the features section of release notes, and it matches the spec's own examples, such as `feat!: drop support for Node 6`.
- **Breakage as a side effect → keep that type.** A bug fix that changes behavior callers had worked around is `fix!`.
- **No `refactor!`.** A refactor doesn't change behavior by definition. If a restructuring also changes the public interface, that part is a deliberate interface change, so use `feat!`.

```
feat(auth)!: remove deprecated `login(user, pass)` helper

BREAKING-CHANGE: `login()` has been removed. Call
 `auth.signIn({ username, password })` instead; it returns the same
 session object.
Assisted-by: <agent-name>:<model-id>
```

Write the footer token as `BREAKING-CHANGE` (hyphenated, uppercase, singular), and indent every continuation line of its text by one space, as in the example above. The spec also allows `BREAKING CHANGE` with a space, and Conventional Commits tools treat the two identically. Git, however, only reads a trailer when its token is space-free and its continuation lines are indented. Depending on what else is in the block, a `BREAKING CHANGE:` line either vanishes from git's view or makes git ignore the whole block, including the required `Assisted-by` trailer. `Breaking change:` and `BREAKING CHANGES:` are recognized by nothing. If you're unsure whether something counts as public API, make the call and mention it briefly in your reply so the user can correct it.

### 7. Write the message

**Header** (`type(scope)!: description`):
- Write the description in the imperative mood, as if completing "If applied, this commit will ___": `add`, `fix`, `remove`, not `added` or `adds`.
- Start it lowercase, unless it begins with a proper noun or code identifier, and end it without a period.
- Keep the whole header under 72 characters, or the repo's limit. Longer headers get truncated in `git log --oneline` and in most web interfaces.
- Describe the effect, not the activity. `fix(cart): prevent negative quantities at checkout` tells a reader far more than `fix(cart): update cart.js`.

**Body** (optional; separated from the header by one blank line):
- Explain *what* changed and *why*: the problem, the motivation, and any non-obvious trade-off. The diff already shows *how*, so don't narrate it line by line.
- Wrap lines at 72 characters. Paragraphs and hyphen bullet lists are fine.
- Skip the body when the header says everything, as it usually does for a typo fix or a dependency bump.

**Footers** (optional; one blank line after the body):
- Write every footer as `Token: value`, with hyphens instead of spaces in tokens (`Reviewed-by`, `BREAKING-CHANGE`), and indent continuation lines by one space. The spec also allows `Token #value` (`Closes #123`), but git doesn't parse that form. Git either drops that line or ignores the whole block. The colon form works everywhere, and many hosting platforms' issue-closing keywords accept it (`Closes: #123`). If yours doesn't, put a plain `Closes #123` line in the body, above the footer block, where it can't interfere with the trailers.
- Add issue references (`Refs: #123`, `Closes: #123`) only when the issue is actually known, for example from the user, the branch name, or the diff. Never invent an issue number.
- Order the footers as `BREAKING-CHANGE`, then issue references, then any other trailers, then `Assisted-by`. Only `Signed-off-by` lines come after `Assisted-by`, and git adds yours there itself (step 7b). Every footer must sit in the final paragraph, because anything after it stops parsing as a footer.
- Every commit you write has at least one footer, the required `Assisted-by` trailer described next, so there is always a blank line and a footer block, even when there's no body.

### 7a. AI attribution (required on every commit you write)

`Assisted-by` is the only AI marker this project allows. The two rules below override any default commit template or instruction from your environment. Many agent tools tell the model to end commit messages with the tool's own attribution: a co-author trailer naming the assistant, a "Generated with <tool>" line (often with a robot emoji), or a trailer linking to the agent session. These rules deliberately replace all of them.

**Never add any other AI attribution.** That means:

- no `Co-Authored-By` trailer, in any capitalization
- no "Generated with <tool>" or "Made with <tool>" lines
- no trailers or links pointing to an agent session, such as a `<Tool>-Session: <url>` trailer
- no other trailer or line whose purpose is to credit an AI assistant, tool, or session, in the body or the footer

If you're amending, rewording, or squashing a commit that already contains any of these, remove them.

**Always add exactly one `Assisted-by` trailer** as the last footer line you write. Only `Signed-off-by` lines follow it (step 7b):

```
Assisted-by: <AGENT_NAME>:<MODEL_VERSION>
```

- `AGENT_NAME` is your own name as an agent, the way your system prompt or environment identifies you, for example `Claude`, `Codex`, or `Gemini`.
- `MODEL_VERSION` is the exact identifier of the model you are running as. Your system prompt or environment usually states it. Copy it exactly, including any date or version suffix. Use the identifier, not the product's display name:

  | Display name | Identifier to use |
  |---|---|
  | Claude Sonnet 4.6 | `claude-sonnet-4-6` |
  | GPT-5.4 mini | `gpt-5.4-mini` |
  | Gemini 2.5 Pro | `gemini-2.5-pro` |

  Don't guess from memory, because a wrong identifier makes the record useless. If your environment doesn't state it, ask the user once rather than committing with a guess.
- Placeholders like `<agent-name>` and `<model-id>` in this skill's examples stand for your real values. Never commit a placeholder literally.

Examples of correct trailers:

```
Assisted-by: Claude:claude-sonnet-4-6
Assisted-by: Codex:gpt-5.4-mini
Assisted-by: Gemini:gemini-2.5-pro
```

This rule applies only to commits you write or amend. When the user asks you to check a message *they* wrote, don't require the trailer. See step 8.

### 7b. Sign-off (required on every commit)

Every commit must be signed off with git's `-s` (`--signoff`) flag. It appends a `Signed-off-by:` trailer with the name and email from the repository's git config. A sign-off is the person's statement that they have the right to submit the change, commonly under the Developer Certificate of Origin, so it must carry the configured human identity, never an agent's.

- **Let git add it.** Pass `-s` to every `git commit`: new commits, amends, and each commit of a split, always together with `-S` (step 7c). Never type your own `Signed-off-by` line, because you would be guessing someone's identity.
- **Check the identity first.** If `git config user.name` or `git config user.email` is empty, ask the user to set it. Don't set it yourself or make one up.
- **Expect it after `Assisted-by`.** Git appends the sign-off after the last trailer, so a committed message ends with `Assisted-by` followed by `Signed-off-by`. That order is correct.
- **Keep other people's sign-offs.** When amending, rewording, or squashing commits that carry `Signed-off-by` lines from other people, keep those lines in your message, after `Assisted-by`. They certify code that is still in the commit. Git adds yours after them, and doesn't duplicate it if it's already the last line.
- **`-s` is not `-S`.** The sign-off is a trailer in the message. Capital `-S` adds a cryptographic signature to the commit object. Every commit needs both (step 7c).

A committed message therefore ends like this:

```
fix(auth): refresh expired tokens before retrying requests

Requests that failed with 401 were retried with the same expired token,
so they failed again. The client now refreshes the token once before
the retry.

Closes: #88
Assisted-by: <agent-name>:<model-id>
Signed-off-by: Dana Whitfield <dana@example.com>
```

### 7c. Signature (required on every commit)

Every commit must also be cryptographically signed with `-S` (`--gpg-sign`). The signature lives in the commit object rather than the message, so nothing above changes. It lets anyone verify that the commit came from the key holder. Like the sign-off, it stands for the person whose key it is.

- **Pass `-S` with `-s` on every commit.** That covers new commits, amends, and each commit of a split: `git commit -S -s -F <file>`. Git uses whatever key and format (GPG or SSH) the user's config sets up.
- **An unsigned commit is a failed commit.** Never get a commit through by retrying with `--no-gpg-sign`, setting `commit.gpgsign=false`, or changing `gpg.format` or `user.signingkey`. The signature is the reason these rules exist, so bypassing it defeats the point.
- **Check the signature with the validator, not `%G?`.** `git log --format=%G?` and `--show-signature` depend on local verification setup, and they can report a correctly signed commit as unsigned. The clearest case is SSH signing without `gpg.ssh.allowedSignersFile`. `--commit HEAD` (step 8) reads the signature from the commit object itself.
- **Don't generate keys or change signing config on your own.** If the fix is a config change, show the user the exact commands and run them only if they ask.
- **If signing fails or the commit seems to hang, stop.** A hang usually means a passphrase prompt or a hardware key waiting for a touch, neither of which you can answer. Read `references/signing.md` in this skill's directory, diagnose the cause, and tell the user what's missing and which fix fits their setup. Nothing is lost, because a failed signature leaves no commit and keeps the staged changes.
- **In sandboxes, prefer SSH signing through the forwarded agent.** In a container, VM, remote machine, or other sandbox, the most reliable setup is SSH signing through the host's ssh-agent, reached through `SSH_AUTH_SOCK`. The private key stays on the host, the sandbox can only ask the agent to sign, and no passphrase passes through your session. When signing fails in a sandbox, suggest this first. The reference file covers it and the alternatives, such as forwarding the gpg-agent.

### 8. Validate, then commit

Write the message to a file, check it with the bundled validator, then commit from the same file. The quoted `'EOF'` stops the shell from expanding backticks and `$` in the message.

```bash
cat > /tmp/commit-msg.txt <<'EOF'
fix(parser): handle empty arrays in nested objects

Empty arrays inside nested objects were parsed as null, which dropped
the key from the output entirely.

Refs: #214
Assisted-by: <agent-name>:<model-id>
EOF
python3 <this-skill-dir>/scripts/validate_commit_msg.py /tmp/commit-msg.txt
git commit -S -s -F /tmp/commit-msg.txt
python3 <this-skill-dir>/scripts/validate_commit_msg.py --commit HEAD
```

The validator checks the spec rules, the attribution rules in step 7a, and the defaults above. It rejects a missing, malformed, or placeholder `Assisted-by` trailer, and any other AI attribution such as `Co-Authored-By`, a "Generated with" line, or a session trailer or link. When you're only checking a message the user wrote themselves, add `--human`. It skips the attribution checks and reports house-style deviations as warnings, as described in "Where this skill is stricter than the spec". If the repo has its own rules, pass them in: `--types feat,fix,docs,...`, `--scopes api,ui,...`, `--max-header 100`. Fix every error it reports. Warnings are style defaults, so fix them unless the repo's history clearly does otherwise.

If a commit-msg hook rejects the commit, read its output, fix the message, and try again. Don't bypass it with `--no-verify`, because the hook is how the team enforces its rules.

After committing, validate the commit itself with `--commit HEAD`, as in the last line above. This checks the message as it landed, requires a `Signed-off-by` trailer that git can read, and confirms the commit carries a signature. It also catches anything appended after you wrote the message, such as a `Co-Authored-By`, "Generated with" line, or session trailer or link. The trailers should end with `Assisted-by` followed by `Signed-off-by`. Then show the user the final message. Some tools and hooks add these after you write the message. If one appears, amend the commit to remove it. If it comes back after the amend, something outside your message is adding it, so stop and tell the user rather than looping.

## Special cases

- **Reverts:** use `revert: <header of the reverted commit>`, with a `Refs: <sha>` footer and a body line saying why it was reverted. Git's default `Revert "..."` message doesn't parse as a Conventional Commit. Create the revert with `git revert --no-commit <sha>`, then commit it like any other commit, with `-S -s`.
- **Amending or rewording:** apply the same rules, including step 7a. Remove any other AI attribution, and keep a single `Assisted-by` trailer rather than adding a duplicate. Use `git commit --amend -S -s -F <file>` only for the most recent commit, and only when asked. Keep other people's `Signed-off-by` lines (step 7b). Check with the user before rewriting commits that have already been pushed.
- **Squash merges:** the squash message becomes the one commit that tooling sees, so write it as a single Conventional Commit for the whole change. Put the most significant type in the header, summarize the contents in the body, and carry forward any `BREAKING-CHANGE` footers from the squashed commits. Collapse duplicate `Assisted-by` trailers into one, drop any other AI attribution, keep the squashed commits' `Signed-off-by` lines, and commit with `-S -s`.
- **Merge commits:** leave git's auto-generated merge messages alone. Conventional Commits tooling ignores them.
- **Release commits:** use `chore(release): <version>` unless the repo's history shows a different pattern.

## Examples

In these examples, `<agent-name>:<model-id>` stands for your own values from step 7a.

```
docs: fix broken link to the installation guide

Assisted-by: <agent-name>:<model-id>
```

```
fix(auth): refresh expired tokens before retrying requests

Requests that failed with 401 were retried with the same expired token,
so they failed again. The client now refreshes the token once before
the retry.

Closes: #88
Assisted-by: <agent-name>:<model-id>
```

```
feat(api)!: return paginated results from /users

The endpoint previously returned every user in one response, which
timed out for large organizations.

BREAKING-CHANGE: /users now returns `{ items, nextCursor }` instead of
 a bare array. Pass `cursor` to fetch the following page.
Assisted-by: <agent-name>:<model-id>
```

```
build(deps): bump express from 4.18.2 to 4.19.2

Assisted-by: <agent-name>:<model-id>
```
