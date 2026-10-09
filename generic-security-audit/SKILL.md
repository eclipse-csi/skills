---
name: generic-security-audit
description: Audit a codebase for security vulnerabilities in its first-party code and write validated, reproducible findings as structured report files. Use this skill whenever the user asks for a security review, vulnerability research, a code audit, a pentest of a library or repo, "find vulns in", "is this safe", "look for injection / traversal / SSRF / deserialisation bugs", or to assess whether a validation, parsing, sanitising, or crypto library actually fulfils its contract — even if they do not say "security audit" or ask for a report. Also use it when the user wants a threat model derived for a repository, or asks whether a specific bug they found is "actually exploitable".
---

# Security Audit

Audit a project's own source code for vulnerabilities an external attacker can reach, prove each finding with a reproduction, and write one report file per finding. The target is first-party code: dependency CVEs are out of scope, and a finding is only valid if the vulnerable logic lives in this project's files.

Read the whole repository's threat model before reading any code for bugs. Almost every false positive in a security audit is a trust-boundary mistake — reporting as an attack something the operator did to themselves — and the only defence is to decide where the boundary sits before you start looking for things that cross it.

## Workflow

1. **Establish the threat model** — read `references/threat-model.md` and follow it. Produce a written threat model (found or inferred) before anything else.
2. **Map the attack surface** — list the entry points that take untrusted input as the threat model defines it.
3. **Hunt** — trace from those entry points to dangerous sinks, and test any documented guarantee directly.
4. **Validate** — reproduce each candidate finding. `references/validation.md` has the source-enumeration lists.
5. **Rate severity** — against the rubric in `references/severity.md`, before writing the report.
6. **Check prior art** — search issues, PRs, and git history for this package's own history with the bug.
7. **Write reports** — one file per finding from `assets/report-template.md`, or a single `assets/no-vuln-template.md` if nothing survived.
8. **Final quality pass** — cut anything that does not survive "can an attacker actually reach this, and is the impact worth a security report rather than a bug report?"

## Step 1: Threat model

This is the step that decides whether the rest of the audit is any good. `references/threat-model.md` lists where projects state their threat model (SECURITY.md, README non-goals sections, advisories, `safe`/`unsafe` options, inline comments, test fixtures, by-design issue closures), what to extract from it, and how to infer one when nothing is written down.

