"""CLI entry point for the offline proposer evals (issues #365, #374).

Runs against a deterministic stub by default (no API keys, used in CI to
validate the harness) or against a real provider adapter when ``--provider`` is
given.  Writes ``results/latest.{json,md}``.

Examples
--------

::

    # Harness self-check with the stub model (no network):
    python -m evals.run_evals

    # Against a real provider (requires the matching extra + credentials):
    python -m evals.run_evals --provider anthropic --model claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import sys

from evals.harness import chain_in_order_stub, load_cases, run_evals, write_reports


def _build_llm_fn(provider: str | None, model: str | None) -> object:
    if provider is None:
        return chain_in_order_stub
    if provider == "anthropic":
        from chainweaver.integrations.llm_anthropic import anthropic_llm_fn

        return anthropic_llm_fn(model or "claude-sonnet-4-6")
    if provider == "openai":
        from chainweaver.integrations.llm_openai import openai_llm_fn

        return openai_llm_fn(model or "gpt-4o")
    raise SystemExit(f"unknown provider: {provider!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline proposer evals.")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

    cases = load_cases()
    llm_fn = _build_llm_fn(args.provider, args.model)
    report = run_evals(cases, llm_fn=llm_fn)  # type: ignore[arg-type]
    json_path, md_path = write_reports(report)
    print(f"pass rate {report.pass_rate:.0%} over {len(report.cases)} cases")
    print(f"wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())
