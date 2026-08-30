"""
MSI App Player emulator integration.
Real detection — no hardcoded config values.
"""

import os
import re
from typing import Optional

from app.emulator.base import BaseEmulator, EmulatorConfig, EmulatorInfo
from app.utils.commands import run_powershell, run_command
from app.utils.logger import get_logger

logger = get_logger("emulator.msi_app_player")


class MSIAppPlayer(BaseEmulator):
    """MSI App Player emulator implementation."""

    EMULATOR_NAME = "msi_app_player"
    DISPLAY_NAME = "MSI App Player"

    PROCESS_NAMES = [
        "msi.exe", "msihelper.exe", "hd-agent.exe", "bhd-agent.exe",
        "hd-frontend.exe", "adb.exe", "MEmuHeadless.exe", "MEmu.exe",
        "BstHdViewer.exe", "BstHdLogRotator.exe", "BstHdSmartBstService.exe",
    ]

    def get_process_names(self) -> list:
        return self.PROCESS_NAMES

    def get_install_paths(self) -> list:
        program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        return [
            f"{program_files}\\MSI\\MSI App Player",
            f"{program_files_x86}\\MSI\\MSI App Player",
            f"{local_app_data}\\MSI\\MSI App Player",
            "C:\\Program Files\\BlueStacks_nxt",
            "C:\\Program Files\\BlueStacks_nxt_msi",
            f"{program_files}\\MSI\\BlueStacks_nxt",
        ]

    def detect(self) -> bool:
        """Detect MSI App Player installation via registry and filesystem."""
        # Registry detection
        success, stdout, _ = run_powershell(
            'Get-ItemProperty "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*" | '
            'Where-Object { $_.DisplayName -like "*MSI*App Player*" -or $_.DisplayName -like "*BlueStacks*" } | '
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

        # Filesystem fallback
        if not self._info.install_path:
            path = self._find_install_path()
            if path:
                self._info.install_path = path

        # Dynamic config discovery
        self._discover_config()

        self.detect_running()
        return bool(self._info.install_path) or self._info.is_running

    def _discover_config(self):
        """Dynamically discover configuration files."""
        if not self._info.install_path:
            return

        # Search for known config file patterns
        config_patterns = [
            "bluestacks.conf",
            "bluestacks.conf.ini",
            "engine.cfg",
            "conf.txt",
            "bluestacks.config",
        ]

        for pattern in config_patterns:
            path = os.path.join(self._info.install_path, pattern)
            if os.path.exists(path):
                self._info.config_path = path
                logger.info(f"Found config: {path}")
                return

        # Search Engine subdirectory
        engine_dir = os.path.join(self._info.install_path, "Engine")
        if os.path.isdir(engine_dir):
            for fname in os.listdir(engine_dir):
                if fname.endswith((".conf", ".cfg", ".ini", ".config")):
                    self._info.config_path = os.path.join(engine_dir, fname)
                    logger.info(f"Found config in Engine/: {self._info.config_path}")
                    return

        # Search for Registry-based config
        self._info.config_path = "(registry-based)"
        logger.debug("No file-based config found, using registry")

    def detect_running(self) -> bool:
        """Detect if MSI App Player is currently running."""
        for proc_name in self.PROCESS_NAMES:
            success, stdout, _ = run_command(f'tasklist /FI "IMAGENAME eq {proc_name}" /NH')
            if success and proc_name.lower() in stdout.lower():
                self._info.is_running = True
                if proc_name not in self._info.process_names:
                    self._info.process_names.append(proc_name)
                return True
        self._info.is_running = False
        return False

    def read_config(self) -> Optional[EmulatorConfig]:
        """Read MSI App Player configuration from discovered config file."""
        config = EmulatorConfig()

        if not self._info.config_path or self._info.config_path == "(registry-based)":
            # Try registry
            self._read_registry_config(config)
            self._info.config = config
            return config

        if os.path.exists(self._info.config_path):
            try:
                config.raw_settings = self._parse_config_file(self._info.config_path)
                logger.info(f"Read {len(config.raw_settings)} settings from {self._info.config_path}")
            except Exception as e:
                logger.error(f"Config parse error: {e}")

        self._info.config = config
        return config

    def _parse_config_file(self, path: str) -> dict:
        """Parse a key=value config file."""
        settings = {}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, _, value = line.partition("=")
                        settings[key.strip()] = value.strip()
        except Exception as e:
            logger.debug(f"Config parse error for {path}: {e}")
        return settings

    def _read_registry_config(self, config: EmulatorConfig):
        """Read configuration from Windows registry."""
        from app.utils.registry import read_registry_value

        reg_paths = [
            (r"Software\BlueStacks_nxt", "Engine"),
            (r"Software\MSI App Player", "Engine"),
            (r"Software\BlueStacks", "Engine"),
        ]
        for hive_path, value_name in reg_paths:
            val = read_registry_value("HKCU", hive_path, value_name)
            if val:
                config.raw_settings["registry_engine"] = str(val)
                break

    def get_config_value(self, key: str) -> str:
        """Get a specific config value. Returns UNKNOWN if not found."""
        if not self._info.config:
            self.read_config()
        if self._info.config and self._info.config.raw_settings:
            return self._info.config.raw_settings.get(key, "UNKNOWN")
        return "UNKNOWN"

    def backup_config(self) -> bool:
        """Backup current configuration to a .bak file."""
        if not self._info.config_path or not os.path.exists(self._info.config_path):
            return False
        try:
            import shutil
            backup_path = self._info.config_path + ".bak"
            shutil.copy2(self._info.config_path, backup_path)
            logger.info(f"Config backed up to: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return False

    def restore_config(self) -> bool:
        """Restore configuration from backup."""
        if not self._info.config_path:
            return False
        backup_path = self._info.config_path + ".bak"
        if not os.path.exists(backup_path):
            logger.warning("No backup found")
            return False
        try:
            import shutil
            shutil.copy2(backup_path, self._info.config_path)
            logger.info(f"Config restored from: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def write_config(self, config: EmulatorConfig) -> bool:
        """Write configuration. Requires emulator NOT running."""
        if self._info.is_running:
            logger.error("Cannot write config while emulator is running")
            return False

        is_valid, errors = self.validate_config(config)
        if not is_valid:
            logger.error(f"Invalid config: {errors}")
            return False

        if not self._info.config_path or self._info.config_path == "(registry-based)":
            return False

        try:
            lines = []
            with open(self._info.config_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("cpu=") and config.cpu_cores > 0:
                        lines.append(f"cpu={config.cpu_cores}\n")
                    elif stripped.startswith("memory=") and config.ram_mb > 0:
                        lines.append(f"memory={config.ram_mb}\n")
                    elif stripped.startswith("resolution=") and config.resolution_x > 0:
                        lines.append(f"resolution={config.resolution_x}x{config.resolution_y}\n")
                    elif stripped.startswith("fps=") and config.fps_limit > 0:
                        lines.append(f"fps={config.fps_limit}\n")
                    elif stripped.startswith("renderer=") and config.renderer:
                        lines.append(f"renderer={config.renderer}\n")
                    else:
                        lines.append(line)

            with open(self._info.config_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            logger.info(f"Config written to {self._info.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to write config: {e}")
            return False

    def get_optimization_settings(self) -> dict:
        """Get recommended settings based on actual system hardware."""
        import psutil
        cpu_count = psutil.cpu_count(logical=True) or 4
        ram_total = psutil.virtual_memory().total / (1024 * 1024)
        recommended_cpu = max(2, cpu_count // 2)
        recommended_ram = max(1024, int(ram_total * 0.4))
        return {
            "cpu_cores": recommended_cpu,
            "ram_mb": recommended_ram,
            "fps_limit": 60,
            "renderer": "auto",
            "vsync": False,
            "resolution_scale": "medium",
        }
