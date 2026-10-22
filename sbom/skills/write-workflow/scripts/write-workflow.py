#!/usr/bin/env python3
"""Write the workflows recorded in ./report.json into local clones of their repositories.

Every product whose get-workflow status is generated, partial or patch-proposed carries
its workflow verbatim in pipeline.workflow.content: a new file (kind workflow), or the
whole existing workflow with the SBOM steps added (kind patch). A product whose SBOM
workflow is started from its release workflow also carries pipeline.release_patch: that
release workflow with the one added job, always a patch. This script writes exactly that
content, at install_as, into the clone of pipeline.host_repo found under a checkouts
folder. A patch is written only over the exact file get-workflow patched (base_sha256).

Files that belong together are written together or not at all: a product's workflow and
its release patch, and the products that share one release patch, which is written once.

    write-workflow.py set-root               read the checkouts folder from stdin, record it
    write-workflow.py [plan]                 check the clones, show what would change
    write-workflow.py choose ORG/REPO N      use the Nth listed clone where several match
    write-workflow.py apply FINGERPRINT [--replace]
                                             write exactly the plan that printed FINGERPRINT

The checkouts folder is kept in report.json (write.root), so no path is passed on the
command line. Clones are found at the folder itself and one and two levels below it, by
the GitHub remotes in their .git/config. Nothing is ever run: no git, nothing inside a
clone, no commit, branch or push. The dry run writes nothing. A plan is applied whole;
replacing a file that exists with other content also needs --replace. Each file's
outcome is recorded in its own written field (pipeline.workflow.written,
pipeline.release_patch.written). Standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

REPORT = Path("report.json")
WRITABLE = ("generated", "partial", "patch-proposed")
INSTALL_AS = re.compile(r"\.github/workflows/[A-Za-z0-9._-]+\.ya?ml")
FINGERPRINT = re.compile(r"[0-9a-f]{64}")
GITHUB_REMOTE = re.compile(
    r"(?:(?:https?|git|ssh|git\+ssh)://(?:[^@/]+@)?(?:www\.)?github\.com(?::\d+)?/"
    r"|(?:[^@/:]+@)?github\.com:)"
    r"([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+?)(?:\.git)?/?",
    re.IGNORECASE)
SECTION = re.compile(r'\[\s*([A-Za-z0-9.-]+)(\s+"[^"]*")?\s*\]')
SCAN_DEPTH = 2
SLOTS = ("workflow", "release_patch")
DONE = {"create": "created", "replace": "replaced", "patch": "patched"}
WRITE_LABEL, REPLACE_LABEL = "Write them", "Replace them"


def sha256(data: bytes) -> str:
    """Hex sha256 of data."""
    return hashlib.sha256(data).hexdigest()


def load_report() -> dict:
    """./report.json, or exit when there is none."""
    if not REPORT.exists():
        sys.exit(f"error: {REPORT} not found in the current directory")
    with REPORT.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_report(report: dict) -> None:
    """Write ./report.json back, formatted the way every skill writes it."""
    with REPORT.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# --- Clones ---------------------------------------------------------------------------


def git_dir(path: Path) -> Path | None:
    """The git directory of a clone at path, or None when path is not a clone."""
    dotgit = path / ".git"
    if dotgit.is_symlink():
        return None
    if dotgit.is_dir():
        return dotgit
    if not dotgit.is_file():
        return None
    # Worktrees and submodules have a .git file pointing at their git directory.
    try:
        first = dotgit.read_text(encoding="utf-8").partition("\n")[0]
    except (OSError, UnicodeDecodeError):
        return None
    if not first.startswith("gitdir:"):
        return None
    gitdir = Path(first[len("gitdir:"):].strip())
    gitdir = gitdir if gitdir.is_absolute() else path / gitdir
    return gitdir if gitdir.is_dir() else None


def config_file(gitdir: Path) -> Path:
    """The config file holding the remotes; a worktree shares its main clone's."""
    commondir = gitdir / "commondir"
    if commondir.is_file():
        common = Path(commondir.read_text(encoding="utf-8").strip())
        return (common if common.is_absolute() else gitdir / common) / "config"
    return gitdir / "config"


def config_value(value: str) -> str:
    """A git config value without its quotes and trailing comment."""
    out, quoted = [], False
    for ch in value.strip():
        if ch == '"':
            quoted = not quoted
        elif ch in "#;" and not quoted:
            break
        else:
            out.append(ch)
    return "".join(out).strip()


