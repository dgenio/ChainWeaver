# Adversarial flow-file corpus (issue #400)

A checked-in corpus of malformed / hostile flow files used to prove that every
bad shape maps to a **typed** `FlowSerializationError` — never an unhandled
traceback, a hang, or a wrong-type "success" — through both the library loaders
(`flow_from_json` / `flow_from_yaml`) and the `chainweaver validate` CLI.

Flow files are the primary untrusted input surface (repositories, contributor
PRs validated by the GitHub Action, generated drafts), so this corpus is the
regression net that the parse guardrails (#416) and the schema-ref policy (#345)
land on top of.

## Layout

- `invalid/` — small, hand-written malformed files, one failure mode each.
- `manifest.json` — the authoritative list. Each entry is:
  - `file` — path relative to this directory.
  - `format` — `json` or `yaml` (the loader to drive).
  - `expect_detail_substring` — a substring that must appear in the raised
    `FlowSerializationError.detail`.

The resource-shaped cases (oversized file, 10k steps, deep nesting, huge
string) are **generated in the test** rather than committed, so the corpus
stays tiny — see `tests/test_flow_corpus.py`.

## Adding a case

1. Add the file under `invalid/`.
2. Add an entry to `manifest.json`.
3. Pin only the exception **type** and a stable **substring** — never the full
   message text, which may evolve.

`tests/test_flow_corpus.py` enforces the manifest; new entries are picked up
automatically.
