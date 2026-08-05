"""File transfer streaming and checksum utilities for Phase 1."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO, Generator

from .messages import FileChunk, FileChecksum
from .protocol import CHUNK_SIZE_BYTES


def compute_file_sha256(filepath: Path, chunk_size: int = CHUNK_SIZE_BYTES) -> tuple[int, bytes]:
    """Tính SHA-256 và tổng kích thước của file theo cơ chế streaming (không load cả file vào RAM)."""
    hasher = hashlib.sha256()
    total_bytes = 0
    
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
            total_bytes += len(chunk)
            
    return total_bytes, hasher.digest()


def read_file_chunks(
    filepath: Path, 
    chunk_size: int = CHUNK_SIZE_BYTES
) -> Generator[tuple[FileChunk, bytes], None, tuple[int, bytes]]:
    """
    Đọc file theo chunk 32KB.
    Trả về Generator sinh ra (FileChunk object, chunk_raw_bytes) và đồng thời tính SHA-256.
    """
    hasher = hashlib.sha256()
    offset = 0
    
    with open(filepath, "rb") as f:
        while chunk_data := f.read(chunk_size):
            hasher.update(chunk_data)
            chunk_msg = FileChunk(offset=offset, data=chunk_data)
            yield chunk_msg, chunk_data
            offset += len(chunk_data)
            
    return offset, hasher.digest()


class ProgressTracker:
    """Helper hỗ trợ ghi file tạm và tính SHA-256 ở phía Server."""
    def __init__(self, temp_filepath: Path) -> None:
        self.temp_filepath = temp_filepath
        self.hasher = hashlib.sha256()
        self.written_bytes = 0
        self._file: BinaryIO | None = None

    def open(self) -> None:
        self.temp_filepath.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.temp_filepath, "wb")

    def write_chunk(self, offset: int, data: bytes) -> None:
        if self._file is None:
            raise RuntimeError("File storage is not open")
        
        # Đảm bảo ghi đúng vị trí offset
        self._file.seek(offset)
        self._file.write(data)
        self.hasher.update(data)
        self.written_bytes += len(data)

    def close(self) -> tuple[int, bytes]:
        if self._file:
            self._file.close()
            self._file = None
        return self.written_bytes, self.hasher.digest()