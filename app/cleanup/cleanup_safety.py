"""
Cleanup safety — path validation, allowlisted roots, traversal prevention.
"""

import os
import platform
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("cleanup.safety")

# ── Approved cleanup roots ────────────────────────────────────
# Only paths under these roots are considered safe for cleanup.
_user_temp = tempfile.gettempdir()

ALLOWED_CLEANUP_ROOTS: List[str] = []

# User TEMP directory
if _user_temp and os.path.isdir(_user_temp):
    ALLOWED_CLEANUP_ROOTS.append(os.path.normpath(_user_temp))

# System TEMP (Windows: C:\Windows\Temp)
_system_temp = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp")
if os.path.isdir(_system_temp):
    ALLOWED_CLEANUP_ROOTS.append(os.path.normpath(_system_temp))

# Recycle Bin root is handled separately via Shell32 API, not path-based.
# NVIDIA shader cache locations
_nvidia_cache = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "NVIDIA", "DXCache"
)
_nvidia_cache2 = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "NVIDIA", "GLCache"
)
for _p in [_nvidia_cache, _nvidia_cache2]:
    if _p and os.path.isdir(_p):
        ALLOWED_CLEANUP_ROOTS.append(os.path.normpath(_p))

# AMD shader cache
_amd_cache = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "AMD", "DXCache"
)
if _amd_cache and os.path.isdir(_amd_cache):
    ALLOWED_CLEANUP_ROOTS.append(os.path.normpath(_amd_cache))

# ── Rejected paths (never delete these) ──────────────────────
# These are absolute, case-insensitive on Windows.

def _norm(p: str) -> str:
    """Normalize path for comparison."""
    return os.path.normpath(os.path.abspath(p)).lower()


# Build rejected paths
_user_profile = os.environ.get("USERPROFILE", "")
_rejected_dirs = []

for _d in ["Documents", "Desktop", "Downloads", "Pictures", "Videos", "Music"]:
    _p = os.path.join(_user_profile, _d)
    if _p:
        _rejected_dirs.append(_norm(_p))

for _d in [
    os.environ.get("SystemRoot", r"C:\Windows"),
    os.environ.get("ProgramFiles", r"C:\Program Files"),
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    os.environ.get("ProgramData", r"C:\ProgramData"),
]:
    if _d:
        _rejected_dirs.append(_norm(_d))

# Project directory (never delete Phoenix/Heaven Society files)
_project_dir = _norm(os.path.join(os.path.dirname(__file__), "..", ".."))
_rejected_dirs.append(_project_dir)


def is_path_in_allowed_root(path: str) -> bool:
    """Check if a path is within an approved cleanup root."""
    try:
        resolved = os.path.normpath(os.path.abspath(path))
        for root in ALLOWED_CLEANUP_ROOTS:
            if resolved.startswith(root):
                return True
        return False
    except (OSError, ValueError):
        return False


def is_path_rejected(path: str) -> bool:
    """Check if a path is in a rejected/protected directory."""
    try:
        resolved = _norm(path)
        for rejected in _rejected_dirs:
            if resolved.startswith(rejected):
                return True
        return False
    except (OSError, ValueError):
        return True  # If we can't resolve, reject it


def is_safe_to_delete(path: str) -> bool:
    """
    Determine if a path is safe to delete.

    Returns True only if:
    - path is within an allowed cleanup root
    - path is NOT in a rejected directory
    - path exists
    - path is NOT a symlink/junction to a rejected location
    """
    if not path or not path.strip():
        return False

    try:
        resolved = os.path.normpath(os.path.abspath(path))
    except (OSError, ValueError):
        return False

    # Check rejected paths first
    if is_path_rejected(resolved):
        return False

    # Check allowed roots
    if not is_path_in_allowed_root(resolved):
        return False

    # Check for symlinks pointing to rejected locations
    try:
        if os.path.islink(resolved):
            real = os.path.realpath(resolved)
            if is_path_rejected(real):
                return False
    except (OSError, ValueError):
        return False

    return True


def is_symlink_or_reparse(path: str) -> bool:
    """
    Check if a path is a symlink, junction, or reparse point.
    On Windows, reparse points include symlinks and junctions.
    We reject deletion of these to prevent traversal attacks.
    """
    try:
        if os.path.islink(path):
            return True
        # On Windows, check for reparse points via stat
        if platform.system() == "Windows":
            try:
                import ctypes
                from ctypes import wintypes
                FILE_ATTRIBUTE_REPARSE_POINT = 0x400
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
                if attrs != -1 and (attrs & FILE_ATTRIBUTE_REPARSE_POINT):
                    return True
            except Exception:
                pass
    except (OSError, ValueError):
        pass
    return False


def validate_path_security(path: str) -> Tuple[bool, str]:
    """
    Comprehensive path security validation.
    Returns (is_safe, reason).

    Checks:
    - Path is not empty
    - Path resolves to an existing location
    - Path is NOT a symlink/junction/reparse point
    - Path does not contain traversal sequences (..)
    - Path is within an approved cleanup root
    - Path is NOT in a rejected/protected directory
    """
    if not path or not path.strip():
        return False, "Empty path"

    try:
        resolved = os.path.normpath(os.path.abspath(path))
    except (OSError, ValueError):
        return False, "Cannot resolve path"

    # Reject traversal sequences that survive normalization
    if ".." in path:
        return False, "Path contains traversal sequences"

    # Reject symlinks and reparse points
    if is_symlink_or_reparse(path):
        return False, "Path is a symlink, junction, or reparse point"

    # Also check the resolved target
    try:
        real = os.path.realpath(path)
        if is_symlink_or_reparse(real):
            return False, "Resolved target is a symlink/junction"
    except (OSError, ValueError):
        pass

    # Check rejected paths
    if is_path_rejected(resolved):
        return False, "Path is in a protected directory"

    # Check allowed roots
    if not is_path_in_allowed_root(resolved):
        return False, "Path is not in an approved cleanup root"

    return True, "OK"


def can_delete_file(filepath: str) -> bool:
    """Check if a specific file can be safely deleted."""
    try:
        if not os.path.isfile(filepath):
            return False
        if not is_safe_to_delete(filepath):
            return False
        # Reject symlinks/reparse points
        if is_symlink_or_reparse(filepath):
            return False
        # Check if file is writable
        return os.access(filepath, os.W_OK)
    except (OSError, ValueError):
        return False


def can_delete_directory(dirpath: str) -> bool:
    """Check if a directory can be safely deleted."""
    try:
        if not os.path.isdir(dirpath):
            return False
        if not is_safe_to_delete(dirpath):
            return False
        return True
    except (OSError, ValueError):
        return False
