"""
Base emulator class.
Defines the interface all emulator implementations must follow.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("emulator.base")


@dataclass
class EmulatorConfig:
    """Emulator configuration values."""
    cpu_cores: int = 0
    ram_mb: int = 0
    resolution_x: int = 0
    resolution_y: int = 0
    dpi: int = 0
    renderer: str = ""
    fps_limit: int = 0
    vsync_enabled: bool = True
    graphics_mode: str = ""
    gpu_config: str = ""
    raw_settings: dict = field(default_factory=dict)


@dataclass
class EmulatorInfo:
    """Detected emulator information."""
    name: str = ""
    display_name: str = ""
    version: str = ""
    install_path: str = ""
    config_path: str = ""
    is_running: bool = False
    process_names: list = field(default_factory=list)
    config: Optional[EmulatorConfig] = None
    backup_config: Optional[EmulatorConfig] = None


class BaseEmulator(ABC):
    """Abstract base class for emulator implementations."""

    EMULATOR_NAME = "base"
    DISPLAY_NAME = "Base Emulator"

    def __init__(self):
        self._info = EmulatorInfo(name=self.EMULATOR_NAME, display_name=self.DISPLAY_NAME)
        self._config_backup = None

    @property
    def info(self) -> EmulatorInfo:
        return self._info

    @abstractmethod
    def detect(self) -> bool:
        """Detect if this emulator is installed. Returns True if found."""
        pass

    @abstractmethod
    def detect_running(self) -> bool:
        """Detect if this emulator is currently running."""
        pass

    @abstractmethod
    def get_process_names(self) -> list:
        """Return list of process names this emulator uses."""
        pass

    @abstractmethod
    def read_config(self) -> Optional[EmulatorConfig]:
        """Read current emulator configuration."""
        pass

    @abstractmethod
    def write_config(self, config: EmulatorConfig) -> bool:
        """Write emulator configuration. Must validate before writing."""
        pass

    def backup_config(self) -> bool:
        """Backup current configuration before modification."""
        try:
            config = self.read_config()
            if config:
                self._config_backup = config
                self._info.backup_config = config
                logger.info(f"Config backed up for {self.DISPLAY_NAME}")
                return True
        except Exception as e:
            logger.error(f"Config backup failed for {self.DISPLAY_NAME}: {e}")
        return False

    def restore_config(self) -> bool:
        """Restore configuration from backup."""
        if self._config_backup:
            try:
                success = self.write_config(self._config_backup)
                if success:
                    logger.info(f"Config restored for {self.DISPLAY_NAME}")
                    self._config_backup = None
                return success
            except Exception as e:
                logger.error(f"Config restore failed for {self.DISPLAY_NAME}: {e}")
        return False

    def validate_config(self, config: EmulatorConfig) -> tuple:
        """
        Validate emulator configuration.
        Returns (is_valid: bool, errors: list).
        """
        errors = []
        if config.cpu_cores < 0 or config.cpu_cores > 64:
            errors.append(f"Invalid CPU cores: {config.cpu_cores}")
        if config.ram_mb < 0 or config.ram_mb > 32768:
            errors.append(f"Invalid RAM: {config.ram_mb}MB")
        if config.resolution_x < 0 or config.resolution_x > 7680:
            errors.append(f"Invalid resolution X: {config.resolution_x}")
        if config.resolution_y < 0 or config.resolution_y > 4320:
            errors.append(f"Invalid resolution Y: {config.resolution_y}")
        if config.fps_limit < 0 or config.fps_limit > 240:
            errors.append(f"Invalid FPS limit: {config.fps_limit}")
        return len(errors) == 0, errors

    def get_install_paths(self) -> list:
        """Return potential installation paths to check."""
        return []

    def _find_install_path(self) -> Optional[str]:
        """Search common paths for this emulator."""
        for path in self.get_install_paths():
            expanded = os.path.expandvars(path)
            if os.path.exists(expanded):
                return expanded
        return None

    def is_detected(self) -> bool:
        """Check if this emulator was successfully detected."""
        return self._info.install_path != "" or self._info.is_running
