from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DiscoveryAdapter(Protocol):
    def search(self, query: str, limits: dict[str, int]) -> list[dict[str, Any]]: ...

    def fetch_metadata(self, identifier: str) -> dict[str, Any]: ...


class AcquisitionAdapter(Protocol):
    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]: ...

    def install_isolated(self, candidate: dict[str, Any], sandbox: Path) -> dict[str, Any]: ...

    def install_project(self, candidate: dict[str, Any], target: Path) -> dict[str, Any]: ...

    def rollback(self, receipt: dict[str, Any]) -> None: ...


class HostWriteAdapter(Protocol):
    """Host-side transport for StackMarshal-signed project mutations.

    Core owns state transitions and the signed pre/postimage contract. A host adapter
    may batch native writes, but it must not weaken CAS checks or acknowledge a plan
    until the final postimages match Core's signed hashes.
    """

    supports_atomic_multi_file: bool
    supports_full_preimage_cas: bool
    supports_append_cas: bool

    def apply_write_plan(self, plan: dict[str, Any]) -> dict[str, Any]: ...


class AgentAdapter(Protocol):
    def detect_environment(self) -> dict[str, Any]: ...

    def list_native_capabilities(self) -> list[dict[str, Any]]: ...

    def execute_task(self, task: dict[str, Any]) -> dict[str, Any]: ...

    def verify(self, scope: Path) -> dict[str, Any]: ...
