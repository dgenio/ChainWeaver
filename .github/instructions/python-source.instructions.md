---
applyTo: "chainweaver/**/*.py"
---

# Python source instructions — ChainWeaver

These instructions apply when editing production source code in `chainweaver/`.

## Module conventions
- Every module has a module-level docstring explaining its role
- Include `from __future__ import annotations` immediately after the module docstring
- All public classes and functions have Google-style docstrings

## Pydantic patterns
- Use `pydantic.BaseModel` for schemas / I/O contracts (v2 API)
- For `BaseModel` types, use `model_dump()` not `.dict()` (v2 migration)
- For `BaseModel` types, use `model_validate()` not `.parse_obj()` (v2 migration)
- Field descriptions via `Field(description="...")` for schema clarity
- Internal runtime records that need to carry `Exception` instances may remain `dataclass`es per repo invariants

## Exception patterns
- All custom exceptions inherit from `ChainWeaverError`
- Exceptions should carry relevant context attributes where applicable; do not assume a uniform
  constructor signature — follow the API defined by each exception class in `chainweaver.exceptions`
- Import exceptions from `chainweaver.exceptions`, never define inline
- Available exception types: `ToolNotFoundError`, `FlowNotFoundError`, `FlowAlreadyExistsError`,
  `SchemaValidationError`, `InputMappingError`, `FlowExecutionError`, `ToolDefinitionError`

## Export rules
- Any new public class/function MUST be added to `chainweaver/__init__.py` `__all__`
- If adding a new module, add its imports to `__init__.py`

## Executor invariant
- `executor.py` must remain deterministic: no LLM calls, no network I/O, no randomness
- The executor runs a compiled graph — it does not make decisions
