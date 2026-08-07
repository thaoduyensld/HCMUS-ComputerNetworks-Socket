"""Namespace resolver and path security for per-user storage isolation."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ..protocol import ErrorCode, ProtocolError

INTERNAL_EXACT_NAMES = frozenset(
    {
        ".hcmus_socket.lock",
        ".hcmus_socket.log",
        "server.log",
        ".DS_Store",
        "Thumbs.db",
    }
)


def ensure_user_namespace(storage_root: Path, username: str) -> Path:
    """Create and return the user's isolated namespace directory."""

    if not username:
        raise ProtocolError(
            ErrorCode.AUTHENTICATION_REQUIRED,
            "username is required for namespace access",
        )
    namespace_dir = storage_root / username
    try:
        namespace_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as error:
        raise ProtocolError(
            ErrorCode.ACCESS_DENIED,
            f"cannot create user namespace directory: {error}",
        ) from error
    except OSError as error:
        raise ProtocolError(
            ErrorCode.FILE_IO_ERROR,
            f"cannot create user namespace directory: {error}",
        ) from error
    return namespace_dir


def is_internal_file(filename: str) -> bool:
    """Return True if *filename* is an internal, partial, or log file."""

    if (
        filename.endswith(".part")
        or filename.endswith(".part.meta")
        or filename in INTERNAL_EXACT_NAMES
    ):
        return True
    return False


def resolve_namespace_path(
    namespace_dir: Path,
    filename: str,
    *,
    allow_internal: bool = False,
    must_exist: bool = False,
) -> Path:
    """Validate and resolve *filename* strictly inside *namespace_dir*."""

    if not filename or filename in {".", ".."}:
        raise ProtocolError(
            ErrorCode.INVALID_FILENAME,
            "filename must not be empty or a traversal component",
        )
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise ProtocolError(
            ErrorCode.INVALID_FILENAME,
            "filename must be a simple basename without path separators",
        )
    if not allow_internal and is_internal_file(filename):
        raise ProtocolError(
            ErrorCode.INVALID_FILENAME,
            "filename is reserved for server-internal use",
        )

    root = namespace_dir.resolve(strict=False)
    target = (namespace_dir / filename).resolve(strict=False)

    try:
        target.relative_to(root)
    except ValueError:
        raise ProtocolError(
            ErrorCode.ACCESS_DENIED,
            "file path escapes the user namespace directory",
        )

    if target.is_symlink():
        try:
            real_path = target.resolve(strict=True)
            real_path.relative_to(root)
        except (OSError, ValueError):
            raise ProtocolError(
                ErrorCode.ACCESS_DENIED,
                "symlink escapes the user namespace directory",
            )

    if must_exist:
        if not target.exists() or not target.is_file():
            raise ProtocolError(ErrorCode.FILE_NOT_FOUND, f"file {filename!r} not found")

    return target
