# Security Policy

ChainWeaver takes security seriously. This file is the entry point GitHub
surfaces in the "Security" tab and the "Report a vulnerability" UI; the
full security posture, what the library does and does not do, redaction
defaults, and production-deployment recommendations live in
[`docs/security.md`](docs/security.md).

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** workflow:

1. Open the repository's
   [Security tab](https://github.com/dgenio/ChainWeaver/security).
2. Click **Report a vulnerability**.
3. Provide a clear description, reproduction steps, affected version(s),
   and the impact you observed.

Private reports are visible only to the maintainers and the reporter, so
embargoed disclosures remain confidential until a fix ships.

Please **do not** open a public issue, pull request, or discussion for
suspected security problems. Use the private reporting channel above so
we can coordinate a fix before the details become public.

## Supported versions

ChainWeaver is pre-1.0; only the latest minor release receives security
fixes. See [`docs/versioning-policy.md`](docs/versioning-policy.md) for
the full support window.

| Version | Supported |
|---------|-----------|
| `0.4.x` | ✅ (current) |
| `< 0.4` | ❌ |

## Response expectations

We aim to acknowledge new reports within **3 business days** and to share
a remediation plan or timeline within **10 business days** after triage.
These targets are best-effort; the maintainer set is small.

## Scope

In scope:

- Vulnerabilities in the `chainweaver` Python package (the executor,
  registry, compiler, CLI, serialization, and supporting modules).
- Dependency vulnerabilities that ChainWeaver propagates to its users
  through `pyproject.toml`.

Out of scope:

- Bugs in user-supplied `Tool.fn` callables — ChainWeaver does not
  sandbox tool code.
- Documentation typos or stylistic feedback (use a regular issue).
- Social-engineering or physical-access attacks on contributors.

## Coordinated disclosure

If a fix requires more time than the response window above, we will
coordinate the embargo with the reporter, request a CVE where
appropriate, and credit the reporter in the release notes unless they
prefer to remain anonymous.
