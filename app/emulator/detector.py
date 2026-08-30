"""
Emulator detector — automatically detects installed and running emulators.
Coordinates detection across all emulator implementations.
"""

import psutil

from app.emulator.base import BaseEmulator, EmulatorInfo
from app.emulator.msi_app_player import MSIAppPlayer
from app.emulator.bluestacks import BlueStacks
from app.emulator.ldplayer import LDPlayer
from app.emulator.gameloop import GameLoop
from app.emulator.mumu import MuMu
from app.utils.logger import get_logger

logger = get_logger("emulator.detector")


class EmulatorDetector:
    """Detects all installed and running Android emulators."""

    def __init__(self):
        self._emulators: list = []
        self._registered = [
            MSIAppPlayer,
            BlueStacks,
            LDPlayer,
            GameLoop,
            MuMu,
        ]

    def detect_all(self) -> list:
        """Detect all installed/running emulators."""
        self._emulators = []
        detected_any = False

        for emulator_class in self._registered:
            try:
                emulator = emulator_class()
                is_installed = emulator.detect()
                is_running = emulator.detect_running()

                if is_installed or is_running:
                    self._emulators.append(emulator)
                    detected_any = True
                    status = "RUNNING" if is_running else "Installed (not running)"
                    logger.info(f"Detected {emulator.DISPLAY_NAME}: {status}")
            except Exception as e:
                logger.error(f"Error detecting {emulator_class.DISPLAY_NAME}: {e}")

        if not detected_any:
            logger.info("No Android emulators detected")

        return self._emulators

    def get_running_emulators(self) -> list:
        """Get only currently running emulators."""
        running = []
        for emu in self._emulators:
            if emu.info.is_running:
                running.append(emu)
        return running

    def get_primary_emulator(self) -> BaseEmulator:
        """Get the primary (MSI App Player or first detected) emulator."""
        # MSI App Player is primary
        for emu in self._emulators:
            if emu.EMULATOR_NAME == "msi_app_player":
                return emu
        # Return first detected
        return self._emulators[0] if self._emulators else None

    def get_emulator_by_name(self, name: str) -> BaseEmulator:
        """Get a specific emulator by name."""
        for emu in self._emulators:
            if emu.EMULATOR_NAME == name or emu.DISPLAY_NAME.lower() == name.lower():
                return emu
        return None

    def list_detected(self) -> list:
        """List summary of all detected emulators."""
        return [
            {
                "name": emu.DISPLAY_NAME,
                "key": emu.EMULATOR_NAME,
                "installed": bool(emu.info.install_path),
                "running": emu.info.is_running,
                "version": emu.info.version,
                "install_path": emu.info.install_path,
            }
            for emu in self._emulators
        ]

    def get_all_emulator_processes(self) -> dict:
        """Get all processes belonging to detected emulators."""
        all_procs = {}
        for emu in self._emulators:
            procs = []
            for proc_name in emu.get_process_names():
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        if proc.info['name'] and proc.info['name'].lower() == proc_name.lower():
                            procs.append({"pid": proc.info['pid'], "name": proc.info['name']})
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            if procs:
                all_procs[emu.DISPLAY_NAME] = procs
        return all_procs

    def get_emulator_pids(self) -> list:
        """Get all PIDs belonging to detected running emulators."""
        pids = []
        for emu in self._emulators:
            if emu.info.is_running:
                for proc_name in emu.get_process_names():
                    for proc in psutil.process_iter(['pid', 'name']):
                        try:
                            if proc.info['name'] and proc.info['name'].lower() == proc_name.lower():
                                pids.append(proc.info['pid'])
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
        return pids


# Singleton
emulator_detector = EmulatorDetector()
