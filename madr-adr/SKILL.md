---
name: madr-adr
description: Write, review and maintain Architectural Decision Records (ADRs) in the MADR 4.x format (Markdown Architectural Decision Records, adr.github.io/madr) using the official MADR templates, plus scripts to find the next ADR number and validate structure. Use this skill whenever the user wants to document, record, justify or write up a technical or architectural decision, such as choosing a database, framework, library, protocol, cloud service, API style, build tool, hosting model or any design trade-off, even if they never say ADR or MADR (e.g. "write up why we picked Kafka", "document our decision to move to a monorepo", "turn this Slack thread into a decision record"). Also use it to review or lint an existing ADR, convert Nygard/adr-tools style ADRs to MADR, add the next numbered ADR to docs/decisions or docs/adr, set up an ADR log in a repo, mark an ADR as accepted, deprecated or superseded, or create/refresh the index of decisions in the ADR folder's README.md.
license: Skill text MIT. Bundled MADR templates are MIT OR CC0-1.0 (adr/madr).
---

# Writing MADR decision records

An ADR captures **one** decision and **why** it was made. Its real reader is someone months or years later asking "why is it built like this, and is it safe to change?". MADR gives that reader a predictable structure: the problem, the options, the choice with its justification, and the costs. Everything below serves that reader.

## Bundled resources

| Path | Use it for |
| --- | --- |
| `assets/templates/adr-template.md` | Official full MADR 4 template with inline guidance |
| `assets/templates/adr-template-minimal.md` | Official template with only the mandatory sections |
| `assets/templates/adr-template-bare.md`, `adr-template-bare-minimal.md` | Same, without guidance text: what you copy into a repo when setting up an ADR log |
| `assets/templates/0000-use-markdown-architectural-decision-records.md` | MADR's bootstrap ADR for a new log |
| `assets/markdownlint.yml` | MADR's markdownlint config (install in a repo as `.markdownlint.yml`) |
| `scripts/find_adrs.py` | Locate the repo's ADR folder, list ADRs, detect conventions, compute next number + filename |
| `scripts/validate_madr.py` | Structural check of one or more ADRs (exit 1 on errors) |
| `scripts/update_index.py` | Create or refresh the index table in `README.md` at the root of the ADR folder (`--check` to detect drift) |
| `references/section-guide.md` | Detailed rules and examples per section, metadata and status lifecycle, superseding, converting from Nygard format |
| `references/review-checklist.md` | Reviewing an ADR: anti-patterns, definition of done |
| `references/examples.md` | A full ADR, a minimal ADR, and a supersede edit |

Paths are relative to this skill's directory. Scripts need only Python 3.

## Workflow

### 1. Understand the decision

A useful ADR needs, at minimum:

* the problem and its context (what component, what triggered the decision),
* at least two options that were genuinely considered,
* the chosen option and the real reason it won.

Worth having: decision drivers (the forces and constraints), consequences, especially the downsides, who decided / was consulted, links to issues or discussions, and how compliance will be checked.

Gather these from the user's message, anything they pasted (Slack threads, PR discussions, meeting notes, RFCs), and the repository itself (e.g. `package.json` or existing ADRs).

If the chosen option or its main reason is missing, ask. Those two can never be guessed, because an ADR is a record of what the team actually decided and why; plausible invented rationale is worse than none, since future readers will trust it. Ask everything you need in one short message rather than drip-feeding questions.

You *may* propose things the user didn't mention (an extra alternative worth listing, a likely downside, a confirmation check), because that is often where an ADR adds value. When you do, tell the user in your reply which parts you added, so they can confirm or delete them. Don't mark them inside the ADR itself; the file should read as the final record.

If the user explicitly wants a quick draft without questions, write it with what you have, use `status: proposed`, and list the gaps in your reply.

### 2. Check the repository (when there is one)

From the repo root run:

```bash
python <skill-dir>/scripts/find_adrs.py --title "Use PostgreSQL for the order service"
```