def github_repo(url: str) -> str | None:
    """org/repo, lower case, of a GitHub remote URL; None for anything else."""
    match = GITHUB_REMOTE.fullmatch(url.strip())
    return f"{match.group(1)}/{match.group(2)}".lower() if match else None


def remote_repos(gitdir: Path) -> set:
    """org/repo of every GitHub remote in a clone's git config, read as text."""
    try:
        text = config_file(gitdir).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    repos, in_remote = set(), False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("["):
            match = SECTION.match(line)
            in_remote = bool(match and match.group(1).lower() == "remote" and match.group(2))
            continue
        key, sep, value = line.partition("=")
        repo = github_repo(config_value(value)) if in_remote and sep else None
        if repo and key.strip().lower() in ("url", "pushurl"):
            repos.add(repo)
    return repos


def branch(gitdir: Path) -> str:
    """The checked-out branch, for information only."""
    try:
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    return f"detached at {head[:12]}"


def find_clones(root: Path) -> list:
    """Every clone at root and one and two levels below it. Symlinks are not followed,
    so every clone found lies inside root."""
    clones = []

    def visit(path: Path, depth: int) -> None:
        gitdir = git_dir(path)
        if gitdir:
            clones.append({"path": path, "repos": remote_repos(gitdir), "branch": branch(gitdir)})
            return
        if depth == SCAN_DEPTH:
            return
        try:
            children = sorted(p for p in path.iterdir() if not p.is_symlink() and p.is_dir())
        except OSError:
            return
        for child in children:
            visit(child, depth + 1)

    visit(root, 0)
    return clones


def checkouts_root(report: dict) -> Path:
    """The recorded checkouts folder; exits when there is none or it is unusable."""
    recorded = (report.get("write") or {}).get("root")
    if not recorded:
        sys.exit("error: no checkouts folder is recorded in report.json: run set-root first")
    root = Path(recorded)
    if not root.is_absolute() or not root.is_dir() or root.resolve() != root:
        sys.exit(f"error: the checkouts folder {recorded} is not an existing folder: "
                 "run set-root again")
    return root


def resolve_repo(repo: str, clones: list, chosen: dict) -> dict:
    """The clone to write into for repo (None when there is none, or several and no
    choice yet), and every clone that matches."""
    matches = [c for c in clones if repo.lower() in c["repos"]]
    if len(matches) == 1:
        return {"clone": matches[0], "matches": matches}
    pick = next((p for r, p in chosen.items() if r.lower() == repo.lower()), None)
    clone = next((c for c in matches if str(c["path"]) == pick), None)
    return {"clone": clone, "matches": matches}


# --- The plan -------------------------------------------------------------------------


def locate(checkout: Path, install_as: str) -> tuple:
    """(target, None) for a safe place to write install_as in checkout, else (None, why)."""
    if not INSTALL_AS.fullmatch(install_as):
        return None, f"install_as {install_as!r} is not a file directly in .github/workflows/"
    github = checkout / ".github"
    workflows = github / "workflows"
    target = workflows / install_as.rsplit("/", 1)[1]
    for path in (github, workflows, target):
        if path.is_symlink():
            return None, f"{path.relative_to(checkout)} in the clone is a symlink"
    for path in (github, workflows):
        if path.exists() and not path.is_dir():
            return None, f"{path.relative_to(checkout)} in the clone is not a folder"
    if target.exists() and not target.is_file():
        return None, f"{install_as} in the clone is not a regular file"
    return target, None


def patch_action(workflow: dict, before: str | None) -> tuple:
    """(action, reason) for a patch: written only over the exact file get-workflow patched."""
    base = workflow.get("base_sha256")
    if not base:
        return "skip", "no base_sha256 is recorded for this patch: re-run /get-workflow"
    if before is None:
        return "skip", "the workflow to patch is not in the clone"
    if before == base:
        return "patch", None
    ref = (workflow.get("base_ref") or "?")[:12]
    return "skip", (f"the workflow in the clone differs from the version get-workflow "
                    f"patched ({ref}): update the clone, or re-run /get-metadata and "
                    f"/get-workflow")


