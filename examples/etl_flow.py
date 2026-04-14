"""Data pipeline flow example for ChainWeaver.

# What this demonstrates
# -----------------------
# A realistic ETL-style flow with five deterministic steps:
#
#   fetch_data → validate_records → normalize_fields → enrich_records → store_records
#
# This mirrors a common MCP tool-invocation pattern where an agent fetches raw data
# from a source, applies a series of transformations, and persists the result.
# All processing is handled by ChainWeaver with zero LLM calls between steps.
#
# Execution trace (mock data):
#
#   fetch_data()             → {"raw_records": [...], "source": "inventory_db", ...}
#   validate_records(...)    → {"valid_records": [...], "invalid_count": 1, ...}
#   normalize_fields(...)    → {"normalized_records": [...]}
#   enrich_records(...)      → {"enriched_records": [...]}
#   store_records(...)       → {"stored_count": N, "destination": "warehouse", ...}

Run this script from the repository root with::

    python examples/etl_flow.py
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Step 1 — Schemas
# ---------------------------------------------------------------------------


class FetchInput(BaseModel):
    """Input for the fetch_data tool."""

    source: str
    limit: int = 10


class RawRecordsOutput(BaseModel):
    """Output of fetch_data: a list of raw dicts plus provenance metadata."""

    raw_records: list[dict[str, Any]]
    source: str
    fetched_count: int


class ValidateInput(BaseModel):
    """Input for validate_records."""

    raw_records: list[dict[str, Any]]
    source: str


class ValidatedOutput(BaseModel):
    """Output of validate_records: records that passed schema checks."""

    valid_records: list[dict[str, Any]]
    invalid_count: int
    source: str


class NormalizeInput(BaseModel):
    """Input for normalize_fields."""

    valid_records: list[dict[str, Any]]
    source: str


class NormalizedOutput(BaseModel):
    """Output of normalize_fields: field names lowercased, types cast."""

    normalized_records: list[dict[str, Any]]


class EnrichInput(BaseModel):
    """Input for enrich_records."""

    normalized_records: list[dict[str, Any]]


class EnrichedOutput(BaseModel):
    """Output of enrich_records: records with an added 'category' field."""

    enriched_records: list[dict[str, Any]]


class StoreInput(BaseModel):
    """Input for store_records."""

    enriched_records: list[dict[str, Any]]


class StoreOutput(BaseModel):
    """Output of store_records: confirmation of the write operation."""

    stored_count: int
    destination: str
    status: str


# ---------------------------------------------------------------------------
# Step 2 — Tool functions (mock / simulated)
# ---------------------------------------------------------------------------

_MOCK_RAW_RECORDS = [
    {"ProductID": "P001", "Name": "Widget Alpha", "Price": "9.99", "Stock": "42"},
    {"ProductID": "P002", "Name": "Widget Beta", "Price": "bad_price", "Stock": "17"},
    {"ProductID": "P003", "Name": "Gadget Gamma", "Price": "24.50", "Stock": "0"},
    {"ProductID": "P004", "Name": "Gadget Delta", "Price": "5.00", "Stock": "200"},
    {"ProductID": "P005", "Name": "Doohickey Epsilon", "Price": "99.00", "Stock": "3"},
]

_CATEGORY_MAP = {
    "Widget": "accessories",
    "Gadget": "electronics",
    "Doohickey": "misc",
}


def fetch_data_fn(inp: FetchInput) -> dict[str, Any]:
    """Return a slice of mock inventory records from the named source."""
    records = _MOCK_RAW_RECORDS[: inp.limit]
    return {
        "raw_records": records,
        "source": inp.source,
        "fetched_count": len(records),
    }


def validate_records_fn(inp: ValidateInput) -> dict[str, Any]:
    """Drop records whose 'Price' field cannot be parsed as a float."""
    valid: list[dict[str, Any]] = []
    invalid = 0
    for rec in inp.raw_records:
        try:
            float(rec["Price"])
            valid.append(rec)
        except (ValueError, KeyError):
            invalid += 1
    return {"valid_records": valid, "invalid_count": invalid, "source": inp.source}


def normalize_fields_fn(inp: NormalizeInput) -> dict[str, Any]:
    """Lowercase all field names and cast Price→float, Stock→int."""
    normalized = []
    for rec in inp.valid_records:
        normalized.append(
            {
                "product_id": rec["ProductID"],
                "name": rec["Name"],
                "price": float(rec["Price"]),
                "stock": int(rec["Stock"]),
            }
        )
    return {"normalized_records": normalized}


def enrich_records_fn(inp: EnrichInput) -> dict[str, Any]:
    """Add a 'category' field derived from the product name prefix."""
    enriched = []
    for rec in inp.normalized_records:
        prefix = rec["name"].split()[0]
        category = _CATEGORY_MAP.get(prefix, "other")
        enriched.append({**rec, "category": category})
    return {"enriched_records": enriched}


def store_records_fn(inp: StoreInput) -> dict[str, Any]:
    """Simulate writing records to a data warehouse (no actual I/O)."""
    return {
        "stored_count": len(inp.enriched_records),
        "destination": "warehouse",
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Step 3 — Tool objects
# ---------------------------------------------------------------------------

fetch_tool = Tool(
    name="fetch_data",
    description="Fetch raw records from the named data source.",
    input_schema=FetchInput,
    output_schema=RawRecordsOutput,
    fn=fetch_data_fn,
)

validate_tool = Tool(
    name="validate_records",
    description="Validate raw records; drop those that fail schema checks.",
    input_schema=ValidateInput,
    output_schema=ValidatedOutput,
    fn=validate_records_fn,
)

normalize_tool = Tool(
    name="normalize_fields",
    description="Normalize field names and cast types.",
    input_schema=NormalizeInput,
    output_schema=NormalizedOutput,
    fn=normalize_fields_fn,
)

enrich_tool = Tool(
    name="enrich_records",
    description="Add derived fields (e.g., category) to each record.",
    input_schema=EnrichInput,
    output_schema=EnrichedOutput,
    fn=enrich_records_fn,
)

store_tool = Tool(
    name="store_records",
    description="Persist enriched records to the destination store.",
    input_schema=StoreInput,
    output_schema=StoreOutput,
    fn=store_records_fn,
)


# ---------------------------------------------------------------------------
# Step 4 — Flow definition
# ---------------------------------------------------------------------------

etl_flow = Flow(
    name="data_etl",
    description="ETL flow: fetch → validate → normalize → enrich → store.",
    steps=[
        FlowStep(
            tool_name="fetch_data",
            input_mapping={"source": "source", "limit": "limit"},
        ),
        FlowStep(
            tool_name="validate_records",
            input_mapping={"raw_records": "raw_records", "source": "source"},
        ),
        FlowStep(
            tool_name="normalize_fields",
            input_mapping={"valid_records": "valid_records", "source": "source"},
        ),
        FlowStep(
            tool_name="enrich_records",
            input_mapping={"normalized_records": "normalized_records"},
        ),
        FlowStep(
            tool_name="store_records",
            input_mapping={"enriched_records": "enriched_records"},
        ),
    ],
    input_schema=FetchInput,
    output_schema=StoreOutput,
)


# ---------------------------------------------------------------------------
# Step 5 — Execute
# ---------------------------------------------------------------------------


def main() -> None:
    registry = FlowRegistry()
    registry.register_flow(etl_flow)

    executor = FlowExecutor(registry=registry)
    for t in (fetch_tool, validate_tool, normalize_tool, enrich_tool, store_tool):
        executor.register_tool(t)

    initial_input = {"source": "inventory_db", "limit": 5}
    print(f"\nExecuting flow '{etl_flow.name}' with input: {initial_input}\n")

    result = executor.execute_flow("data_etl", initial_input)

    print("\n--- Execution Summary ---")
    print(f"Flow      : {result.flow_name}")
    print(f"Success   : {result.success}")
    print(f"Output    : {result.final_output}")
    print("\n--- Step Log ---")
    for record in result.execution_log:
        status = "OK" if record.success else "FAIL"
        print(
            f"  [{status}] Step {record.step_index} | {record.tool_name} | "
            f"outputs={record.outputs}"
        )

    assert result.success, "ETL flow failed!"
    assert result.final_output is not None
    assert result.final_output["stored_count"] == 4, (
        f"Expected 4 stored records (1 invalid dropped), got {result.final_output['stored_count']}"
    )
    print(
        f"\n✓ ETL flow complete: {result.final_output['stored_count']} records "
        f"stored to '{result.final_output['destination']}' "
        f"(status: {result.final_output['status']})"
    )


if __name__ == "__main__":
    main()