If the project has no threat model and the Alpha-Omega `threat-model` skill (https://github.com/alpha-omega-security/threat-model) is available, generate one with it rather than sketching one by hand; the reference explains how to invoke it, how to map its output onto the audit, and how to treat its `(inferred)` claims. Fall back to manual inference only when the skill is not available.

The output of this step is a short written document with five parts: untrusted inputs, trusted inputs, guarantees claimed, documented non-goals, deployment assumptions — each with the evidence for it. Every later judgement cites this document, and every report includes it.

The project's threat model takes precedence over the general trust-boundary defaults below. Those defaults are for projects that say nothing.

## Step 2: Attack surface and prioritisation

Focus first on code that handles untrusted input as classified by the threat model: parsers, request handlers, deserialisation entry points, protocol implementations, authentication and authorisation gates. Move to internal utility code only after the attack surface is covered. If the codebase is large, name the areas you did not reach and why.

For libraries whose purpose is validation, parsing, or security (IP address validation, input sanitisation, cryptographic operations, authentication), the library's input *is* the application's untrusted data. The trust boundary passes through the library, not around it. A validation method that accepts input it should reject is a vulnerability even if the library contains no dangerous sink of its own.

## Step 3: Hunt

You may install dependencies and read their source to understand how the project uses them, but the audit target is the project's own code.

Trace data flow from source to sink and confirm the path is reachable through actual code paths, not just lexically present. Check for sanitisation, type coercion, or guards along the path. Read the tests: a test that deliberately asserts the dangerous behaviour means the maintainers consider it a feature, a known limitation, or compatibility behaviour they intend to deprecate. Engage with that in the report — do not ignore it, and do not treat it as automatically closing the finding.

### Trust-boundary defaults

Apply these where the threat model is silent.

The attacker is not the developer calling the library. If a finding requires the application author to pass malicious input to their own dependency, it is not a finding. The boundary sits between the library and data the application receives from outside: network input, file contents, environment variables where they cross privilege boundaries, deserialised data.

A config option that takes a file path is not path traversal. A method that runs a caller-supplied block is not code injection. A regex compiled from a config file the operator wrote is not ReDoS. These are the library doing what it was told.

Evaluate the boundary as it exists in the documented deployment. Do not construct hypothetical multi-tenant, templated-config, or indirect-influence scenarios to manufacture a boundary the documentation does not describe. If the README's example shows the operator writing a value, the operator is the trust boundary for that value. "But what if a lower-privileged process generates the config" is a finding in whatever generates the config, not in this library.

A bug that causes an exception, wrong output, or a hang is a security finding only if an attacker can trigger it across the boundary to deny service to other users, corrupt shared state, or escalate privilege. A method that raises on bad input from its own caller is a bug report.

## Step 4: Validate

Any finding rated Medium or above needs a minimal reproduction script, run, with its observed output pasted into the report. The reproduction proves the vulnerable flow executes as described; it need not demonstrate the full attack.

Before concluding you cannot reproduce, enumerate every mechanism that could produce the value the sink consumes, write the list down, and try each one. Start from the untrusted-input list in your threat model. `references/validation.md` has per-sink starting lists. Only after that enumeration may you say you could not construct a reproduction — and then say precisely what stopped you and downgrade Confidence. "I traced the code and it looks exploitable" is not validation.

## Step 5: Severity

Rate before writing, using `references/severity.md`. The short version: Critical means it works on a fresh install following the quickstart with no precondition at all; any "the attacker needs X" disqualifies Critical. A violation of an explicitly documented guarantee starts at High. A chain of low-severity issues is one finding rated at the combined impact, provided each link is individually reachable.

## Step 6: Prior art

Before finalising, check whether this maintainer has already seen this report. Search the repo's issues and pull requests, open and closed. Run `git log --all --grep` with keywords from the finding. The question is this package's history, not whether the weakness class has a CVE somewhere else.

State what you searched and what you found. Known and fixed later → the report becomes a note confirming a known issue with its affected range. Known and unfixed → cite the existing report and add what your analysis contributes. Related variant fixed, this one left open → say so; that shapes disclosure. Closed as by-design → your report must address the maintainers' reasoning and explain what is different about this variant or why the reasoning no longer holds.

## Step 7: Reports

Write each validated finding to `reports/{repository-name}--{number}.md`, `{number}` zero-padded to three digits starting at `001`; if the name is taken, use the next free number. Use `assets/report-template.md` exactly — every section, in order. The `## Threat Model` section is where you show which input class the finding crosses and why the project treats it as untrusted.

If nothing survived validation, write one `assets/no-vuln-template.md` report. It must state the threat model you audited against and list every suspicious pattern you examined with the reason you ruled it out, so a reviewer can spot a wrong rejection. "I saw the eval and concluded X" is checkable; silence is not.

## Step 8: Quality pass

Prefer fewer, high-confidence findings over many speculative ones. More than ten findings is a signal to re-check the lower-confidence ones against the bar above.

## Key constraints

1. **Threat model first.** Where the project has one, it defines the trust boundary. Where it does not, generate one with the `threat-model` skill if available, otherwise infer one from the documentation — and say which you did.
2. **The attacker is external.** Developer-controlled config is not attacker input unless the project says otherwise.
3. **Validation libraries are the boundary.** Input passed through them is untrusted.
4. **Guarantees are contracts.** A documented security claim that does not hold is a finding, sink or no sink.
5. **Reproduce it.** Medium and above require a script with observed output.
6. **Chains count** at their combined severity.
7. **Prior art** in this repo's issues and history, including by-design closures.
8. **Quality over quantity.**
9. **Severity discipline.** A precondition means it is not Critical.
