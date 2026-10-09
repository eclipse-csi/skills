# Validation

## What a reproduction has to show

Before reporting any finding rated Medium or above, write a minimal reproduction script and run it. Paste the script and its observed output into the report's Validation section. The reproduction proves the vulnerable flow executes as you describe; it does not need to demonstrate the full attack, only that the dangerous behaviour occurs. A script that shows a crafted filename reaching `open()` outside the root is enough; you do not need to exfiltrate `/etc/passwd`.

Trace the data flow from source to sink and confirm the path is reachable through actual code paths, not just lexically present. Check for sanitisation, type coercion, or guards along the path that mitigate the issue, and say in the report which ones you checked and why they do not apply.

## Enumerating sources before giving up

Before concluding you cannot construct a reproduction, enumerate the mechanisms that produce the kind of value the sink consumes, write the list down, and try each one. Begin with the untrusted-input list from your threat model — it already names the sources that count for this project — then extend it with the sink-specific list below. The written list is your evidence that you looked.

Adapt these to the language and domain of the project.

### Sink takes a file path

argv, environment variables, config files, glob expansion, archive extraction (zip/tar member names), user-supplied filenames in uploads, redirect targets, URL path segments, template names, locale or theme identifiers, plugin or module names resolved to disk.

### Sink takes a method, function, class, or attribute name

`define_method`, `OpenStruct`, `Struct.new`, attribute macros, JSON-to-object or YAML-to-object patterns, `getattr`/`send`/`__send__`/`public_send`, dynamic dispatch tables keyed on input, plugin registries, deserialisation hooks, ORM column names from query parameters, GraphQL field resolvers.

### Sink takes a hostname or URL

User input, HTTP redirect targets (`Location` headers on 3xx), DNS responses, service-discovery payloads, parsed `Link` headers, webhook registration fields, OAuth callback and issuer URLs, `Host` and `X-Forwarded-*` headers, URLs embedded in fetched documents (sitemaps, feeds, OpenAPI specs), image and avatar URLs.

### Sink takes a SQL fragment or query parameter

Form fields, query strings, HTTP headers, cookies, deserialised objects, CSV/JSON import fields, sort and filter parameters, column or table names passed as identifiers, search terms reaching `LIKE` or full-text syntax.

### Sink takes a shell command or argument

argv, filenames (especially ones starting with `-`), git refs and branch names, environment variables, archive member names, values interpolated into `system`/`exec`/`subprocess` with `shell=True`, hostnames passed to `ping`/`ssh`/`curl`.

### Sink takes markup, a template, or a format string

Any text later rendered into HTML, Markdown, XML, PDF, or email; template names and template source; log messages reaching `format`/`printf`-style calls; error messages echoing input.

### Sink is a deserialiser or parser

Request bodies, uploaded files, cached objects, message-queue payloads, cookies and sessions, config files declared untrusted by the threat model, nested documents inside other documents (XML entities, zip-in-zip, YAML anchors).

## If you still cannot reproduce

Only after that enumeration may you write that you could not construct a reproduction. Explain precisely what stops you — missing test fixture, environment dependency, requires a network position you don't have, requires a victim configuration you cannot confirm — and downgrade Confidence accordingly.

"I traced the code and it looks exploitable" is not validation. "I could not find a realistic source" is only acceptable after you have shown your search.

## Tests that assert the dangerous behaviour

Read the tests. If a test deliberately asserts the behaviour you are about to report, the maintainers may consider it a feature, a known limitation, or backwards-compatible behaviour they intend to deprecate. Note this context in the report and engage with it. Do not silently ignore it, and do not treat it as automatically closing the finding — a feature that violates a documented guarantee or crosses a declared boundary is still a finding, just one the maintainers will push back on, and your report should anticipate that.