def classify(entry: dict, workflow: dict) -> None:
    """Fill in what writing this workflow would do to the file in the clone."""
    content = workflow["content"].encode("utf-8")
    entry["content"], entry["after"] = content, sha256(content)
    entry["edited"] = workflow.get("sha256") != entry["after"]
    try:
        current = entry["target"].read_bytes() if entry["target"].exists() else None
    except OSError as exc:
        entry["reason"] = f"cannot read {entry['file']} in the clone: {exc.strerror}"
        return
    entry["current"] = current
    entry["before"] = sha256(current) if current is not None else None
    if current == content:
        entry["action"] = "unchanged"
    elif workflow.get("kind") == "patch":
        entry["action"], entry["reason"] = patch_action(workflow, entry["before"])
    else:
        entry["action"] = "create" if current is None else "replace"


def plan_entry(name: str, pipeline: dict, repos: dict, slot: str = "workflow") -> dict:
    """What would happen to one of a product's files: its workflow, or its release patch."""
    workflow, repo = pipeline.get(slot) or {}, pipeline.get("host_repo")
    entry = {"product": name, "slot": slot, "repo": repo, "file": workflow.get("install_as"),
             "checkout": None, "target": None, "current": None, "content": None,
             "before": None, "after": None, "edited": False, "ambiguous": False,
             "action": "skip", "reason": None, "record": True, "leader": None}
    if pipeline.get("status") not in WRITABLE or not workflow:
        entry["reason"] = f"status {pipeline.get('status')}: no workflow to write"
        entry["record"] = False
        return entry
    if not repo:
        entry["reason"] = "pipeline.host_repo is missing"
        return entry
    clone = repos[repo]["clone"]
    if clone is None:
        entry["ambiguous"] = bool(repos[repo]["matches"])
        entry["reason"] = ("several clones match: choose one" if entry["ambiguous"]
                           else "no clone of it under the checkouts folder")
        return entry
    entry["checkout"] = clone["path"]
    entry["target"], entry["reason"] = locate(clone["path"], entry["file"] or "")
    if entry["target"] is not None:
        classify(entry, workflow)
    return entry


def skip_shared_targets(entries: list) -> None:
    """Several entries writing one file: written once when they all carry the same content
    (one release patch shared by the products it starts), otherwise none of them, since
    each would overwrite the other."""
    by_target = {}
    for entry in entries:
        if entry["target"] is not None:
            by_target.setdefault(entry["target"], []).append(entry)
    for shared in (group for group in by_target.values() if len(group) > 1):
        if len({entry["content"] for entry in shared}) == 1:
            for follower in shared[1:]:
                follower["leader"] = shared[0]
            continue
        names = ", ".join(entry["product"] for entry in shared)
        for entry in shared:
            entry["action"] = "skip"
            entry["reason"] = (f"{names} all write this file with different content: re-run "
                               "/get-workflow so that one file covers them")


def write_together(entries: list) -> None:
    """Skip every file of a group when one of them is skipped. A group is a product's
    workflow and release patch, joined with the products sharing that release patch: an
    SBOM workflow nothing starts, or a start job for a workflow that is not there, is a
    half-installed change."""
    group = {entry["product"]: entry["product"] for entry in entries}

    def root(product: str) -> str:
        while group[product] != product:
            product = group[product]
        return product

    for entry in entries:
        if entry["leader"] is not None:
            group[root(entry["product"])] = root(entry["leader"]["product"])
    skipped = {}
    for entry in entries:
        if entry["record"] and entry["action"] == "skip":
            skipped.setdefault(root(entry["product"]), f"{entry['product']}: {entry['file']}")
    for entry in entries:
        why = skipped.get(root(entry["product"]))
        if entry["record"] and why and entry["action"] != "skip":
            entry["action"] = "skip"
            entry["reason"] = f"written together with {why}, which is skipped"


def build_plan(report: dict) -> dict:
    """Everything the dry run shows and apply does, computed from the current state."""
    root = checkouts_root(report)
    clones = find_clones(root)
    chosen = (report.get("write") or {}).get("checkouts") or {}
    pipelines = [(name, (report["products"][name].get("pipeline") or {}))
                 for name in sorted(report.get("products") or {})]
    pipelines = [(name, pipeline) for name, pipeline in pipelines if pipeline]
    repos = {pipeline["host_repo"]: resolve_repo(pipeline["host_repo"], clones, chosen)
             for _, pipeline in pipelines
             if pipeline.get("status") in WRITABLE and pipeline.get("host_repo")}
    entries = [plan_entry(name, pipeline, repos, slot) for name, pipeline in pipelines
               for slot in SLOTS if slot == "workflow" or pipeline.get(slot)]
    skip_shared_targets(entries)
    write_together(entries)
    return {"root": root, "repos": repos, "entries": entries}


