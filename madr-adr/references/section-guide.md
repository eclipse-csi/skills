# MADR 4.x section-by-section guide

Detailed guidance for each part of a MADR record. SKILL.md has the condensed rules; read this when you want the reasoning, stronger/weaker examples, or you are handling an unusual case (metadata, superseding, categories, converting another format).

## Contents

1. Metadata (YAML front matter) and status lifecycle
2. Title
3. Context and Problem Statement
4. Decision Drivers
5. Considered Options
6. Decision Outcome
7. Consequences
8. Confirmation
9. Pros and Cons of the Options
10. More Information
11. Formatting conventions and where they come from
12. Files, numbering, categories
13. Linking, superseding, deprecating
14. Converting other ADR formats to MADR

---

## 1. Metadata (YAML front matter) and status lifecycle

All metadata is optional in MADR, but `status` and `date` are worth including in almost every record because they are what a future reader checks first ("is this still in force? how old is it?").

```yaml
---
status: accepted
date: 2026-09-25
decision-makers: Priya Shah, Tom Okafor
consulted: Platform team, Security (Lena Varga)
informed: All backend engineers
---
```

Field meanings (they come from RACI):

* `decision-makers`: people accountable for the decision.
* `consulted`: subject-matter experts whose opinion was sought, two-way communication.
* `informed`: people kept up to date, one-way communication.
* `date`: YYYY-MM-DD when the decision was last updated (not when the file was first created, if they differ).

Only fill people fields with names or groups the user actually gave you. A fabricated "decision-makers: Architecture Board" is worse than omitting the field, because it misrepresents who is accountable. If the user doesn't know or doesn't care, drop the field.

Either a comma-separated string or a YAML list is fine for people fields; match what existing ADRs in the repo do.

Status lifecycle:

| Status | Meaning |
| --- | --- |
| `proposed` | Written up for discussion; not yet agreed. The "Chosen option" is the proposal. |
| `accepted` | Agreed and in force. |
| `rejected` | Considered and deliberately not adopted. Keep the file: knowing what was rejected and why prevents re-litigating it. |
| `deprecated` | No longer relevant (e.g. the component was removed) but not replaced by a specific decision. |
| `superseded by ADR-NNNN` | Replaced by a later decision. Point to it. |

MADR allows other statuses (its own ADR-0003 uses "on hold"), but prefer the standard five unless the repo already has its own vocabulary.

If the repo renders ADRs with Jekyll "Just the Docs" (front matter has `parent:` and `nav_order:`), keep those keys and set `nav_order` to the ADR number.

## 2. Title

The H1 is a short phrase that names both the problem that was solved and the solution that was chosen. Imperative verb phrases read best because they state the decision itself.

* Strong: `# Use PostgreSQL for the order service`
* Strong: `# Stream dashboard updates over WebSockets`
* Weak: `# Database` (names a topic, not a decision)
* Weak: `# Decision about which message broker to use` (no answer in the title)
* Weak: `# 7. Use Kafka` (MADR keeps numbers out of headings; the filename carries the number)

For a `proposed` ADR the title still names the proposed choice. If the decision is still genuinely open and you are writing it up to compare options, a question-style working title is acceptable ("Choose a message broker for order events") but rename it once decided.

The title and the filename slug should say the same thing.

## 3. Context and Problem Statement

Two or three sentences, or a short story, that let someone with no background understand why a decision was needed. Good context usually contains:

* The situation: what system, component or process is affected (make the scope explicit, e.g. "the order service and its reporting jobs", not "the backend").
* The trigger: what changed or what hurts now (growth, an incident, a new requirement, an end-of-life dependency).
* The question being decided, phrased as a question. MADR encourages this because it keeps the ADR focused on one decision.
* Links to the issue, RFC, incident report or discussion thread, if known.

Keep implementation detail, history lessons and solution arguments out of here; arguments belong in drivers and pros/cons.

Example:

> The order service stores orders in MongoDB. Finance reporting now needs multi-document transactions and ad-hoc joins across orders, refunds and invoices, which we currently emulate in application code and which caused two reconciliation incidents in Q2 (INC-412, INC-431).
> Which database should the order service use going forward?

## 4. Decision Drivers (optional)

The forces that decide between the options: quality attributes, constraints, concerns, deadlines, team skills, cost ceilings, compliance. Drivers are what make the justification checkable, so include them whenever there is a real trade-off.

Make each driver specific enough that an option could clearly satisfy or fail it:

* Strong: `* Reporting queries must join orders, refunds and invoices with ACID guarantees`
* Strong: `* p99 read latency under 50 ms at 2,000 req/s`
* Strong: `* Team of 4 has no Cassandra experience; must ship by 2026-12`
* Weak: `* Performance` / `* Scalability` / `* Best practices`

