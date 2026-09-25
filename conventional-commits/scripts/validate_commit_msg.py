#!/usr/bin/env python3
"""Validate a commit message against Conventional Commits 1.0.0.

Usage:
    python3 validate_commit_msg.py MESSAGE_FILE [options]    # before committing
    echo "feat: add thing" | python3 validate_commit_msg.py - [options]
    python3 validate_commit_msg.py --commit HEAD [options]   # after committing

Options:
    --types a,b,c       Allowed types (default: the standard commitlint set)
    --scopes a,b,c      Allowed scopes (default: any)
    --max-header N      Maximum header length (default: 72)
    --max-body-line N   Body/footer line length that triggers a warning (default: 72)
    --require-signoff   Require a 'Signed-off-by: Name <email>' trailer that git can
                        parse. Use it on the committed message (git log -1 --format=%B),
                        since 'git commit -s' adds the sign-off after validation.
    --commit REV        Check an existing commit instead of a file: its message,
                        a git-readable Signed-off-by trailer, and a signature.
    --human             Message was written by a person: skip the AI attribution
                        checks (required Assisted-by trailer; no Co-Authored-By,
                        "Generated with" lines, session trailers or links)

Errors are spec violations and violations of house rules (or of rules the repo
configures via --types/--scopes/--max-header); the script exits 1 if there are
any. Warnings are style suggestions; exit 0. With --human, house rules that the
spec itself doesn't require are reported as "House style" warnings instead of
errors, because a person's spec-valid message is still a Conventional Commit.
Rules passed in from the repo's config stay errors either way.
"""
import argparse
import re
import subprocess
import sys

DEFAULT_TYPES = [
    "feat", "fix", "docs", "style", "refactor", "perf",
    "test", "build", "ci", "chore", "revert",
]

HEADER_RE = re.compile(
    r"^(?P<type>[A-Za-z]+)"
    r"(?:\((?P<scope>[^()\r\n]*)\))?"
    r"(?P<bang>!)?"
    r"(?P<sep>:\s?)"
    r"(?P<desc>.*)$"
)
# A footer line starts with a token followed by ": " or " #".
FOOTER_START_RE = re.compile(r"^(?P<token>BREAKING CHANGE|[A-Za-z0-9][A-Za-z0-9-]*)(?:: | #)")
# Near-misses that tooling will not recognise as a breaking-change footer.
BAD_BREAKING_RE = re.compile(r"^\s*breaking[ -]changes?\b", re.IGNORECASE)
GOOD_BREAKING_RE = re.compile(r"^BREAKING[ -]CHANGE: \S")
# AI attribution: exactly 'Assisted-by: <AGENT_NAME>:<MODEL_VERSION>'.
ASSISTED_OK_RE = re.compile(r"^Assisted-by: [A-Za-z][A-Za-z0-9._-]*:[A-Za-z0-9][A-Za-z0-9._-]*$")
ASSISTED_ANY_RE = re.compile(r"^\s*assisted[- ]?by\b", re.IGNORECASE)
SIGNOFF_ANY_RE = re.compile(r"^\s*signed[- ]?off[- ]?by\b", re.IGNORECASE)
SIGNOFF_OK_RE = re.compile(r"^Signed-off-by: [^<>]*\S <[^<>\s@]+@[^<>\s]+>$")
COAUTHOR_RE = re.compile(r"^\s*co[- ]?authored[- ]?by\b", re.IGNORECASE)
# Other AI attribution, in vendor-neutral forms; Assisted-by must be the only AI marker.
OTHER_AI_MARKERS = [
    # Trailers whose token names a session: Agent-Session:, <Tool>-Session:, Session-Url: ...
    (re.compile(r"^\s*[A-Za-z0-9-]*session[A-Za-z0-9-]*:\s", re.IGNORECASE), "session trailer"),
    # Attribution trailers: Generated-by:, Made-with:, AI-Assisted: ...
    (re.compile(r"^\s*((generated|made|created|built|written)-(by|with|using)|ai-[a-z-]+):\s", re.IGNORECASE),
     "AI attribution trailer"),
    # A line that is only "Generated with <tool>" (optionally a markdown link), or any robot emoji.
    (re.compile(r"^\W*(generated|made|created|built|written)\s+(with|by|using)\s+"
                r"(\[[^\]]{1,40}\]\(\S+\)|\S+(\s+\S+){0,2})\s*[.!]?\s*$", re.IGNORECASE),
     "'Generated with <tool>' line"),
    (re.compile("\U0001F916"), "robot-emoji attribution line"),
    # Links to an agent session: .../session_<id>, .../sessions/<id> (id contains a digit).
    (re.compile(r"https?://\S*/sessions?[/_-](?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{8,}", re.IGNORECASE),
     "agent session link"),
]
# Common non-imperative openings ("added", "fixes", "updating", ...).
_VERBS = [
    "add", "fix", "update", "remove", "change", "create", "implement", "improve",
    "refactor", "rename", "move", "delete", "bump", "upgrade", "clean", "support",
    "handle", "allow", "prevent", "introduce", "replace", "drop", "use", "enable",
    "disable", "correct", "adjust", "migrate", "convert", "extract", "simplify",
]
NON_IMPERATIVE = set()
for _v in _VERBS:
    _stem = _v[:-1] if _v.endswith("e") else _v
    _ed = _v + "d" if _v.endswith("e") else _v + ("ped" if _v == "drop" else "ed")
    _s = _v + "es" if _v.endswith(("x", "sh", "ch")) else _v + "s"
    _ing = _stem + ("ping" if _v == "drop" else "ing")
    NON_IMPERATIVE.update({_ed, _s, _ing})
