# Design proposal: a stable, signed flow-bundle format

> Design proposal for issue #425 (low confidence — the goal is to scope the
> format and signing choices before any implementation). Builds on the existing
> attestation machinery and relates to the reference-host direction (#291) and
> the language-neutral spec proposal (#426).
>
> **Date:** 2026-07-11 · **Method:** design synthesis grounded in
> `chainweaver/attest.py`, `chainweaver/schemas.py`,
> `chainweaver/serialization.py`, and `chainweaver/flow/`.
> **Confidence tags:** *Confirmed* = grounded in the codebase; *Proposed* = a
> design choice open for review; *Could not determine* = deferred.

## 1. Motivation

ChainWeaver already produces attestations — `attest_flow()` →
`AttestationReport` with schema-hash fingerprints (#154, *Confirmed*). The
missing piece for real distribution is a **self-contained artifact** that
travels with its provenance and can be **cryptographically verified before
execution**, so a vetted flow can ship to production hosts (the #291 direction)
with tamper-evidence. Today a `.flow.yaml` file carries the flow definition but
not its referenced schemas, its attestation, or a signature.

## 2. What must travel together

A flow is not self-contained on disk:

- The **flow definition** (`.flow.yaml` / `.flow.json`) — *Confirmed* via
  `serialization.py`.
- The **referenced schemas** — `input_schema_ref` / `output_schema_ref` /
  `context_schema_ref` are `"module:qualname"` strings resolved by importing
  Python modules (`chainweaver/flow/refs.py`). *Confirmed.* This is the hard
  part: a bundle that only names a Python module is neither portable nor
  verifiable. A bundle must carry the **resolved JSON Schema** of each ref
  (via `schemas.py` / `model_json_schema()`), not the import path.
- The **attestation / provenance** — the `AttestationReport` and the tool
  `schema_hash` set the flow was vetted against. *Confirmed available.*
- A **format version** — so consumers can detect shape evolution (mirroring
  `trace_schema_version` / `SNAPSHOT_VERSION`). *Confirmed pattern exists.*

## 3. Proposed bundle shape (`.cwb`)

*Proposed.* A single archive (zip or tar) — or a canonical-JSON manifest with
embedded content — containing:

```text
bundle.json                # manifest: bundle_format_version, flow name/version,
                           #   provenance, schema digests, signature block
flow.flow.json             # canonical flow definition
schemas/<name>.schema.json # resolved JSON Schema per *_schema_ref (no import)
attestation.json           # AttestationReport (aggregate_fingerprint, seeds)
```

`bundle.json` manifest fields (*Proposed*):

| Field | Purpose |
|-------|---------|
| `bundle_format_version` | MAJOR-gated compatibility, like `SNAPSHOT_VERSION` |
| `flow` | name + version + `sha256` of `flow.flow.json` |
| `schemas` | map of ref → filename + `sha256` |
| `attestation` | `sha256` of `attestation.json` + its `aggregate_fingerprint` |
| `provenance` | producer identity, build time, source commit (host-supplied) |
| `signature` | detached signature over the canonical manifest bytes |

Verification order (*Proposed*): verify signature over the manifest → verify
each `sha256` in the manifest against the archived bytes → only then load the
flow. A mismatch aborts before any flow parsing or ref resolution runs.

## 4. Signing

*Proposed, open for review — the core decision this doc exists to scope.*

- **Option A — Sigstore/`cosign`-style keyless** (OIDC-backed). Matches the
  release pipeline's existing OIDC trusted-publishing posture (#346) and avoids
  key management, at the cost of a heavier dependency and an online transparency
  log. *Inferred fit: strong for the org's own CI-published bundles.*
- **Option B — detached signature with a supplied key** (e.g. `ed25519` via a
  minimal crypto dep, or PEP 740-style attestations). Simpler, offline-friendly,
  no transparency log; the host owns key distribution.
- **Constraint (#431):** signing pulls a crypto library into scope. It must live
  behind an optional extra (e.g. `chainweaver[bundle]`), never the base package —
  the dependency-contract guard (#378/#431) would otherwise fail. *Confirmed
  constraint.*

Recommendation: ship **verification** in a lightweight extra and support both
signer options behind an interface, so an air-gapped consumer can verify Option
B bundles without the Sigstore stack. *Proposed.*

## 5. Boundaries and non-goals

- The bundle carries **resolved schemas**, so it never resolves a
  `"module:qualname"` ref by importing untrusted code — this closes the same
  trust boundary the CLI ref-allowlist (#345) addresses, by construction.
- No new runtime behavior in `executor.py`; bundling/verification is an
  offline, build/deploy-time concern. *Confirmed invariant-preserving.*
- Tool *implementations* are out of scope — a bundle distributes the governed
  flow contract + provenance, not the Python tool code (that remains the host's
  responsibility, like today).

## 6. Open questions / could not determine

- Archive vs. single-file-JSON encoding — ergonomics vs. streaming verification.
- Whether to co-design the manifest with #426's language-neutral spec so a
  bundle is executable by non-Python runtimes (strong synergy; *Proposed* to
  sequence #426 first).
- Revocation / expiry semantics — *Could not determine*; likely out of scope for v1.
