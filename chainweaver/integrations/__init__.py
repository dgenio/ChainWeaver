"""Optional, third-party-aware integrations for ChainWeaver.

Each submodule under :mod:`chainweaver.integrations` wraps a specific
external ecosystem (OpenTelemetry, the Weaver Stack today; LangChain /
LlamaIndex / others later) so it can plug into ChainWeaver's lifecycle
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
- :mod:`chainweaver.integrations.weaver_spec` — Weaver Stack mirror
  types (``SelectableItem``, ``RoutingDecision``, ``CapabilityToken``)
  plus the :func:`flow_to_selectable_item` exporter (issues #91, #107).
  No external dependency required.
- :mod:`chainweaver.integrations.contextweaver` — bridges a
  ``RoutingDecision`` into ChainWeaver's
  :class:`~chainweaver.decisions.DecisionCallback` seam (issue #106).
  Accepts any duck-typed :class:`ContextweaverClient`.
- :mod:`chainweaver.integrations.agent_kernel` — optional
  :class:`KernelBackedExecutor` that delegates capability-typed DAG
  steps to a structural :class:`KernelProtocol` (issue #89).
"""

from __future__ import annotations
