"""
BlueStacks emulator integration.
"""

import os
from typing import Optional

from app.emulator.base import BaseEmulator, EmulatorConfig
from app.utils.commands import run_powershell, run_command
from app.utils.logger import get_logger

logger = get_logger("emulator.bluestacks")


class BlueStacks(BaseEmulator):
    """BlueStacks emulator implementation."""

    EMULATOR_NAME = "bluestacks"
    DISPLAY_NAME = "BlueStacks"

    PROCESS_NAMES = [
        "bluestacks.exe",
        "bluestacksservice.exe",
        "hd-agent.exe",
        "bluestacksfrontend.exe",
        "bluestacksthreshservice.exe",
        "HD-Player.exe",
        "BstkSVC.exe",
    ]

    def get_process_names(self) -> list:
        return self.PROCESS_NAMES

    def get_install_paths(self) -> list:
        program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
        return [
            f"{program_files}\\BlueStacks_nxt",
            f"{program_files_x86}\\BlueStacks_nxt",
            f"{program_files}\\BlueStacks",
            f"{program_files_x86}\\BlueStacks",
        ]

    def detect(self) -> bool:
        """Detect BlueStacks installation."""
        success, stdout, _ = run_powershell(
            'Get-ItemProperty "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*" | '
            'Where-Object { $_.DisplayName -like "*BlueStacks*" } | '
            'Select-Object DisplayName, DisplayVersion, InstallLocation | ConvertTo-Json'
        )

        if success and stdout.strip():
            try:
                import json
                data = json.loads(stdout)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("DisplayName"):
                        self._info.version = item.get("DisplayVersion", "")
                        self._info.install_path = item.get("InstallLocation", "")
                        break
            except (json.JSONDecodeError, KeyError):
                pass

        if not self._info.install_path:
            path = self._find_install_path()
            if path:
                self._info.install_path = path

        self.detect_running()
        return bool(self._info.install_path) or self._info.is_running

    def detect_running(self) -> bool:
        for proc_name in self.PROCESS_NAMES:
            success, stdout, _ = run_command(f'tasklist /FI "IMAGENAME eq {proc_name}" /NH')
            if success and proc_name.lower() in stdout.lower():
                self._info.is_running = True
                return True
        self._info.is_running = False
        return False

    def read_config(self) -> Optional[EmulatorConfig]:
        config = EmulatorConfig()
        if self._info.install_path:
            for conf_file in ["bluestacks.conf", "bluestacks.conf.ini"]:
                conf_path = os.path.join(self._info.install_path, conf_file)
                if os.path.exists(conf_path):
                    try:
                        with open(conf_path, "r", encoding="utf-8", errors="replace") as f:
                            for line in f:
                                line = line.strip()
                                if "=" in line and not line.startswith("#"):
                                    key, _, value = line.partition("=")
                                    config.raw_settings[key.strip()] = value.strip()
                    except Exception as e:
                        logger.debug(f"Config parse error: {e}")
                    break
        return config

    def write_config(self, config: EmulatorConfig) -> bool:
        logger.debug("BlueStacks config write not yet fully implemented")
        return False
