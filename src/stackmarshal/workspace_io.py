from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
from typing import Any


class WorkspaceWriteError(RuntimeError):
    pass


@dataclass
class TextMutation:
    path: str
    expected_preimage_sha256: str | None
    expected_preimage: str | None
    content_sha256: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": "write_text",
            "path": self.path,
            "expected_preimage_sha256": self.expected_preimage_sha256,
            "expected_preimage": self.expected_preimage,
            "content_sha256": self.content_sha256,
            "content": self.content,
        }


@dataclass
class AppendTextMutation:
    path: str
    expected_preimage_sha256: str | None
    expected_preimage_size: int
    expected_tail: str | None
    append_sha256: str
    append_content: str
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": "append_text",
            "path": self.path,
            "expected_preimage_sha256": self.expected_preimage_sha256,
            "expected_preimage_size": self.expected_preimage_size,
            "expected_tail": self.expected_tail,
            "append_sha256": self.append_sha256,
            "append_content": self.append_content,
            "content_sha256": self.content_sha256,
            "preimage_blob_sha256": self.expected_preimage_sha256,
        }


class DirectWorkspaceWriter:
    mode = "direct"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root.resolve() if root is not None else None

    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def read_text(self, path: Path, *, encoding: str = "utf-8") -> str:
        return path.read_text(encoding=encoding)

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def mkdir(self, path: Path, *, parents: bool = False, exist_ok: bool = False) -> None:
        path.mkdir(parents=parents, exist_ok=exist_ok)

    def write_text(
        self,
        path: Path,
        text: str,
        *,
        encoding: str = "utf-8",
        atomic: bool = False,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not atomic:
            path.write_text(text, encoding=encoding)
            return
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding=encoding)
        temporary.replace(path)

    def append_text(self, path: Path, text: str, *, encoding: str = "utf-8") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding=encoding, newline="\n") as handle:
            handle.write(text)

    def copy_text(self, source: Path, destination: Path, *, encoding: str = "utf-8") -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def planned_paths_under(self, root: Path) -> list[Path]:
        del root
        return []