def fingerprint(plan: dict) -> str:
    """Identifies a plan: the clones, the files, the actions, and the bytes before and after."""
    rows = [[e["product"], e["slot"], e["repo"], str(e["checkout"]) if e["checkout"] else None,
             e["file"], e["action"], e["before"], e["after"], e["leader"] is not None]
            for e in plan["entries"]]
    return sha256(json.dumps([str(plan["root"]), rows]).encode("utf-8"))


# --- Output ---------------------------------------------------------------------------


def cell(text: str) -> str:
    """Text safe inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def shown(root: Path, path: Path) -> str:
    """A clone's path relative to the checkouts folder."""
    return "the folder itself" if path == root else f"`{path.relative_to(root)}`"


def lines(text: str) -> list:
    """text split after each newline, every line keeping its own ending."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def diff(entry: dict) -> str:
    """The unified diff of the file in the clone against what would be written."""
    old = [] if entry["current"] is None else lines(entry["current"].decode("utf-8", "replace"))
    new = lines(entry["content"].decode("utf-8"))
    old_label = "/dev/null" if entry["current"] is None else f"a/{entry['file']}"
    out = difflib.unified_diff(old, new, old_label, f"b/{entry['file']}")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                   for line in out)


def fenced(text: str, lang: str) -> str:
    """text in a Markdown code fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`{3,}", text)), default=2)
    fence = "`" * (longest + 1)
    return f"{fence}{lang}\n{text}{fence}\n"


def action_text(entry: dict) -> str:
    """The Action column of the plan table."""
    text = entry["action"] if entry["action"] != "skip" else f"skip: {entry['reason']}"
    if entry["leader"] is not None and entry["action"] != "skip":
        text += f" (the same file as for {entry['leader']['product']}, written once)"
    if entry["edited"] and entry["action"] != "skip":
        text += " (**edited since audit**)"
    return cell(text)


def print_clones(plan: dict) -> None:
    """Which clone each repository's workflows go into."""
    print("### Clones\n")
    if not plan["repos"]:
        print("No product has a workflow to write.\n")
        return
    print("| Repository | Clone | Branch |\n|---|---|---|")
    for repo, found in sorted(plan["repos"].items()):
        clone, matches = found["clone"], found["matches"]
        if clone:
            where = shown(plan["root"], clone["path"])
            print(f"| `{repo}` | {where} | `{cell(clone['branch'])}` |")
        elif matches:
            print(f"| `{repo}` | {len(matches)} clones match: choose one | |")
        else:
            print(f"| `{repo}` | not found under the checkouts folder | |")
    print()


def print_plan(plan: dict) -> None:
    """The plan table, any audit warning, and the diff of every change."""
    print("### Plan\n\n| Product | Repository | File | Action |\n|---|---|---|---|")
    for e in plan["entries"]:
        print(f"| `{e['product']}` | `{e['repo'] or '-'}` | `{e['file'] or '-'}` "
              f"| {action_text(e)} |")
    print()
    edited = [e["product"] for e in plan["entries"] if e["edited"] and e["action"] != "skip"]
    if edited:
        print("**Edited since audit:** the content recorded for " + ", ".join(edited) +
              " is not what get-workflow audited (its sha256 differs or is missing). "
              "Re-run /get-workflow to have it audited again.\n")
    changes = [e for e in plan["entries"] if e["action"] in DONE and e["leader"] is None]
    if changes:
        print("### Changes\n")
    for e in changes:
        print(f"#### `{e['repo']}`: `{e['file']}` ({e['action']})\n")
        print(fenced(diff(e), "diff"))


def ask(question: str, header: str, options: list) -> str:
    """A question in the shape of the agent's question tool, as JSON."""
    return fenced(json.dumps({"question": question, "header": header, "multiSelect": False,
                              "options": [{"label": label, "description": description}
                                          for label, description in options]},
                             indent=2, ensure_ascii=False) + "\n", "json")


