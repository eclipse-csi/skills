# Establishing the threat model

Do this before reading any code for bugs. The maintainers' own threat model, where one exists, is the authority on where the trust boundary sits. Every later judgement about reachability and severity depends on it.

## Where to look

Search the repository for an explicit threat model. Check each of these and record what you found, including the negatives — "no SECURITY.md" is itself a data point.

- `docs/threat-model.md` and `threat-model.yaml`. These are the outputs of the Alpha-Omega `threat-model` skill (see below); if the project ships them, it has an explicit, structured threat model and you should use it in preference to everything else here. Its claims carry provenance tags — `(documented)`, `(maintainer)`, `(inferred)` — so you can see which parts the maintainers have actually confirmed.
- `SECURITY.md`, `THREAT_MODEL.md`, `.github/SECURITY.md`, and anything under `docs/` or `doc/` whose name contains `security`, `threat`, `trust`, `hardening`, or `architecture`.
- README and documentation sections titled Security, Threat model, Security considerations, Non-goals, Limitations, Assumptions, Deployment, or Safe usage.
- Published advisories: the GitHub Security tab, `CHANGELOG` entries tagged security, release notes for past CVEs. A past advisory is the maintainers saying that input class is untrusted.
- Configuration options and API parameters named `safe`, `unsafe`, `strict`, `trusted_*`, `allow_*`, `verify_*`, `insecure_*`, and their documentation. A `safe` mode tells you what the maintainers think the unsafe mode exposes. Note which mode is the default — that decides severity later.
- Code comments near trust-sensitive code. `grep -rni` for `untrusted`, `trusted`, `attacker`, `malicious`, `user-controlled`, `user-supplied`, `sanitize`, `must not`, `do not pass`, `security`. These are the threat model as the author actually wrote it, inline.
- Tests and fixtures named `malicious`, `evil`, `attack`, `exploit`, `fuzz`, `traversal`, `injection`, or that assert a rejection. A test that rejects a payload class declares that class in scope. A test that deliberately accepts a dangerous payload declares it a feature or a known limitation.
- Issue tracker labels and closed issues: `security`, `wontfix`, `not-a-bug`, `by-design`. A maintainer closing a security report as by-design is a threat-model decision. Record it; it is prior art for anything in the same area.

## What to extract

Write down, before you start the audit:

1. **Untrusted inputs.** Which inputs does the project treat as potentially hostile? Network requests, file contents, archive members, deserialised payloads, repository-local config, environment variables, command-line arguments — list each with the evidence for classifying it.
2. **Trusted inputs.** Which inputs does the project assume are operator- or developer-controlled? Config files, plugin code, caller-supplied blocks, build-time constants.
3. **Guarantees claimed.** What does the project promise? "Output is safe to embed in HTML", "paths cannot escape the root", "safe on untrusted input", "constant-time comparison". Each is a contract; violating one is a finding even if no classic sink is involved.
4. **Documented non-goals.** What does the project explicitly disclaim? "Not designed for untrusted input", "assumes a single-tenant deployment", "does not protect against a malicious plugin".
5. **Deployment assumptions.** Runs as root or unprivileged? Behind a reverse proxy? Single user or multi-tenant? Local tool or network service? These decide impact.

## How it governs the audit

The project's threat model takes precedence over the general trust-boundary defaults in SKILL.md. Those defaults exist for projects that say nothing; a project that has said something gets audited against what it said.

- **A declared untrusted input is across the boundary** even where the defaults would call it developer-controlled. A linter that documents running against arbitrary repositories has declared repository-local config files untrusted; a config-file finding in that project is valid. A build tool that documents reading only the operator's own project files has not.
- **A claimed guarantee is tested directly.** A sanitiser that documents "safe against XSS" and lets an event handler through has failed its contract. That is the finding, and it does not matter that the sanitiser never writes to the DOM itself.
- **A documented non-goal normally excludes findings inside it.** Note it under Methodology and move on. The exception is when the project's own quickstart, default configuration, or examples contradict the disclaimer — a README that says "not for untrusted input" above an example that pipes a web request into it has a documentation-versus-default conflict, and that conflict is the finding. Rate it on what the default does, not on what the disclaimer says, and quote both.
- **A by-design closure is prior art.** Your report must engage with the maintainers' stated reasoning, not just the code.

## If no threat model exists

Many projects have none. Then you have to produce one, and the way you produce it depends on whether the Alpha-Omega `threat-model` skill is available.