Order drivers by importance if there is an obvious ranking. Mark hard constraints ("knock-out criteria") explicitly, because they justify decisions like "only option that meets …".

## 5. Considered Options

A bullet list of option titles, at least two genuine alternatives. Each title is short and is reused verbatim in "Decision Outcome" and in "Pros and Cons of the Options" (MADR ADR-0006: repeat names instead of inventing identifiers like `[A]`).

* Include "keep the status quo" / "do nothing" when it is a realistic choice; it often is.
* Don't pad with straw-man options nobody would pick, to make the favourite look good. A reader can tell, and it undermines trust in the whole record.
* If the user only told you about one option, ask what else was considered. If you add plausible alternatives yourself, tell the user you did so they can confirm or remove them.

Option titles may contain a link, e.g. `* [Vitest](https://vitest.dev/)`, and optionally a short dash-separated gloss: `* PostgreSQL 16 – managed via RDS`. Keep the part before the gloss identical wherever the option is named.

## 6. Decision Outcome

Always starts with this sentence form:

```markdown
Chosen option: "PostgreSQL", because it is the only option that gives us multi-document ACID transactions and SQL joins (the top two drivers) while being a technology the whole team already operates.
```

Rules:

* The quoted title matches an item in Considered Options.
* The justification comes right after `because` and refers back to drivers. MADR's template lists typical shapes: "only option which meets k.o. criterion …", "resolves force …", "comes out best (see below)".
* "comes out best (see below)" alone is acceptable only when the Pros and Cons section makes the winner obvious; a one-clause summary of *why* it wins is almost always better.
* For multi-point justifications, end the sentence with `because` and follow with a bullet list (MADR's own ADR-0000 does this).

A useful self-check is the Y-statement (Olaf Zimmermann), which should be derivable from the ADR:

> In the context of *<use case / component>*, facing *<concern>*, we decided for *<option>* and against *<other options>*, to achieve *<quality / benefit>*, accepting *<downside>*.

If you can't fill every slot from what you wrote, something is missing.

## 7. Consequences (optional, under Decision Outcome)

What becomes true because of the decision, good and bad, written with the same grammar as pros and cons (MADR ADR-0017):

```markdown
* Good, because finance can run reporting queries directly with SQL instead of the nightly export
* Good, because we drop about 1,200 lines of hand-written transaction compensation code
* Neutral, because hosting cost stays roughly the same (RDS vs. Atlas)
* Bad, because we need a one-off migration of ~40 M orders, estimated at two sprints
* Bad, because schema changes now need migrations, which the team must get used to
```

Consequences are about the *chosen* option's effect on the system and team (follow-up work, migrations, new risks, things that get easier). They are not a copy of the chosen option's pros list. Almost every real decision has at least one `Bad, because`; a consequences list with only good news reads like a sales pitch and hides the cost future maintainers will pay.

## 8. Confirmation (optional, under Decision Outcome)

How anyone will know the decision is actually being followed and still holds. Concrete beats generic:

* An automated fitness function: an ArchUnit/dependency-cruiser/import-linter rule, a CI check that the old library is no longer in the lockfile, a load test with a threshold.
* A manual check: a design/code review checkpoint, an item in the PR template.
* A review trigger: "revisit when order volume exceeds 10 M/month or in 2027-Q2, whichever is first".

MADR marks it optional but notes many ADRs include it; include it for any decision that could quietly erode.

## 9. Pros and Cons of the Options (optional)

One `###` subsection per considered option, titled exactly like the option, in the same order as the Considered Options list. MADR places this section *after* the outcome (ADR-0016) so the result is above the fold and this acts as an appendix.

Inside each subsection:

* Optionally a one-line description, example, code snippet, or link to the option's homepage.
* Bullets that start with `Good, because`, `Neutral, because` or `Bad, because` (ADR-0014 introduced "Neutral" for arguments that weigh neither way).

Aim for fairness: the chosen option should have at least one `Bad`, and rejected options should get their real strengths as `Good`. Tie arguments to the drivers where you can ("Bad, because no multi-document transactions (driver 1)"). The analysis is what lets a future team re-run the decision when a driver changes.

## 10. More Information (optional)

Anything that adds confidence or context without cluttering the core:

* Evidence: benchmark results, spike/prototype links, vendor docs.
* Team agreement: when/where it was agreed, who objected and how that was resolved.
* Realization plan: rollout steps, owner, target date.
* When to revisit the decision.
* Links to related ADRs, e.g. `Supersedes [ADR-0004](0004-use-mongodb-for-orders.md).`

## 11. Formatting conventions and where they come from

These come from MADR's own decision log (ADR-00NN refers to https://adr.github.io/madr/decisions/):

* `*` is the list marker (ADR-0011). Only change this if the repo's existing ADRs consistently use `-`.
* No numbers in headings (ADR-0002); the number lives in the filename.
* Line headings like `Chosen option:` are not bolded (ADR-0007).
* Metadata goes in YAML front matter (ADR-0013).
* Option names are repeated verbatim, not referenced by ID (ADR-0006).
* Pros/cons and consequences use `Good/Neutral/Bad, because …` (ADR-0014, ADR-0017).
* Links between ADRs go in More Information (ADR-0009).
* One sentence per line is MADR's own style (that's why its markdownlint config disables line-length checks). It makes diffs and reviews cleaner; follow it unless the repo wraps differently.
* `{curly braces}` mark placeholders in the templates (ADR-0012), so any `{...}` left in a finished ADR is a bug.
* Headings are the exact MADR names in Title Case: `## Context and Problem Statement`, `## Decision Drivers`, `## Considered Options`, `## Decision Outcome`, `### Consequences`, `### Confirmation`, `## Pros and Cons of the Options`, `## More Information`.