It prints the ADR directory, the next number, a suggested filename, and the conventions existing ADRs use. **Follow the repo's conventions over MADR defaults** (directory, number width, front matter keys, Just-the-Docs `parent`/`nav_order`, list markers, numbered titles); a consistent log matters more than textbook MADR. If the repo contains its own `adr-template.md`, start from that instead of the bundled one.

If the existing log is Nygard/adr-tools style and the user asked for MADR, write the new ADR in MADR and mention that the log is now mixed; offer to convert the older ones (see `references/section-guide.md` §14).

No repository (plain chat): name the file `NNNN-title-with-dashes.md` and tell the user to replace `NNNN` with their next number, unless they told you the number.

### 3. Pick the size

Start from the full structure and **delete every optional section you cannot fill with real content**. That naturally scales the ADR: a small, obvious decision ends up close to the minimal template, a big one keeps drivers, pros/cons and confirmation. Leaving an optional heading empty, or filling it with filler, is worse than removing it.

Required: title, `## Context and Problem Statement`, `## Considered Options`, `## Decision Outcome`. Strongly recommended: front matter `status` and `date`, and `### Consequences`.

### 4. Write it

Use exactly this skeleton, in this order (headings verbatim):

```markdown
---
status: accepted
date: 2026-09-25
decision-makers: Priya Shah, Tom Okafor
consulted: Platform team
informed: Backend engineers
---

# Use WebSockets for Live Dashboard Updates

## Context and Problem Statement

## Decision Drivers

## Considered Options

## Decision Outcome

Chosen option: "WebSockets", because …

### Consequences

### Confirmation

## Pros and Cons of the Options

### WebSockets

### Server-Sent Events

## More Information
```

Section rules (the *why* and more examples are in `references/section-guide.md`):