def print_choices(plan: dict) -> None:
    """One question per repository with several matching clones."""
    print("### Choose a clone\n")
    for repo, found in sorted(plan["repos"].items()):
        if found["clone"] or len(found["matches"]) <= 1:
            continue
        paths = [c["path"] for c in found["matches"]]
        print(f"Several clones match `{repo}`:\n")
        for n, match in enumerate(found["matches"], 1):
            print(f"{n}. {shown(plan['root'], match['path'])}, on `{cell(match['branch'])}`")
        print(f"\nAsk this, then run `choose {repo} <n>` with the number of the chosen clone:\n")
        print(ask(f"Which clone of {repo} should its workflows be written into?", "Clone",
                  [(f"{n}. {path.relative_to(plan['root']) if path != plan['root'] else '.'}",
                    str(path)) for n, path in enumerate(paths[:4], 1)]))


def counted(entries: list, action: str, one: str, many: str) -> str:
    """'2 new files', '1 patched workflow' — empty when there are none."""
    n = sum(1 for e in entries if e["action"] == action and e["leader"] is None)
    return f"{n} {one if n == 1 else many}" if n else ""


def print_go_ahead(plan: dict) -> None:
    """The go-ahead question, the replacement question when needed, and the fingerprint."""
    entries = plan["entries"]
    summary = ", ".join(part for part in (
        counted(entries, "create", "new file", "new files"),
        counted(entries, "patch", "patched workflow", "patched workflows"),
        counted(entries, "replace", "replaced file (confirmed separately)",
                "replaced files (confirmed separately)")) if part)
    print("### Go-ahead\n")
    print("Ask this first. Only the answer \"" + WRITE_LABEL + "\" goes ahead:\n")
    print(ask(f"Write these changes into your local clones: {summary}?", "Write",
              [(WRITE_LABEL, "Write exactly the changes shown above. Nothing is committed "
                             "or pushed."),
               ("Cancel", "Write nothing.")]))
    replaced = [f"{e['repo']}: {e['file']}" for e in entries
                if e["action"] == "replace" and e["leader"] is None]
    if replaced:
        print("Then ask this. Only the answer \"" + REPLACE_LABEL + "\" adds `--replace`:\n")
        print(ask("These files already exist with different content. Replace them with the "
                  "generated workflow? " + "; ".join(replaced), "Replace",
                  [(REPLACE_LABEL, "Overwrite them with the content shown in their diffs."),
                   ("Keep them", "Leave them as they are and write only the other changes.")]))
    print(f"Then run `apply {fingerprint(plan)}`" +
          (", with `--replace` if both answers were yes." if replaced else ".") + "\n")


def show_plan(report: dict) -> int:
    """The dry run: verification results, plan, diffs and the go-ahead. Writes nothing."""
    plan = build_plan(report)
    print("## Dry run: nothing has been written\n")
    print(f"Checkouts folder: `{plan['root']}`\n")
    print_clones(plan)
    print_plan(plan)
    if any(e["ambiguous"] for e in plan["entries"]):
        print_choices(plan)
        print("Choose the clones first; the go-ahead question follows on the next dry run.")
    elif any(e["action"] in DONE for e in plan["entries"]):
        print_go_ahead(plan)
    else:
        print("Nothing to write.")
    return 0


# --- Commands that change something ---------------------------------------------------