class HostPlanWorkspaceWriter:
    mode = "host"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        self._mutations: OrderedDict[str, TextMutation | AppendTextMutation] = OrderedDict()
        self._overlay: dict[str, str] = {}
        self._initial_preimages: dict[str, tuple[str | None, str | None]] = {}
        self._required_directories: OrderedDict[str, None] = OrderedDict()

    def _relative(self, path: Path) -> str:
        absolute = path.resolve(strict=False)
        try:
            relative = absolute.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceWriteError(f"Host write path is outside the workspace: {path}") from exc
        if not relative.parts:
            raise WorkspaceWriteError("Host write may not target the workspace root itself")
        current = self.root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise WorkspaceWriteError(f"Host write ancestor may not be a symlink: {relative.as_posix()}")
            if current.exists() and not current.is_dir():
                raise WorkspaceWriteError(f"Host write ancestor is not a directory: {relative.as_posix()}")
        if path.is_symlink():
            raise WorkspaceWriteError(f"Host write target may not be a symlink: {relative.as_posix()}")
        return relative.as_posix()

    def _initial_text(self, path: Path, relative: str, encoding: str) -> tuple[str | None, str | None]:
        if relative in self._initial_preimages:
            return self._initial_preimages[relative]
        if not path.exists():
            result: tuple[str | None, str | None] = (None, None)
            self._initial_preimages[relative] = result
            return result
        if path.is_symlink() or not path.is_file():
            raise WorkspaceWriteError(f"Host write target is not a regular file: {relative}")
        payload = path.read_bytes()
        try:
            text = payload.decode(encoding)
        except UnicodeDecodeError as exc:
            raise WorkspaceWriteError(f"Host write only supports UTF-8 text project files: {relative}") from exc
        result = (text, hashlib.sha256(payload).hexdigest())
        self._initial_preimages[relative] = result
        return result

    def exists(self, path: Path) -> bool:
        relative = self._relative(path)
        return relative in self._overlay or path.exists() or relative in self._required_directories

    def is_file(self, path: Path) -> bool:
        relative = self._relative(path)
        return relative in self._overlay or path.is_file()

    def is_dir(self, path: Path) -> bool:
        relative = self._relative(path)
        return relative in self._required_directories or path.is_dir()

    def read_text(self, path: Path, *, encoding: str = "utf-8") -> str:
        relative = self._relative(path)
        if relative in self._overlay:
            return self._overlay[relative]
        return path.read_text(encoding=encoding)

    def read_bytes(self, path: Path) -> bytes:
        relative = self._relative(path)
        if relative in self._overlay:
            return self._overlay[relative].encode("utf-8")
        return path.read_bytes()

    def mkdir(self, path: Path, *, parents: bool = False, exist_ok: bool = False) -> None:
        del parents, exist_ok
        relative = self._relative(path)
        self._required_directories.setdefault(relative, None)

    def write_text(
        self,
        path: Path,
        text: str,
        *,
        encoding: str = "utf-8",
        atomic: bool = False,
    ) -> None:
        del atomic
        if encoding.casefold().replace("-", "") != "utf8":
            raise WorkspaceWriteError("Host write plans support UTF-8 text only")
        relative = self._relative(path)
        preimage, preimage_hash = self._initial_text(path, relative, encoding)
        content_hash = hashlib.sha256(text.encode(encoding)).hexdigest()
        self._overlay[relative] = text
        self._mutations[relative] = TextMutation(
            path=relative,
            expected_preimage_sha256=preimage_hash,
            expected_preimage=preimage,
            content_sha256=content_hash,
            content=text,
        )
        parent = Path(relative).parent
        while parent.as_posix() not in {".", ""}:
            self._required_directories.setdefault(parent.as_posix(), None)
            parent = parent.parent

    def append_text(self, path: Path, text: str, *, encoding: str = "utf-8") -> None:
        if encoding.casefold().replace("-", "") != "utf8":
            raise WorkspaceWriteError("Host write plans support UTF-8 text only")
        relative = self._relative(path)
        existing = self._mutations.get(relative)
        current = self._overlay.get(relative)
        if current is None:
            preimage, preimage_hash = self._initial_text(path, relative, encoding)
            current = preimage or ""
        else:
            preimage, preimage_hash = self._initial_text(path, relative, encoding)
        next_content = current + text
        self._overlay[relative] = next_content
        if isinstance(existing, TextMutation):
            self._mutations[relative] = TextMutation(
                path=relative,
                expected_preimage_sha256=preimage_hash,
                expected_preimage=preimage,
                content_sha256=hashlib.sha256(next_content.encode(encoding)).hexdigest(),
                content=next_content,
            )
        else:
            append_content = (existing.append_content if isinstance(existing, AppendTextMutation) else "") + text
            self._mutations[relative] = AppendTextMutation(
                path=relative,
                expected_preimage_sha256=preimage_hash,
                expected_preimage_size=len((preimage or "").encode(encoding)),
                expected_tail=(preimage[-512:] if preimage else None),
                append_sha256=hashlib.sha256(append_content.encode(encoding)).hexdigest(),
                append_content=append_content,
                content_sha256=hashlib.sha256(next_content.encode(encoding)).hexdigest(),
            )
        parent = Path(relative).parent
        while parent.as_posix() not in {".", ""}:
            self._required_directories.setdefault(parent.as_posix(), None)
            parent = parent.parent

    def copy_text(self, source: Path, destination: Path, *, encoding: str = "utf-8") -> None:
        self.write_text(destination, source.read_text(encoding=encoding), encoding=encoding)

    def mutations(self) -> list[dict[str, Any]]:
        return [mutation.to_dict() for mutation in self._mutations.values()]

    def recovery_preimages(self) -> dict[str, str]:
        return {
            relative: preimage
            for relative, (preimage, _digest) in self._initial_preimages.items()
            if preimage is not None
        }

    def required_directories(self) -> list[str]:
        return list(self._required_directories)

    def planned_paths_under(self, root: Path) -> list[Path]:
        relative_root = self._relative(root)
        prefix = relative_root.rstrip("/") + "/"
        return [self.root / relative for relative in self._overlay if relative == relative_root or relative.startswith(prefix)]


_CURRENT_WRITER: ContextVar[DirectWorkspaceWriter | HostPlanWorkspaceWriter | None] = ContextVar(
    "stackmarshal_workspace_writer",
    default=None,
)


def current_writer() -> DirectWorkspaceWriter | HostPlanWorkspaceWriter:
    writer = _CURRENT_WRITER.get()
    return writer if writer is not None else DirectWorkspaceWriter()


@contextmanager
def use_writer(writer: DirectWorkspaceWriter | HostPlanWorkspaceWriter) -> Iterator[None]:
    token = _CURRENT_WRITER.set(writer)
    try:
        yield
    finally:
        _CURRENT_WRITER.reset(token)


def exists(path: Path) -> bool:
    return current_writer().exists(path)


def is_file(path: Path) -> bool:
    return current_writer().is_file(path)


def is_dir(path: Path) -> bool:
    return current_writer().is_dir(path)


def read_text(path: Path, *, encoding: str = "utf-8") -> str:
    return current_writer().read_text(path, encoding=encoding)


def read_bytes(path: Path) -> bytes:
    return current_writer().read_bytes(path)


def mkdir(path: Path, *, parents: bool = False, exist_ok: bool = False) -> None:
    current_writer().mkdir(path, parents=parents, exist_ok=exist_ok)


def write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    atomic: bool = False,
) -> None:
    current_writer().write_text(path, text, encoding=encoding, atomic=atomic)


def append_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    current_writer().append_text(path, text, encoding=encoding)


def copy_text(source: Path, destination: Path, *, encoding: str = "utf-8") -> None:
    current_writer().copy_text(source, destination, encoding=encoding)


def planned_paths_under(root: Path) -> list[Path]:
    return current_writer().planned_paths_under(root)
