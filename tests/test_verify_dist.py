from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_dist import verify_dist


def _metadata(version: str) -> bytes:
    return f"Metadata-Version: 2.4\nName: chainweaver\nVersion: {version}\n\n".encode()


def _build_fixture(dist: Path, version: str, *, metadata_version: str | None = None) -> None:
    dist.mkdir()
    effective = metadata_version or version

    wheel = dist / f"chainweaver-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"chainweaver-{version}.dist-info/METADATA", _metadata(effective))
        archive.writestr("chainweaver/py.typed", b"")

    sdist = dist / f"chainweaver-{version}.tar.gz"
    raw = _metadata(effective)
    info = tarfile.TarInfo(name=f"chainweaver-{version}/PKG-INFO")
    info.size = len(raw)
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(raw))


def test_verify_dist_accepts_matching_wheel_and_sdist(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3")

    verify_dist(dist, "1.2.3")


def test_verify_dist_rejects_metadata_version_drift(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3", metadata_version="1.2.2")

    with pytest.raises(ValueError, match="metadata Version"):
        verify_dist(dist, "1.2.3")


def test_verify_dist_rejects_missing_py_typed(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3")
    wheel = dist / "chainweaver-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("chainweaver-1.2.3.dist-info/METADATA", _metadata("1.2.3"))

    with pytest.raises(ValueError, match="py.typed"):
        verify_dist(dist, "1.2.3")


def test_verify_dist_rejects_extra_distribution_files(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3")
    (dist / "unexpected.txt").write_text("unexpected")

    with pytest.raises(ValueError, match="unexpected files"):
        verify_dist(dist, "1.2.3")
