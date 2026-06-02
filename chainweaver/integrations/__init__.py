"""Optional, third-party-aware integrations for ChainWeaver.

Each submodule under :mod:`chainweaver.integrations` wraps a specific
external ecosystem (OpenTelemetry, the Weaver Stack, LangChain,
LlamaIndex, and more) so it can plug into ChainWeaver's lifecycle
hook or decision seams without pulling its dependency into the base
install.  Every submodule guards any optional third-party import and
surfaces a clear ``ImportError`` if the user hasn't installed the
relevant extra.

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
- :mod:`chainweaver.integrations.weaver_spec` — consumes the published
  Weaver Stack contract types (``SelectableItem``, ``RoutingDecision``,
  ``CapabilityToken``, …) from the ``weaver-contracts`` package, plus
  the :func:`flow_to_selectable_item` exporter and the routing
  resolvers (issues #91, #107, #233).  Install with
  ``pip install 'chainweaver[weaver-stack]'``.
- :mod:`chainweaver.integrations.contextweaver` — bridges a
  ``RoutingDecision`` into ChainWeaver's
  :class:`~chainweaver.decisions.DecisionCallback` seam (issue #106).
  Accepts any duck-typed :class:`ContextweaverClient`.  Requires the
  ``weaver-stack`` extra.
- :mod:`chainweaver.integrations.agent_kernel` — optional
  :class:`KernelBackedExecutor` that delegates capability-typed DAG
  steps to a structural :class:`KernelProtocol` (issue #89).  Requires
  the ``weaver-stack`` extra.
"""

from __future__ import annotations