NON_IMPERATIVE.update({"made", "makes", "making", "wrote", "writes", "writing"})


def git_trailer_check(msg, footer_block, warnings, required):
    """Confirm git parses the required trailers and every other footer (what `git log --format=%(trailers)` sees)."""
    try:
        out = subprocess.run(["git", "interpret-trailers", "--parse"], input=msg,
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        warnings.append("git not available; could not verify that git parses the trailers.")
        return [], []
    parsed = {l.split(":", 1)[0].lower() for l in out.splitlines() if l[:1].strip() and ":" in l}
    missing = [t for t in required if t.lower() not in parsed]
    hints = []
    for l in footer_block:
        fm = FOOTER_START_RE.match(l)
        if fm:
            if fm.group("token").lower() in parsed:
                continue
            if l.startswith("BREAKING CHANGE"):
                hints.append("use 'BREAKING-CHANGE:' (hyphen) instead of 'BREAKING CHANGE:'")
            elif re.match(r"^[A-Za-z][A-Za-z0-9-]* #", l):
                hints.append(f"use the colon form ('{l.split(' ')[0]}: #...') instead of {l!r}")
            else:
                hints.append(f"git does not read {l[:40]!r} as a trailer")
        elif not l[:1].isspace():
            hints.append(f"indent continuation line {l[:30]!r} by one space")
    if not missing and not hints:
        return [], []
    hint = "; ".join(dict.fromkeys(hints)) or "make every footer line a 'Token: value' trailer"
    if missing:
        return [f"git does not recognise the footer block as trailers, so it cannot see {', '.join(missing)}: {hint}."], []
    return [], [f"git doesn't read every footer line as a trailer: {hint}."]


def validate(msg, types, scopes, max_header, max_body_line, human=False, require_signoff=False,
             types_from_repo=False, max_header_from_repo=False):
    errors, warnings = [], []

    def house(text, from_repo=False):
        """A house rule the spec doesn't require: an error for your own commits, a warning for a person's."""
        if human and not from_repo:
            warnings.append(f"House style (the spec allows this): {text}")
        else:
            errors.append(text)

    lines = msg.rstrip("\n").split("\n")
    lines = [l.rstrip() for l in lines]
    # Trim trailing blank lines.
    while lines and not lines[-1]:
        lines.pop()
    if not lines or not lines[0]:
        return ["Message is empty or starts with a blank line."], warnings

    header = lines[0]
    m = HEADER_RE.match(header)
    if not m:
        errors.append(
            f"Header does not match '<type>[(scope)][!]: <description>': {header!r}"
        )
    else:
        ctype, scope, bang, sep, desc = (
            m.group("type"), m.group("scope"), m.group("bang"), m.group("sep"), m.group("desc")
        )
        if sep != ": ":
            errors.append("Type/scope must be followed by a colon and exactly one space.")
        if not desc.strip():
            errors.append("Description is missing after 'type: '.")
        elif desc != desc.lstrip():
            errors.append("Description must immediately follow ': ' (extra spaces found).")
        if types and ctype.lower() not in types:
            house(f"Type '{ctype}' is not in the allowed list: {', '.join(types)}.", types_from_repo)
        if ctype != ctype.lower():
            warnings.append(f"Type '{ctype}' should be lowercase for consistency.")
        if scope is not None:
            if not scope.strip():
                errors.append("Scope parentheses are empty; drop them or add a scope.")
            elif scopes and scope not in scopes:
                errors.append(f"Scope '{scope}' is not in the allowed list: {', '.join(scopes)}.")
            if scope and scope != scope.lower():
                warnings.append(f"Scope '{scope}' should usually be lowercase.")
        d = desc.strip()
        if d.endswith("."):
            warnings.append("Description should not end with a period.")
        if d and d[0].isupper() and not re.match(r"^[A-Z][A-Z0-9]+\b", d):
            warnings.append(
                "Description should start lowercase (unless it begins with a proper noun or identifier)."
            )
        first_word = d.split(" ")[0].lower() if d else ""
        if first_word in NON_IMPERATIVE:
            warnings.append(
                f"Description starts with '{first_word}'; prefer the imperative mood (e.g. 'add', not 'added'/'adding')."
            )

    if len(header) > max_header:
        house(f"Header is {len(header)} characters; the limit is {max_header}.", max_header_from_repo)

    if len(lines) > 1 and lines[1] != "":
        errors.append("There must be a blank line between the header and the body/footers.")

    # Split the rest into paragraphs.
    rest = lines[2:] if len(lines) > 1 else []
    paragraphs, cur = [], []
    for l in rest:
        if l == "":
            if cur:
                paragraphs.append(cur)
                cur = []
        else:
            cur.append(l)
    if cur:
        paragraphs.append(cur)

    footer_block = []
    if paragraphs and FOOTER_START_RE.match(paragraphs[-1][0]):
        footer_block = paragraphs[-1]

    has_breaking_footer = False
    for l in footer_block:
        if GOOD_BREAKING_RE.match(l):
            has_breaking_footer = True
    for para in paragraphs:
        for l in para:
            if BAD_BREAKING_RE.match(l) and not GOOD_BREAKING_RE.match(l):
                errors.append(
                    f"Breaking-change footer must be exactly 'BREAKING CHANGE: <description>' "
                    f"(uppercase, singular, colon and space): {l!r}"
                )
            elif GOOD_BREAKING_RE.match(l) and para is not footer_block:
                errors.append(
                    "'BREAKING CHANGE:' appears outside the final footer block; "
                    "footers must come last, after a blank line."
                )

    if m and m.group("bang") is None and has_breaking_footer:
        house("BREAKING CHANGE footer present but the header has no '!'; add '!' before the colon.")
    if m and m.group("bang") and not has_breaking_footer:
        warnings.append("Header has '!' but no 'BREAKING CHANGE:' footer; add one telling users what to change.")

    if not human:
        all_lines = [l for para in paragraphs for l in para]
        for l in all_lines:
            if COAUTHOR_RE.match(l):
                errors.append(f"Co-Authored-By trailers are not allowed; remove it: {l!r}")
                continue
            for rx, what in OTHER_AI_MARKERS:
                if rx.search(l):
                    errors.append(f"Assisted-by is the only allowed AI marker; remove this {what}: {l!r}")
                    break
        attempts = [l for l in all_lines if ASSISTED_ANY_RE.match(l)]
        if not attempts:
            errors.append("Missing required 'Assisted-by: <AGENT_NAME>:<MODEL_VERSION>' trailer in the footer.")
        for l in attempts:
            if "<" in l or ">" in l:
                errors.append(f"Assisted-by still contains a placeholder; use your real agent name and model ID: {l!r}")
            elif not ASSISTED_OK_RE.match(l):
                errors.append(
                    f"Assisted-by must be exactly 'Assisted-by: <AGENT_NAME>:<MODEL_VERSION>' "
                    f"(one colon between name and model identifier, no spaces): {l!r}"
                )
            elif not re.search(r"\d", l.split(":", 2)[2]):
                warnings.append(f"Model version in {l!r} has no digits; use the exact model ID, not a family name.")
            if l not in footer_block:
                errors.append("Assisted-by must be in the final footer block, after a blank line, with nothing after it.")
        if len(attempts) != len(set(attempts)):
            errors.append("Duplicate Assisted-by trailers; keep exactly one.")
        # Assisted-by is the last trailer you write; only Signed-off-by lines may follow it.
        tail = [l for l in footer_block if not SIGNOFF_ANY_RE.match(l)]
        if attempts and tail and not ASSISTED_ANY_RE.match(tail[-1]):
            warnings.append("Put Assisted-by after the other footers; only Signed-off-by lines may follow it.")
        before_ab = footer_block[:footer_block.index(attempts[0])] if attempts and attempts[0] in footer_block else []
        if any(SIGNOFF_ANY_RE.match(l) for l in before_ab):
            warnings.append("Signed-off-by lines belong after Assisted-by (that's where 'git commit -s' puts them).")

    signoffs = [l for para in paragraphs for l in para if SIGNOFF_ANY_RE.match(l)]
    for l in signoffs:
        if not SIGNOFF_OK_RE.match(l):
            errors.append(f"Sign-off must be exactly 'Signed-off-by: Name <email>' (let 'git commit -s' write it): {l!r}")
        elif l not in footer_block:
            errors.append(f"Signed-off-by must be in the final footer block: {l!r}")
    if len(signoffs) != len(set(signoffs)):
        warnings.append("Duplicate Signed-off-by lines; keep one per person.")
    if require_signoff and not signoffs:
        errors.append("Missing Signed-off-by trailer; every commit must be made with 'git commit -s'.")

    required = ([] if human else ["Assisted-by"]) + (["Signed-off-by"] if require_signoff else [])
    if footer_block and not errors:
        missing_errs, dropped = git_trailer_check(msg, footer_block, warnings, required)
        errors.extend(missing_errs)
        for d in dropped:
            house(d)

    for para in paragraphs:
        for l in para:
            if len(l) > max_body_line and " " in l.strip() and not re.search(r"https?://", l):
                warnings.append(f"Line exceeds {max_body_line} characters ({len(l)}): {l[:40]!r}...")

    return errors, warnings


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", nargs="?", help="Path to the message file, or '-' for stdin")
    p.add_argument("--commit", metavar="REV")
    p.add_argument("--types", default=None)
    p.add_argument("--scopes", default="")
    p.add_argument("--max-header", type=int, default=None)
    p.add_argument("--max-body-line", type=int, default=72)
    p.add_argument("--human", action="store_true")
    p.add_argument("--require-signoff", action="store_true")
    a = p.parse_args()

    signature_error = None
    if a.commit:
        def git(*args):
            r = subprocess.run(["git", *args], capture_output=True, text=True)
            if r.returncode:
                sys.exit(f"ERROR: git {' '.join(args)} failed: {r.stderr.strip()}")
            return r.stdout
        msg = git("log", "-1", "--format=%B", a.commit)
        header = git("cat-file", "commit", a.commit).split("\n\n", 1)[0]
        if not re.search(r"^gpgsig(-sha256)? ", header, re.M):
            signature_error = (f"Commit {a.commit} is not signed. Every commit needs -S; never retry with "
                               "--no-gpg-sign. See references/signing.md to diagnose.")
        a.require_signoff = True
    elif a.file:
        msg = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
    else:
        p.error("give a message file, '-' for stdin, or --commit REV")
    types_from_repo = a.types is not None
    types = [t.strip().lower() for t in (a.types or ",".join(DEFAULT_TYPES)).split(",") if t.strip()]
    max_header_from_repo = a.max_header is not None
    max_header = a.max_header if max_header_from_repo else 72
    scopes = [s.strip() for s in a.scopes.split(",") if s.strip()]
    errors, warnings = validate(msg, types, scopes, max_header, a.max_body_line, a.human, a.require_signoff,
                                types_from_repo, max_header_from_repo)
    if signature_error:
        errors.insert(0, signature_error)

    for e in errors:
        print(f"ERROR: {e}")
    for w in warnings:
        print(f"WARNING: {w}")
    if not errors and not warnings:
        print("OK: message follows Conventional Commits.")
    elif not errors:
        print("OK (with warnings): message is valid Conventional Commits.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
