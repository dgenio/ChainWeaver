"""Streamlit shell for the ChainWeaver interactive playground (issue #81).

Run locally::

    pip install -r playground/requirements.txt
    streamlit run playground/app.py

All flow-building, execution, diagram, and share logic lives in
``playground/core.py`` (Streamlit-free, unit-tested).  This file is only the
thin UI layer, so it is intentionally outside the linted/typed package scope.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

# ``streamlit run`` executes this file as a script, so the sibling ``core``
# module is not importable as ``playground.core`` without help.  Add this
# directory to the path and import it as a top-level module.  Streamlit reruns
# this script on most UI interactions, so guard the insertion to keep
# ``sys.path`` free of accumulating duplicate entries.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import core

try:  # Optional: render Mermaid diagrams inline when the helper is installed.
    from streamlit_mermaid import st_mermaid
except ImportError:  # pragma: no cover - exercised only without the extra
    st_mermaid = None


def _render_mermaid(diagram: str, *, key: str) -> None:
    if st_mermaid is not None:
        st_mermaid(diagram, key=key)
    else:
        st.caption(
            "Install `streamlit-mermaid` to render this inline, or paste it into mermaid.live:"
        )
        st.code(diagram, language="mermaid")


def main() -> None:
    st.set_page_config(page_title="ChainWeaver Playground", page_icon="🧵", layout="wide")
    st.title("🧵 ChainWeaver Playground")
    st.write(
        "Pick a pre-loaded flow, edit its input, and run it — deterministically, "
        "with **zero LLM calls between steps**. This is the same `FlowExecutor` "
        "the library ships."
    )

    # Restore a shared selection from the URL (?share=<token>) if present.
    params = st.query_params
    shared_name: str | None = None
    shared_input: dict[str, object] | None = None
    if "share" in params:
        share_param = params["share"]
        # ``st.query_params`` returns a single string in the current API, but a
        # repeated ``?share=a&share=b`` (or the legacy list-valued API) can hand
        # back a list — normalize to the last value before decoding so a stray
        # list never reaches ``decode_share`` and raises an uncaught error.
        if isinstance(share_param, (list, tuple)):
            share_param = share_param[-1] if share_param else ""
        try:
            shared_name, shared_input = core.decode_share(share_param)
        except ValueError as exc:
            st.warning(f"Ignoring invalid share link: {exc}")

    names = list(core.EXAMPLES)
    default_index = names.index(shared_name) if shared_name in core.EXAMPLES else 0
    name = st.sidebar.selectbox("Example flow", names, index=default_index)
    example = core.EXAMPLES[name]
    st.sidebar.write(example.description)

    if shared_name == name and shared_input is not None:
        default_input = shared_input
    else:
        default_input = example.default_input
    input_text = st.text_area(
        "Initial input (JSON)",
        value=json.dumps(default_input, indent=2),
        height=160,
    )

    st.subheader("Flow")
    _, flow = core.build_executor(example)
    _render_mermaid(core.flow_diagram(flow), key=f"flow-{name}")

    if st.button("▶ Run flow", type="primary"):
        try:
            initial_input = json.loads(input_text)
        except json.JSONDecodeError as exc:
            st.error(f"Initial input is not valid JSON: {exc}")
            return
        if not isinstance(initial_input, dict):
            st.error("Initial input must be a JSON object.")
            return

        result = core.run_example(name, initial_input)

        st.subheader("Result")
        if result.success:
            st.success(f"Flow `{result.flow_name}` succeeded in {result.total_duration_ms:.2f} ms")
        else:
            st.error(f"Flow `{result.flow_name}` failed")
        st.json(result.final_output)

        st.subheader("Step trace")
        st.dataframe(core.trace_rows(result), use_container_width=True)

        st.subheader("Execution diagram")
        _render_mermaid(core.result_diagram(result), key=f"result-{name}")

        token = core.encode_share(name, initial_input)
        st.subheader("Share this run")
        st.code(f"?share={token}", language="text")
        st.caption("Append the query string above to the playground URL to reproduce this run.")


if __name__ == "__main__":
    main()
