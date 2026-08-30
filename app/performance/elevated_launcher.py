"""
Elevated process launcher for Windows.

Uses ShellExecuteW with 'runas' verb to properly handle UAC elevation.
This avoids the problem where subprocess.Popen + --restart_as_admin
causes the UAC prompt to be auto-denied.
"""

import ctypes
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import psutil

from app.utils.logger import get_logger

logger = get_logger("performance.elevated_launcher")

# ShellExecuteW constants
SW_SHOWNORMAL = 1
SEE_MASK_NOCLOSEPROCESS = 0x00000040


@dataclass
class ElevatedProcess:
    """Handle for an elevated process launched via ShellExecuteW."""
    pid: int = 0
    exe_path: str = ""
    session_name: str = ""
    launch_time: float = 0.0
    command_line: str = ""


def launch_elevated(
    exe_path: str,
    args: list,
    session_name: str = "",
    wait_for_child: bool = True,
    child_timeout: float = 15.0,
) -> Optional[ElevatedProcess]:
    """
    Launch a process elevated via ShellExecuteW 'runas'.

    ShellExecuteW doesn't return a process handle directly.
    After launching, we discover the child process by:
    1. Recording the launch time
    2. Waiting for a new PresentMon process to appear
    3. Matching by executable name and command line

    Args:
        exe_path: Absolute path to the executable
        args: Command-line arguments (list)
        session_name: Unique session identifier for tracking
        wait_for_child: Whether to wait for the child process to appear
        child_timeout: Max seconds to wait for child process discovery

    Returns:
        ElevatedProcess if found, None on failure/UAC cancellation
    """
    exe_path = os.path.abspath(exe_path)
    if not os.path.exists(exe_path):
        logger.error(f"Executable not found: {exe_path}")
        return None

    # Build the full command line for ShellExecuteW
    # ShellExecuteW needs: exe "arg1" "arg2" ...
    args_str = " ".join(f'"{a}"' if " " in a else a for a in args)
    full_cmd = f'"{exe_path}" {args_str}'

    # Record pre-launch PIDs for PresentMon
    pre_pids = set()
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info["name"] or "").lower()
                if "presentmon" in name:
                    pre_pids.add(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass

    launch_time = time.time()

    # ShellExecuteW returns > 32 on success
    logger.info(f"Launching elevated: {full_cmd}")
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # lpOperation - triggers UAC
            exe_path,       # lpFile
            args_str,       # lpParameters
            None,           # lpDirectory
            SW_SHOWNORMAL,  # nShowCmd
        )
    except Exception as e:
        logger.error(f"ShellExecuteW failed: {e}")
        return None

    if ret <= 32:
        # Error code 5 = ERROR_ACCESS_DENIED (UAC cancelled)
        # Error code 1223 = ERROR_CANCELLED by user
        logger.warning(
            f"ShellExecuteW returned error {ret} — "
            f"UAC may have been cancelled or access denied"
        )
        return None

    logger.info(f"ShellExecuteW returned {ret}")

    if not wait_for_child:
        return ElevatedProcess(
            pid=0,
            exe_path=exe_path,
            session_name=session_name,
            launch_time=launch_time,
            command_line=full_cmd,
        )

    # Wait for the elevated child process to appear
    exe_name = os.path.basename(exe_path).lower()
    discovered_pid = None

    logger.info(f"Waiting for elevated child (timeout={child_timeout}s)...")
    deadline = time.time() + child_timeout
    poll_interval = 0.5

    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            for proc in psutil.process_iter(
                ["pid", "name", "exe", "create_time", "cmdline"]
            ):
                try:
                    info = proc.info
                    name = (info.get("name") or "").lower()
                    if exe_name not in name and "presentmon" not in name:
                        continue

                    pid = info["pid"]
                    if pid in pre_pids:
                        continue  # Skip pre-existing processes

                    # Match by creation time (must be after our launch)
                    create_time = info.get("create_time", 0)
                    if create_time and create_time < launch_time - 1:
                        continue  # Too old

                    # This is a newly created process
                    discovered_pid = pid
                    logger.info(
                        f"Discovered elevated child: PID={pid} "
                        f"name={info.get('name')} "
                        f"created={create_time:.0f} "
                        f"launched={launch_time:.0f}"
                    )
                    break

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if discovered_pid:
                break

        except Exception as e:
            logger.debug(f"Process scan error: {e}")
            continue

    if not discovered_pid:
        logger.warning(
            "No elevated child process discovered. "
            "UAC may have been cancelled."
        )
        return None

    elapsed = time.time() - launch_time
    logger.info(
        f"Elevated process discovered after {elapsed:.1f}s: PID={discovered_pid}"
    )

    return ElevatedProcess(
        pid=discovered_pid,
        exe_path=exe_path,
        session_name=session_name,
        launch_time=launch_time,
        command_line=full_cmd,
    )


def kill_elevated_process(pid: int) -> bool:
    """
    Kill an elevated process using taskkill.

    Elevated processes cannot be terminated via psutil.terminate() from a
    non-elevated process (AccessDenied). taskkill /F /PID works across
    elevation boundaries.
    """
    if not pid:
        return False

    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            logger.info(f"Killed elevated process PID={pid}")
            return True
        else:
            stderr = result.stderr.decode(errors="replace")
            logger.warning(
                f"taskkill failed for PID={pid}: {stderr.strip()}"
            )
            return False
    except Exception as e:
        logger.error(f"taskkill error for PID={pid}: {e}")
        return False


def find_presentmon_processes(
    session_name: str = "",
    min_create_time: float = 0,
) -> list:
    """
    Find running PresentMon processes.

    Filters by:
    - executable name containing 'presentmon'
    - optionally by session_name in command line
    - optionally by minimum creation time

    Returns list of dicts with pid, name, cmdline, create_time.
    """
    results = []
    try:
        for proc in psutil.process_iter(
            ["pid", "name", "exe", "cmdline", "create_time"]
        ):
            try:
                info = proc.info
                name = (info.get("name") or "").lower()

                if "presentmon" not in name:
                    continue

                # Filter by session name if provided
                if session_name:
                    cmdline = " ".join(info.get("cmdline") or [])
                    if session_name not in cmdline:
                        continue

                # Filter by creation time if provided
                if min_create_time:
                    ct = info.get("create_time", 0)
                    if ct and ct < min_create_time - 1:
                        continue

                results.append({
                    "pid": info["pid"],
                    "name": info.get("name", ""),
                    "exe": info.get("exe", ""),
                    "cmdline": info.get("cmdline", []),
                    "create_time": info.get("create_time", 0),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logger.error(f"Error scanning for PresentMon: {e}")

    return results


def kill_stale_phoenix_sessions(session_name: str = ""):
    """
    Kill only Phoenix-owned PresentMon processes.

    Matches by session_name in the command line arguments.
    Never kills unrelated PresentMon instances.
    """
    procs = find_presentmon_processes(session_name=session_name)
    for p in procs:
        logger.info(f"Killing stale Phoenix PresentMon PID={p['pid']}")
        kill_elevated_process(p["pid"])
