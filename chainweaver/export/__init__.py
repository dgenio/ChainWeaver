"""Schema-export adapters for external agent frameworks (issue #25).

These adapters emit ChainWeaver flows and tools as the JSON schemas
that downstream frameworks expect:

- :mod:`chainweaver.export.openai` — OpenAI function-calling schema.
- :mod:`chainweaver.export.anthropic` — Anthropic ``tool_use`` schema.
- :mod:`chainweaver.export.callable` — plain ``dict → dict`` callables
  for any framework that accepts arbitrary Python callables.

The adapters are intentionally *dependency-free* — they emit dict /
str payloads only, never importing the ``openai`` or ``anthropic``
packages.  Runtime integration with those clients is out of scope for
this module; that is the consumer's responsibility.
"""

from __future__ import annotations

from chainweaver.export.anthropic import (
    flow_to_anthropic_tool,
    tool_to_anthropic_tool,
)
from chainweaver.export.callable import (
    flow_to_callable,
    tool_to_callable,
)
from chainweaver.export.openai import (
    flow_to_openai_function,
    tool_to_openai_function,
)

__all__ = [
    "flow_to_anthropic_tool",
    "flow_to_callable",
    "flow_to_openai_function",
    "tool_to_anthropic_tool",
    "tool_to_callable",
    "tool_to_openai_function",
]
