"""Privacy-preserving stable device identity for desktop activation.

Generates a persistent random UUID installation ID stored in the user profile
(~/.slidecast/device_id) with 0600 permissions. No invasive hardware serials
are collected.
"""

from __future__ import annotations

import hashlib
import os
import platform
from pathlib import Path
import uuid


def get_slidecast_user_dir() -> Path:
    """Return user-scoped storage directory (~/.slidecast or override)."""
    override = os.environ.get("SLIDECAST_USER_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    else:
        path = Path.home() / ".slidecast"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_device_id() -> str:
    """Return persistent, anonymous device ID (SHA256 of persistent install UUID)."""
    id_file = get_slidecast_user_dir() / "device_id"
    if id_file.is_file():
        try:
            content = id_file.read_text(encoding="utf-8").strip()
            if len(content) >= 32:
                return content
        except OSError:
            pass

    # Generate fresh stable UUID
    raw_uuid = str(uuid.uuid4())
    hashed = hashlib.sha256(raw_uuid.encode("utf-8")).hexdigest()
    try:
        # Atomic write with 0600 mode
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(str(id_file), flags, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(hashed)
    except OSError:
        pass
    return hashed


def get_device_name() -> str:
    """Return human-readable friendly device name for device management."""
    node = platform.node() or "Computador"
    system_name = platform.system()
    if system_name == "Darwin":
        system_name = "macOS"
    return f"{node} ({system_name})"


def get_platform_name() -> str:
    """Return canonical platform name: 'windows', 'linux', or 'macos'."""
    sys_lower = platform.system().lower()
    if "darwin" in sys_lower:
        return "macos"
    if "win" in sys_lower:
        return "windows"
    return "linux"
