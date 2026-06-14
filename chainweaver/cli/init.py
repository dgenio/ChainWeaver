"""``chainweaver init`` command (issue #441).

Scaffold a runnable first flow project — tool definitions, a flow file, and a
run script — so new users see value in one command instead of assembling the
pieces by hand.  Three templates are offered: a ``linear`` flow, a ``dag``
flow with a fan-in, and an ``mcp``-ready starter.  ``--with-tests`` adds a
passing pytest module.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer

from chainweaver.cli._shared import app

# ---------------------------------------------------------------------------
# Template payloads — each builder returns {relative_path: file_contents}.
# Flow names are fixed per template so the generated files have no f-string /
# brace-escaping hazards and stay byte-stable (snapshot-friendly).
# ---------------------------------------------------------------------------

_LINEAR_TOOLS = '''"""Tool definitions for the scaffolded linear flow."""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import Tool


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str


double = Tool(
    name="double",
    description="Takes a number and returns its double.",
    input_schema=NumberInput,
    output_schema=ValueOutput,
    fn=lambda inp: {"value": inp.number * 2},
)

add_ten = Tool(
    name="add_ten",
    description="Takes a value and returns value + 10.",
    input_schema=ValueInput,
    output_schema=ValueOutput,
    fn=lambda inp: {"value": inp.value + 10},
)

format_result = Tool(
    name="format_result",
    description="Formats a numeric value into a human-readable result string.",
    input_schema=ValueInput,
    output_schema=FormattedOutput,
    fn=lambda inp: {"result": f"Final value: {inp.value}"},
)

# Exposed at top level so ``--tools tools`` (CLI) discovers them.
TOOLS = [double, add_ten, format_result]
'''

_LINEAR_FLOW_YAML = """type: Flow
name: my_flow
version: "0.1.0"
description: Doubles a number, adds 10, and formats the result.
steps:
  - tool_name: double
    input_mapping:
      number: number
  - tool_name: add_ten
    input_mapping:
      value: value
  - tool_name: format_result
    input_mapping:
      value: value
"""

_LINEAR_RUN = '''"""Run the scaffolded linear flow."""

from __future__ import annotations

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep

from tools import TOOLS

flow = Flow(
    name="my_flow",
    version="0.1.0",
    description="Doubles a number, adds 10, and formats the result.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
)


def run() -> dict:
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in TOOLS:
        executor.register_tool(tool)
    result = executor.execute_flow("my_flow", {"number": 5})
    return result.final_output or {}


if __name__ == "__main__":
    print(run())
'''

_DAG_TOOLS = '''"""Tool definitions for the scaffolded DAG flow."""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import Tool


class NumberInput(BaseModel):
    number: int


class DoubledOutput(BaseModel):
    doubled: int


class TripledOutput(BaseModel):
    tripled: int


class SumInput(BaseModel):
    doubled: int
    tripled: int


class TotalOutput(BaseModel):
    total: int


double = Tool(
    name="double",
    description="Returns 2 * number.",
    input_schema=NumberInput,
    output_schema=DoubledOutput,
    fn=lambda inp: {"doubled": inp.number * 2},
)

triple = Tool(
    name="triple",
    description="Returns 3 * number.",
    input_schema=NumberInput,
    output_schema=TripledOutput,
    fn=lambda inp: {"tripled": inp.number * 3},
)

sum_two = Tool(
    name="sum_two",
    description="Adds the doubled and tripled values.",
    input_schema=SumInput,
    output_schema=TotalOutput,
    fn=lambda inp: {"total": inp.doubled + inp.tripled},
)

TOOLS = [double, triple, sum_two]
'''

_DAG_FLOW_YAML = """type: DAGFlow
name: my_dag_flow
version: "0.1.0"
description: Fan-in DAG — double and triple run in parallel, then sum.
steps:
  - step_id: double
    tool_name: double
    input_mapping:
      number: number
    depends_on: []
  - step_id: triple
    tool_name: triple
    input_mapping:
      number: number
    depends_on: []
  - step_id: sum
    tool_name: sum_two
    input_mapping:
      doubled: doubled
      tripled: tripled
    depends_on:
      - double
      - triple
"""

_DAG_RUN = '''"""Run the scaffolded DAG flow."""

from __future__ import annotations

from chainweaver import DAGFlow, DAGFlowStep, FlowExecutor, FlowRegistry

from tools import TOOLS

flow = DAGFlow(
    name="my_dag_flow",
    version="0.1.0",
    description="Fan-in DAG — double and triple run in parallel, then sum.",
    steps=[
        DAGFlowStep(
            step_id="double",
            tool_name="double",
            input_mapping={"number": "number"},
            depends_on=[],
        ),
        DAGFlowStep(
            step_id="triple",
            tool_name="triple",
            input_mapping={"number": "number"},
            depends_on=[],
        ),
        DAGFlowStep(
            step_id="sum",
            tool_name="sum_two",
            input_mapping={"doubled": "doubled", "tripled": "tripled"},
            depends_on=["double", "triple"],
        ),
    ],
)


def run() -> dict:
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in TOOLS:
        executor.register_tool(tool)
    result = executor.execute_flow("my_dag_flow", {"number": 5})
    return result.final_output or {}


if __name__ == "__main__":
    print(run())
'''

_MCP_FLOW_YAML = """type: Flow
name: my_mcp_flow
version: "0.1.0"
description: A flow ready to expose over MCP with `chainweaver serve`.
steps:
  - tool_name: double
    input_mapping:
      number: number
  - tool_name: add_ten
    input_mapping:
      value: value
  - tool_name: format_result
    input_mapping:
      value: value
"""

_MCP_RUN = '''"""Run the scaffolded MCP-ready flow, or expose it over MCP.

