"""ChainWeaver — deterministic orchestration layer for MCP-based agents.

Public API
----------

.. code-block:: python

    from chainweaver import (
        Tool, Flow, FlowStep, DAGFlow, DAGFlowStep,
        FlowBuilder, FlowRegistry, FlowExecutor, validate_dag_topology,
    )
    from chainweaver.exceptions import (
        ChainWeaverError,
        DAGDefinitionError,
        ToolNotFoundError,
        FlowNotFoundError,
        FlowAlreadyExistsError,
        SchemaValidationError,
        InputMappingError,
        FlowExecutionError,
        ToolDefinitionError,
    )
"""

from __future__ import annotations

import logging

from chainweaver.builder import FlowBuilder, FlowBuilderError
from chainweaver.cost import CostProfile, CostReport
from chainweaver.decorators import tool
from chainweaver.exceptions import (
    ChainWeaverError,
    DAGDefinitionError,
    FlowAlreadyExistsError,
    FlowExecutionError,
    FlowNotFoundError,
    InputMappingError,
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
    StepPlan,
    StepRecord,
)
from chainweaver.flow import (
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowStep,
    RetryPolicy,
    validate_dag_topology,
)
from chainweaver.log_utils import RedactionPolicy
from chainweaver.observation import ObservedStep, ObservedTrace, TraceRecorder
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# Follow Python library best practice: attach only a NullHandler so that
# applications can configure logging centrally without interference.
logging.getLogger("chainweaver").addHandler(logging.NullHandler())

__version__ = "0.1.0"

__all__ = [
    "ChainWeaverError",
    "CostProfile",
    "CostReport",
    "DAGDefinitionError",
    "DAGFlow",
    "DAGFlowStep",
    "ExecutionPlan",
    "ExecutionResult",
    "Flow",
    "FlowAlreadyExistsError",
    "FlowBuilder",
    "FlowBuilderError",
    "FlowExecutionError",
    "FlowExecutor",
    "FlowNotFoundError",
    "FlowRegistry",
    "FlowStep",
    "InputMappingError",
    "ObservedStep",
    "ObservedTrace",
    "RedactionPolicy",
    "RetryPolicy",
    "SchemaValidationError",
    "StepPlan",
    "StepRecord",
    "Tool",
    "ToolDefinitionError",
    "ToolNotFoundError",
    "ToolOutputSizeError",
    "ToolTimeoutError",
    "TraceRecorder",
    "tool",
    "validate_dag_topology",
]
