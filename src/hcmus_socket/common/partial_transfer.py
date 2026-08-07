import json
from pathlib import Path
from typing import Optional, Dict, Any

def get_part_paths(target_path: Path) -> tuple[Path, Path]:
    """Trả về đường dẫn file .part và file .part.meta tương ứng."""
    part_path = target_path.with_name(f"{target_path.name}.part")
    meta_path = target_path.with_name(f"{target_path.name}.part.meta")
    return part_path, meta_path

def save_part_metadata(meta_path: Path, total_size: int, uploaded_bytes: int) -> None:
    """Ghi atomically thông tin metadata của file dở dang."""
    data = {
        "total_size": total_size,
        "uploaded_bytes": uploaded_bytes,
    }
    temp_meta = meta_path.with_suffix(".meta.tmp")
    with open(temp_meta, "w", encoding="utf-8") as f:
        json.dump(data, f)
    temp_meta.replace(meta_path)  # Atomic replace

def load_part_metadata(meta_path: Path) -> Optional[Dict[str, Any]]:
    """Đọc file metadata nếu tồn tại."""
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def compute_prefix_hash(file_path: Path, length: int) -> tuple[bytes, int]:
    """
    Đọc length bytes đầu tiên của file và tính SHA-256 prefix state.
    Trả về hasher object (hoặc bytes digest) và số bytes thực sự đã đọc.
    """
    import hashlib
    hasher = hashlib.sha256()
    bytes_read = 0
    
    if not file_path.exists():
        return hasher.digest(), 0
        
    with open(file_path, "rb") as f:
        remaining = length
        chunk_size = 32 * 1024
        while remaining > 0:
            to_read = min(remaining, chunk_size)
            chunk = f.read(to_read)
            if not chunk:
                break
            hasher.update(chunk)
            bytes_read += len(chunk)
            remaining -= len(chunk)
            
    return hasher, bytes_read 