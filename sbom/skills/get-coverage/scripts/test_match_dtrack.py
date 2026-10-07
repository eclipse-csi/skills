#!/usr/bin/env python3
"""Regression tests for match-dtrack.py's rules, on a small made-up fixture.

Run: python3 -m unittest <this file>   (standard library only)
"""

import importlib.util
import os
import unittest

spec = importlib.util.spec_from_file_location(
    "match_dtrack", os.path.join(os.path.dirname(os.path.abspath(__file__)), "match-dtrack.py"))
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)

GH = "https://github.com/"
PRODUCTS = {
    "Eclipse Foo": {
        "foo-core": {"repos": [GH + "eclipse-foo/foo"]},
        "foo-server": {"repos": [GH + "eclipse-foo/foo"]},
        "foo-server-image": {"repos": [GH + "eclipse-foo/foo"]},
        "foo-web-backend": {"repos": [GH + "eclipse-foo/foo-web"]},
        "foo-agent-image": {"repos": [GH + "eclipse-foo/agent"]},
    },
    "Eclipse Bar": {
        "bar-cli": {"repos": [GH + "eclipse-bar/bar-tools"]},
        "bar-lib": {"repos": [GH + "eclipse-bar/bar-lib"]},
    },
    "Eclipse Baz": {
        "baz-library": {"repos": [GH + "eclipse-baz/baz"]},
    },
}
PROJECTS = {"Eclipse Foo": {"short_id": "foo"}, "Eclipse Bar": {"short_id": "bar"},
            "Eclipse Baz": {"short_id": "baz"}}
FACTS = {
    GH + "eclipse-bar/bar-lib": {"root_pom": {"group_id": "org.eclipse.bar", "artifact_id": "bar-parent"}},
    GH + "eclipse-bar/bar-tools": {"root_package_json": {"name": "@eclipse-bar/cli"}},
}


def dt(name, purl=None, refs=(), classifier="LIBRARY"):
    """A Dependency-Track project as dump-dtrack-projects.py writes it."""
    return {"name": name, "purl": purl, "classifier": classifier,
            "externalReferences": [{"type": "vcs", "url": u} for u in refs]}


class MatchTest(unittest.TestCase):
    """Each rule, the narrowing, and the refusal to guess."""

    def setUp(self):
        self.m = md.Matcher(PRODUCTS, PROJECTS, FACTS)

    def check(self, project, expected):
        found = self.m.match(project)
        self.assertEqual(found and (found[0], found[1][1]), expected)

    def test_repo_reference_with_subpath(self):
        self.check(dt("x", refs=[GH + "eclipse-bar/bar-lib/releases"]), ("repo", "bar-lib"))

    def test_repo_from_purl_vcs_url_and_github_packages(self):
        self.check(dt("x", purl="pkg:npm/y@1?vcs_url=git%2Bhttps%3A%2F%2Fgithub.com%2Feclipse-bar%2Fbar-tools.git"),
                   ("repo", "bar-cli"))
        self.check(dt("x", refs=["https://maven.pkg.github.com/eclipse-bar/bar-lib"]), ("repo", "bar-lib"))

    def test_classifier_picks_image(self):
        self.check(dt("foo-server", refs=[GH + "eclipse-foo/foo"], classifier="CONTAINER"),
                   ("repo", "foo-server-image"))

    def test_name_narrows_within_repo(self):
        self.check(dt("Foo Server", refs=[GH + "eclipse-foo/foo"]), ("repo", "foo-server"))

    def test_coordinates(self):
        self.check(dt("x", purl="pkg:maven/org.eclipse.bar/bar-parent@2.0-SNAPSHOT?type=pom"),
                   ("coordinates", "bar-lib"))
        self.check(dt("x", purl="pkg:npm/%40eclipse-bar/cli@1.0"), ("coordinates", "bar-cli"))
        self.check(dt("x", purl="pkg:golang/github.com/eclipse-baz/baz@v0.1?type=module"),
                   ("coordinates", "baz-library"))

    def test_name_forms(self):
        self.check(dt("Foo Web - Backend"), ("name", "foo-web-backend"))
        self.check(dt("agent", classifier="CONTAINER"), ("name", "foo-agent-image"))
        self.check(dt("bar-tools"), ("name", "bar-cli"))
        self.check(dt("baz"), ("name", "baz-library"))

    def test_no_guessing(self):
        self.check(dt("x", refs=[GH + "eclipse-foo/foo"]), None)
        self.check(dt("server"), None)
        self.check(dt("unknown"), None)

    def test_decisions(self):
        decisions = {"names": {"a": {"project": "P", "product": "p-a"}},
                     "prefixes": [{"prefix": "b-", "project": "P", "product": "p-b"}],
                     "ignore": {"c": "not a product"}}
        self.assertEqual(md.decide(decisions, dt("a")), ("P", "p-a"))
        self.assertEqual(md.decide(decisions, dt("b-1")), ("P", "p-b"))
        self.assertEqual(md.decide(decisions, dt("c")), "ignored")
        self.assertIsNone(md.decide(decisions, dt("d")))


if __name__ == "__main__":
    unittest.main()
