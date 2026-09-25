# Worked MADR examples

Three examples at different sizes. They are illustrations of shape and tone, not content to copy.

## Contents

1. Full ADR (significant decision with real trade-offs)
2. Minimal ADR (small decision)
3. Superseding an older ADR

---

## 1. Full ADR

File: `docs/decisions/0007-use-opentelemetry-for-distributed-tracing.md`

```markdown
---
status: accepted
date: 2026-03-12
decision-makers: Amara Diallo (platform lead), Jonas Berg
consulted: SRE on-call group, Security (Kim Lee)
informed: All service teams
---

# Use OpenTelemetry for Distributed Tracing

## Context and Problem Statement

Our 14 backend services log independently, and a checkout request crosses up to six of them.
During the February payment incident (INC-2291) it took four hours to find which service added 3 s of latency, because nothing connects the logs of one request across services.
How should we trace requests across services?

## Decision Drivers

* Find the slow or failing hop of a single request in minutes, not hours
* Avoid lock-in to one observability vendor; our Datadog contract is up for renewal in 2027
* Instrumentation must work for both our Go and Kotlin services
* Overhead under 2 % CPU per service at current traffic

## Considered Options

* OpenTelemetry SDKs with the OTel Collector
* Datadog APM agents
* Correlation IDs in logs only

## Decision Outcome

Chosen option: "OpenTelemetry SDKs with the OTel Collector", because it is the only option that gives full request traces without tying our instrumentation to one vendor, and the collector lets us keep sending data to Datadog today while leaving the 2027 renewal open.

### Consequences

* Good, because any request can be followed end to end in the trace view
* Good, because switching or adding a backend is a collector config change, not a code change in 14 services
* Neutral, because we still pay Datadog for storage and UI for now
* Bad, because the team must run and upgrade the collector fleet (new on-call runbook needed)
* Bad, because auto-instrumentation for our Kotlin coroutine code is incomplete; some spans need manual code

### Confirmation

* A CI check fails any service whose build does not include the OTel SDK dependency.
* The SRE team verifies in the April game day that a synthetic checkout shows one trace spanning all six services.
* Revisit before the Datadog renewal decision in 2027-Q1.

## Pros and Cons of the Options

### OpenTelemetry SDKs with the OTel Collector

Vendor-neutral CNCF standard: <https://opentelemetry.io/>

* Good, because it is vendor-neutral and supported by all major backends
* Good, because the collector can sample, filter and route data centrally
* Neutral, because overhead measured in the spike was 1.1 % CPU, within budget
* Bad, because we operate an extra component (the collector)
* Bad, because Kotlin coroutine context propagation needs manual work

### Datadog APM agents

* Good, because it is the fastest to roll out; agents are already installed for metrics
* Good, because auto-instrumentation for Kotlin is more complete today
* Bad, because instrumentation is proprietary, which weakens our position at renewal
* Bad, because moving away later means re-instrumenting all services

### Correlation IDs in logs only

* Good, because it is cheap and needs no new infrastructure
* Neutral, because it would help with error searches even without tracing
* Bad, because it shows which services a request touched but not where time was spent, so it would not have shortened INC-2291

## More Information

The two-week spike (PR #1832) instrumented checkout and cart; results and the overhead measurement are in the spike report linked from the PR.
Agreed in the architecture sync on 2026-03-10; Jonas raised the collector operating cost, addressed by the SRE runbook action item.
```

Why it works: the title states the decision; the context has scope, a concrete trigger and a question; drivers are specific; the justification names the drivers that decided it; costs are honest; confirmation is checkable; each option gets a fair hearing.

## 2. Minimal ADR

File: `docs/decisions/0008-use-pnpm-as-package-manager.md`

```markdown
---
status: accepted
date: 2026-04-02
decision-makers: Web team
---

# Use pnpm as Package Manager

## Context and Problem Statement

The web monorepo mixes npm and Yarn 1 across packages, and CI installs take about 6 minutes.
Which package manager should all packages in the monorepo use?

## Considered Options

* pnpm
* npm workspaces
* Yarn 4

## Decision Outcome

Chosen option: "pnpm", because it cut CI install time to under 2 minutes in our trial branch, has first-class workspace support, and its strict dependency resolution already surfaced two undeclared dependencies.

### Consequences

* Good, because CI installs are about 3× faster
* Bad, because contributors must install pnpm (documented in CONTRIBUTING.md; Corepack pins the version)
```

Small decisions don't need drivers or a pros/cons section; the one-sentence justification carries it. Don't pad a minimal ADR with empty optional sections.

## 3. Superseding an older ADR

Suppose ADR-0003 chose Jest and the new ADR-0009 moves to Vitest.

New file `0009-use-vitest-for-unit-tests.md` (excerpt):

```markdown
---
status: accepted
date: 2026-05-20
decision-makers: Web team
---

# Use Vitest for Unit Tests

## Context and Problem Statement

ADR-0003 chose Jest in 2024. Since moving the build to Vite (ADR-0006), Jest needs a separate Babel transform pipeline that diverges from the production build and doubles test startup time.
Which test runner should the web packages use now?

...

## More Information

Supersedes [ADR-0003](0003-use-jest-for-unit-tests.md).
```

Edit to the old file `0003-use-jest-for-unit-tests.md` (front matter only, plus one link; the body stays as history):

```markdown
---
status: superseded by ADR-0009
date: 2026-05-20
decision-makers: Web team
---
```

and at the start of its More Information section:

```markdown
Superseded by [ADR-0009](0009-use-vitest-for-unit-tests.md).
```