## 12. Files, numbering, categories

* Location: `docs/decisions/` by default. Use whatever directory the repo already uses (`docs/adr/`, `doc/adr/`, `architecture/decisions/`, …).
* Filename: `NNNN-title-with-dashes.md`: four-digit zero-padded number, lowercase, dashes (ADR-0005). If the repo pads to three digits, match it.
* Numbers are consecutive and never reused, even for rejected or superseded ADRs.
* MADR ships a bootstrap record `0000-use-markdown-architectural-decision-records.md`; some repos start there, others start at 0001.
* Categories: large projects may use subfolders (`decisions/backend/`, `decisions/ui/`); numbering is then per folder.
* Index: `README.md` at the root of the ADR folder lists every ADR in a table (number linked to the file, title, status, date), with one `### <category>` table per category subfolder. It is generated by `scripts/update_index.py` between `<!-- adrlog -->` and `<!-- adrlogstop -->` (the markers of the `adr-log` tool, so existing adr-log READMEs keep working). Text outside the markers is yours; text inside is overwritten. Refresh it whenever an ADR is added, renamed, or changes status.

## 13. Linking, superseding, deprecating

ADRs are an append-only log. Once accepted, don't rewrite the substance of an ADR to reflect a new decision; write a new ADR and link the two. Fixing typos, broken links or adding "superseded by" is fine.

To supersede ADR-0004 with a new ADR-0012:

1. Write `0012-…md` normally. In its Context, say briefly what changed since ADR-0004. In More Information, add `Supersedes [ADR-0004](0004-use-mongodb-for-orders.md).`
2. In `0004-…md`, change the front matter to `status: superseded by ADR-0012` and update its `date`. Optionally add a line at the top of its More Information: `Superseded by [ADR-0012](0012-use-postgresql-for-orders.md).`

To deprecate without replacement: set `status: deprecated`, update `date`, and add a sentence in More Information explaining why.

To accept a proposed ADR: change `status: proposed` to `accepted`, update `date`, and fill `decision-makers` if now known.

After any of these, rerun `scripts/update_index.py` so the README index shows the new statuses; a reader scanning the index should never be told a superseded decision is still accepted.

## 14. Converting other ADR formats to MADR

Michael Nygard's format (and adr-tools output) maps like this:

| Nygard / adr-tools | MADR |
| --- | --- |
| `# 3. Use Kafka` | `# Use Kafka for order events` (drop the number, sharpen the phrase) |
| `Date: 2024-02-01` line | `date: 2024-02-01` in front matter |
| `## Status` → `Accepted` | `status: accepted` in front matter |
| `## Context` | `## Context and Problem Statement` (add the explicit question) |
| (usually absent) | `## Decision Drivers`: extract forces mentioned in Context |
| (usually absent) | `## Considered Options`: extract alternatives mentioned anywhere; ask if none |
| `## Decision` "We will use Kafka …" | `## Decision Outcome` → `Chosen option: "Kafka", because …` |
| `## Consequences` prose | `### Consequences` as `Good, because …` / `Bad, because …` bullets |
| "Supersedes 2" / "Superseded by 5" status lines | status `superseded by ADR-0005`; links in More Information |

When converting, keep the original meaning. If the source never mentions alternatives, don't invent a rich comparison and present it as history; either ask the user, or list the alternatives you can reasonably infer and flag them in your reply as reconstructed.

Y-statements convert directly: *context* and *facing* → Context and Problem Statement / drivers; *we decided for* → Chosen option; *and neglected* → other Considered Options; *to achieve* → Good consequences; *accepting that* → Bad consequences.
