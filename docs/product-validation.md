# Product validation and adoption gates

ChainWeaver is technically mature enough that the next risk is not a missing
workflow feature. It is building more architecture before proving that the
product solves a problem external users want solved.

This page records the current product thesis as a **falsifiable hypothesis**,
not a claim of market validation.

## The hypothesis

> **ChainWeaver analyzes how agents actually use tools, finds repeated
> model-mediated paths, proves which ones no longer require reasoning, rejects
> unsafe or non-deterministic candidates, and turns approved paths into
> governed deterministic capabilities.**

The deterministic executor is useful, but deterministic execution by itself is
not the differentiator. A team that already knows a workflow is fixed can write
a normal Python function, a LangGraph node, or a provider-native tool.

ChainWeaver earns its place only when the **discovery, evidence, rejection,
review, security, drift, or portability lifecycle** adds enough value to justify
another dependency.

The primary validation experiment is tracked in
[#553](https://github.com/dgenio/ChainWeaver/issues/553). Independent participants
can follow the concrete [validation participant guide](validation-participant-guide.md).

## The baseline ChainWeaver must beat

For every accepted candidate in the validation program, compare two solutions:

1. the obvious plain-Python or host-framework implementation;
2. the ChainWeaver analysis and governed lifecycle.

The comparison must cover more than execution speed:

- time to discover the opportunity;
- evidence for recurrence and actual model mediation;
- cumulative dataflow and schema validation;
- counterexamples and rejected candidates;
- approval and authorization handling;
- reproducibility and auditability;
- drift detection;
- maintenance effort;
- latency, model-call, and token effects when they are actually observed.

If `def macro(...): ...` is the better lifecycle for the user, record that as a
negative result rather than redefining success.

## Independent-trace validation

Before broad distribution or a large lifecycle rewrite, analyze at least five
independent tool-using agent workloads. Prefer external projects or teams.
Where traces are sensitive, run the analysis locally and export only minimized
or aggregate evidence.

For each workload:

1. ask the owner to inspect the traces and write down the deterministic
   capabilities they would create manually;
2. run ChainWeaver without using those answers as hints;
3. retain accepted **and rejected** candidates;
4. classify findings as obvious, useful-after-inspection, genuinely non-obvious,
   wrong, or missing;
5. implement accepted candidates using both the manual baseline and ChainWeaver;
6. ask whether the owner would keep ChainWeaver installed for this job, and why.

A flattering demo is not the objective. Workloads where ChainWeaver finds
nothing useful belong in the result set.

The repository includes a structured **Independent validation result** issue form
so reports capture the pre-analysis baseline, privacy mode, rejected/missed
candidates, manual comparison, security result, and keep/uninstall verdict rather
than only positive outcomes.

## Security invariant

> **ChainWeaver may remove unnecessary reasoning boundaries. It must never
> silently remove security, authorization, or approval boundaries.**

Compiling several child tools into one macro capability must not implicitly
aggregate privileges. Governed execution should preserve or narrow the
principal, resource scope, approval requirements, and side-effect constraints
of the child operations unless a reviewer explicitly approves a different
policy.

The detailed contract and adversarial cases are tracked in
[#554](https://github.com/dgenio/ChainWeaver/issues/554), with the current
implementation/gap described in
[Macro-capability security boundary](macro-capability-security.md). An independent
threat-model review is requested in
[#558](https://github.com/dgenio/ChainWeaver/issues/558).

At minimum:

- authorizing a macro does not automatically authorize every child tool;
- a child approval boundary survives compilation by default;
- unknown safety semantics fail closed for recommendation and promotion;
- fallback, retry, and nested-flow paths use the same enforcement;
- policy or safety-contract drift suspends governed execution rather than
  rewriting historical approval evidence;
- audit evidence makes the macro-level and child-level decisions reconstructable.

### Current limitation

Today `FlowServer` can authenticate a caller and authorize the flow/MCP-tool
invocation, while `FlowExecutor` can independently enforce child
`ToolSafetyContract` approval and side-effect rules. The authenticated caller is
not yet threaded into the executor's per-step approval context, so ChainWeaver
does **not** currently claim generic caller-specific child authorization for a
macro invocation. That missing compositional principal/policy seam is a v1
blocker under #554, not a documentation caveat to wave away.

## Privacy invariant

Useful trace analysis must not require sending raw agent conversations or tool
payloads to the project maintainer or a hosted service.

The intended default for platform trace ingestion is **shape-only/minimized
evidence**: identities, ordering, schema/key shape, timing, outcome, provenance,
and model/tool boundaries without raw argument or output values wherever the
analysis does not need them.

Privacy profiles are tracked in
[#527](https://github.com/dgenio/ChainWeaver/issues/527), with ingestion
redaction work in
[#376](https://github.com/dgenio/ChainWeaver/issues/376).

## Architecture gate

The canonical evidence/candidate architecture in
[#334](https://github.com/dgenio/ChainWeaver/issues/334) is a likely destination
**if independent validation demonstrates the lifecycle is valuable**. It is no
longer a prerequisite for running the product experiment.

Use current or temporary interfaces where necessary to learn from real traces.
Only turn recurring validation pain into durable architecture after the pain is
observed.

The production-grade OTel-to-governed-capability golden path in
[#498](https://github.com/dgenio/ChainWeaver/issues/498) follows the same rule:
first validate the job, then make the proof canonical and production-grade.

## Runtime portability gate

If users value ChainWeaver's analysis and review evidence but do not want to
adopt `FlowExecutor`, treat that as product information rather than resistance
to overcome.

[#555](https://github.com/dgenio/ChainWeaver/issues/555) explores whether an
approved capability can preserve identity, provenance, schemas, and the
portable subset of governance guarantees while executing outside the
ChainWeaver runtime.

The repository already has adapter portability (`flow_to_callable`, OpenAI /
Anthropic tool schemas, LangGraph and Agents SDK recipes) that lets other hosts
**call ChainWeaver's executor**. #555 is intentionally about the harder question
of true **execution portability** if validation creates demand for it.

Do not build a broad adapter matrix before user evidence demands it.

## Distribution gate

Broad directory submissions, marketplace work, hosted playground investment,
and additional framework adapters are useful only after the product thesis and
name are sufficiently stable.

The naming/search decision is tracked in
[#556](https://github.com/dgenio/ChainWeaver/issues/556). The immediate
validation-phase decision is to keep the current technical identifiers and
qualify the public brand/category; the final keep-vs-rename gate happens after
#553 and before broad launch/v1 distribution.

Distribution work may continue when it directly supports a validation
participant, but it should not out-prioritize the validation program.

## Success, kill, and pivot signals

| Evidence | Interpretation |
| --- | --- |
| At least three of five independent owners would keep using ChainWeaver | Strong positive product signal |
| ChainWeaver repeatedly finds useful candidates owners did not identify beforehand | Strong discovery signal |
| ChainWeaver provides materially better evidence or rejection for tempting candidates | Strong governance/analysis signal |
| Independent projects integrate it without maintainer-led implementation | Strong adoption signal |
| Repeated deterministic paths are rare | Narrow the market or stop the broad thesis |
| Humans immediately identify every useful candidate and evidence adds little | Trace-mining value is weak |
| Users value analysis but prefer their existing runtime | Pivot toward analyzer/compiler + portable artifacts |
| Users value `FlowExecutor` but not trace discovery | Simplify toward a deterministic-flow library |
| Security reviewers reject macro capabilities because boundaries collapse | Fix the security model before growth |

Negative results are product results. Do not move the goalposts to preserve the
current architecture.

## v1 implication

`v1.0.0` should mean more than "the feature checklist is complete." It should
indicate that a deliberately small public surface has survived a release-candidate
soak **and** that the project has independent evidence that people use the core
job successfully.

The measurable v1 thresholds live in
[`v1-release-criteria.md`](v1-release-criteria.md).