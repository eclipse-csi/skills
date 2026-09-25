#!/usr/bin/env python3
"""
Validate Markdown Architectural Decision Records against the MADR 4.x structure.

Usage:
    python validate_madr.py <file-or-dir> [<file-or-dir> ...] [--strict]

Directories are searched recursively for numbered ADR files (NNNN-*.md).
Explicit file paths are always validated.

Exit code is 1 if any ERROR was found (or any WARN with --strict), else 0.
Pure standard library; no third-party dependencies.

What it checks (see references/section-guide.md for the reasoning):
  * front matter: status value, ISO date, empty or placeholder fields
  * exactly one H1 title, no leftover placeholder, no number prefix (MADR ADR-0002)
  * required sections present and non-empty; sections in canonical MADR order
  * "Chosen option: "<title>", because ..." sentence, and <title> matches a considered option
  * Consequences / Pros and Cons bullets use "Good|Neutral|Bad, because ..."
  * one "Pros and Cons" subsection per considered option, same names, same order
  * leftover template placeholders, guidance comments and lone "…" bullets
  * asterisk list markers (MADR ADR-0011), filename pattern NNNN-title-with-dashes.md
  * duplicate ADR numbers within one directory
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

CANONICAL_H2 = [
    "Context and Problem Statement",
    "Decision Drivers",
    "Considered Options",
    "Decision Outcome",
    "Pros and Cons of the Options",
    "More Information",
]
REQUIRED_H2 = {"context and problem statement", "considered options", "decision outcome"}
OUTCOME_H3 = ["Consequences", "Confirmation"]
LEGACY_H3 = {"positive consequences", "negative consequences"}

STATUS_RE = re.compile(r"^(proposed|accepted|rejected|deprecated|superseded by .+)$", re.I)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ADR_FILE_RE = re.compile(r"^(?:\d{3,5}|NNNN)-.+\.md$")
GOOD_FILE_RE = re.compile(r"^\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
BULLET_RE = re.compile(r"^([*+-])\s+(.*)$")
ARG_RE = re.compile(r"^(good|neutral|bad),\s+because\b", re.I)
NUMBERED_TITLE_RE = re.compile(r"^(adr[-\s]?)?\d+\s*[.:)\-–]\s*", re.I)

# Distinctive phrases from the official MADR templates; finding one means a placeholder was left in.
TEMPLATE_PHRASES = [
    "short title, representative of solved problem",
    "describe the context and problem statement",
    "title of option",
    "title of other option",
    "decision driver 1",
    "argument a}",
    "positive consequence, e.g.",
    "negative consequence, e.g.",
    "justification. e.g.",
    "example | description | pointer",
    "yyyy-mm-dd when the decision was last updated",
    "list everyone involved in the decision",
    "proposed | rejected | accepted",
    "describe how the implementation",
    "you might want to provide additional evidence",
]
TEMPLATE_COMMENTS = [
    "this is an optional element",
    "can vary -->",
    'use "neutral" if the given argument',
    "optional metadata elements",
]
SKIP_NAMES = {"readme.md", "index.md", "template.md"}

QUOTE_PAIRS = {'"': '"', "'": "'", "“": "”", "‘": "’", "«": "»"}


class Report:
    def __init__(self, path):
        self.path = path
        self.issues = []  # (level, line, msg)

    def err(self, line, msg):
        self.issues.append(("ERROR", line, msg))

    def warn(self, line, msg):
        self.issues.append(("WARN", line, msg))

    @property
    def errors(self):
        return sum(1 for i in self.issues if i[0] == "ERROR")

    @property
    def warnings(self):
        return sum(1 for i in self.issues if i[0] == "WARN")


def normalize(text):
    """Normalize an option title for comparison: drop markdown, quotes, case, extra spaces."""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"<!--.*?-->", "", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)  # [text](url) -> text
    t = re.sub(r"<(https?://[^>]+)>", r"\1", t)
    t = re.sub(r"[`*_]", "", t)
    t = re.sub(r"[\"'“”‘’«»]", "", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t.rstrip(".:;, ")


def titles_match(a, b):
    """True if two option titles refer to the same option (exact or one is a prefix of the other)."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = sorted((na, nb), key=len)
    return long_.startswith(short + " ") or long_.startswith(short + ",")


