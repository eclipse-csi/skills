# Reviewing an ADR

Use this when the user asks you to review, critique or improve an ADR, and as a final self-review of any ADR you wrote. `scripts/validate_madr.py` checks structure; this checklist covers the things a script can't judge: is the reasoning sound and honest, and will it be useful to someone reading it in two years?

## Contents

1. Review questions, in priority order
2. Common anti-patterns
3. Definition of done for a decision (ecADR)
4. How to report a review

---

## 1. Review questions, in priority order

**Is it one decision?** An ADR that bundles "use Kafka, adopt event sourcing, and split the monolith" should be split. Each decision can be superseded independently later.

**Would a newcomer understand the problem?** Read the Context as if you had never seen the codebase. Is the scope clear (which component)? Is it clear why the decision was needed *now*?

**Is the problem the one the decision solves?** Watch for a context that describes one problem and an outcome that solves a different or broader one.

**Are the alternatives genuine?** At least two options a reasonable team might actually pick. "Do nothing" included when realistic. No options that only exist to lose.

**Is the justification traceable?** The `because` should point at drivers. Could you rebuild the choice from the drivers and the pros/cons alone? If a driver changed, would a reader know which options to re-evaluate?

**Are the costs written down?** At least one `Bad, because` in Consequences and in the chosen option's pros/cons. Missing costs are the single most common weakness, and the one that hurts future maintainers most.

**Is the tone factual?** No marketing adjectives ("blazing fast", "industry-leading", "seamless"). Claims that matter should be sourced (benchmark, doc, incident).

**Is it verifiable and revisitable?** Is there a Confirmation, or at least a revisit trigger, for decisions that could drift?

**Is the metadata right?** Status matches reality; date is set; people fields only contain real names/groups. In a repository, the ADR appears in the folder's `README.md` index with its current status (`scripts/update_index.py --check`).

**Is it the right size?** A good ADR is typically one to two screens. Long design detail, API specs, or how-to instructions belong in linked docs.

## 2. Common anti-patterns

Olaf Zimmermann (co-author of MADR) catalogued typical ways ADRs go wrong. The names below follow his catalogue; descriptions are paraphrased:

| Anti-pattern | What it looks like | Fix |
| --- | --- | --- |
| Fairy Tale | Justification is shallow or only lists benefits. | Add the trade-off; state what was given up. |
| Sales Pitch | Marketing language, unsupported superlatives. | Replace adjectives with facts, numbers, sources. |
| Free Lunch Coupon | No negative consequences or risks at all. | Add `Bad, because …` items: cost, migration, lock-in, learning curve, new failure modes. |
| Dummy Alternative | Non-viable options added to make the winner look good. | Replace with real alternatives, or honestly state there was one realistic option and why. |
| Sprint / Rush | Only one option seriously considered; only short-term effects discussed. | Consider at least two options; add long-term consequences (operations, maintenance, exit cost). |
| Tunnel Vision | Only the local component's view; ignores ops, security, other teams, users. | Add drivers/consequences for affected stakeholders. |
| Maze | Drifts into unrelated topics or several decisions at once. | Cut to one decision; move tangents to their own ADRs or links. |
| Blueprint / Policy in Disguise | Reads like a cookbook or a rulebook, with no problem, options or rationale. | Restore the problem, options and justification; move instructions to docs. |
| Mega-ADR | Pages of architecture description, diagrams, and detailed design. | Keep the decision and rationale; link out to design docs. |
| Pseudo-accuracy | Weighted scoring matrices with made-up precision decide the outcome. | Keep reasoning qualitative unless the numbers are real measurements. |

## 3. Definition of done for a decision (ecADR)

Zimmermann's ecADR checklist is a useful gate before setting `status: accepted`:

* **E**vidence: there is reason to believe the chosen design will work (a spike, a prototype, prior experience, a reference).
* **C**riteria: at least two options were compared against explicit criteria (the drivers).
* **A**greement: the decision-makers (and ideally those consulted) agree; disagreements were heard.
* **D**ocumentation: the decision is captured (this ADR) and shared with those informed.
* **R**ealization / **R**eview: implementation is planned, and there is a point at which the decision will be reviewed.

If something is missing, the ADR can still be written, just as `proposed`, with the gap noted in More Information.

## 4. How to report a review

Lead with the two or three issues that matter most (usually: missing alternatives, missing costs, unclear problem), then list smaller fixes. Quote the line you're commenting on. Offer a corrected version of the ADR or of the specific sections; for a small number of fixes, show only the changed sections. Run `scripts/validate_madr.py` and fold its errors into the review in plain language rather than pasting raw output.
