# ChainWeaver v1.0 Release Criteria

This document defines the **measurable, testable bar** ChainWeaver must clear
before the `v1.0.0` tag is cut.

`v1.0.0` is not a reward for completing a feature backlog. It is a promise that:

1. the core public contract is small enough to support for years;
2. the deterministic execution and security invariants are proven by tests;
3. independent users have demonstrated that the product solves the job it claims
   to solve;
4. the release/distribution path is boring and auditable.

Pre-1.0 releases (`0.x.y`) follow
[docs/versioning-policy.md](versioning-policy.md) and may include breaking
changes between minor versions. Once v1.0.0 ships, SemVer guarantees apply in
full to the explicitly designated **stable** API tier.

The product-validation rationale and kill/pivot rules are documented in
[product-validation.md](product-validation.md).

## 0. Product thesis validated independently

These are release blockers, not optional adoption goals.

- [ ] The independent-trace validation program in
  [#553](https://github.com/dgenio/ChainWeaver/issues/553) has analyzed at least
  **5 independent tool-using agent workloads**. Negative/no-op results remain in
  the evidence set.
- [ ] At least **3 independent workload owners** say they would keep using
  ChainWeaver for the validated job (analysis/discovery, governed lifecycle,
  deterministic runtime, or the product shape #553 reveals), with the reason
  recorded.
- [ ] The validation set contains at least one useful candidate that was not
  already identified by the owner **or** one materially better evidence/rejection
  result than the owner's manual analysis.
- [ ] At least one tempting candidate is correctly rejected for a meaningful
  non-determinism, dataflow, side-effect, authorization, or approval reason.
- [ ] Every accepted validation candidate has an explicit **plain-Python or
  host-framework baseline** so ChainWeaver's lifecycle advantage/disadvantage is
  measured against "just write a function", not against a deliberately naive
  agent loop.
- [ ] A public, sanitized validation report includes false positives, false
  negatives, no-op workloads, limitations, and the resulting product decision.
- [ ] [#497](https://github.com/dgenio/ChainWeaver/issues/497) records the chosen
  positioning based on that evidence, or the pivot if the original thesis was
  falsified.
- [ ] [#556](https://github.com/dgenio/ChainWeaver/issues/556) records a deliberate
  keep/qualify/rename decision before broad v1 distribution.

Stars, social impressions, and raw GitHub traffic are **not** v1 criteria.

## 1. Stable public API is deliberately small

The stable API is defined by the tiering work in
[#522](https://github.com/dgenio/ChainWeaver/issues/522), not by everything that
happens to be importable today.

- [ ] Stable, supported, and experimental API tiers are documented and enforced.
- [ ] The stable top-level API is intentionally minimal around the deterministic
  contracts the project is prepared to support long term (for example `Tool`,
  `Flow`, `FlowStep`, `FlowRegistry`, `FlowExecutor`, core serialization, and
  base errors where still justified by #553).
- [ ] Lifecycle/evidence APIs are promoted to the stable tier only if independent
  validation demonstrates that their current shape is durable. Otherwise they
  remain supported or experimental with explicit migration policy.
- [ ] Framework/vendor adapters remain namespaced and do not silently inherit the
  stable-core compatibility promise.
- [ ] Deprecated pre-v1 top-level aliases have a documented migration table and
  transition release.
- [ ] The stable API snapshot has not changed incompatibly during a **minimum
  30-day `1.0.0-rc` soak**, except to fix a release-blocking correctness or
  security defect that restarts the relevant soak.
- [ ] All stable public classes/functions have complete docstrings with
  Args/Returns/Raises where applicable.
- [ ] `docs/versioning-policy.md` states exactly which API tiers receive SemVer
  guarantees after v1.

## 2. Deterministic execution core

- [ ] Linear flows execute without LLM calls (delivered; enforced by
  `tests/test_executor_import_contract.py`).
- [ ] Supported DAG execution semantics are deterministic and covered by the
  branching/topology suites.
- [ ] Conditional branching uses the documented safe predicate model; unsupported
  async parity cases fail explicitly rather than silently changing semantics.
- [ ] Partial-determinism metadata and checkpoint behavior remain explicit and
  tested.
- [ ] The executor invariants remain in force: no LLM, no hidden network I/O, and
  no randomness that influences execution decisions in `executor.py` (see
  [invariants.md](agent-context/invariants.md)).
- [ ] Flow input/output, tool input/output, fallbacks, retries, caching,
  checkpoint/resume, and sync/async paths do not create known validation or
  safety bypasses.

## 3. Authorization, approval, and side-effect safety

The macro-capability security model in
[#554](https://github.com/dgenio/ChainWeaver/issues/554) is a v1 blocker.

- [ ] Compiling several child operations into one capability does **not**
  implicitly aggregate privileges.
- [ ] Authorizing the macro does not make an unauthorized child operation
  executable.
- [ ] Child approval boundaries survive compilation by default; any intentional
  coalescing is explicit, reviewed, scoped, and auditable.
- [ ] Principal/resource-scope semantics are explicit for every governed child
  operation.
- [ ] Fallback, retry, nested-flow, and emergency-override paths cannot bypass
  the same policy checks.
- [ ] Safety/policy contract drift suspends governed deployment instead of
  rewriting the historical approval basis.
- [ ] Audit evidence can reconstruct both the macro-level decision and relevant
  child-level authorization/approval decisions.
- [ ] At least one **independent security/threat-model review** of the v1 security
  boundary has been completed by someone other than the principal maintainer;
  blocking findings are fixed and non-blocking findings are explicitly tracked.

## 4. Privacy and trace minimization

The trace-driven product cannot require unsafe collection practices.

- [ ] Privacy profiles from
  [#527](https://github.com/dgenio/ChainWeaver/issues/527) define at least the
  guarantees for shape-only/minimized, redacted, and explicitly trusted content.
- [ ] Platform/coding-agent trace ingestion defaults to a minimized/shape-only
  mode sufficient for candidate discovery wherever raw values are unnecessary.
- [ ] Redaction/minimization occurs **before persistence**, not only when rendering
  reports.
- [ ] Missing, absent, redacted, hashed (if supported), and trusted-present values
  remain distinguishable in durable evidence.
- [ ] Caches, checkpoints, traces, and generated analysis artifacts cannot
  silently retain fuller payloads than the configured privacy profile permits.
- [ ] Approved governed artifacts contain contracts/digests rather than raw
  observed values unless raw values are explicitly required by the artifact
  contract.

## 5. Evidence, candidate, and lifecycle contracts

This section follows the product evidence rather than forcing the current
architecture into v1.

- [ ] The product decision from #553 determines which evidence/candidate/lifecycle
  APIs actually belong in the v1-supported surface.
- [ ] If the trace-analysis lifecycle remains core, every supported ingestion path
  maps into one durable evidence model or an explicitly versioned compatibility
  layer.
- [ ] Candidate identity, scoring/recommendation policy, evidence references, and
  rejection reasons are deterministic and versioned where they affect durable
  artifacts.
- [ ] Actual observed model boundaries are distinguished from estimated model
  calls; cost/token claims identify measured versus assumed basis.
- [ ] Safety-name heuristics cannot satisfy an explicit safety requirement.
- [ ] Rejected candidates are first-class observable results rather than silently
  disappearing from the recommendation.
- [ ] If #555 demonstrates that portable outputs matter, artifact identity and
  provenance do not require execution through `FlowExecutor`, and exports do not
  claim guarantees their target runtime cannot enforce.

The canonical architecture in #334 should satisfy these criteria **only if it is
still the architecture justified by validation**.

## 6. Structured execution trace and observability

- [ ] Every supported flow execution produces a serializable `ExecutionResult`
  with stable trace identity, timestamps, per-step outcomes, and flow/artifact
  metadata.
- [ ] `ExecutionResult` / `StepRecord` round-trip through their documented
  serialization form.
- [ ] Trace schema is versioned independently of flow/artifact versions.
- [ ] Per-step wall-clock timings are captured consistently.
- [ ] Trace IDs propagate through structured logs and supported observability
  exports.
- [ ] Trace/log output honors the configured privacy profile.

## 7. Persistence, serialization, and drift

- [ ] Supported flow/artifact formats serialize to and from their documented JSON
  and YAML forms.
- [ ] Durable format/schema versions have explicit compatibility rules.
- [ ] Tool and safety/policy contract fingerprints required for governed execution
  round-trip through the relevant artifact.
- [ ] Schema, safety, or policy drift produces structured findings and the
  documented suspend/fail behavior.
- [ ] Import/reference failures surface typed, actionable diagnostics rather than
  executing partially trusted state.

## 8. CLI and first-success path

- [ ] A new evaluator can reach a useful first success without maintainer help.
- [ ] The primary trace-analysis/demo path is runnable from the CLI with a
  checked-in minimized fixture and demonstrates both an accepted and rejected
  candidate.
- [ ] `inspect`, `validate`, `check`, `run`, and the supported analysis/governance
  commands have documented machine-readable output and exit-code contracts.
- [ ] Common first-run failures have deterministic troubleshooting guidance.
- [ ] The README and getting-started docs answer **"why not just write a Python
  function/workflow?"** directly and include a clear `when not to use` path.

## 9. Tooling, CI, release, and supply-chain evidence

- [ ] Lint (`ruff check`), format (`ruff format --check`), type-check, and tests
  pass on the canonical supported Python/OS matrix.
- [ ] Test coverage remains at or above the documented gate.
- [ ] Conformance, minimum-dependency, latest/pre-release dependency, and other
  declared compatibility lanes pass on the exact release commit.
- [ ] PyPI package, source version, Git tag, GitHub Release, changelog, docs
  metadata, wheel, and sdist agree on the exact released version; CI fails on
  incoherence (tracked by #519).
- [ ] Built wheel/sdist metadata is inspected before publication and the exact
  release commit/tag is verified.
- [ ] Release artifacts use the project's documented trusted-publishing and
  attestation path.
- [ ] A failed or intentionally delayed release is visible rather than leaving an
  ambiguous package/tag state.

## 10. Independent adoption and maintainership evidence

A v1 compatibility promise should be informed by people outside the maintainer's
own test suite.

- [ ] At least **3 independent projects or teams** have used the validated core
  product on a serious workload, not only run the tutorial.
- [ ] At least **2 of those adopters** have repeated use across time (for example,
  multiple analysis runs/releases or at least 30 days of continued use) rather
  than a one-off evaluation.
- [ ] At least **one independent downstream integration or adapter** consumes a
  supported ChainWeaver contract without requiring a hard-coded dependency on a
  private maintainer environment.
- [ ] At least **3 non-maintainer humans** have made substantive contributions to
  code, docs, examples, integrations, security review, or real-world validation.
  Bot-only changes do not count.
- [ ] At least one sanitized adopter case study documents what worked, what did
  not, and why the adopter kept or rejected ChainWeaver.
- [ ] `CONTRIBUTING.md`, issue/discussion routing, and release processes are
  sufficient for an outsider to contribute without private maintainer knowledge.

These criteria deliberately prefer downstream use and contribution over star
counts.

## 11. Benchmarks and claims

- [ ] Deterministic-core benchmarks remain reproducible from checked-in scripts
  and fixtures.
- [ ] Any headline correctness, model-call, token, latency, or cost claim links to
  the exact benchmark/trace window/configuration that produced it.
- [ ] Synthetic comparisons are labeled synthetic.
- [ ] Measured and assumed quantities are distinguished explicitly.
- [ ] The public product story includes at least one rejected/no-benefit result so
  benchmarks cannot imply that every repeated sequence should be compiled.
- [ ] The plain-Python/host-framework baseline from #553 is represented wherever
  it is the meaningful competing implementation.

## 12. Documentation and governance

- [ ] README, docs site, package metadata, GitHub description/topics, and release
  notes describe the same product boundary.
- [ ] AGENTS.md, `docs/agent-context/`, and `.github/` instruction projections
  remain internally consistent.
- [ ] `CHANGELOG.md` tracks every supported release and clearly separates
  `Unreleased` work from installable behavior.
- [ ] `docs/versioning-policy.md` defines SemVer, API tiers, artifact versions,
  and the deprecation process.
- [ ] [product-validation.md](product-validation.md) reflects the final v1 product
  decision rather than an obsolete pre-validation hypothesis.
- [ ] This document reflects the actual codebase and adoption state.

## 13. Definition of "done"

ChainWeaver may be tagged `v1.0.0` when:

1. every applicable checkbox above is ticked with a concrete source of evidence;
2. #553 has produced a product decision rather than simply being closed;
3. the stable API has completed its minimum 30-day release-candidate soak;
4. the exact release commit is green across the declared compatibility/release
   gates;
5. blocking security-review findings are resolved;
6. source, package, tag, release, docs, and changelog version state are coherent;
7. the `v1.0.0` changelog and `0.x → 1.0` migration guide are published.

If independent validation falsifies the current product thesis, the correct
response is to change this document and the product **before** v1, not to waive
the evidence criteria.

## Currently outstanding

The following are known v1 blockers as of August 2026. This is not a substitute
for the checkboxes above.

| Item | Why it still blocks v1.0 |
| --- | --- |
| #553 independent product validation | The trace-analysis/governed-capability thesis has not yet been demonstrated across independent real workloads. |
| #554 macro authorization/approval boundary | v1 must not collapse child security boundaries when promoting macro capabilities. |
| #522 API tiering | The current public surface is broader than the compatibility promise v1 should make. |
| #527 privacy profiles | Trace-driven adoption needs explicit minimization and pre-persistence privacy semantics. |
| #519 release coherence | The release pipeline must make source/tag/package/docs state auditable and fail closed on divergence. |
| Independent security review | The v1 threat boundary needs at least one review outside the principal maintainer. |
| Independent adoption evidence | Three serious independent adopters, including repeated use and one downstream integration, are not yet established. |
| 1.0.0-rc soak | The stable API must survive a minimum 30-day release-candidate window. |
| v1 migration/release artifacts | CHANGELOG and `0.x → 1.0` migration material must be ready before tagging. |

Large architecture work such as #334 and the full production golden path #498
is **gated by product evidence** rather than listed as an unconditional v1
feature requirement.
