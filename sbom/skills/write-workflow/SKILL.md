---
name: write-workflow
description: >-
  Write the SBOM workflows recorded in ./report.json into local clones of the
  project's repositories. Finds each repository's clone under a checkouts folder by
  its git remotes, shows a dry run with the full diff of every file it would create
  or change, and writes only after the user agrees: new workflow files, and existing
  workflows patched exactly as get-workflow recorded and audited them. A
  deterministic script does the finding, diffing and writing; it never commits,
  branches or pushes, and never runs anything in a clone. Use after get-workflow, or
  through onboard --write.
argument-hint: "[checkouts-folder] — a clone, or a folder holding clones; asked for when omitted"
---

# Write the generated workflows into local clones

Takes the workflows `/get-workflow` recorded in `./report.json` and writes them, verbatim,
into local clones of the repositories they belong to. Each product's `pipeline.workflow`
says what goes where:

- **`kind: workflow`** (`generated`, `partial`): a new file at `install_as`.
- **`kind: patch`** (`patch-proposed`): the whole existing workflow at `install_as`, with
  the SBOM steps added. It is written only over the exact file get-workflow patched
  (`base_sha256`); a clone holding any other version of it is skipped.

Every step that finds, compares or writes runs in the script next to this skill:

```sh
# Substitute the quoted "Base directory for this skill" from your context; `python` if no `python3`.
python3 "<skill base directory>/scripts/write-workflow.py" <command>
```

**The script is the only thing that writes.** Never create, edit or delete a file in a
clone yourself, never change a workflow's content to make it fit, and never run anything
inside a clone — no git, no build, nothing. Never commit, branch, push or open a pull
request, and do not offer to. If a product is skipped, report the script's reason; the fix
belongs in `report.json` or in a re-run of `/get-workflow`, not here.

## 1. Check the report

`./report.json` must exist and validate:

```sh
python3 "<skill base directory>/../validate-report.py"
```

If it fails, stop and report the errors. If no product has a `pipeline` yet, say to run
`/get-workflow` first and stop.

## 2. Record the checkouts folder

The folder is the argument; it can be a single clone, or a folder holding clones one or two
levels down (`~/src/jkube`, `~/src/eclipse-jkube/jkube`). With no argument, ask the user
for it and wait. Never guess one.

Pass it on stdin, exactly as given, in a quoted heredoc so the shell changes nothing:

```sh
python3 "<skill base directory>/scripts/write-workflow.py" set-root <<'EOF'
<folder>
EOF
```

The script records it in `report.json` as `write.root`. It is never a command-line
argument.

## 3. Dry run

```sh
python3 "<skill base directory>/scripts/write-workflow.py" plan
```

It writes nothing. It checks each clone and prints, as Markdown:

- **Clones** — the clone each repository's workflows go into, and the branch it is on;
  repositories with no clone under the folder; repositories with several.
- **Plan** — every product and what would happen to its file: `create`, `replace`,
  `patch`, `unchanged`, or `skip` with the reason. A workflow whose content no longer
  matches what get-workflow audited is marked **edited since audit**.
- **Changes** — the unified diff of every file that would be created or changed, in full.
- **Choose a clone** or **Go-ahead** — the questions to ask next.

**Show the user the Clones, Plan and Changes sections verbatim, in full, in your reply.**
Command output does not reach the user by itself, and the diff is exactly what they are
agreeing to: never summarise it, shorten it, or leave a part out. The last section is for
you: it holds the questions to ask next.

## 4. Choose between clones

When the output has a **Choose a clone** section, ask each question it prints with your
question tool, exactly as printed. Record each answer with the number of the chosen clone,
then go back to step 3:

```sh
python3 "<skill base directory>/scripts/write-workflow.py" choose <org/repo> <n>
```

## 5. Ask for the go-ahead

The **Go-ahead** section prints one question, or two when existing files would be
replaced, as JSON. Ask the first with your question tool, exactly as printed. **Only the
answer "Write them" goes ahead**; anything else, including a free-text answer, means
nothing is written: stop, and say how to run this skill again. After a "Write them", ask the
second question if there is one; only "Replace them" adds `--replace`.

Ask both before writing anything. The plan is applied whole; the only choice within it
is whether existing files are replaced.

## 6. Write

```sh
python3 "<skill base directory>/scripts/write-workflow.py" apply <fingerprint> [--replace]
```

Pass the fingerprint the dry run printed. The script recomputes the plan and writes nothing
if anything changed since — exit code 2. Then go back to step 3 and ask again; an answer
given to an earlier plan never carries over.

Every outcome is recorded in `pipeline.workflow.written`. Validate:

```sh
python3 "<skill base directory>/../validate-report.py"
```

## 7. Report and stop

Show the script's result table verbatim. Then say:

- Nothing was committed or pushed. The maintainer reviews the change in each clone (for
  example `git -C <clone> status` and `git diff`), commits it and opens a pull request
  themselves.
- **Every patch edits a pipeline that ships software**: review it before committing.
- Every product skipped, and the script's reason.
- The upload in every workflow fails until upload permission is granted: the HelpDesk
  ticket's link from `project.upload_request.url`, which the maintainer files.

Then stop.