* **Front matter**: `status` is one of `proposed | accepted | rejected | deprecated | superseded by ADR-NNNN`. `date` is `YYYY-MM-DD` of the last update (today, if you don't know better). Only put real names or groups in `decision-makers`, `consulted`, `informed`; drop fields you don't know rather than inventing an owner. (If every existing ADR names the same group, e.g. "Web team", and the user speaks as part of it, reusing it is reasonable; mention it in your reply.)
* **Title**: short phrase naming the problem *and* the chosen solution, usually imperative ("Use X for Y"). No number in the heading; the filename carries it. Title and filename slug say the same thing.
* **Context and Problem Statement**: 2–3 sentences or a short story. State the scope (which component), the trigger (why now), and end with the question being decided. Link the issue/incident/thread if known. Keep arguments for options out of here.
* **Decision Drivers**: specific, checkable forces ("p99 < 50 ms at 2k req/s", "team has no Rust experience", "must ship before 2026-12"), not labels like "performance". Flag hard constraints.
* **Considered Options**: `*` bullets of short option titles. At least two real alternatives; include "keep the status quo" when realistic. No straw men.
* **Decision Outcome**: first line is always `Chosen option: "<title>", because <justification>.` The quoted title is copied verbatim from Considered Options. The justification points at the drivers that decided it; "comes out best (see below)" alone is a weak justification. For several reasons, end with `because` and follow with bullets.
* **Consequences**: `* Good, because …`, `* Neutral, because …`, `* Bad, because …`, describing what changes for the system and team (migrations, new ops burden, risks, things that get easier). Include at least one honest `Bad`; decisions without costs are rare, and the cost is exactly what future maintainers need to know.
* **Confirmation**: how adherence will be verified: a fitness function or CI check (ArchUnit, dependency rules, lockfile check), a review step, and/or a revisit trigger.
* **Pros and Cons of the Options**: one `###` per option, titled exactly as in Considered Options, same order. Optional one-line description or link, then `Good/Neutral/Bad, because` bullets. Be fair: the chosen option gets its cons, rejected ones get their pros.
* **More Information**: evidence (spikes, benchmarks), how/when agreement was reached, rollout plan, when to revisit, links to related ADRs as `[ADR-0004](0004-title.md)`.

Formatting conventions (from MADR's own decision log):

* `*` as list marker; exact MADR heading names; no bold on line headings like `Chosen option:`.
* One sentence per line in prose paragraphs (cleaner diffs), unless the repo wraps differently.
* No leftover `{placeholders}`, template guidance comments (`<!-- This is an optional element… -->`) or `…` bullets.
* Write in the language the user or the repo uses. Keep the MADR heading names in English unless existing ADRs translate them.

### 5. Validate and self-review

```bash
python <skill-dir>/scripts/validate_madr.py path/to/0012-use-postgresql-for-orders.md
```

Fix every ERROR. Read each WARN and fix it unless there is a reason not to (e.g. the repo's convention differs); the validator is deliberately a bit strict.

Then reread the ADR as a newcomer and check the things a script can't: Is it one decision? Are the alternatives genuine? Does the `because` trace back to the drivers? Are costs stated? Is the tone factual rather than salesy? `references/review-checklist.md` has the full list and the common anti-patterns.

### 6. Deliver

* **In a repository**: write the file into the ADR directory. If the new ADR supersedes an older one, also update the old ADR's front matter (`status: superseded by ADR-NNNN`, new `date`) and add a link in its More Information; leave the rest of the old ADR untouched. Then refresh the index (below). Don't commit unless asked.
* **In chat**: create the `.md` file and share it.
* **Index**: from the repo root run `python <skill-dir>/scripts/update_index.py` (add `--dir` if `find_adrs.py` picked a different folder than the one you wrote to). The `README.md` at the root of the ADR folder is where newcomers start reading the log, and its status column is how they see at a glance which decisions still hold, so it is part of every change to the log, not an afterthought. The script rewrites only the block between `<!-- adrlog -->` and `<!-- adrlogstop -->`; anything hand-edited inside it is lost on the next run, so put intro text outside the markers. If it reports that it appended an `## Index` section and the README already had a hand-written list of ADRs, remove the old list so there is one source of truth, and say so in your reply.
* **Your reply** (short): where the file is, the status you used, that the index was updated (or created), what you added or inferred beyond what the user told you, and open gaps (e.g. "decision-makers unknown, so omitted"). Don't paste the whole ADR back if you've already delivered the file.

## Other ADR tasks

* **Review / critique an ADR**: follow `references/review-checklist.md`, run the validator, lead with the two or three issues that matter most, then offer corrected sections.
* **Convert a Nygard, adr-tools, Y-statement or free-form ADR to MADR**: mapping in `references/section-guide.md` §14; refresh the index afterwards, since titles and statuses may change. Preserve the original meaning; if the source never mentions alternatives, ask or clearly flag reconstructed ones in your reply rather than presenting invented history as fact.
* **Accept, deprecate or supersede**: ADRs are an append-only log. Change status and date, then rerun `scripts/update_index.py` so the index shows the new status; don't rewrite an accepted ADR's reasoning to fit a new decision; write a new ADR instead. Details in `references/section-guide.md` §13, example in `references/examples.md` §3.
* **Several decisions in one request** (or one discussion that settled several things): write one ADR per decision, numbered consecutively, and cross-link them in More Information.
* **Decision not made yet**: write it as `status: proposed`; "Chosen option" states the recommended option, and the pros/cons carry the comparison for the people who will decide.
* **Set up MADR in a repository**: create `docs/decisions/` (unless the user wants another location), copy the templates from `assets/templates/` (the bare ones are handy for humans, the full one for guidance), copy `assets/markdownlint.yml` to the repo root as `.markdownlint.yml` if they use markdownlint, optionally add the bootstrap `0000-use-markdown-architectural-decision-records.md`, and finish with `scripts/update_index.py --dir docs/decisions` to create the folder's `README.md` index.
* **Index only** (create, refresh or check the list of decisions): run `scripts/update_index.py`; `--check` exits 1 when the README is missing or stale, which is also handy as a CI step.
