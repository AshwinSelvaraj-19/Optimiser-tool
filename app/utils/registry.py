"""
Windows Registry utilities for reading and writing registry values.
All operations are logged and include backup before modification.
"""

import winreg
from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger("utils.registry")

# Registry hive constants
HIVE_MAP = {
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
}

KEY_ACCESS = {
    "read": winreg.KEY_READ,
    "write": winreg.KEY_WRITE,
    "all": winreg.KEY_ALL_ACCESS,
}


def _parse_hive(hive: str) -> int:
    """Parse a hive string to a winreg constant."""
    if isinstance(hive, int):
        return hive
    normalized = hive.strip().upper()
    if normalized in HIVE_MAP:
        return HIVE_MAP[normalized]
    raise ValueError(f"Unknown registry hive: {hive}")


def read_registry_value(hive: str, key_path: str, value_name: str) -> Optional[Any]:
    """
    Read a single registry value.
    Returns None if the value doesn't exist.
    """
    hive_const = _parse_hive(hive)
    try:
        with winreg.OpenKey(hive_const, key_path, 0, KEY_ACCESS["read"]) as key:
            value, reg_type = winreg.QueryValueEx(key, value_name)
            logger.debug(f"Read registry: {hive}\\{key_path}\\{value_name} = {value}")
            return value
    except FileNotFoundError:
        logger.debug(f"Registry value not found: {hive}\\{key_path}\\{value_name}")
        return None
    except PermissionError:
        logger.warning(f"Permission denied reading: {hive}\\{key_path}\\{value_name}")
        return None
    except OSError as e:
        logger.error(f"Error reading registry {hive}\\{key_path}\\{value_name}: {e}")
        return None


def read_registry_all(hive: str, key_path: str) -> dict:
    """Read all values under a registry key."""
    hive_const = _parse_hive(hive)
    values = {}
    try:
        with winreg.OpenKey(hive_const, key_path, 0, KEY_ACCESS["read"]) as key:
            i = 0
            while True:
                try:
                    name, value, reg_type = winreg.EnumValue(key, i)
                    values[name] = {"value": value, "type": reg_type}
                    i += 1
                except OSError:
                    break
    except FileNotFoundError:
        logger.debug(f"Registry key not found: {hive}\\{key_path}")
    except PermissionError:
        logger.warning(f"Permission denied reading key: {hive}\\{key_path}")
    except OSError as e:
        logger.error(f"Error reading registry key {hive}\\{key_path}: {e}")

    return values


def backup_registry_key(hive: str, key_path: str) -> dict:
    """
    Backup all values under a registry key.
    Returns a dict that can be used for restoration.
    """
    hive_const = _parse_hive(hive)
    backup = {"hive": hive, "key_path": key_path, "values": {}}

    try:
        with winreg.OpenKey(hive_const, key_path, 0, KEY_ACCESS["read"]) as key:
            i = 0
            while True:
                try:
                    name, value, reg_type = winreg.EnumValue(key, i)
                    backup["values"][name] = {"value": value, "type": reg_type}
                    i += 64
                except OSError:
                    break
        logger.info(f"Backed up registry key: {hive}\\{key_path} ({len(backup['values'])} values)")
    except FileNotFoundError:
        logger.warning(f"Registry key not found for backup: {hive}\\{key_path}")
    except PermissionError:
        logger.warning(f"Permission denied backing up: {hive}\\{key_path}")

    return backup


def write_registry_value(hive: str, key_path: str, value_name: str,
                         value: Any, reg_type: int = winreg.REG_DWORD) -> bool:
    """
    Write a registry value. Creates the key if it doesn't exist.
    Returns True on success.
    """
    hive_const = _parse_hive(hive)
    try:
        with winreg.OpenKey(hive_const, key_path, 0, KEY_ACCESS["write"]) as key:
            winreg.SetValueEx(key, value_name, 0, reg_type, value)
            logger.info(f"Wrote registry: {hive}\\{key_path}\\{value_name} = {value}")
            return True
    except PermissionError:
        logger.warning(f"Permission denied writing: {hive}\\{key_path}\\{value_name}")
        return False
    except OSError as e:
        logger.error(f"Error writing registry {hive}\\{key_path}\\{value_name}: {e}")
        return False


def restore_registry_backup(backup: dict) -> bool:
    """
    Restore a previously backed up registry key.
    Returns True on success.
    """
    hive = backup["hive"]
    key_path = backup["key_path"]
    values = backup["values"]
    hive_const = _parse_hive(hive)

    try:
        with winreg.OpenKey(hive_const, key_path, 0, KEY_ACCESS["write"]) as key:
            for name, data in values.items():
                winreg.SetValueEx(key, name, 0, data["type"], data["value"])
            logger.info(f"Restored registry key: {hive}\\{key_path} ({len(values)} values)")
            return True
    except PermissionError:
        logger.warning(f"Permission denied restoring: {hive}\\{key_path}")
        return False
    except OSError as e:
        logger.error(f"Error restoring registry {hive}\\{key_path}: {e}")
        return False


def registry_key_exists(hive: str, key_path: str) -> bool:
    """Check if a registry key exists."""
    hive_const = _parse_hive(hive)
    try:
        with winreg.OpenKey(hive_const, key_path, 0, KEY_ACCESS["read"]):
            return True
    except (FileNotFoundError, PermissionError, OSError):
        return False
