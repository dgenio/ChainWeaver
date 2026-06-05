# ChainWeaver Playground

A zero-install, interactive playground for ChainWeaver (issue
[#81](https://github.com/dgenio/ChainWeaver/issues/81)). Pick a pre-loaded
flow, edit its initial input as JSON, run it, and watch the step-by-step,
**LLM-free** execution trace — the same `FlowExecutor` the library ships.

## Features

- **Three pre-loaded example flows** — arithmetic (`double → add_ten → format`),
  a data flow (`extract → filter_positive → summarize`), and an MCP-style
  flow (`search → extract_facts → format_answer`). All deterministic, no I/O,
  no randomness.
- **Editable JSON input** — change the input and re-run to see results change.
- **Step-by-step trace** — per-step tool, success, duration, and outputs.
- **Mermaid visualization** — the flow graph and a per-run execution diagram
  with success/failure markers (links to the `chainweaver.viz` renderers).
- **Share links** — every run produces a `?share=<token>` query string that
  encodes the flow + input so a run round-trips through the URL. No server-side
  state.

## Scope

The playground demonstrates **deterministic, LLM-free execution** with an
editable **input**. Editing tool *functions* live (arbitrary user-supplied
Python) is intentionally out of scope: the hosted app runs untrusted input, so
executing user code would be a security risk and would break the determinism the
playground exists to show. To author your own tools and flows, use the library
directly — see the top-level [README](../README.md).

## Run locally

```bash
pip install -r playground/requirements.txt
streamlit run playground/app.py
```

The app opens at <http://localhost:8501>. To run it against local, unreleased
ChainWeaver changes instead of the released package, install the repo in
editable mode first:

```bash
pip install -e .
pip install streamlit streamlit-mermaid
streamlit run playground/app.py
```

## Deploy (Streamlit Community Cloud)

1. Push this repository to GitHub (already done for this repo).
2. On [share.streamlit.io](https://share.streamlit.io), create a new app
   pointing at this repository.
3. Set **Main file path** to `playground/app.py` and the **requirements file**
   to `playground/requirements.txt`.
4. Deploy. The app is stateless, so no secrets or persistent storage are
   required. The shareable `?share=<token>` links work on the deployed URL.

## Architecture

```text
playground/
├── app.py            Thin Streamlit UI (imports core; no flow logic here)
├── core.py           Streamlit-free flow builders, runner, diagrams, share codec
├── requirements.txt  streamlit + streamlit-mermaid + chainweaver
└── README.md         this file
```

All flow-building and execution logic lives in `core.py`, which imports **no
Streamlit** and is unit-tested in
[`tests/test_playground.py`](../tests/test_playground.py). `app.py` is a thin
presentation layer.
