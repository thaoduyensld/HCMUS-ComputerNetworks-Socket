"""Stable application-facing API shared by desktop UI and other front ends."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from ..config import AppConfig
from ..messages import FileListResponse
from .download import DownloadResult, download_file
from .listing import list_files
from .session import ClientSession, SessionError
from .upload import UploadResult, upload_file


ProgressCallback: TypeAlias = Callable[[int, int, int], None]
SessionFactory: TypeAlias = Callable[..., ClientSession]
ListOperation: TypeAlias = Callable[[ClientSession], FileListResponse]
UploadOperation: TypeAlias = Callable[..., UploadResult]
DownloadOperation: TypeAlias = Callable[..., DownloadResult]


class ClientApi:
    """Own a client session and expose UI-safe, protocol-free operations.

    The caller should serialize operations, for example through one desktop
    worker thread. Protocol framing and socket access remain encapsulated in
    the existing client modules.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        username: str | None = None,
        session_factory: SessionFactory = ClientSession,
        list_operation: ListOperation = list_files,
        upload_operation: UploadOperation = upload_file,
        download_operation: DownloadOperation = download_file,
    ) -> None:
        self.config = config
        self._session = session_factory(config, username=username)
        self._list_operation = list_operation
        self._upload_operation = upload_operation
        self._download_operation = download_operation

    @property
    def session(self) -> ClientSession:
        """Return the owned session for lifecycle inspection and cancellation."""

        return self._session

    @property
    def connected(self) -> bool:
        return self._session.connected

    @property
    def authenticated(self) -> bool:
        return self._session.authenticated

    @property
    def username(self) -> str | None:
        return self._session.username

    @property
    def user_id(self) -> int:
        return self._session.user_id

    def connect(self, username: str | None = None) -> None:
        self._session.connect(username)

    def disconnect(self) -> None:
        self._session.disconnect()

    def close(self, *, abort: bool = True) -> None:
        self._session.close(abort=abort)

    def list_files(self) -> FileListResponse:
        self._require_authenticated()
        return self._list_operation(self._session)

    def upload_file(
        self,
        source: str | Path,
        remote_filename: str | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> UploadResult:
        self._require_authenticated()
        return self._upload_operation(
            self._session,
            source,
            remote_filename,
            progress=progress,
        )

    def download_file(
        self,
        filename: str,
        *,
        destination: str | Path | None = None,
        progress: ProgressCallback | None = None,
    ) -> DownloadResult:
        self._require_authenticated()
        return self._download_operation(
            self._session,
            filename,
            destination=destination,
            progress=progress,
        )

    def _require_authenticated(self) -> None:
        if not self.connected or not self.authenticated:
            raise SessionError("client must be connected and authenticated")

    def __enter__(self) -> ClientApi:
        self.connect()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self.connected:
            self.disconnect()
