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
from chainweaver.analyzer import ChainAnalyzer, ToolChain
from chainweaver.builder import FlowBuilder, FlowBuilderError
from chainweaver.cache import FileStepCache, InMemoryStepCache, StepCache, StepCacheKey
from chainweaver.checkpoint import (
    Checkpointer,
    ExecutionSnapshot,
    FileCheckpointer,
    InMemoryCheckpointer,
)
from chainweaver.compat import CompatibilityIssue, check_flow_compatibility, schema_fingerprint
from chainweaver.compiler import (
    CompilationError,
    CompilationResult,
    CompilationWarning,
    compile_flow,
)
from chainweaver.cost import CostProfile, CostReport
from chainweaver.decorators import tool
from chainweaver.events import FlowEvent
from chainweaver.exceptions import (
    ChainWeaverError,
    CheckpointDriftError,
    CheckpointerNotConfiguredError,
    CheckpointNotFoundError,
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
from chainweaver.middleware import (
    BaseMiddleware,
    FlowEndContext,
    FlowExecutorMiddleware,
    FlowStartContext,
    StepEndContext,
    StepStartContext,
)
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
from chainweaver.viz import flow_to_ascii, flow_to_dot, flow_to_mermaid, result_to_mermaid

# Resolve forward references in middleware context, event, and snapshot
# models — ``StepRecord`` and ``ExecutionResult`` are defined in
# ``chainweaver.executor`` (imported above), so they are now available
# for Pydantic to bind into the ``StepEndContext`` / ``FlowEndContext``
# schemas, ``FlowEvent``, and ``ExecutionSnapshot``.
_forward_namespace = {"StepRecord": StepRecord, "ExecutionResult": ExecutionResult}
StepEndContext.model_rebuild(_types_namespace=_forward_namespace)
FlowEndContext.model_rebuild(_types_namespace=_forward_namespace)
FlowEvent.model_rebuild(_types_namespace=_forward_namespace)
ExecutionSnapshot.model_rebuild(_types_namespace=_forward_namespace)

# Follow Python library best practice: attach only a NullHandler so that
# applications can configure logging centrally without interference.
logging.getLogger("chainweaver").addHandler(logging.NullHandler())

__version__ = "0.4.0"

__all__ = [
    "BaseMiddleware",
    "ChainAnalyzer",
    "ChainWeaverError",
    "CheckpointDriftError",
    "CheckpointNotFoundError",
    "Checkpointer",
    "CheckpointerNotConfiguredError",
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
    "ExecutionSnapshot",
    "FileCheckpointer",
    "FileStepCache",
    "FileStore",
    "Flow",
    "FlowAlreadyExistsError",
    "FlowBuilder",
    "FlowBuilderError",
    "FlowEndContext",
    "FlowEvent",
    "FlowExecutionError",
    "FlowExecutor",
    "FlowExecutorMiddleware",
    "FlowNotFoundError",
    "FlowRegistry",
    "FlowSerializationError",
    "FlowStartContext",
    "FlowStatus",
    "FlowStatusError",
    "FlowStep",
    "InMemoryCheckpointer",
    "InMemoryStepCache",
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
    "StepCache",
    "StepCacheKey",
    "StepDiff",
    "StepEndContext",
    "StepPlan",
    "StepRecord",
    "StepStartContext",
    "Tool",
    "ToolChain",
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
    "flow_to_dot",
    "flow_to_json",
    "flow_to_mermaid",
    "flow_to_yaml",
    "result_to_mermaid",
    "schema_fingerprint",
    "tool",
    "validate_dag_topology",
]
