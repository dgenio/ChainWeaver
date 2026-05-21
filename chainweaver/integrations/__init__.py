"""Optional, third-party-aware integrations for ChainWeaver.

Each submodule under :mod:`chainweaver.integrations` wraps a specific
external ecosystem so it can plug into ChainWeaver's lifecycle hook
seam without pulling its dependency into the base install.  Every
submodule guards the optional third-party import and surfaces a clear
``ImportError`` if the user hasn't installed the relevant extra.

Available integrations
----------------------

- :mod:`chainweaver.integrations.opentelemetry` — emits OpenTelemetry
  spans for every flow execution via the
  :class:`~chainweaver.middleware.FlowExecutorMiddleware` API.  Install
  with ``pip install 'chainweaver[otel]'``.
- :mod:`chainweaver.integrations.langchain` — bidirectional adapters
  between LangChain ``BaseTool`` and ChainWeaver :class:`Tool`.
  Install with ``pip install 'chainweaver[langchain]'``.
- :mod:`chainweaver.integrations.llamaindex` — bidirectional adapters
  between LlamaIndex ``FunctionTool`` and ChainWeaver :class:`Tool`.
  Install with ``pip install 'chainweaver[llamaindex]'``.
"""

from __future__ import annotations
