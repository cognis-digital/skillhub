# Demo 01 - Basic: install a skill with a dependency

This demo ships a tiny local registry under `registry/` containing three
skills, one of which depends on another:

- `web-fetch` (1.0.0) - fetch a URL (leaf dependency)
- `summarize` (2.1.0) - summarize text; **requires** `web-fetch`
- `pdf-extract` (0.3.0) - extract text from a PDF (standalone)

## Try it

List everything in the registry:

```
python -m skillhub --format table list -r demos/01-basic/registry
```

Search (ranked by name/tag/description hits):

```
python -m skillhub search summarize -r demos/01-basic/registry
```

Inspect a skill and see its dependency install order:

```
python -m skillhub info summarize -r demos/01-basic/registry
```

Install `summarize` into an agent skills directory. Because `summarize`
requires `web-fetch`, both are installed in dependency order:

```
python -m skillhub --format json install summarize \
    -r demos/01-basic/registry -t /tmp/agent-skills
```

Re-running the same install is idempotent (skills already at the same content
hash are reported under `skipped`). See what is installed:

```
python -m skillhub installed -t /tmp/agent-skills
```

Removing `web-fetch` while `summarize` still needs it fails with a non-zero
exit code (dependency protection); remove `summarize` first.