def strip_inline_code(line):
    return re.sub(r"`[^`]*`", "", line)


def parse_front_matter(lines):
    """Return (dict key -> (value, lineno), body_start_index). Minimal YAML subset."""
    if not lines or lines[0].strip() != "---":
        return None, 0
    fm = {}
    last_key = None
    for i in range(1, len(lines)):
        raw = lines[i]
        if raw.strip() == "---":
            return fm, i + 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", raw)
        if m and not raw.startswith((" ", "\t", "-")):
            last_key = m.group(1).lower()
            fm[last_key] = (m.group(2).strip(), i + 1)
        elif stripped.startswith("- ") and last_key:
            val, ln = fm[last_key]
            fm[last_key] = ((val + ", " if val else "") + stripped[2:].strip(), ln)
    return None, 0  # unterminated: treat as no front matter


def tokenize(lines, offset):
    """Yield (lineno, text, in_code) for body lines, tracking fenced code blocks."""
    out = []
    fence = None
    for idx, line in enumerate(lines):
        lineno = idx + offset + 1
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(1)[0] * len(m.group(1))
            out.append((lineno, line, True))
            continue
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):].strip():
                fence = None
            out.append((lineno, line, True))
            continue
        out.append((lineno, line, False))
    return out


def build_sections(tokens):
    """Split into heading-delimited sections: list of dicts with level, title, line, body tokens."""
    sections = []
    current = {"level": 0, "title": "", "line": 0, "body": []}
    for lineno, text, in_code in tokens:
        m = HEADING_RE.match(text) if not in_code else None
        if m:
            sections.append(current)
            current = {"level": len(m.group(1)), "title": m.group(2).strip(), "line": lineno, "body": []}
        else:
            current["body"].append((lineno, text, in_code))
    sections.append(current)
    return sections


def has_content(body):
    for _, text, in_code in body:
        if in_code:
            return True
        t = re.sub(r"<!--.*?-->", "", text).strip()
        if t:
            return True
    return False


def top_bullets(body):
    """Top-level bullet items (not indented, not in code): list of (lineno, marker, text)."""
    items = []
    for lineno, text, in_code in body:
        if in_code:
            continue
        m = BULLET_RE.match(text)
        if m:
            items.append((lineno, m.group(1), m.group(2).strip()))
    return items


def extract_chosen(body):
    """Find 'Chosen option: ...' in Decision Outcome. Returns (lineno, title|None, rest, quoted)."""
    for i, (lineno, text, in_code) in enumerate(body):
        if in_code:
            continue
        m = re.search(r"chosen option\s*:\s*(.*)$", text, re.I)
        if not m:
            continue
        s = m.group(1).strip()
        # Collect following lines so a justification on the next line / in a list still counts.
        following = " ".join(t for _, t, c in body[i + 1:i + 6] if not c)
        if s and s[0] in QUOTE_PAIRS:
            op, cl = s[0], QUOTE_PAIRS[s[0]]
            mm = re.match(re.escape(op) + r"(.*?)" + re.escape(cl) + r"(?=\s*(?:,|\.|;|$|\s+because))", s)
            if mm:
                return lineno, mm.group(1), s[mm.end():] + " " + following, True
        # Unquoted: take text up to ', because' or end of sentence.
        mm = re.match(r"(.*?)(?:,\s*because\b|\s+because\b|\.$|$)", s)
        return lineno, (mm.group(1).strip() if mm else s), s + " " + following, False
    return None, None, "", False


