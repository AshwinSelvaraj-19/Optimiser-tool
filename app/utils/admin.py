"""
Admin privilege detection and elevation request for Windows.
Detects if running as admin, provides safe elevation requests.
"""

import ctypes
import os
import sys
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("utils.admin")


def is_admin() -> bool:
    """Check if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


def request_elevation_if_needed() -> bool:
    """
    Check if admin is needed and request elevation.
    Returns True if admin (or elevation succeeded), False otherwise.
    """
    if is_admin():
        logger.info("Running with administrator privileges")
        return True

    logger.warning("Not running as administrator — some optimizations may be limited")
    return False


def get_privilege_status() -> dict:
    """Get current privilege status as a dictionary."""
    admin = is_admin()
    return {
        "is_admin": admin,
        "username": os.environ.get("USERNAME", "unknown"),
        "process_id": os.getpid(),
        "elevation_required_for": [
            "Power plan modification",
            "Process priority changes",
            "Emulator priority adjustment",
        ] if not admin else [],
        "available_without_admin": [
            "Hardware scanning",
            "System telemetry",
            "Emulator detection",
            "Benchmark running",
            "Process analysis (read-only)",
            "Network diagnostics",
            "Input configuration inspection",
            "Display configuration inspection",
        ],
    }


def run_as_admin() -> bool:
    """
    Attempt to re-launch the application with admin privileges.
    Uses ShellExecuteW with 'runas' verb.
    Returns True if elevation was initiated, False on failure.
    """
    if is_admin():
        logger.info("Already running as admin")
        return True

    try:
        script = os.path.abspath(sys.argv[0])
        logger.info(f"Requesting elevation for: {script}")
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}"', None, 1
        )
        # ShellExecuteW returns > 32 on success
        return ret > 32
    except Exception as e:
        logger.error(f"Elevation request failed: {e}")
        return False


def get_privilege_level() -> str:
    """Return a human-readable privilege level."""
    if is_admin():
        return "Administrator"
    return "Standard User"
