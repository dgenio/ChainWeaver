"""Public flow models and validation helpers.

The implementation is split by concern while this package preserves the
historical ``chainweaver.flow`` import and serialization surface.
"""

from __future__ import annotations

from chainweaver.flow.dag import DAGFlow, DAGFlowStep, validate_dag_topology
from chainweaver.flow.definitions import (
    ConditionalEdge,
    ContextCollisionPolicy,
    Flow,
    FlowStatus,
)
from chainweaver.flow.drift import DriftInfo
from chainweaver.flow.governance import FlowGovernance, FlowLifecycle
from chainweaver.flow.refs import (
    SchemaRefAllowlist,
    SchemaRefPolicy,
    get_schema_ref_policy,
    resolve_class_ref,
    schema_ref_policy,
    set_schema_ref_policy,
)
from chainweaver.flow.steps import FlowStep, RetryPolicy

__all__ = [
    "ConditionalEdge",
    "ContextCollisionPolicy",
    "DAGFlow",
    "DAGFlowStep",
    "DriftInfo",
    "Flow",
    "FlowGovernance",
    "FlowLifecycle",
    "FlowStatus",
    "FlowStep",
    "RetryPolicy",
    "SchemaRefAllowlist",
    "SchemaRefPolicy",
    "get_schema_ref_policy",
    "resolve_class_ref",
    "schema_ref_policy",
    "set_schema_ref_policy",
    "validate_dag_topology",
]

# Keep public API snapshots and ``module:qualname`` / pickle references stable
# after moving the implementations into focused submodules.
_LEGACY_MODULE_SYMBOLS = (
    ConditionalEdge,
    DAGFlow,
    DAGFlowStep,
    DriftInfo,
    Flow,
    FlowGovernance,
    FlowLifecycle,
    FlowStatus,
    FlowStep,
    RetryPolicy,
    SchemaRefAllowlist,
    get_schema_ref_policy,
    resolve_class_ref,
    schema_ref_policy,
    set_schema_ref_policy,
    validate_dag_topology,
)

for _symbol in _LEGACY_MODULE_SYMBOLS:
    _symbol.__module__ = __name__

del _symbol
