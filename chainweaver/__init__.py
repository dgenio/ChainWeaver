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
)
from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep, validate_dag_topology
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# Follow Python library best practice: attach only a NullHandler so that
# applications can configure logging centrally without interference.
logging.getLogger("chainweaver").addHandler(logging.NullHandler())

__version__ = "0.1.0"

__all__ = [
    "ChainWeaverError",
    "DAGDefinitionError",
    "DAGFlow",
    "DAGFlowStep",
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
    "SchemaValidationError",
    "StepRecord",
    "Tool",
    "ToolDefinitionError",
    "ToolNotFoundError",
    "tool",
    "validate_dag_topology",
]
