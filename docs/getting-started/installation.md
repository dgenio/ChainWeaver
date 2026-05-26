# Installation

ChainWeaver is published on PyPI and supports Python 3.10+.

## From PyPI

```bash
pip install chainweaver
```

The base install ships with a small runtime dependency stack: `pydantic`, `typer`,
`tenacity`, `packaging`, and `deepdiff`. Everything else is opt-in.

## Optional extras

| Extra | Purpose | Install |
|---|---|---|
| `yaml` | Read and write `.flow.yaml` files | `pip install "chainweaver[yaml]"` |
| `otel` | OpenTelemetry exporter middleware | `pip install "chainweaver[otel]"` |
| `docs` | Build this documentation site locally | `pip install "chainweaver[docs]"` |
| `dev` | Lint, type-check, and test (contributor extra) | `pip install "chainweaver[dev]"` |

## From source

```bash
git clone https://github.com/dgenio/ChainWeaver.git
cd ChainWeaver
pip install -e ".[dev]"
```

## Verify

```bash
python -c "import chainweaver; print(chainweaver.__version__)"
chainweaver --help
```

Both should succeed without error. Continue to
[Your first flow](first-flow.md).
