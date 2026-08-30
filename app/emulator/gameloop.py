"""
GameLoop emulator integration.
"""

import os
from typing import Optional

from app.emulator.base import BaseEmulator, EmulatorConfig
from app.utils.commands import run_powershell, run_command
from app.utils.logger import get_logger

logger = get_logger("emulator.gameloop")


class GameLoop(BaseEmulator):
    """GameLoop (Tencent Gaming Buddy) emulator implementation."""

    EMULATOR_NAME = "gameloop"
    DISPLAY_NAME = "GameLoop"

    PROCESS_NAMES = [
        "gameloop.exe",
        "ty.exe",
        "appmarket.exe",
        "aow_exe.exe",
        "mobilegamepc.exe",
        "GHZServer.exe",
    ]

    def get_process_names(self) -> list:
        return self.PROCESS_NAMES

    def get_install_paths(self) -> list:
        program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        return [
            f"{program_files}\\TxGameAssistant",
            "C:\\Program Files\\GameLoop",
            f"{program_files}\\GameLoop",
        ]

    def detect(self) -> bool:
        success, stdout, _ = run_powershell(
            'Get-ItemProperty "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*" | '
            'Where-Object { $_.DisplayName -like "*GameLoop*" -or $_.DisplayName -like "*Tencent*" } | '
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
        logger.debug("GameLoop config write not yet implemented")
        return False
