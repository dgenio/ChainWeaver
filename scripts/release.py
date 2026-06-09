"""Prepare and verify ChainWeaver releases.

The package version in ``chainweaver.__init__`` is authoritative. This script
updates the small set of release artifacts that cannot read it dynamically.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SOURCE_VERSION_RE = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
_RELEASE_HEADING_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)
_PYPI_URL = "https://pypi.org/pypi/chainweaver/{version}/json"

_VERSIONED_DOCS = (
    Path(".github/actions/chainweaver/README.md"),
    Path("docs/github-action.md"),
)

_MANUAL_DISTRIBUTION = (
    (
        "MCP Registry publication and awesome-list submissions",
        "Tracked in #325",
        "https://github.com/dgenio/ChainWeaver/issues/325",
    ),
    (
        "Framework ecosystem listings",
        "Tracked in #231",
        "https://github.com/dgenio/ChainWeaver/issues/231",
    ),
    (
        "GitHub Marketplace publication",
        "Tracked in #325",
        "https://github.com/dgenio/ChainWeaver/issues/325",
    ),
)

FetchJson = Callable[[str], dict[str, Any]]
Sleep = Callable[[float], None]


def _parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"Version '{value}' must use X.Y.Z semantic-version format.")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def source_version(root: Path) -> str:
    """Return the authoritative package version."""
    source = (root / "chainweaver/__init__.py").read_text(encoding="utf-8")
    match = _SOURCE_VERSION_RE.search(source)
    if match is None:
        raise ValueError("chainweaver/__init__.py has no literal __version__ assignment.")
    return match.group(1)


def _replace_once(text: str, old: str, new: str, *, path: Path) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"Expected one occurrence of {old!r} in '{path}', found {count}.")
    return text.replace(old, new, 1)


def _update_source_version(root: Path, current: str, target: str) -> None:
    path = root / "chainweaver/__init__.py"
    text = path.read_text(encoding="utf-8")
    old = f'__version__ = "{current}"'
    updated = _replace_once(text, old, f'__version__ = "{target}"', path=path)
    path.write_text(updated, encoding="utf-8")


def _update_manifest(root: Path, target: str) -> None:
    path = root / "server.json"
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    manifest["version"] = target
    packages = manifest.get("packages", [])
    pypi_packages = [item for item in packages if item.get("registryType") == "pypi"]
    if len(pypi_packages) != 1:
        raise ValueError("server.json must contain exactly one PyPI package entry.")
    pypi_packages[0]["version"] = target
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _action_version(text: str, *, path: Path) -> str:
    start = text.find("  chainweaver-version:")
    end = text.find("\n  extra-args:", start)
    if start < 0 or end < 0:
        raise ValueError(f"Could not locate the chainweaver-version input in '{path}'.")
    block = text[start:end]
    match = re.search(r'^    default: "([^"]+)"$', block, re.MULTILINE)
    if match is None:
        raise ValueError(f"Could not locate the chainweaver-version default in '{path}'.")
    return match.group(1)


def _update_action_version(root: Path, current: str, target: str) -> None:
    path = root / ".github/actions/chainweaver/action.yml"
    text = path.read_text(encoding="utf-8")
    actual = _action_version(text, path=path)
    if actual != current:
        raise ValueError(
            f"Action version drift: expected '{current}' before bump, found '{actual}'."
        )
    start = text.index("  chainweaver-version:")
    end = text.index("\n  extra-args:", start)
    block = text[start:end]
    updated = _replace_once(
        block,
        f'    default: "{current}"',
        f'    default: "{target}"',
        path=path,
    )
    path.write_text(text[:start] + updated + text[end:], encoding="utf-8")


def _update_versioned_docs(root: Path, current: str, target: str) -> None:
    for relative in _VERSIONED_DOCS:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        if current not in text:
            raise ValueError(f"Expected release version '{current}' in '{path}'.")
        path.write_text(text.replace(current, target), encoding="utf-8")


def _promote_changelog(root: Path, current: str, target: str, release_date: str) -> None:
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    heading = "## [Unreleased]\n"
    replacement = f"## [Unreleased]\n\n## [{target}] - {release_date}\n"
    text = _replace_once(text, heading, replacement, path=path)
    old_link = f"[Unreleased]: https://github.com/dgenio/ChainWeaver/compare/v{current}...HEAD"
    new_links = (
        f"[Unreleased]: https://github.com/dgenio/ChainWeaver/compare/v{target}...HEAD\n"
        f"[{target}]: https://github.com/dgenio/ChainWeaver/compare/v{current}...v{target}"
    )
    path.write_text(_replace_once(text, old_link, new_links, path=path), encoding="utf-8")


def prepare_release(root: Path, target: str, release_date: str) -> None:
    """Update all release-derived references for ``target``."""
    target_parts = _parse_version(target)
    current = source_version(root)
    current_parts = _parse_version(current)
    if target_parts <= current_parts:
        raise ValueError(f"Release version '{target}' must be greater than current '{current}'.")
    try:
        date.fromisoformat(release_date)
    except ValueError as exc:
        raise ValueError(f"Release date '{release_date}' must use YYYY-MM-DD format.") from exc

    existing_issues = release_issues(root, expected_version=current)
    if existing_issues:
        raise ValueError("Current release metadata is inconsistent: " + "; ".join(existing_issues))

    _update_source_version(root, current, target)
    _update_manifest(root, target)
    _update_action_version(root, current, target)
    _update_versioned_docs(root, current, target)
    _promote_changelog(root, current, target, release_date)


def release_issues(root: Path, *, expected_version: str | None = None) -> list[str]:
    """Return release-metadata consistency problems."""
    version = source_version(root)
    issues: list[str] = []
    if expected_version is not None and version != expected_version:
        issues.append(f"source version is {version}, expected {expected_version}")

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    if 'dynamic = ["version"]' not in pyproject:
        issues.append("pyproject.toml does not declare version as dynamic")
    if 'version = { attr = "chainweaver.__version__" }' not in pyproject:
        issues.append("pyproject.toml does not read chainweaver.__version__")

    manifest: dict[str, Any] = json.loads((root / "server.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        issues.append(f"server.json version is {manifest.get('version')}, expected {version}")
    pypi_versions = [
        item.get("version")
        for item in manifest.get("packages", [])
        if item.get("registryType") == "pypi"
    ]
    if pypi_versions != [version]:
        issues.append(f"server.json PyPI versions are {pypi_versions}, expected [{version!r}]")

    action_path = root / ".github/actions/chainweaver/action.yml"
    action_version = _action_version(
        action_path.read_text(encoding="utf-8"),
        path=action_path,
    )
    if action_version != version:
        issues.append(f"action default is {action_version}, expected {version}")

    for relative in _VERSIONED_DOCS:
        text = (root / relative).read_text(encoding="utf-8")
        if f"v{version}" not in text:
            issues.append(f"{relative.as_posix()} does not reference release tag v{version}")

    for relative in (
        Path(".github/workflows/release.yml"),
        Path(".github/workflows/distribution-check.yml"),
    ):
        if not (root / relative).is_file():
            issues.append(f"{relative.as_posix()} is missing")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = _RELEASE_HEADING_RE.search(changelog)
    if heading is None or heading.group(1) != version:
        actual = heading.group(1) if heading is not None else "missing"
        issues.append(f"CHANGELOG.md top release is {actual}, expected {version}")
    return issues


def release_status(
    root: Path,
    *,
    expected_version: str | None = None,
    generated_on: str | None = None,
) -> str:
    """Render release status as Markdown."""
    version = source_version(root)
    issues = release_issues(root, expected_version=expected_version)
    consistency = "PASS" if not issues else "FAIL"
    details = "All governed references agree." if not issues else "; ".join(issues)
    status_date = generated_on or date.today().isoformat()
    rows = [
        ("Package version", "READY", version),
        ("Release metadata consistency", consistency, details),
        (
            "Release PR automation",
            "CONFIGURED",
            "`.github/workflows/release.yml`",
        ),
        (
            "Post-publish verification",
            "CONFIGURED",
            "`.github/workflows/distribution-check.yml`",
        ),
    ]
    lines = [
        "## Release status",
        "",
        f"Generated: {status_date}",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    lines.extend(f"| {name} | {status} | {detail} |" for name, status, detail in rows)
    lines.extend(
        [
            "",
            "### Manual / asynchronous distribution",
            "",
            "| Item | Status | Completed | Tracker |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {item} | MANUAL | Not completed | [{status}]({url}) |"
        for item, status, url in _MANUAL_DISTRIBUTION
    )
    return "\n".join(lines) + "\n"


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "chainweaver-release-check"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload: dict[str, Any] = json.load(response)
    return payload


def verify_pypi(
    version: str,
    *,
    attempts: int = 12,
    delay: float = 10.0,
    fetch: FetchJson = _fetch_json,
    sleep: Sleep = time.sleep,
) -> None:
    """Wait for an exact ChainWeaver version to resolve from PyPI."""
    _parse_version(version)
    if attempts < 1:
        raise ValueError("PyPI verification attempts must be at least 1.")
    url = _PYPI_URL.format(version=version)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            payload = fetch(url)
            actual = payload.get("info", {}).get("version")
            if actual != version:
                raise ValueError(f"PyPI returned version '{actual}', expected '{version}'.")
            return
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            last_error = exc
            if attempt < attempts:
                sleep(delay)
    raise RuntimeError(
        f"PyPI version '{version}' did not resolve after {attempts} attempts: {last_error}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Prepare a release version.")
    prepare.add_argument("version")
    prepare.add_argument("--date", default=date.today().isoformat())

    check = subparsers.add_parser("check", help="Check release metadata for drift.")
    check.add_argument("--expected-version")

    status = subparsers.add_parser("status", help="Render release status Markdown.")
    status.add_argument("--expected-version")

    subparsers.add_parser("version", help="Print the authoritative package version.")

    pypi = subparsers.add_parser("verify-pypi", help="Wait for a version to resolve on PyPI.")
    pypi.add_argument("version")
    pypi.add_argument("--attempts", type=int, default=12)
    pypi.add_argument("--delay", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the release command-line interface."""
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "prepare":
            prepare_release(root, args.version, args.date)
            problems = release_issues(root, expected_version=args.version)
            if problems:
                raise RuntimeError("; ".join(problems))
        elif args.command == "check":
            problems = release_issues(root, expected_version=args.expected_version)
            if problems:
                raise RuntimeError("; ".join(problems))
        elif args.command == "status":
            print(release_status(root, expected_version=args.expected_version), end="")
            problems = release_issues(root, expected_version=args.expected_version)
            return 1 if problems else 0
        elif args.command == "version":
            print(source_version(root))
        elif args.command == "verify-pypi":
            verify_pypi(args.version, attempts=args.attempts, delay=args.delay)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"release error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
