"""
MuMu (NetEase) emulator integration.
"""

import os
from typing import Optional

from app.emulator.base import BaseEmulator, EmulatorConfig
from app.utils.commands import run_powershell, run_command
from app.utils.logger import get_logger

logger = get_logger("emulator.mumu")


class MuMu(BaseEmulator):
    """MuMu (NetEase) emulator implementation."""

    EMULATOR_NAME = "mumu"
    DISPLAY_NAME = "MuMu Player"

    PROCESS_NAMES = [
        "mumu.exe",
        "mumudriver.exe",
        "mumuserver.exe",
        "nemuheadless.exe",
        "MuMuVMMHeadless.exe",
    ]

    def get_process_names(self) -> list:
        return self.PROCESS_NAMES

    def get_install_paths(self) -> list:
        program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        return [
            f"{program_files}\\Netease\\MuMuPlayer-12.0",
            f"{program_files}\\Netease\\MuMuPlayer",
            "C:\\Program Files\\Netease\\MuMuPlayer-12.0",
        ]

    def detect(self) -> bool:
        success, stdout, _ = run_powershell(
            'Get-ItemProperty "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*" | '
            'Where-Object { $_.DisplayName -like "*MuMu*" } | '
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
        return config

    def write_config(self, config: EmulatorConfig) -> bool:
        logger.debug("MuMu config write not yet implemented")
        return False
