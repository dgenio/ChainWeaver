---
applyTo: "chainweaver/**/*.py"
---

# Python source instructions — ChainWeaver

These instructions apply when editing production source code in `chainweaver/`.

## Module conventions
- Every module starts with `from __future__ import annotations`
- Every module has a module-level docstring explaining its role
- All public classes and functions have Google-style docstrings

## Pydantic patterns
- Use `pydantic.BaseModel` for all data models (v2 API)
- Use `model_dump()` not `.dict()` (v2 migration)
- Use `model_validate()` not `.parse_obj()` (v2 migration)
- Field descriptions via `Field(description="...")` for schema clarity

## Exception patterns
- All custom exceptions inherit from `ChainWeaverError`
- Exception constructors accept context kwargs: `tool_name`, `step_index`, `detail`
- Import exceptions from `chainweaver.exceptions`, never define inline
- Available exception types: `ToolNotFoundError`, `FlowNotFoundError`,
  `FlowAlreadyExistsError`, `SchemaValidationError`, `InputMappingError`,
  `FlowExecutionError`, `ToolDefinitionError`

## Export rules
- Any new public class/function MUST be added to `chainweaver/__init__.py` `__all__`
- If adding a new module, add its imports to `__init__.py`

## Executor invariant
- `executor.py` must remain deterministic: no LLM calls, no network I/O, no randomness
- The executor runs a compiled graph — it does not make decisions