### Preferred: generate one with the `threat-model` skill

Check whether the skill is available. Look for `threat-model` in your available-skills list, for a `threat-model` plugin installed in the agent, or for `skills/threat-model/SKILL.md` / `.claude/skills/threat-model/SKILL.md` in the checkout. If it is not available, tell the user it can be installed from https://github.com/alpha-omega-security/threat-model (in Claude Code: `/plugin marketplace add alpha-omega-security/threat-model` then `/plugin install threat-model@threat-model`) and fall back to manual inference below. Do not clone and install it yourself mid-audit unless the user asks.

If it is available, invoke it on the project checkout before auditing — `/threat-model:threat-model` in Claude Code, or by following its SKILL.md directly — and let it write `docs/threat-model.md` (and the `threat-model.yaml` sidecar if it emits one). It is purpose-built for exactly this: it orients on the codebase and docs, writes a provisional model with every claim tagged `(documented)` / `(maintainer)` / `(inferred)`, and produces the per-parameter input trust table, adversary model, claimed and disclaimed security properties, downstream responsibilities, recurring scanner false positives, and a closed set of triage dispositions. That is a far more rigorous starting point than a model you sketch by hand, and it is in a format maintainers already use for triage, so a finding framed against it lands better.

Run it draft-first and do not block on its maintainer interview. The skill collects open questions for the maintainers in its `§1.18 Open questions` section; during an audit there is usually no maintainer to answer them, so accept the draft as-is and treat each unanswered question as a stated uncertainty. Keep the file in the audit workspace; do not commit it to the target repository unless asked.

Then map its sections onto the five parts this audit needs:

1. **Untrusted inputs** ← the input trust table: every parameter or input class the model marks as attacker-reachable.
2. **Trusted inputs** ← the same table: everything marked trusted, operator-controlled, or integrator-responsibility.
3. **Guarantees claimed** ← the claimed security properties, with their violation symptoms and severity tiers.
4. **Documented non-goals** ← the disclaimed properties, out-of-scope components, and downstream responsibilities.
5. **Deployment assumptions** ← scope, intended use, and the adversary model (including whether plugin authors, co-tenants, or peers are adversaries).

Two rules for using the generated model:

- **Respect the provenance tags.** A `(documented)` or `(maintainer)` claim is authoritative. An `(inferred)` claim is the skill's reading of the evidence, not the maintainers' word; before a finding rests on one, open the evidence the model cites and confirm it supports the inference. The rule against inferring a more hostile model than the documentation supports applies to the skill's inferences as much as to yours — if an `(inferred)` row marks config as untrusted and nothing in the docs backs that, do not report a config finding on its strength.
- **Carry the uncertainty into the report.** When a finding's reachability depends on an `(inferred)` claim or on an open `§1.18` question, say so in the report's Threat Model and Confidence sections, and cite the question number. That tells the maintainer precisely which single answer would confirm or dismiss the finding.

If the skill also provides `threat-model-triage`, you may run each finalised finding through it to obtain a disposition (in model, out of model, by design, redirect upstream) and cite that disposition in the report. A finding the model routes to "out of model" or "by design" is usually not reportable — see "How it governs the audit" above for the documentation-versus-default exception.

Record `threat_model_source` in the report frontmatter as the path of the generated file plus the note "generated by alpha-omega-security/threat-model, draft, N open questions".

### Fallback: infer one manually

If the skill is not available, infer the model yourself, in writing, from the strongest available evidence in this order:

1. The quickstart and default configuration.
2. The README's description of who uses it and how.
3. The public API surface and what types it accepts.
4. The test suite.

Mark every element of the inferred model as inferred and cite the evidence for it. Borrow the skill's discipline even without the skill: tag each claim `(documented)` or `(inferred)`, and keep a short list of open questions you would ask the maintainers.

Do not infer a more hostile model than the documentation supports. The absence of a statement that config is trusted is not a statement that config is untrusted. If the README's example shows the operator writing a value, infer that the operator is the trust boundary for that value. The purpose of inferring a threat model is to make your boundary assumptions explicit and checkable — not to license the hypothetical multi-tenant and indirect-influence scenarios the trust-boundary defaults forbid.

Record `threat_model_source` as "inferred" and the evidence you used.

### Either way

State the threat model you used — found, generated, or inferred — in every report, including a no-vulnerability report.
