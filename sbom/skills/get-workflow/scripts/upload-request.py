#!/usr/bin/env python3
"""Draft the HelpDesk ticket that requests SBOM upload permission for a project.

Reads ./report.json and covers every product whose generated workflow uploads its SBOM
(pipeline.status generated, partial or patch-proposed): each name in
pipeline.upload_names, with the repository that runs the upload (pipeline.host_repo).

Writes the draft to project.upload_request in ./report.json and prints it, with a link
that opens a new Eclipse Foundation HelpDesk issue pre-filled with it. The ticket follows
the security handbook:
https://eclipse-csi.github.io/security-handbook/sbom/howto.html#prerequisite-request-upload-permission

The same report always gives the same ticket and link. Standard library only.
"""

import json
import os
import sys
import urllib.parse

REPORT = "report.json"
UPLOADING = ("generated", "partial", "patch-proposed")
LABELS = ["service:dependencytrack", "team:security"]
NEW_ISSUE_URL = "https://gitlab.eclipse.org/eclipsefdn/helpdesk/-/issues/new"
HANDBOOK = ("https://eclipse-csi.github.io/security-handbook/sbom/howto.html"
            "#prerequisite-request-upload-permission")
# Browsers and servers commonly refuse URLs much longer than this.
MAX_URL = 8000


def uploads(report: dict) -> tuple:
    """(entries, problems): one entry per upload name of every uploading product."""
    entries, problems, owner = [], [], {}
    for product, entry in (report.get("products") or {}).items():
        pipeline = entry.get("pipeline") or {}
        if pipeline.get("status") not in UPLOADING:
            continue
        names, workload = pipeline.get("upload_names") or [], pipeline.get("host_repo")
        if not names:
            problems.append(f"{product}: pipeline.upload_names is missing")
        if not workload:
            problems.append(f"{product}: pipeline.host_repo is missing")
        for name in names:
            if name in owner:
                problems.append(f"upload name {name!r} is used by both {owner[name]} and {product}")
            owner[name] = product
            entries.append({"product": product, "upload_name": name, "workload": workload})
    return entries, problems


def draft(project: dict, entries: list) -> dict:
    """The ticket title, description, labels and creation link."""
    title = f"{project['name']}: Request SBOM upload permission"
    rows = "\n".join(f"| {e['upload_name']} | {e['workload']} |" for e in entries)
    description = (
        "Please grant SBOM upload permission for the products below, so that their GitHub "
        "Actions workflows can upload SBOMs to sbom.eclipse.org through PIA.\n\n"
        f"**Project name:** {project['id']}\n\n"
        "| Product name | Workload name |\n"
        "|---|---|\n"
        f"{rows}\n\n"
        f"Please label: {', '.join(LABELS)}\n\n"
        f"Requested as described in the Eclipse security handbook: {HANDBOOK}\n")
    query = urllib.parse.urlencode({"issue[title]": title, "issue[description]": description},
                                   quote_via=urllib.parse.quote)
    url = f"{NEW_ISSUE_URL}?{query}"
    complete = len(url) <= MAX_URL
    if not complete:
        url = f"{NEW_ISSUE_URL}?" + urllib.parse.urlencode({"issue[title]": title},
                                                           quote_via=urllib.parse.quote)
    return {"title": title, "description": description, "labels": LABELS, "url": url,
            "url_includes_description": complete, "products": entries}


def main() -> int:
    """Write project.upload_request into report.json and print the ticket."""
    if not os.path.exists(REPORT):
        sys.exit(f"error: {REPORT} not found in the current directory")
    with open(REPORT, encoding="utf-8") as fh:
        report = json.load(fh)
    project = report.get("project") or {}

    entries, problems = uploads(report)
    if entries and not (project.get("name") and project.get("id")):
        problems.append("project.name and project.id are needed for the ticket "
                        "(run /list-repositories, or add them to report.json)")
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    if entries:
        project["upload_request"] = draft(project, entries)
    else:
        project.pop("upload_request", None)
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    if not entries:
        print("No product uploads an SBOM, so no upload permission is needed.")
        return 0
    request = project["upload_request"]
    print("Request SBOM upload permission: open this link to create the HelpDesk issue")
    print(request["url"])
    if not request["url_includes_description"]:
        print("\nThe link opens the issue with the title only: paste the description below into it.")
    print(f"\nTitle: {request['title']}\n\n{request['description']}", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
