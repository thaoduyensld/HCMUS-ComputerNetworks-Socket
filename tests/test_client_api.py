from __future__ import annotations

from pathlib import Path

import pytest

from hcmus_socket.client.api import ClientApi
from hcmus_socket.client.download import DownloadResult
from hcmus_socket.client.session import SessionError
from hcmus_socket.client.upload import UploadResult
from hcmus_socket.config import AppConfig
from hcmus_socket.messages import FileListResponse


class FakeSession:
    def __init__(self, config: AppConfig, *, username: str | None = None) -> None:
        self.config = config
        self.username = username
        self.user_id = 0
        self.connected = False
        self.authenticated = False
        self.calls: list[tuple[object, ...]] = []

    def connect(self, username: str | None = None) -> None:
        if username is not None:
            self.username = username
        self.connected = True
        self.authenticated = True
        self.user_id = 7
        self.calls.append(("connect", username))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))
        self.connected = False
        self.authenticated = False
        self.user_id = 0

    def close(self, *, abort: bool = False) -> None:
        self.calls.append(("close", abort))
        self.connected = False
        self.authenticated = False
        self.user_id = 0


def make_api() -> tuple[ClientApi, FakeSession, list[tuple[object, ...]]]:
    operations: list[tuple[object, ...]] = []

    def list_operation(session: FakeSession) -> FileListResponse:
        operations.append(("list", session.user_id))
        return FileListResponse(())

    def upload_operation(
        session: FakeSession,
        source: str | Path,
        remote_filename: str | None,
        *,
        progress: object,
    ) -> UploadResult:
        operations.append(("upload", source, remote_filename, progress))
        return UploadResult(Path(source), remote_filename or Path(source).name, 3, b"x" * 32)

    def download_operation(
        session: FakeSession,
        filename: str,
        *,
        progress: object,
    ) -> DownloadResult:
        operations.append(("download", filename, progress))
        return DownloadResult(Path(filename), 4, b"y" * 32)

    api = ClientApi(
        AppConfig(),
        username="alice",
        session_factory=FakeSession,  # type: ignore[arg-type]
        list_operation=list_operation,  # type: ignore[arg-type]
        upload_operation=upload_operation,
        download_operation=download_operation,
    )
    return api, api.session, operations  # type: ignore[return-value]


def test_facade_delegates_session_lifecycle_and_exposes_identity() -> None:
    api, session, _operations = make_api()

    api.connect()
    assert api.connected
    assert api.authenticated
    assert api.username == "alice"
    assert api.user_id == 7
    api.disconnect()

    assert session.calls == [("connect", None), ("disconnect",)]
    assert not api.connected


def test_file_operations_require_authenticated_session() -> None:
    api, _session, _operations = make_api()

    with pytest.raises(SessionError, match="connected and authenticated"):
        api.list_files()
    with pytest.raises(SessionError, match="connected and authenticated"):
        api.upload_file("local.bin")
    with pytest.raises(SessionError, match="connected and authenticated"):
        api.download_file("remote.bin")


def test_facade_delegates_file_operations_and_progress_callbacks() -> None:
    api, _session, operations = make_api()
    progress = lambda _done, _total, _percent: None
    api.connect()

    listing = api.list_files()
    upload = api.upload_file("local.bin", "remote.bin", progress=progress)
    download = api.download_file("remote.bin", progress=progress)

    assert listing.entries == ()
    assert upload.remote_filename == "remote.bin"
    assert download.bytes_received == 4
    assert operations == [
        ("list", 7),
        ("upload", "local.bin", "remote.bin", progress),
        ("download", "remote.bin", progress),
    ]


def test_close_aborts_owned_session() -> None:
    api, session, _operations = make_api()
    api.connect()

    api.close()

    assert session.calls[-1] == ("close", True)
    assert not api.connected