def check_file(path, report):
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # --- filename -------------------------------------------------------
    name = path.name
    if name.startswith("NNNN-"):
        if not GOOD_FILE_RE.match("0000-" + name[5:]):
            report.warn(0, f'Filename "{name}" should be lowercase-with-dashes after the number')
    elif ADR_FILE_RE.match(name) and not GOOD_FILE_RE.match(name):
        report.warn(0, f'Filename "{name}" should follow NNNN-title-with-dashes.md (4 digits, lowercase, dashes)')
    elif not ADR_FILE_RE.match(name):
        report.warn(0, f'Filename "{name}" does not follow the MADR pattern NNNN-title-with-dashes.md')

    # --- front matter ---------------------------------------------------
    fm, body_start = parse_front_matter(lines)
    if fm is not None:
        for key, (val, ln) in fm.items():
            v = val.strip().strip("\"'")
            if key in {"status", "date", "decision-makers", "consulted", "informed"}:
                if not v:
                    report.warn(ln, f'Front matter "{key}" is empty; fill it in or remove the field')
                    continue
                if "{" in v and "}" in v:
                    report.err(ln, f'Front matter "{key}" still contains a template placeholder: {v}')
                    continue
            if key == "status" and v and not STATUS_RE.match(v):
                report.warn(ln, f'Non-standard status "{v}" (MADR uses proposed | accepted | rejected | deprecated | superseded by ADR-NNNN)')
            if key == "date" and v and not DATE_RE.match(v):
                report.err(ln, f'Date "{v}" must be YYYY-MM-DD')

    tokens = tokenize(lines[body_start:], body_start)

    # --- leftovers from the template (outside code) ---------------------
    lower_lines = [(ln, t.lower(), c) for ln, t, c in tokens]
    for ln, t, c in lower_lines:
        if c:
            continue
        tl = strip_inline_code(t)
        for phrase in TEMPLATE_PHRASES:
            if phrase in tl:
                report.err(ln, f'Leftover template placeholder text ("{phrase}…")')
                break
        else:
            if re.search(r"\{[^{}\n]{2,}\}", tl):
                report.warn(ln, "Curly-brace placeholder-like text; MADR uses {…} for placeholders, replace it with real content")
        for c_phrase in TEMPLATE_COMMENTS:
            if c_phrase in tl and "<!--" in tl:
                report.warn(ln, "Leftover template guidance comment; remove it from the final ADR")
                break
        if re.match(r"^\s*[*+-]\s*(…|\.\.\.)\s*(<!--.*-->)?\s*$", t):
            report.err(ln, 'Leftover "…" bullet from the template')

    # --- list markers ---------------------------------------------------
    non_asterisk = [ln for ln, t, c in tokens if not c and re.match(r"^[-+]\s+\S", t)]
    if non_asterisk:
        report.warn(non_asterisk[0], f'{len(non_asterisk)} top-level list item(s) use "-" or "+"; MADR uses "*" as list marker (ADR-0011)')

    sections = build_sections(tokens)

    # --- title ----------------------------------------------------------
    h1s = [s for s in sections if s["level"] == 1]
    if not h1s:
        report.err(1, "Missing H1 title (# Short title of solved problem and chosen solution)")
    else:
        if len(h1s) > 1:
            report.warn(h1s[1]["line"], "More than one H1 heading; an ADR has exactly one title")
        title = h1s[0]["title"]
        if not title or "{" in title or "<!--" in title:
            report.err(h1s[0]["line"], "Title is empty or still a placeholder")
        elif NUMBERED_TITLE_RE.match(title):
            report.warn(h1s[0]["line"], "Title starts with a number; MADR keeps numbers out of headings (ADR-0002). Keep it only if the repo already does this")
        elif len(title) > 100:
            report.warn(h1s[0]["line"], "Title is very long; aim for a short phrase naming the problem and the chosen solution")

    # --- H2 structure ---------------------------------------------------
    h2_idx = [i for i, s in enumerate(sections) if s["level"] == 2]
    h2_titles = [sections[i]["title"] for i in h2_idx]
    canon_lower = [c.lower() for c in CANONICAL_H2]
    present = {}
    for i in h2_idx:
        t = sections[i]["title"].lower()
        if t in canon_lower:
            present.setdefault(t, i)
        elif t in {"status", "decision", "context", "consequences"}:
            report.warn(sections[i]["line"], f'"## {sections[i]["title"]}" looks like a Nygard-style section; MADR equivalents: status→front matter, context→Context and Problem Statement, decision→Decision Outcome, consequences→### Consequences')
        else:
            report.warn(sections[i]["line"], f'Non-MADR section "## {sections[i]["title"]}" (canonical: {", ".join(CANONICAL_H2)})')

    for req in CANONICAL_H2:
        if req.lower() in REQUIRED_H2 and req.lower() not in present:
            report.err(0, f'Missing required section "## {req}"')

    order = [canon_lower.index(sections[i]["title"].lower()) for i in h2_idx if sections[i]["title"].lower() in canon_lower]
    if order != sorted(order):
        report.warn(0, "Sections are out of MADR order: " + " → ".join(CANONICAL_H2))

    def section_span(i):
        """All tokens belonging to section i including its sub-sections."""
        lvl = sections[i]["level"]
        span = [i]
        for j in range(i + 1, len(sections)):
            if sections[j]["level"] <= lvl:
                break
            span.append(j)
        return span

    for key, i in present.items():
        span = section_span(i)
        if not any(has_content(sections[j]["body"]) for j in span):
            label = sections[i]["title"]
            if key in REQUIRED_H2:
                report.err(sections[i]["line"], f'Required section "## {label}" is empty')
            else:
                report.warn(sections[i]["line"], f'Optional section "## {label}" is empty; remove it instead of leaving it blank')

    # --- options --------------------------------------------------------
    options = []
    if "considered options" in present:
        i = present["considered options"]
        options = [(ln, txt) for ln, _, txt in top_bullets(sections[i]["body"]) if normalize(txt) not in {"", "…", "..."}]
        if len(options) == 1:
            report.warn(sections[i]["line"], "Only one considered option; a decision needs at least two genuine alternatives (unless you justify 'only option')")
        seen = set()
        for ln, txt in options:
            n = normalize(txt)
            if n in seen:
                report.warn(ln, f'Duplicate option "{txt}"')
            seen.add(n)

    # --- decision outcome -----------------------------------------------
    if "decision outcome" in present:
        i = present["decision outcome"]
        ln, chosen, rest, quoted = extract_chosen(sections[i]["body"])
        if chosen is None:
            report.err(sections[i]["line"], 'Decision Outcome lacks the sentence: Chosen option: "<option title>", because <justification>.')
        elif not chosen.strip():
            report.err(ln, 'Chosen option is empty; name one of the considered options')
        else:
            if not quoted:
                report.warn(ln, 'Put the chosen option title in double quotes: Chosen option: "<title>", because …')
            if "because" not in rest.lower():
                report.warn(ln, 'Chosen option has no "because …" justification')
            if options:
                matches = [o for o in options if titles_match(chosen, o[1])]
                if not matches:
                    report.err(ln, f'Chosen option "{chosen}" does not match any item under "## Considered Options" (repeat the option title verbatim, ADR-0006)')

        # sub-sections of Decision Outcome
        subs = [j for j in section_span(i)[1:] if sections[j]["level"] == 3]
        sub_titles = [sections[j]["title"].lower() for j in subs]
        known = [t for t in sub_titles if t in [o.lower() for o in OUTCOME_H3]]
        if known != sorted(known, key=lambda t: [o.lower() for o in OUTCOME_H3].index(t)):
            report.warn(sections[i]["line"], "Under Decision Outcome, put ### Consequences before ### Confirmation")
        for j in subs:
            t = sections[j]["title"].lower()
            if t in LEGACY_H3:
                report.warn(sections[j]["line"], f'"### {sections[j]["title"]}" is MADR 2.x; MADR 3+ uses a single ### Consequences list with Good/Bad, because …')
            if t == "consequences":
                bullets = top_bullets(sections[j]["body"])
                if not bullets and has_content(sections[j]["body"]):
                    report.warn(sections[j]["line"], 'Consequences should be a list of "* Good, because …" / "* Bad, because …" items')
                for bln, _, btxt in bullets:
                    if not ARG_RE.match(btxt):
                        report.warn(bln, f'Consequence should start with "Good, because", "Neutral, because" or "Bad, because": "{btxt[:60]}"')
                if bullets and not any(btxt.lower().startswith("bad") for _, _, btxt in bullets):
                    report.warn(sections[j]["line"], 'No "Bad, because …" consequence; nearly every decision has a cost or risk worth recording')
            if t == "confirmation" and not has_content(sections[j]["body"]):
                report.warn(sections[j]["line"], "Confirmation is empty; describe how compliance will be checked or remove the section")

    # --- pros and cons ----------------------------------------------------
    if "pros and cons of the options" in present:
        i = present["pros and cons of the options"]
        subs = [j for j in section_span(i)[1:] if sections[j]["level"] == 3]
        if not subs:
            report.warn(sections[i]["line"], "Pros and Cons of the Options should have one ### subsection per considered option")
        matched_order = []
        for j in subs:
            st = sections[j]["title"]
            idx = next((k for k, (_, o) in enumerate(options) if titles_match(st, o)), None)
            if idx is None:
                report.warn(sections[j]["line"], f'Pros/cons subsection "### {st}" does not match any considered option (use the same title, ADR-0006)')
            else:
                matched_order.append(idx)
            for bln, _, btxt in top_bullets(sections[j]["body"]):
                if not ARG_RE.match(btxt):
                    report.warn(bln, f'Argument should start with "Good, because", "Neutral, because" or "Bad, because": "{btxt[:60]}"')
        if options and subs:
            missing = [o for k, (_, o) in enumerate(options) if k not in matched_order]
            for o in missing:
                report.warn(sections[i]["line"], f'Considered option "{o}" has no pros/cons subsection')
            if matched_order != sorted(matched_order):
                report.warn(sections[i]["line"], "Pros/cons subsections are not in the same order as Considered Options")


