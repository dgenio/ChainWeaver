"""Verify that built ChainWeaver distributions match the intended release.

This is deliberately stdlib-only so the release workflow can inspect the exact
wheel and sdist produced by ``python -m build`` before trusted publishing. It
checks artifact cardinality, filenames, core package metadata, and the typed
package marker without importing the package from the build environment.
"""

from __future__ import annotations

import argparse
import email
import re
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Sequence

_PROJECT = "chainweaver"
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _metadata_value(raw: bytes, field: str, *, artifact: Path) -> str:
    message = email.message_from_bytes(raw)
    value = message.get(field)
    if value is None:
        raise ValueError(f"{artifact.name}: metadata has no {field!r} field")
    return value


def _one(paths: list[Path], *, kind: str) -> Path:
    if len(paths) != 1:
        names = ", ".join(path.name for path in paths) or "none"
        raise ValueError(f"expected exactly one {kind}; found {len(paths)}: {names}")
    return paths[0]


def _verify_wheel(path: Path, expected_version: str) -> None:
    expected_prefix = f"{_PROJECT}-{expected_version}-"
    if not path.name.startswith(expected_prefix) or path.suffix != ".whl":
        raise ValueError(
            f"wheel filename {path.name!r} does not match expected version {expected_version!r}"
        )

    with zipfile.ZipFile(path) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError(
                f"{path.name}: expected one .dist-info/METADATA, found {len(metadata_names)}"
            )
        raw = archive.read(metadata_names[0])
        name = _metadata_value(raw, "Name", artifact=path)
        version = _metadata_value(raw, "Version", artifact=path)
        if name.lower() != _PROJECT:
            raise ValueError(f"{path.name}: metadata Name is {name!r}, expected {_PROJECT!r}")
        if version != expected_version:
            raise ValueError(
                f"{path.name}: metadata Version is {version!r}, expected {expected_version!r}"
            )
        if f"{_PROJECT}/py.typed" not in archive.namelist():
            raise ValueError(f"{path.name}: required {_PROJECT}/py.typed marker is missing")


def _verify_sdist(path: Path, expected_version: str) -> None:
    expected_name = f"{_PROJECT}-{expected_version}.tar.gz"
    if path.name != expected_name:
        raise ValueError(f"sdist filename is {path.name!r}, expected {expected_name!r}")

    with tarfile.open(path, mode="r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.endswith("/PKG-INFO")
        ]
        if len(members) != 1:
            raise ValueError(f"{path.name}: expected one PKG-INFO, found {len(members)}")
        extracted = archive.extractfile(members[0])
        if extracted is None:  # pragma: no cover - guarded by member.isfile
            raise ValueError(f"{path.name}: could not read PKG-INFO")
        raw = extracted.read()
        name = _metadata_value(raw, "Name", artifact=path)
        version = _metadata_value(raw, "Version", artifact=path)
        if name.lower() != _PROJECT:
            raise ValueError(f"{path.name}: metadata Name is {name!r}, expected {_PROJECT!r}")
        if version != expected_version:
            raise ValueError(
                f"{path.name}: metadata Version is {version!r}, expected {expected_version!r}"
            )


def verify_dist(dist_dir: Path, expected_version: str) -> None:
    """Validate the exact wheel and sdist under *dist_dir*.

    Raises:
        ValueError: When artifact count, filenames, metadata, or package-data
            invariants do not match *expected_version*.
    """
    if _VERSION_RE.fullmatch(expected_version) is None:
        raise ValueError(
            f"version {expected_version!r} must use X.Y.Z semantic-version format"
        )
    if not dist_dir.is_dir():
        raise ValueError(f"distribution directory does not exist: {dist_dir}")

    wheel = _one(sorted(dist_dir.glob("*.whl")), kind="wheel")
    sdist = _one(sorted(dist_dir.glob("*.tar.gz")), kind="sdist")
    unexpected = sorted(
        path.name
        for path in dist_dir.iterdir()
        if path.is_file() and path not in {wheel, sdist}
    )
    if unexpected:
        raise ValueError(f"unexpected files in distribution directory: {', '.join(unexpected)}")

    _verify_wheel(wheel, expected_version)
    _verify_sdist(sdist, expected_version)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Expected release version in X.Y.Z format")
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify_dist(args.dist_dir, args.version)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"distribution verification error: {exc}", file=sys.stderr)
        return 1
    print(f"verified ChainWeaver {args.version} wheel + sdist metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
