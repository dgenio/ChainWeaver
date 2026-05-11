# Security Posture

> Reference document for ChainWeaver's security posture and recommended
> production configuration.  Skim this before deploying ChainWeaver in any
> environment that handles credentials, PII, or other sensitive data.

---

## What ChainWeaver does — and does not — do

ChainWeaver is a deterministic in-process orchestration layer.  It deliberately
omits behaviours that would expand its security surface:

| ChainWeaver does NOT… | …because |
|---|---|
| Make any LLM or AI client calls in `executor.py` | Hard executor invariant 1 |
| Perform network I/O in `executor.py` | Hard executor invariant 2 |
| Use randomness in `executor.py` | Hard executor invariant 3 (jitter is opt-in inside `flow.py`'s `RetryPolicy`) |
| Persist data, logs, or traces by default | The library is in-memory; persistence is the application's choice |
| Send telemetry | The library has no outbound calls |
| Pull additional dependencies at runtime | The runtime deps are limited to `pydantic`, `tenacity`, `typer`, and `packaging` |

Network I/O — when needed — happens inside individual `Tool.fn` callables
that the application registers, not in the executor itself.

---

## What ChainWeaver logs

`chainweaver/log_utils.py` emits structured log records via the standard
library `logging` module under the `chainweaver` logger namespace.

| Log point | Default contents |
|---|---|
| `Step <i> START` | step index, tool name, fully resolved input dict |
| `Step <i> END` | step index, tool name, output dict |
| `Step <i> ERROR` | step index, tool name, exception class + message |
| Flow `started`, `aborted at step`, `completed successfully` | flow name, trace id |

Log handlers are **not** attached by ChainWeaver.  A
`logging.NullHandler` is registered on the package logger so the application
controls verbosity, format, and destination via `logging.basicConfig`,
`logging.config.dictConfig`, or any other mechanism.

---

## Redaction (`RedactionPolicy`)

When tool inputs or outputs may carry secrets or PII, configure a
`RedactionPolicy` on the executor.  Redaction is applied to the log
output only — the raw values remain in the in-memory `ExecutionResult`
trace so authorized callers can still inspect what happened.

```python
import re
from chainweaver import FlowExecutor, RedactionPolicy

policy = RedactionPolicy(
    # Override the defaults if you want a different set:
    # redact_keys=frozenset({"password", "token", "ssn", ...}),
    redact_pattern=re.compile(r"sk-\w+"),  # OpenAI-style keys appearing in values
    max_value_length=200,                  # truncate long values in logs
)
executor = FlowExecutor(registry=registry, redaction_policy=policy)
```

**Defaults** (`DEFAULT_REDACT_KEYS`): `password`, `token`, `api_key`, `apikey`,
`secret`, `authorization`.  Matching is case-insensitive.  Redaction is
applied recursively to nested dicts and lists.

> **Trace fields are stored raw on purpose.**  Treat the `ExecutionResult`
> object as you would treat any other in-memory structure carrying tool
> data: don't serialize it to disk or send it across the network without an
> explicit decision about which fields are safe to expose.

---

## Recommendations for production

1. **Always configure a `RedactionPolicy`** for flows whose tools handle
   credentials, PII, or PHI — even if you "trust" the upstream
   sanitization.  Defense in depth.
2. **Use the trace ID** (`ExecutionResult.trace_id`) as the correlator
   between log lines and any external logging or tracing system you
   forward records to.
3. **Set `max_output_size` on tools** that fetch arbitrary external data
   (HTTP, database queries) to bound the log volume and the in-memory
   trace.  See issue #43 — `Tool(timeout_seconds=..., max_output_size=...)`.
4. **Avoid logging the full raw trace** to long-term storage.  If you
   must persist execution data, redact first via
   `RedactionPolicy.redact(...)` on the inputs/outputs you care about, or
   serialize a derived/projected form.
5. **Keep tool functions side-effect-aware.**  ChainWeaver's executor is
   deterministic, but your tools may not be (network, files, databases).
   Apply your own least-privilege practices to tool implementations —
   limit credentials they can read, don't log secrets inside the
   function body, prefer scoped service accounts.
6. **Pin runtime dependencies.**  `pydantic`, `tenacity`, `typer`, and
   `packaging` are the runtime dependencies; all four are well-maintained,
   but pinning protects against supply-chain regressions.

---

## Reporting a security issue

Open a GitHub issue using the bug-report form, or contact the
maintainers privately if the issue is sensitive.  Do not include
proof-of-concept exploits or production secrets in public issues.
