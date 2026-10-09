# Severity rubric

Rate the finding before you write the report, not as you write the section. Writing first tends to inflate — the prose makes the attack feel more real than the preconditions allow.

## Critical

Works on a fresh install following the project's quickstart or default example configuration, with no additional setup. Unauthenticated RCE, auth bypass, secret disclosure — reachable by anyone who can send a request.

Any precondition the attacker must satisfy disqualifies Critical: file existence, permission state, environment variable already set, race window, non-default configuration. If you find yourself writing "the attacker needs X" anywhere in the report, it is not Critical.

## High

RCE or data theft with realistic preconditions, or a default that silently breaks a security guarantee — TLS verification off, CSRF absent on state-mutating routes, credentials forwarded across origins. The precondition is something a normal deployment satisfies without the operator doing anything unusual.

A violation of a guarantee the project explicitly documents starts at High; the project told users they could rely on it.

## Medium

Requires significant attacker positioning, an unusual but plausible victim configuration, or a chain of conditions that each individually hold often enough to matter.

## Low

Requires unrealistic preconditions, has narrow impact, or is largely neutralised by the deployment environment most users run.

A finding that sits inside a documented non-goal but is still reportable under the documentation-versus-default rule (see `threat-model.md`) is capped at Low unless the default configuration itself triggers it.

## Vulnerability chains

Multiple low-severity issues that combine into a higher-impact attack are a valid finding. Report the chain as a single finding and rate it at the severity of the combined impact, not the individual steps. Each link must be individually reachable; do not chain hypotheticals.

## Quick self-check

- Did I write "the attacker needs" anywhere? → not Critical.
- Does the default config satisfy every precondition on its own? → High is on the table.
- Does the project document the guarantee this breaks? → start at High.
- Is this inside a documented non-goal? → Low unless the defaults trigger it.
- Am I rating the chain or the weakest link? → the chain.
