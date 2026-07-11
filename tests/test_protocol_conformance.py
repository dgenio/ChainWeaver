"""Run the in-tree persistence backends through the shipped conformance kit (#397).

This both validates the reference implementations against their protocols and
exercises the ``chainweaver.testing.protocol_suites`` kit itself, so the suite
and the backends it is meant to certify are verified together.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chainweaver.cache import FileStepCache, InMemoryStepCache, StepCache
from chainweaver.checkpoint import Checkpointer, FileCheckpointer, InMemoryCheckpointer
from chainweaver.storage import FileStore, InMemoryStore, RegistryStore
from chainweaver.testing.protocol_suites import (
    CheckpointerConformance,
    RegistryStoreConformance,
    StepCacheConformance,
)


class TestInMemoryStoreConformance(RegistryStoreConformance):
    @pytest.fixture()
    def store(self) -> RegistryStore:
        return InMemoryStore()


class TestFileStoreConformance(RegistryStoreConformance):
    @pytest.fixture()
    def store(self, tmp_path: Path) -> RegistryStore:
        return FileStore(tmp_path)


class TestInMemoryStepCacheConformance(StepCacheConformance):
    @pytest.fixture()
    def cache(self) -> StepCache:
        return InMemoryStepCache()


class TestFileStepCacheConformance(StepCacheConformance):
    @pytest.fixture()
    def cache(self, tmp_path: Path) -> StepCache:
        return FileStepCache(tmp_path)


class TestInMemoryCheckpointerConformance(CheckpointerConformance):
    @pytest.fixture()
    def checkpointer(self) -> Checkpointer:
        return InMemoryCheckpointer()


class TestFileCheckpointerConformance(CheckpointerConformance):
    @pytest.fixture()
    def checkpointer(self, tmp_path: Path) -> Checkpointer:
        return FileCheckpointer(tmp_path)
