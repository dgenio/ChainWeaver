"""ChainWeaver — deterministic orchestration layer for MCP-based agents.

Public API
----------

.. code-block:: python

    from chainweaver import (
        Tool, Flow, FlowStep, FlowStatus, DAGFlow, DAGFlowStep, DriftInfo,
        FlowBuilder, FlowRegistry, FlowExecutor, validate_dag_topology,
        schema_fingerprint, check_flow_compatibility, CompatibilityIssue,
        compile_flow, CompilationResult, CompilationError, CompilationWarning,
    )
    from chainweaver.exceptions import (
        ChainWeaverError,
        DAGDefinitionError,
        ToolNotFoundError,
        FlowNotFoundError,
        FlowAlreadyExistsError,
        FlowStatusError,
        SchemaValidationError,
        InputMappingError,
        FlowExecutionError,
        ToolDefinitionError,
    )
"""

from __future__ import annotations

import logging

from chainweaver.builder import FlowBuilder, FlowBuilderError
from chainweaver.compat import CompatibilityIssue, check_flow_compatibility, schema_fingerprint
from chainweaver.compiler import (
    CompilationError,
    CompilationResult,
    CompilationWarning,
    compile_flow,
)
from chainweaver.decorators import tool
from chainweaver.exceptions import (
    ChainWeaverError,
    DAGDefinitionError,
    FlowAlreadyExistsError,
    FlowExecutionError,
    FlowNotFoundError,
    FlowStatusError,
    InputMappingError,
    SchemaValidationError,
    ToolDefinitionError,
    ToolNotFoundError,
)
from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.flow import (
    DAGFlow,
    DAGFlowStep,
    DriftInfo,
    Flow,
    FlowStatus,
    FlowStep,
    validate_dag_topology,
)
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

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
    "DAGDefinitionError",
    "DAGFlow",
    "DAGFlowStep",
    "DriftInfo",
    "ExecutionResult",
    "Flow",
    "FlowAlreadyExistsError",
    "FlowBuilder",
    "FlowBuilderError",
    "FlowExecutionError",
    "FlowExecutor",
    "FlowNotFoundError",
    "FlowRegistry",
    "FlowStatus",
    "FlowStatusError",
    "FlowStep",
    "InputMappingError",
    "SchemaValidationError",
    "StepRecord",
    "Tool",
    "ToolDefinitionError",
    "ToolNotFoundError",
    "check_flow_compatibility",
    "compile_flow",
    "schema_fingerprint",
    "tool",
    "validate_dag_topology",
]
