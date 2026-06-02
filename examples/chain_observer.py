"""Suggest compiled flows from runtime tool traces with ChainObserver (issue #78).

Run with::

    python examples/chain_observer.py

Output: the flows ChainObserver proposes after watching an agent repeat the
same fetch -> validate -> transform sequence many times, plus the projected
LLM calls each compiled flow would avoid. Nothing is registered or executed —
suggestions are proposals for a human (or governance gate) to promote.
"""

from __future__ import annotations

from chainweaver import ChainObserver, FlowRegistry


def main() -> None:
    observer = ChainObserver()

    # --- 1. Watch the agent work (record runtime tool calls) ----------------
    # The agent walks the same deterministic path on most requests...
    for _ in range(8):
        observer.record("fetch", {"url": "https://api.example.com"}, {"body": "<json>"})
        observer.record("validate", {"body": "<json>"}, {"valid": True})
        observer.record("transform", {"body": "<json>"}, {"records": [1, 2, 3]})
        observer.end_trace()

    # ...and occasionally does something one-off that should NOT be compiled.
    observer.record("fetch", {"url": "https://api.example.com"}, {"body": "<json>"})
    observer.record("summarize", {"body": "<json>"}, {"summary": "hi"})
    observer.end_trace()

    print(f"Recorded {len(observer)} traces.\n")

    # --- 2. Mine repeated patterns into flow suggestions --------------------
    suggestions = observer.suggest_flows(min_occurrences=3, min_length=2)
    print(f"Suggested {len(suggestions)} flow(s):")
    for suggestion in suggestions:
        chain = " -> ".join(suggestion.tools)
        print(f"\n  {suggestion.flow.name}")
        print(f"    pattern:     {chain}")
        print(f"    occurrences: {suggestion.occurrences}")
        print(f"    confidence:  {suggestion.confidence}")
        print(f"    est. LLM calls avoided: {suggestion.estimated_llm_calls_avoided}")
        for index, step in enumerate(suggestion.flow.steps):
            print(f"    step {index}: {step.tool_name}  mapping={dict(step.input_mapping)}")

    # --- 3. Promote explicitly (governance gate lives with the caller) -----
    if suggestions:
        registry = FlowRegistry()
        registry.register_flow(suggestions[0].flow)
        print(f"\nPromoted '{suggestions[0].flow.name}' into a registry on approval.")


if __name__ == "__main__":
    main()