def write_file(entry: dict) -> None:
    """Write one planned file. A new file is created exclusively; an existing one is
    swapped for a complete copy, only if it is still exactly what the plan saw."""
    target, checkout = entry["target"], entry["checkout"]
    workflows = target.parent
    if entry["action"] == "create":
        workflows.mkdir(parents=True, exist_ok=True)
    if workflows.resolve() != checkout / ".github" / "workflows":
        raise OSError(f"{entry['file']} would land outside .github/workflows/ of the clone")
    if entry["action"] == "create":
        with open(target, "xb") as fh:
            fh.write(entry["content"])
        return
    if sha256(target.read_bytes()) != entry["before"]:
        raise OSError(f"{entry['file']} changed after the dry run")
    mode = stat.S_IMODE(target.stat().st_mode)
    fd, tmp = tempfile.mkstemp(dir=workflows, prefix=".write-workflow-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(entry["content"])
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


def carry_out(entry: dict, replace: bool) -> tuple:
    """(outcome, reason, failed) for one entry of an approved plan."""
    action = entry["action"]
    if action == "skip":
        return "skipped", entry["reason"], False
    if action == "unchanged":
        return "unchanged", None, False
    if action == "replace" and not replace:
        return "skipped", "replacing the existing file was declined", False
    try:
        write_file(entry)
    except OSError as exc:
        return "skipped", f"writing failed: {exc}", True
    return DONE[action], None, False


def written(entry: dict, outcome: str, reason: str | None) -> dict:
    """The pipeline.workflow.written record for one outcome."""
    record = {"action": outcome}
    if entry["checkout"]:
        record["checkout"] = str(entry["checkout"])
    if entry["file"]:
        record["file"] = entry["file"]
    if outcome == "skipped":
        record["reason"] = reason
    else:
        record["sha256"] = entry["after"]
    return record


def apply(report: dict, expected: str, replace: bool) -> int:
    """Write the plan the user approved, record each outcome in report.json."""
    if not FINGERPRINT.fullmatch(expected):
        sys.exit("error: the fingerprint is the 64-character hex value the dry run printed")
    plan = build_plan(report)
    if fingerprint(plan) != expected:
        print("The plan has changed since the dry run that printed this fingerprint, so "
              "nothing was written. Run the dry run again, and ask again.")
        return 2
    print("## Written\n\n| Product | Repository | File | Result |\n|---|---|---|---|")
    failed, outcomes = False, {}
    for entry in (e for e in plan["entries"] if e["record"]):
        if entry["leader"] is not None:  # the same file, already written for its leader
            outcome, reason = outcomes[id(entry["leader"])]
        else:
            outcome, reason, error = carry_out(entry, replace)
            failed |= error
        outcomes[id(entry)] = (outcome, reason)
        report["products"][entry["product"]]["pipeline"][entry["slot"]]["written"] = \
            written(entry, outcome, reason)
        result = outcome if not reason else f"{outcome}: {reason}"
        print(f"| `{entry['product']}` | `{entry['repo'] or '-'}` | `{entry['file'] or '-'}` "
              f"| {cell(result)} |")
    save_report(report)
    print("\nRecorded in report.json, under each file's written field (pipeline.workflow, "
          "pipeline.release_patch). Nothing was committed or pushed.")
    return 1 if failed else 0


def set_root(report: dict) -> int:
    """Record the checkouts folder read from stdin, so that no path is a command argument."""
    given = sys.stdin.read().strip()
    if not given or "\n" in given:
        sys.exit("error: pass exactly one folder on stdin")
    root = Path(os.path.expanduser(given))
    root = (root if root.is_absolute() else Path.cwd() / root).resolve()
    if not root.is_dir():
        sys.exit(f"error: {root} is not an existing folder")
    settings = report.setdefault("write", {})
    if settings.get("root") != str(root):
        settings.pop("checkouts", None)  # choices made among another folder's clones
    settings["root"] = str(root)
    save_report(report)
    print(f"Checkouts folder recorded: {root}")
    return 0


def choose(report: dict, repo: str, number: int) -> int:
    """Record which of several matching clones a repository's workflows go into."""
    plan = build_plan(report)
    found = next((f for r, f in plan["repos"].items() if r.lower() == repo.lower()), None)
    if not found or len(found["matches"]) <= 1:
        sys.exit(f"error: {repo} is not a repository with several matching clones")
    if not 1 <= number <= len(found["matches"]):
        sys.exit(f"error: choose a number from 1 to {len(found['matches'])}")
    name = next(r for r in plan["repos"] if r.lower() == repo.lower())
    path = found["matches"][number - 1]["path"]
    report.setdefault("write", {}).setdefault("checkouts", {})[name] = str(path)
    save_report(report)
    print(f"{name}: workflows go into {path}. Run the dry run again.")
    return 0


def main() -> int:
    """Run one command; the dry run when none is given."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("set-root", help="record the checkouts folder, read from stdin")
    commands.add_parser("plan", help="check the clones and show what would change (default)")
    choice = commands.add_parser("choose", help="pick one of several matching clones")
    choice.add_argument("repo", help="org/repo")
    choice.add_argument("number", type=int, help="the clone's number in the dry run")
    approve = commands.add_parser("apply", help="write the plan the user approved")
    approve.add_argument("fingerprint", help="as printed by the dry run")
    approve.add_argument("--replace", action="store_true",
                         help="also replace existing files with different content")
    args = parser.parse_args()

    report = load_report()
    if args.command == "set-root":
        return set_root(report)
    if args.command == "choose":
        return choose(report, args.repo, args.number)
    if args.command == "apply":
        return apply(report, args.fingerprint, args.replace)
    return show_plan(report)


if __name__ == "__main__":
    sys.exit(main())
