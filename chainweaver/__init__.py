"""ChainWeaver — deterministic orchestration layer for MCP-based agents.

Public API
----------

.. code-block:: python

    from chainweaver import Tool, Flow, FlowStep, FlowRegistry, FlowExecutor
    from chainweaver.exceptions import (
        ChainWeaverError,
        ToolNotFoundError,
        FlowNotFoundError,
        FlowAlreadyExistsError,
        SchemaValidationError,
        InputMappingError,
        FlowExecutionError,
    )
"""

from __future__ import annotations

import logging

from chainweaver.exceptions import (
    ChainWeaverError,
    FlowAlreadyExistsError,
    FlowExecutionError,
    FlowNotFoundError,
    InputMappingError,
    SchemaValidationError,
    ToolNotFoundError,
)
from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# Follow Python library best practice: attach only a NullHandler so that
# applications can configure logging centrally without interference.
logging.getLogger("chainweaver").addHandler(logging.NullHandler())

__version__ = "0.0.2"

__all__ = [
    "ChainWeaverError",
    "ExecutionResult",
    "Flow",
    "FlowAlreadyExistsError",
    "FlowExecutionError",
    "FlowExecutor",
    "FlowNotFoundError",
    "FlowRegistry",
    "FlowStep",
    "InputMappingError",
    "SchemaValidationError",
    "StepRecord",
    "Tool",
    "ToolNotFoundError",
]
