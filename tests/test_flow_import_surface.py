"""Regression tests for the stable ``chainweaver.flow`` package surface."""

from __future__ import annotations

import pickle

import chainweaver.flow as flow_package
from chainweaver.flow import (
    ConditionalEdge,
    ContextCollisionPolicy,
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
    SchemaRefPolicy,
    get_schema_ref_policy,
    resolve_class_ref,
    schema_ref_policy,
    set_schema_ref_policy,
    validate_dag_topology,
)
from chainweaver.flow.dag import (
    DAGFlow as DAGFlowImplementation,
)
from chainweaver.flow.dag import (
    DAGFlowStep as DAGFlowStepImplementation,
)
from chainweaver.flow.dag import (
    validate_dag_topology as validate_dag_topology_implementation,
)
from chainweaver.flow.definitions import (
    ConditionalEdge as ConditionalEdgeImplementation,
)
from chainweaver.flow.definitions import (
    ContextCollisionPolicy as ContextCollisionPolicyImplementation,
)
from chainweaver.flow.definitions import (
    Flow as FlowImplementation,
)
from chainweaver.flow.definitions import (
    FlowStatus as FlowStatusImplementation,
)
from chainweaver.flow.drift import DriftInfo as DriftInfoImplementation
from chainweaver.flow.governance import (
    FlowGovernance as FlowGovernanceImplementation,
)
from chainweaver.flow.governance import (
    FlowLifecycle as FlowLifecycleImplementation,
)
from chainweaver.flow.refs import (
    SchemaRefAllowlist as SchemaRefAllowlistImplementation,
)
from chainweaver.flow.refs import (
    SchemaRefPolicy as SchemaRefPolicyImplementation,
)
from chainweaver.flow.refs import (
    get_schema_ref_policy as get_schema_ref_policy_implementation,
)
from chainweaver.flow.refs import (
    resolve_class_ref as resolve_class_ref_implementation,
)
from chainweaver.flow.refs import (
    schema_ref_policy as schema_ref_policy_implementation,
)
from chainweaver.flow.refs import (
    set_schema_ref_policy as set_schema_ref_policy_implementation,
)
from chainweaver.flow.steps import (
    FlowStep as FlowStepImplementation,
)
from chainweaver.flow.steps import (
    RetryPolicy as RetryPolicyImplementation,
)


def test_legacy_imports_are_implementation_objects() -> None:
    """The package facade must not create duplicate model or helper objects."""
    expected_pairs = (
        (ConditionalEdge, ConditionalEdgeImplementation),
        (ContextCollisionPolicy, ContextCollisionPolicyImplementation),
        (DAGFlow, DAGFlowImplementation),
        (DAGFlowStep, DAGFlowStepImplementation),
        (DriftInfo, DriftInfoImplementation),
        (Flow, FlowImplementation),
        (FlowGovernance, FlowGovernanceImplementation),
        (FlowLifecycle, FlowLifecycleImplementation),
        (FlowStatus, FlowStatusImplementation),
        (FlowStep, FlowStepImplementation),
        (RetryPolicy, RetryPolicyImplementation),
        (SchemaRefAllowlist, SchemaRefAllowlistImplementation),
        (SchemaRefPolicy, SchemaRefPolicyImplementation),
        (get_schema_ref_policy, get_schema_ref_policy_implementation),
        (resolve_class_ref, resolve_class_ref_implementation),
        (schema_ref_policy, schema_ref_policy_implementation),
        (set_schema_ref_policy, set_schema_ref_policy_implementation),
        (validate_dag_topology, validate_dag_topology_implementation),
    )

    assert hasattr(flow_package, "__path__")
    for legacy_symbol, implementation_symbol in expected_pairs:
        assert legacy_symbol is implementation_symbol


def test_moved_runtime_symbols_keep_legacy_module_identity() -> None:
    """Public runtime objects must keep stable qualified and pickle references."""
    runtime_symbols = (
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

    for symbol in runtime_symbols:
        assert symbol.__module__ == "chainweaver.flow"
        assert pickle.loads(pickle.dumps(symbol)) is symbol
