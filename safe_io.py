"""Small cross-process-safe file helpers used by the desktop app."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from filelock import FileLock


def resolve_file_path(path: str | os.PathLike[str], base_dir: str | os.PathLike[str] | None = None) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute() and base_dir is not None:
        target = Path(base_dir).expanduser() / target
    return target.resolve()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int | None = None,
) -> Path:
    target = Path(path).expanduser().resolve()
    _ensure_parent(target)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)
        if mode is not None:
            os.chmod(target, mode)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    return target


def atomic_write_json(
    path: str | os.PathLike[str],
    data: Any,
    *,
    indent: int = 2,
    mode: int | None = None,
) -> Path:
    payload = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    return atomic_write_text(path, payload, mode=mode)


def append_text_locked(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
    timeout: float = 30,
    mode: int | None = None,
) -> Path:
    target = Path(path).expanduser().resolve()
    _ensure_parent(target)
    with FileLock(str(target) + ".lock", timeout=timeout):
        with open(target, "a", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(target, mode)
    return target


def update_json_locked(
    path: str | os.PathLike[str],
    updater: Callable[[Any], Any],
    *,
    default: Any = None,
    timeout: float = 30,
    mode: int | None = None,
) -> Any:
    target = Path(path).expanduser().resolve()
    _ensure_parent(target)
    with FileLock(str(target) + ".lock", timeout=timeout):
        current = default
        if target.exists():
            with open(target, "r", encoding="utf-8") as handle:
                current = json.load(handle)
        updated = updater(current)
        atomic_write_json(target, updated, mode=mode)
        return updated
