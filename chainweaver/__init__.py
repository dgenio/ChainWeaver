"""ChainWeaver — deterministic orchestration layer for MCP-based agents.

Public API
----------

.. code-block:: python

    from chainweaver import (
        Tool, Flow, FlowStep, FlowStatus, DAGFlow, DAGFlowStep, DriftInfo,
        FlowBuilder, FlowRegistry, FlowExecutor, RetryPolicy,
        ExecutionPlan, ExecutionResult, ReplayMode, ReplayResult,
        StepDiff, StepPlan, StepRecord,
        RedactionPolicy, TraceRecorder, ObservedStep, ObservedTrace,
        CostProfile, CostReport,
        validate_dag_topology,
        schema_fingerprint, check_flow_compatibility, CompatibilityIssue,
        compile_flow, CompilationResult, CompilationError, CompilationWarning,
        flow_to_ascii, flow_to_mermaid, result_to_mermaid,
        flow_to_dict, flow_to_json, flow_to_yaml,
        flow_from_dict, flow_from_json, flow_from_yaml,
    )
    from chainweaver.exceptions import (
        ChainWeaverError,
        DAGDefinitionError,
        ToolNotFoundError,
        FlowNotFoundError,
        FlowAlreadyExistsError,
        FlowSerializationError,
        FlowStatusError,
        InvalidFlowVersionError,
        SchemaValidationError,
        InputMappingError,
        FlowExecutionError,
        ToolDefinitionError,
    )
"""

from __future__ import annotations

import logging

from chainweaver import cli
from chainweaver.builder import FlowBuilder, FlowBuilderError
from chainweaver.compat import CompatibilityIssue, check_flow_compatibility, schema_fingerprint
from chainweaver.compiler import (
    CompilationError,
    CompilationResult,
    CompilationWarning,
    compile_flow,
)
from chainweaver.cost import CostProfile, CostReport
from chainweaver.decorators import tool
from chainweaver.exceptions import (
    ChainWeaverError,
    DAGDefinitionError,
    FlowAlreadyExistsError,
    FlowExecutionError,
    FlowNotFoundError,
    FlowSerializationError,
    FlowStatusError,
    InputMappingError,
    InvalidFlowVersionError,
    SchemaValidationError,
    ToolDefinitionError,
    ToolNotFoundError,
    ToolOutputSizeError,
    ToolTimeoutError,
)
from chainweaver.executor import (
    ExecutionPlan,
    ExecutionResult,
    FlowExecutor,
    ReplayMode,
    ReplayResult,
    StepDiff,
    StepPlan,
    StepRecord,
)
from chainweaver.flow import (
    DAGFlow,
    DAGFlowStep,
    DriftInfo,
    Flow,
    FlowStatus,
    FlowStep,
    RetryPolicy,
    validate_dag_topology,
)
from chainweaver.log_utils import RedactionPolicy
from chainweaver.observation import ObservedStep, ObservedTrace, TraceRecorder
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import (
    flow_from_dict,
    flow_from_json,
    flow_from_yaml,
    flow_to_dict,
    flow_to_json,
    flow_to_yaml,
)
from chainweaver.storage import FileStore, InMemoryStore, RegistryStore
from chainweaver.tools import Tool
from chainweaver.viz import flow_to_ascii, flow_to_mermaid, result_to_mermaid

# Follow Python library best practice: attach only a NullHandler so that
# applications can configure logging centrally without interference.
logging.getLogger("chainweaver").addHandler(logging.NullHandler())

__version__ = "0.1.0"

__all__ = [
    "ChainWeaverError",
    "CompatibilityIssue",
    "CompilationError",
    "CompilationResult",
    "CompilationWarning",
    "CostProfile",
    "CostReport",
    "DAGDefinitionError",
    "DAGFlow",
    "DAGFlowStep",
    "DriftInfo",
    "ExecutionPlan",
    "ExecutionResult",
    "FileStore",
    "Flow",
    "FlowAlreadyExistsError",
    "FlowBuilder",
    "FlowBuilderError",
    "FlowExecutionError",
    "FlowExecutor",
    "FlowNotFoundError",
    "FlowRegistry",
    "FlowSerializationError",
    "FlowStatus",
    "FlowStatusError",
    "FlowStep",
    "InMemoryStore",
    "InputMappingError",
    "InvalidFlowVersionError",
    "ObservedStep",
    "ObservedTrace",
    "RedactionPolicy",
    "RegistryStore",
    "ReplayMode",
    "ReplayResult",
    "RetryPolicy",
    "SchemaValidationError",
    "StepDiff",
    "StepPlan",
    "StepRecord",
    "Tool",
    "ToolDefinitionError",
    "ToolNotFoundError",
    "ToolOutputSizeError",
    "ToolTimeoutError",
    "TraceRecorder",
    "check_flow_compatibility",
    "cli",
    "compile_flow",
    "flow_from_dict",
    "flow_from_json",
    "flow_from_yaml",
    "flow_to_ascii",
    "flow_to_dict",
    "flow_to_json",
    "flow_to_mermaid",
    "flow_to_yaml",
    "result_to_mermaid",
    "schema_fingerprint",
    "tool",
    "validate_dag_topology",
]
