from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load_verify_dist() -> ModuleType:
    """Load the release helper without making ``scripts`` a Python package."""
    path = _ROOT / "scripts" / "verify_dist.py"
    spec = importlib.util.spec_from_file_location("chainweaver_verify_dist", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_dist = _load_verify_dist().verify_dist


def _metadata(version: str) -> bytes:
    return f"Metadata-Version: 2.4\nName: chainweaver\nVersion: {version}\n\n".encode()


def _build_fixture(
    dist: Path,
    version: str,
    *,
    wheel_metadata_version: str | None = None,
    sdist_metadata_version: str | None = None,
) -> None:
    dist.mkdir()
    wheel_version = wheel_metadata_version or version
    sdist_version = sdist_metadata_version or version

    wheel = dist / f"chainweaver-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"chainweaver-{version}.dist-info/METADATA", _metadata(wheel_version))
        archive.writestr("chainweaver/py.typed", b"")

    sdist = dist / f"chainweaver-{version}.tar.gz"
    raw = _metadata(sdist_version)
    info = tarfile.TarInfo(name=f"chainweaver-{version}/PKG-INFO")
    info.size = len(raw)
    # setuptools ships the .egg-info directory inside the sdist, so a real
    # archive carries a second PKG-INFO. The fixture models that: without it
    # these tests pass against a shape no `python -m build` ever produces.
    egg = tarfile.TarInfo(name=f"chainweaver-{version}/chainweaver.egg-info/PKG-INFO")
    egg.size = len(raw)
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(raw))
        archive.addfile(egg, io.BytesIO(raw))


def test_verify_dist_accepts_matching_wheel_and_sdist(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3")

    verify_dist(dist, "1.2.3")


def test_verify_dist_rejects_wheel_metadata_version_drift(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3", wheel_metadata_version="1.2.2")

    with pytest.raises(ValueError, match="metadata Version"):
        verify_dist(dist, "1.2.3")


def test_verify_dist_rejects_sdist_metadata_version_drift(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3", sdist_metadata_version="1.2.2")

    with pytest.raises(ValueError, match="metadata Version"):
        verify_dist(dist, "1.2.3")


def test_verify_dist_rejects_missing_py_typed(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3")
    wheel = dist / "chainweaver-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("chainweaver-1.2.3.dist-info/METADATA", _metadata("1.2.3"))

    with pytest.raises(ValueError, match=r"py\.typed"):
        verify_dist(dist, "1.2.3")


def test_verify_dist_rejects_extra_distribution_files(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3")
    (dist / "unexpected.txt").write_text("unexpected")

    with pytest.raises(ValueError, match="unexpected files"):
        verify_dist(dist, "1.2.3")


def test_the_nested_egg_info_pkg_info_is_not_mistaken_for_the_sdist_metadata(
    tmp_path: Path,
) -> None:
    """A real sdist carries two PKG-INFO files; only the top-level one counts.

    Verified against a genuine `python -m build` sdist, whose members are
    `chainweaver-X/PKG-INFO` and `chainweaver-X/chainweaver.egg-info/PKG-INFO`.
    Selecting on the `/PKG-INFO` suffix alone finds both and rejects every real
    distribution — which would have failed the build job on the next tag push,
    before upload.
    """
    dist = tmp_path / "dist"
    _build_fixture(dist, "1.2.3")

    with tarfile.open(dist / "chainweaver-1.2.3.tar.gz") as archive:
        names = [m.name for m in archive.getmembers() if m.name.endswith("/PKG-INFO")]
    assert len(names) == 2, f"fixture must model a real sdist, got {names}"

    verify_dist(dist, "1.2.3")
