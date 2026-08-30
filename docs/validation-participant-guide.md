# Independent validation participant guide

ChainWeaver is looking for **critical validation**, not testimonials.

If you operate a tool-using AI agent and can run ChainWeaver against a real or
representative trace set, your result is useful whether ChainWeaver finds a
valuable deterministic capability, finds nothing, or produces a candidate you
reject.

The program is tracked in
[#553](https://github.com/dgenio/ChainWeaver/issues/553). The product thesis and
kill/pivot criteria are in [product-validation.md](product-validation.md).

## What counts as an independent workload?

A workload is independent when it was not created specifically to demonstrate
ChainWeaver's preferred outcome.

Good candidates include:

- coding agents using repository, CI, issue, or documentation tools;
- support/operations agents calling several internal APIs;
- research agents with repeated search/read/extract paths;
- internal MCP-based assistants;
- tool-using workflows from another open-source project.

Synthetic fixtures are useful for reproducing a result after discovery, but
should not be the only source of evidence.

## Keep your traces private

You do **not** need to upload raw prompts, tool arguments, tool outputs, source
code, customer data, credentials, or internal URLs.

Prefer local analysis and export only the evidence needed to explain the result.
Where possible use shape-only/minimized evidence:

- tool identity;
- event order;
- session/trace boundaries;
- model-vs-tool boundaries;
- input/output key or schema shape;
- timing and outcome;
- explicit side-effect/safety classification;
- provenance describing what was observed, inferred, redacted, or unavailable.

The privacy contract is tracked in #527 and trace-ingestion redaction work in
#376. If your environment cannot be represented safely, **do not share the raw
trace**; a qualitative result is better than leaking sensitive data.

## Before running ChainWeaver

This step matters. It prevents hindsight from making every ChainWeaver finding
look obvious.

Inspect the workload yourself and record:

1. which repeated path(s), if any, you would manually turn into a normal Python
   function, workflow node, or macro-tool;
2. which paths you would explicitly **not** automate;
3. why;
4. roughly how much effort you expect the manual solution to take.

Do not use ChainWeaver's candidates as hints for this baseline.

## Run the analysis

Use the current trace/observer path that matches your environment. It is okay if
an adapter or temporary script is needed; #553 is explicitly allowed to learn
before the canonical #334 architecture is complete.

Capture:

- number of sessions/traces analyzed;
- repeated candidate paths;
- support/recurrence evidence;
- actual model-mediated boundaries when observable;
- incompatible/counterexample traces;
- dataflow/schema findings;
- safety/side-effect/approval findings;
- accepted and rejected recommendations;
- fields that were unavailable because of privacy minimization.

A candidate that cannot be justified from the available evidence should be
recorded as uncertain/rejected, not promoted by assumption.

## Compare against the obvious alternative

For at least one accepted candidate, implement the practical baseline you would
otherwise ship:

```python
def the_obvious_macro(...):
    ...
```

or the equivalent primitive in your existing agent/workflow framework.

Then compare it with the ChainWeaver path on:

- discovery effort;
- implementation effort;
- schema/dataflow validation;
- evidence and reviewability;
- authorization/approval handling;
- trace/audit quality;
- drift handling;
- runtime latency;
- actual model-call/token changes where measurable;
- ongoing maintenance burden.

If the manual version wins, say so.

## Security check

Do not approve a macro just because its top-level invocation is convenient.
Verify whether child operations have different:

- principals;
- resource scopes;
- side effects;
- approval requirements;
- retry/idempotency semantics;
- environment policies.

ChainWeaver's target invariant is:

> **remove unnecessary reasoning boundaries, never silently security or approval
> boundaries.**

If compilation would weaken a boundary, reject the candidate and report that as
a valuable result. See #554.

## Result classification

For each meaningful finding, use one of these labels in your report:

- **non-obvious useful discovery** — you did not identify it in the pre-analysis
  baseline and would now consider shipping it;
- **useful evidence for an obvious candidate** — you already knew the path, but
  ChainWeaver materially improved proof/review/governance;
- **useful rejection** — ChainWeaver or the review surfaced a reason not to
  compile a tempting path;
- **false positive** — ChainWeaver recommended or over-ranked something that
  still requires reasoning or is unsafe/unhelpful;
- **false negative** — your manual baseline contains an important candidate
  ChainWeaver missed;
- **no useful candidate** — valid and important evidence.

## Final verdict

Please answer these directly:

1. **Would you keep ChainWeaver installed for this job?** Yes / no / only the
   analyzer / only the runtime / unsure.
2. What is the strongest reason?
3. What is the biggest reason not to adopt it?
4. What would have to change for your answer to improve?
5. Did ChainWeaver change a decision you would otherwise have made?

## Sharing the result

You can share a sanitized result using the repository's **Independent validation
result** issue form after PR #557 lands, or comment directly on #553.

Do not turn the report into a testimonial. Include negative findings, missing
data, and any place where the manual baseline is simpler.
