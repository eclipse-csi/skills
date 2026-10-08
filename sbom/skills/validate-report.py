#!/usr/bin/env python3
"""Validate ./report.json against schema.json, plus the cross-field rules the schema
cannot express. It always checks report.json in the current directory.

Every skill in the chain runs this as the last action of its record step. The schema is
`additionalProperties: false` almost everywhere, so without a validator drift is silent:
a misspelled key is simply lost, and the next skill reads an absent field as an
unobserved fact.

This script finds its own schema, so it works from any directory and in any install
form. Invoke it by absolute path -- a skill substitutes its own base directory:

    python3 "<skill base directory>/../validate-report.py"
    python3 "<skill base directory>/../validate-report.py" --expect-fail   # report.json must fail

Where python3 does not exist (some Windows installs), use `python`.

Without `jsonschema` installed the structural check cannot run. Rather than validating
nothing, the cross-field rules still run and the report is marked PARTIAL. A partial
run is never reported as OK and always exits non-zero: a skipped check recorded as a
pass is worse than no check at all.

Exit status is 0 when the report passed in full, 1 otherwise (inverted under
--expect-fail).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - environment problem, not a report problem
    Draft202012Validator = None

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
REPORT = Path("report.json")

# ---------------------------------------------------------------------------
# Cross-field rules
#
# These are real constraints from the skills that JSON Schema cannot express, either
# because they compare values across sibling subtrees or because they depend on data
# the schema deliberately leaves open. Each one exists because violating it produces a
# plausible-looking report that yields a wrong SBOM — not merely an untidy one.
# ---------------------------------------------------------------------------


def _rule_hook_immutable_input(report: dict[str, Any]) -> Iterator[str]:
    """`immutable_input: none` forces `extend-existing` (get-metadata §4).

    Nothing immutable to rebuild from means only the release job holds the truth, so a
    standalone workflow would re-resolve against whatever HEAD happens to be — an SBOM
    for something that was never released.
    """
    for name, product in (report.get("products") or {}).items():
        hook = ((product.get("release") or {}).get("hook")) or {}
        if hook.get("immutable_input") == "none" and hook.get("strategy") == "new-workflow":
            yield (
                f"products.{name}.release.hook: immutable_input 'none' with strategy "
                f"'new-workflow'. With no immutable input a standalone workflow cannot "
                f"reproduce the release; get-metadata §4 requires 'extend-existing'."
            )


def _rule_fidelity_risk_null(report: dict[str, Any]) -> Iterator[str]:
    """`fidelity_risk: null` is only honest for `oci-digest` (get-metadata §5).

    Every other input re-resolves dependencies, which can drift from what shipped. A
    null risk on those claims a guarantee the approach does not provide.
    """
    for name, product in (report.get("products") or {}).items():
        hook = ((product.get("release") or {}).get("hook")) or {}
        if "fidelity_risk" not in hook:
            continue
        if hook["fidelity_risk"] is None and hook.get("immutable_input") != "oci-digest":
            yield (
                f"products.{name}.release.hook: fidelity_risk is null but "
                f"immutable_input is {hook.get('immutable_input')!r}. Only 'oci-digest' "
                f"describes the shipped bytes exactly; anything else re-resolves and "
                f"carries drift risk that must be stated."
            )


def _rule_extend_existing_target(report: dict[str, Any]) -> Iterator[str]:
    """`extend-existing` needs a `target` naming the pipeline to patch."""
    for name, product in (report.get("products") or {}).items():
        hook = ((product.get("release") or {}).get("hook")) or {}
        if hook.get("strategy") == "extend-existing" and not hook.get("target"):
            yield (
                f"products.{name}.release.hook: strategy 'extend-existing' with no "
                f"'target'. There is no way to say which pipeline to patch."
            )


def _rule_sources_in_repos(report: dict[str, Any]) -> Iterator[str]:
    """Every `sources[].repo` must exist in `project.repos`.

    A source pointing at a repo the project does not own is either a typo or a product
    boundary nobody confirmed. Skipped when the report has no project block, since a
    report can legitimately be hand-authored from a bare repo list.
    """
    repos = {r.get("name") for r in ((report.get("project") or {}).get("repos") or [])}
    if not repos:
        return
    for name, product in (report.get("products") or {}).items():
        for i, source in enumerate(product.get("sources") or []):
            if source.get("repo") not in repos:
                yield (
                    f"products.{name}.sources[{i}].repo {source.get('repo')!r} is not "
                    f"in project.repos."
                )


def _rule_shipping_repos_covered(report: dict[str, Any]) -> Iterator[str]:
    """A `ships: true` repo must appear in a product or in `project.coverage_gaps`.

    This is the reconciliation CLAUDE.md asks for: a repo that ships but has no product
    and no recorded gap is an SBOM nobody will notice is missing. Warning-level, because
    it is legitimate mid-chain — before get-workflow has run there are no coverage_gaps
    yet.
    """
    project = report.get("project") or {}
    covered = {
        s.get("repo")
        for p in (report.get("products") or {}).values()
        for s in (p.get("sources") or [])
    }
    gapped = {g.get("repo") for g in (project.get("coverage_gaps") or [])}
    for repo in project.get("repos") or []:
        if repo.get("ships") is True and repo.get("name") not in covered | gapped:
            yield (
                f"project.repos: {repo.get('name')!r} is marked ships:true but appears "
                f"in no product's sources and in no project.coverage_gaps entry."
            )


def _rule_generator_targets_matrix(report: dict[str, Any]) -> Iterator[str]:
    """A matrixed build root needs one generator target per matrix entry.

    Several generators bake the target into the document (cyclonedx-gomod bakes
    GOOS/GOARCH), so one SBOM for a matrixed product is silently wrong rather than
    merely incomplete.
    """
    for name, product in (report.get("products") or {}).items():
        generators = product.get("generator") or []
        if not generators:
            continue
        for source in product.get("sources") or []:
            matrix = (source.get("build") or {}).get("matrix") or []
            if len(matrix) <= 1:
                continue
            key = (source.get("repo"), source.get("path"))
            for gen in generators:
                gsrc = gen.get("source") or {}
                if (gsrc.get("repo"), gsrc.get("path")) != key:
                    continue
                if len(gen.get("targets") or []) != len(matrix):
                    yield (
                        f"products.{name}.generator[{gen.get('tool')}]: build root "
                        f"{key[0]}:{key[1]} has {len(matrix)} matrix targets but the "
                        f"generator records {len(gen.get('targets') or [])}. A matrixed "
                        f"build root needs one SBOM per target."
                    )


def _rule_pipeline_needs_release(report: dict[str, Any]) -> Iterator[str]:
    """A pipeline that emitted files needs the `release` block it was derived from."""
    for name, product in (report.get("products") or {}).items():
        pipeline = product.get("pipeline") or {}
        if pipeline.get("status") in {"generated", "partial", "patch-proposed"}:
            if not product.get("release"):
                yield (
                    f"products.{name}: pipeline.status is {pipeline['status']!r} but the "
                    f"product has no release block. The trigger and hook it was built "
                    f"from are unrecorded, so the workflow cannot be reviewed."
                )


ERROR_RULES = (
    _rule_hook_immutable_input,
    _rule_fidelity_risk_null,
    _rule_extend_existing_target,
    _rule_sources_in_repos,
    _rule_generator_targets_matrix,
    _rule_pipeline_needs_release,
)

WARNING_RULES = (_rule_shipping_repos_covered,)


def validate(path: Path, schema: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one report file.

    `schema` is None when jsonschema is unavailable; the cross-field rules still run,
    and main() reports the result as PARTIAL rather than OK.
    """
    try:
        report = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"not valid JSON: {exc}"], []

    errors = []
    if schema is not None:
        errors += [
            "/" + "/".join(map(str, e.path)) + ": " + e.message
            for e in sorted(Draft202012Validator(schema).iter_errors(report),
                            key=lambda e: list(e.path))
        ]
    for rule in ERROR_RULES:
        errors.extend(rule(report))
    warnings = [w for rule in WARNING_RULES for w in rule(report)]
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expect-fail", action="store_true",
                        help="invert the exit status: succeed only if report.json fails. "
                             "Used to prove the validator actually rejects bad input — "
                             "one that never rejects anything proves nothing.")
    parser.add_argument("--quiet", action="store_true", help="suppress warnings")
    args = parser.parse_args()

    degraded = Draft202012Validator is None
    if degraded:
        print("jsonschema is not installed - structural validation SKIPPED.",
              file=sys.stderr)
        print("  pip install jsonschema   (or: uv pip install jsonschema)",
              file=sys.stderr)
        schema = None
    else:
        schema = json.loads(SCHEMA_PATH.read_text())
        Draft202012Validator.check_schema(schema)

    failed = True
    if not REPORT.exists():
        print(f"{REPORT}: MISSING", file=sys.stderr)
    else:
        errors, warnings = validate(REPORT, schema)
        failed = bool(errors)
        if errors:
            print(f"{REPORT}: FAIL ({len(errors)} error(s))")
            for e in errors:
                print(f"  ERROR   {e}")
        elif degraded:
            print(f"{REPORT}: PARTIAL - cross-field rules passed, schema check skipped")
        else:
            print(f"{REPORT}: OK")
        if warnings and not args.quiet:
            for w in warnings:
                print(f"  WARNING {w}")

    if args.expect_fail:
        if failed:
            print("\nreport rejected, as expected")
            return 0
        print("\nEXPECTED FAILURE: the report validated when it should not have")
        return 1
    if degraded:
        # A skipped check must never read as a pass, so a partial run cannot exit 0.
        print("\nPARTIAL RUN: install jsonschema and re-run before trusting this report.")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