def collect(paths):
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*.md")):
                if f.name.lower() in SKIP_NAMES or f.name.lower().startswith("adr-template"):
                    continue
                if ADR_FILE_RE.match(f.name):
                    files.append(f)
        elif p.is_file():
            files.append(p)
        else:
            print(f"Not found: {p}", file=sys.stderr)
    return files


def check_duplicates(files):
    """Duplicate ADR numbers within the same directory (categories may reuse numbers)."""
    problems = []
    by_dir = {}
    for f in files:
        m = re.match(r"^(\d{3,5})-", f.name)
        if m:
            by_dir.setdefault((f.parent, int(m.group(1))), []).append(f)
    for (d, num), fs in by_dir.items():
        if len(fs) > 1:
            problems.append(f"Duplicate ADR number {num:04d} in {d}: " + ", ".join(x.name for x in fs))
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="ADR files or directories")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = ap.parse_args()

    files = collect(args.paths)
    if not files:
        print("No ADR files found.")
        return 1

    total_e = total_w = 0
    for f in files:
        r = Report(f)
        try:
            check_file(f, r)
        except Exception as exc:  # keep going on odd files
            r.err(0, f"Could not parse file: {exc}")
        total_e += r.errors
        total_w += r.warnings
        status = "OK " if not r.issues else ("FAIL" if r.errors else "WARN")
        print(f"[{status}] {f}")
        for level, line, msg in sorted(r.issues, key=lambda x: (x[1], x[0])):
            loc = f"L{line}" if line else "   "
            print(f"    {level:<5} {loc:>5}  {msg}")

    dups = check_duplicates(files)
    for d in dups:
        print(f"ERROR  {d}")
    total_e += len(dups)

    print(f"\n{len(files)} file(s): {total_e} error(s), {total_w} warning(s)")
    if total_e or (args.strict and total_w):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
