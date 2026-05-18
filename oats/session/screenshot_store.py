"""
Session-scoped screenshot storage.

Screenshots are saved under the coder data directory at
``{data_dir}/screenshots/{session_id}/``.

Each image is named with a timestamp and optional label.
The store provides helpers to:

- save a screenshot from raw bytes or a local file
- list screenshots for the current session
- clean up all screenshots for a session (called on session delete)
- encode a screenshot as a base64 image dict ready for the vision pipeline
"""
from __future__ import annotations

import base64
import shutil
import time
from pathlib import Path
from typing import Any

from oats.core.config import get_data_dir


def _screenshots_root() -> Path:
    """Top-level screenshots directory."""
    return get_data_dir() / "screenshots"


def _session_dir(session_id: str) -> Path:
    """Per-session screenshot directory (created on demand)."""
    d = _screenshots_root() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Public API ───────────────────────────────────────────────────────

def save_screenshot(
    session_id: str,
    data: bytes,
    *,
    label: str = "",
    fmt: str = "png",
) -> Path:
    """Persist a screenshot and return its path.

    Parameters
    ----------
    session_id : str
        Current session ID — used as the subdirectory.
    data : bytes
        Raw image bytes (PNG, JPEG, etc.).
    label : str, optional
        Short label appended to the filename for identification.
    fmt : str
        File extension (default ``"png"``).
    """
    ts = int(time.time() * 1000)
    suffix = f"_{label}" if label else ""
    name = f"{ts}{suffix}.{fmt}"
    path = _session_dir(session_id) / name
    path.write_bytes(data)
    return path


def save_screenshot_from_file(
    session_id: str,
    source: str | Path,
    *,
    label: str = "",
) -> Path:
    """Copy an existing image file into the session screenshot store."""
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Source image not found: {source}")
    fmt = source.suffix.lstrip(".") or "png"
    data = source.read_bytes()
    return save_screenshot(session_id, data, label=label, fmt=fmt)


def list_screenshots(session_id: str) -> list[Path]:
    """Return all screenshots for a session, sorted newest-first."""
    d = _screenshots_root() / session_id
    if not d.exists():
        return []
    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    files = [f for f in d.iterdir() if f.suffix.lower() in exts]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def delete_session_screenshots(session_id: str) -> int:
    """Remove all screenshots for a session.  Returns count deleted."""
    d = _screenshots_root() / session_id
    if not d.exists():
        return 0
    count = sum(1 for _ in d.iterdir())
    shutil.rmtree(d, ignore_errors=True)
    return count


def cleanup_old_screenshots(max_age_seconds: int = 7 * 86400) -> int:
    """Remove screenshot directories older than *max_age_seconds*.

    Called opportunistically — not on a schedule.  Returns count of
    session directories removed.
    """
    root = _screenshots_root()
    if not root.exists():
        return 0
    now = time.time()
    removed = 0
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            age = now - d.stat().st_mtime
            if age > max_age_seconds:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


# ── Vision pipeline helpers ──────────────────────────────────────────

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def encode_image(path: str | Path) -> dict[str, str]:
    """Read an image file and return a dict suitable for Message.add_image().

    Returns ``{"media_type": "image/png", "data": "<base64>"}``
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {p}")
    suffix = p.suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix, "image/png")
    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return {"media_type": media_type, "data": b64}


def encode_image_bytes(data: bytes, fmt: str = "png") -> dict[str, str]:
    """Encode raw image bytes for the vision pipeline."""
    media_type = _MEDIA_TYPES.get(f".{fmt}", "image/png")
    b64 = base64.b64encode(data).decode("ascii")
    return {"media_type": media_type, "data": b64}
