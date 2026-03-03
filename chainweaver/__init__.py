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

import logging

from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.exceptions import (
    ChainWeaverError,
    FlowAlreadyExistsError,
    FlowExecutionError,
    FlowNotFoundError,
    InputMappingError,
    SchemaValidationError,
    ToolNotFoundError,
)
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# Follow Python library best practice: attach only a NullHandler so that
# applications can configure logging centrally without interference.
logging.getLogger("chainweaver").addHandler(logging.NullHandler())

__version__ = "0.0.1"

__all__ = [
    # Core abstractions
    "Tool",
    "FlowStep",
    "Flow",
    "FlowRegistry",
    "FlowExecutor",
    # Result types
    "ExecutionResult",
    "StepRecord",
    # Exceptions
    "ChainWeaverError",
    "ToolNotFoundError",
    "FlowNotFoundError",
    "FlowAlreadyExistsError",
    "SchemaValidationError",
    "InputMappingError",
    "FlowExecutionError",
]