Run it directly::

    python run.py

Or expose it as an MCP server (requires the mcp extra:
``pip install 'chainweaver[mcp]'``)::

    chainweaver serve my_mcp_flow.flow.yaml --tools tools
"""

from __future__ import annotations

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep

from tools import TOOLS

flow = Flow(
    name="my_mcp_flow",
    version="0.1.0",
    description="A flow ready to expose over MCP with `chainweaver serve`.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
)


def run() -> dict:
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in TOOLS:
        executor.register_tool(tool)
    result = executor.execute_flow("my_mcp_flow", {"number": 5})
    return result.final_output or {}


if __name__ == "__main__":
    print(run())
'''


def _test_module(expected_key: str, expected_value: str) -> str:
    """Build a passing pytest module asserting the scaffolded flow's output."""
    return (
        '"""Smoke test for the scaffolded flow."""\n\n'
        "from __future__ import annotations\n\n"
        "from run import run\n\n\n"
        "def test_flow_runs() -> None:\n"
        "    output = run()\n"
        f"    assert output[{expected_key!r}] == {expected_value!r}\n"
    )


class InitTemplate(str, Enum):
    """Project templates offered by ``chainweaver init``."""

    LINEAR = "linear"
    DAG = "dag"
    MCP = "mcp"


def _template_files(template: InitTemplate, *, with_tests: bool) -> dict[str, str]:
    """Return the {relative_path: contents} map for *template*."""
    if template is InitTemplate.LINEAR:
        files = {
            "tools.py": _LINEAR_TOOLS,
            "my_flow.flow.yaml": _LINEAR_FLOW_YAML,
            "run.py": _LINEAR_RUN,
        }
        if with_tests:
            files["test_flow.py"] = _test_module("result", "Final value: 20")
        return files
    if template is InitTemplate.DAG:
        files = {
            "tools.py": _DAG_TOOLS,
            "my_dag_flow.flow.yaml": _DAG_FLOW_YAML,
            "run.py": _DAG_RUN,
        }
        if with_tests:
            files["test_flow.py"] = _test_module("total", "25")
        return files
    # InitTemplate.MCP — reuses the linear tools, adds a serve-ready flow/script.
    files = {
        "tools.py": _LINEAR_TOOLS,
        "my_mcp_flow.flow.yaml": _MCP_FLOW_YAML,
        "run.py": _MCP_RUN,
    }
    if with_tests:
        files["test_flow.py"] = _test_module("result", "Final value: 20")
    return files


def _next_steps(directory: Path, template: InitTemplate, *, with_tests: bool) -> list[str]:
    """Build the deterministic 'next commands' guidance printed after scaffolding."""
    flow_file = {
        InitTemplate.LINEAR: "my_flow.flow.yaml",
        InitTemplate.DAG: "my_dag_flow.flow.yaml",
        InitTemplate.MCP: "my_mcp_flow.flow.yaml",
    }[template]
    lines = ["", "Next steps:"]
    if directory != Path("."):
        lines.append(f"  cd {directory}")
    lines.append("  python run.py")
    lines.append("  pip install 'chainweaver[yaml]'  # to load .flow.yaml via the CLI")
    lines.append(f"  chainweaver run {flow_file} --tools tools --input '{{\"number\": 5}}'")
    if template is InitTemplate.MCP:
        lines.append("  pip install 'chainweaver[mcp]'  # to expose the flow over MCP")
        lines.append(f"  chainweaver serve {flow_file} --tools tools")
    if with_tests:
        lines.append("  pytest test_flow.py")
    return lines


_INIT_DIR_ARG = typer.Argument(
    Path("."),
    help="Directory to scaffold the project into (created if missing; defaults to '.').",
)
_INIT_TEMPLATE_OPTION = typer.Option(
    InitTemplate.LINEAR,
    "--template",
    "-t",
    case_sensitive=False,
    help="Project template: 'linear', 'dag', or 'mcp'.",
)
_INIT_WITH_TESTS_OPTION = typer.Option(
    False,
    "--with-tests",
    help="Also scaffold a passing pytest module (test_flow.py).",
)
_INIT_FORCE_OPTION = typer.Option(
    False,
    "--force",
    help="Overwrite existing files instead of aborting on a collision.",
)


@app.command("init")
def init_command(
    directory: Path = _INIT_DIR_ARG,
    template: InitTemplate = _INIT_TEMPLATE_OPTION,
    with_tests: bool = _INIT_WITH_TESTS_OPTION,
    force: bool = _INIT_FORCE_OPTION,
) -> None:
    """Scaffold a runnable first flow project (issue #441).

    Generates tool definitions, a ``.flow.yaml`` file, and a ``run.py`` script
    (plus a passing test with ``--with-tests``) from one of three templates,
    then prints the exact next commands.

    Exit codes: 0 on success, 1 if a target file already exists and ``--force``
    was not given, 2 if *directory* exists but is not a directory.
    """
    if directory.exists() and not directory.is_dir():
        typer.echo(f"chainweaver: not a directory: {directory}", err=True)
        raise typer.Exit(code=2)

    files = _template_files(template, with_tests=with_tests)

    if not force:
        collisions = [rel for rel in files if (directory / rel).exists()]
        if collisions:
            typer.echo(
                "chainweaver: refusing to overwrite existing file(s): "
                f"{', '.join(sorted(collisions))}. Re-run with --force to overwrite.",
                err=True,
            )
            raise typer.Exit(code=1)

    directory.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        (directory / rel).write_text(content, encoding="utf-8")

    typer.echo(f"Created {template.value} flow project in {directory}:")
    for rel in files:
        typer.echo(f"  - {rel}")
    for line in _next_steps(directory, template, with_tests=with_tests):
        typer.echo(line)
