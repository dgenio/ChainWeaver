# Contributing to ChainWeaver

Thank you for your interest in contributing to ChainWeaver! This guide covers how to get started.

## Getting Started

1. **Fork** the repository and clone your fork:
   ```bash
   git clone https://github.com/<your-username>/ChainWeaver.git
   cd ChainWeaver
   ```

2. **Install dependencies** (requires Python 3.10+):
   ```bash
   pip install -e ".[dev]"
   ```

3. **Create a branch** from `main`:
   ```bash
   git checkout -b your-feature-branch
   ```

## Development Workflow

### Code Style

- Follow existing project conventions (see `.github/copilot-instructions.md`)
- Use [ruff](https://github.com/astral-sh/ruff) for linting: `ruff check .`
- Use [mypy](https://mypy-lang.org/) for type checking: `mypy .`

### Testing

- Run the test suite before submitting:
  ```bash
  pytest
  ```
- Add tests for any new functionality
- Ensure all existing tests still pass

### Commit Messages

Use clear, descriptive commit messages:
- `fix: resolve edge case in flow compilation`
- `feat: add retry logic to tool execution`
- `docs: update quickstart guide`

## Submitting a Pull Request

1. Push your branch to your fork
2. Open a PR against `main` on the upstream repository
3. Fill out the PR template completely
4. Link any related issues (e.g., `Closes #41`)
5. Wait for CI checks to pass and a maintainer review

## Reporting Issues

- Use the **Bug Report** or **Feature Request** issue templates
- Include reproduction steps and version information
- Search existing issues before creating a new one

## Code of Conduct

Be respectful and constructive. We're all here to build something great together.

---

Thank you for contributing! 🎉
