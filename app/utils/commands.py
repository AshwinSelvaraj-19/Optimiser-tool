"""
Windows command execution utilities.
Safe wrappers for subprocess calls with logging and timeout handling.
"""

import subprocess
import sys
from typing import Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("utils.commands")


def run_command(
    command: str,
    timeout: int = 30,
    capture_output: bool = True,
    shell: bool = True,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> Tuple[bool, str, str]:
    """
    Run a Windows command safely with timeout.

    Returns:
        (success, stdout, stderr)
    """
    try:
        logger.debug(f"Executing command: {command}")
        result = subprocess.run(
            command,
            capture_output=capture_output,
            shell=shell,
            timeout=timeout,
            encoding=encoding,
            errors=errors,
            text=True,
        )
        success = result.returncode == 0
        if not success:
            logger.debug(f"Command returned non-zero: {result.returncode}")
        return success, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.warning(f"Command timed out ({timeout}s): {command}")
        return False, "", "Command timed out"
    except FileNotFoundError:
        logger.warning(f"Command not found: {command}")
        return False, "", "Command not found"
    except Exception as e:
        logger.error(f"Error executing command '{command}': {e}")
        return False, "", str(e)


def run_powershell(
    script: str,
    timeout: int = 30,
    elevated: bool = False,
) -> Tuple[bool, str, str]:
    """
    Run a PowerShell script safely.
    """
    ps_cmd = f'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "{script}"'
    logger.debug(f"PowerShell script: {script[:200]}...")
    return run_command(ps_cmd, timeout=timeout)


def run_wmic(
    query: str,
    timeout: int = 15,
) -> Tuple[bool, str, str]:
    """Run a WMIC query."""
    cmd = f"wmic {query}"
    return run_command(cmd, timeout=timeout)


def get_system_info() -> dict:
    """Get basic system information using system commands."""
    info = {}

    # Windows version
    success, stdout, _ = run_powershell(
        '(Get-CimInstance Win32_OperatingSystem).Caption'
    )
    if success and stdout.strip():
        info["os_caption"] = stdout.strip()

    # Windows build
    success, stdout, _ = run_powershell(
        '[System.Environment]::OSVersion.Version.ToString()'
    )
    if success and stdout.strip():
        info["os_version"] = stdout.strip()

    # Computer name
    import os
    info["computer_name"] = os.environ.get("COMPUTERNAME", "unknown")

    # Username
    info["username"] = os.environ.get("USERNAME", "unknown")

    return info


def is_process_running(process_name: str) -> bool:
    """Check if a process is currently running."""
    success, stdout, _ = run_command(
        f'tasklist /FI "IMAGENAME eq {process_name}" /NH'
    )
    if success and process_name.lower() in stdout.lower():
        return True
    return False


def get_process_list() -> list:
    """Get a list of all running processes with basic info."""
    success, stdout, _ = run_powershell(
        'Get-Process | Select-Object Name, Id, CPU, WorkingSet64 | ConvertTo-Json'
    )
    import json
    if success and stdout.strip():
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                return [data]
            return data
        except json.JSONDecodeError:
            return []
    return []


def kill_process(process_name: str, force: bool = False) -> bool:
    """Safely kill a process by name."""
    flag = "/F" if force else ""
    success, _, stderr = run_command(f"taskkill /IM {process_name} {flag}")
    if success:
        logger.info(f"Killed process: {process_name}")
    else:
        logger.warning(f"Failed to kill process {process_name}: {stderr}")
    return success


def check_admin_required(operation: str) -> bool:
    """Check if an operation requires admin and warn if not elevated."""
    from app.utils.admin import is_admin
    if not is_admin():
        logger.warning(f"Operation '{operation}' may require administrator privileges")
        return True
    return False
