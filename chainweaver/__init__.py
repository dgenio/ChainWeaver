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
        CostProfile, CostReport, PriceSnap, PROVIDER_PRICES, lookup_price,
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
from chainweaver.analyzer import ChainAnalyzer, Suggestion, ToolChain, suggest_optimizations
from chainweaver.attest import AttestationInputError, AttestationReport, attest_flow
from chainweaver.builder import FlowBuilder, FlowBuilderError
from chainweaver.cache import FileStepCache, InMemoryStepCache, StepCache, StepCacheKey
from chainweaver.cancellation import CancellationToken
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
from chainweaver.compiler_llm import LLMProposal, llm_propose_flows, write_proposals
from chainweaver.contracts import (
    DeterminismLevel,
    SideEffectLevel,
    StabilityLevel,
    ToolSafetyContract,
    evaluate_predicate,
    merge_safety,
)
from chainweaver.cost import (
    PROVIDER_PRICES,
    CostProfile,
    CostReport,
    PriceSnap,
    lookup_price,
)
from chainweaver.decisions import (
    BaseDecisionCallback,
    DecisionCallable,
    DecisionCallback,
    DecisionContext,
    coerce_decision_callback,
)
from chainweaver.decorators import tool
from chainweaver.events import FlowEvent
from chainweaver.exceptions import (
    ChainWeaverError,
    CheckpointDriftError,
    CheckpointerNotConfiguredError,
    CheckpointNotFoundError,
    ContribError,
    CostProfileError,
    DAGDefinitionError,
    DecisionCallbackError,
    FlowAlreadyExistsError,
    FlowCancelledError,
    FlowCompositionError,
    FlowExecutionError,
    FlowNotFoundError,
    FlowSerializationError,
    FlowStatusError,
    InputMappingError,
    InvalidFlowVersionError,
    KernelInvocationError,
    MCPError,
    MCPSchemaConversionError,
    MCPToolInvocationError,
    OfflineLLMError,
    PluginDiscoveryError,
    PredicateSyntaxError,
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
    validate_dag_topology,
)
from chainweaver.fuzz import (
    BUILTIN_PROPERTIES,
    FaultConfig,
    FlowFuzzer,
    FlowProperty,
    FuzzCase,
    FuzzConfigError,
    FuzzFailure,
    FuzzReport,
    minimize_failure,
)
from chainweaver.lessons import (
    LessonCandidate,
    LessonEvidenceStep,
    LessonReview,
    trace_to_lesson_candidate,
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
from chainweaver.observer import ChainObserver, FlowSuggestion
from chainweaver.optimizer import (
    OptimizationStrategy,
    ToolDescriptionProposal,
    optimize_new_tool_description,
    optimize_tool_descriptions,
)
from chainweaver.plugins import discover_flows, discover_tools
from chainweaver.registry import FlowRegistry
from chainweaver.schemas import flow_schema_json
from chainweaver.serialization import (
    flow_from_dict,
    flow_from_json,
    flow_from_yaml,
    flow_to_dict,
    flow_to_json,
    flow_to_yaml,
)
from chainweaver.service import (
    ChainWeaverService,
    ProposalStatus,
    ServiceConfig,
    ServiceEvent,
    ServiceMetrics,
    ServiceProposal,
)
from chainweaver.storage import FileStore, InMemoryStore, RegistryStore
from chainweaver.testing.replay import FixtureStaleError
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

__version__ = "0.11.0"

__all__ = [
    "BUILTIN_PROPERTIES",
    "PROVIDER_PRICES",
    "AttestationInputError",
    "AttestationReport",
    "BaseDecisionCallback",
    "BaseMiddleware",
    "CancellationToken",
    "ChainAnalyzer",
    "ChainObserver",
    "ChainWeaverError",
    "ChainWeaverService",
    "CheckpointDriftError",
    "CheckpointNotFoundError",
    "Checkpointer",
    "CheckpointerNotConfiguredError",
    "CompatibilityIssue",
    "CompilationError",
    "CompilationResult",
    "CompilationWarning",
    "ConditionalEdge",
    "ContribError",
    "CostProfile",
    "CostProfileError",
    "CostReport",
    "DAGDefinitionError",
    "DAGFlow",
    "DAGFlowStep",
    "DecisionCallable",
    "DecisionCallback",
    "DecisionCallbackError",
    "DecisionContext",
    "DeterminismLevel",
    "DriftInfo",
    "ExecutionPlan",
    "ExecutionResult",
    "ExecutionSnapshot",
    "FaultConfig",
    "FileCheckpointer",
    "FileStepCache",
    "FileStore",
    "FixtureStaleError",
    "Flow",
    "FlowAlreadyExistsError",
    "FlowBuilder",
    "FlowBuilderError",
    "FlowCancelledError",
    "FlowCompositionError",
    "FlowEndContext",
    "FlowEvent",
    "FlowExecutionError",
    "FlowExecutor",
    "FlowExecutorMiddleware",
    "FlowFuzzer",
    "FlowGovernance",
    "FlowLifecycle",
    "FlowNotFoundError",
    "FlowProperty",
    "FlowRegistry",
    "FlowSerializationError",
    "FlowStartContext",
    "FlowStatus",
    "FlowStatusError",
    "FlowStep",
    "FlowSuggestion",
    "FuzzCase",
    "FuzzConfigError",
    "FuzzFailure",
    "FuzzReport",
    "InMemoryCheckpointer",
    "InMemoryStepCache",
    "InMemoryStore",
    "InputMappingError",
    "InvalidFlowVersionError",
    "KernelInvocationError",
    "LLMProposal",
    "LessonCandidate",
    "LessonEvidenceStep",
    "LessonReview",
    "MCPError",
    "MCPSchemaConversionError",
    "MCPToolInvocationError",
    "ObservedStep",
    "ObservedTrace",
    "OfflineLLMError",
    "OptimizationStrategy",
    "PluginDiscoveryError",
    "PredicateSyntaxError",
    "PriceSnap",
    "ProposalStatus",
    "RedactionPolicy",
    "RegistryStore",
    "ReplayMode",
    "ReplayResult",
    "RetryPolicy",
    "SchemaValidationError",
    "ServiceConfig",
    "ServiceEvent",
    "ServiceMetrics",
    "ServiceProposal",
    "SideEffectLevel",
    "StabilityLevel",
    "StepCache",
    "StepCacheKey",
    "StepDiff",
    "StepEndContext",
    "StepPlan",
    "StepRecord",
    "StepStartContext",
    "Suggestion",
    "Tool",
    "ToolChain",
    "ToolDefinitionError",
    "ToolDescriptionProposal",
    "ToolNotFoundError",
    "ToolOutputSizeError",
    "ToolSafetyContract",
    "ToolTimeoutError",
    "TraceRecorder",
    "attest_flow",
    "check_flow_compatibility",
    "cli",
    "coerce_decision_callback",
    "compile_flow",
    "discover_flows",
    "discover_tools",
    "evaluate_predicate",
    "flow_from_dict",
    "flow_from_json",
    "flow_from_yaml",
    "flow_schema_json",
    "flow_to_ascii",
    "flow_to_dict",
    "flow_to_dot",
    "flow_to_json",
    "flow_to_mermaid",
    "flow_to_yaml",
    "llm_propose_flows",
    "lookup_price",
    "merge_safety",
    "minimize_failure",
    "optimize_new_tool_description",
    "optimize_tool_descriptions",
    "result_to_mermaid",
    "schema_fingerprint",
    "suggest_optimizations",
    "tool",
    "trace_to_lesson_candidate",
    "validate_dag_topology",
    "write_proposals",
]
