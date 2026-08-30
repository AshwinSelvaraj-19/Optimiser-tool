"""
Power management detection and configuration module.
Reads and modifies Windows power plan settings.
"""

import subprocess
from dataclasses import dataclass
from typing import Optional

from app.utils.commands import run_powershell, run_command
from app.utils.logger import get_logger

logger = get_logger("system.power")


@dataclass
class PowerInfo:
    """Power configuration information."""
    active_plan_name: str = "Unknown"
    active_plan_guid: str = ""
    available_plans: list = None
    processor_throttle_min: int = 0
    processor_throttle_max: int = 100
    processor_performance_boost_mode: int = -1
    sleep_timeout_ac: int = 0
    hibernate_timeout_ac: int = 0
    is_on_battery: bool = False

    def __post_init__(self):
        if self.available_plans is None:
            self.available_plans = []


class PowerMonitor:
    """Windows power configuration management."""

    PERF_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    BALANCED_GUID = "381b4222-f694-41df-9d23-1e0c0c4e1e44"
    POWER_SAVER_GUID = "a1841308-3541-4fab-bc81-f71556f20b4a"

    def detect(self) -> PowerInfo:
        """Detect current power configuration."""
        info = PowerInfo()

        # Get active plan
        success, stdout, _ = run_powershell(
            "powercfg /getactivescheme"
        )
        if success and stdout.strip():
            import re
            match = re.search(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\s*\((.+?)\)\s*\*?', stdout)
            if match:
                info.active_plan_guid = match.group(1)
                info.active_plan_name = match.group(2).strip()
            else:
                # Fallback
                parts = stdout.strip().split()
                if len(parts) >= 2:
                    info.active_plan_guid = parts[0]
                    info.active_plan_name = parts[-1].strip('()* ')

        # Get all available plans
        success, stdout, _ = run_powershell(
            "powercfg /list"
        )
        if success:
            plans = self._parse_power_plans(stdout)
            info.available_plans = plans

        # Processor throttle
        success, stdout, _ = run_powershell(
            f"powercfg /query {self.PERF_GUID} 5d76a2ca-e8c0-402f-a133-2158492d58ad"
        )
        if success:
            min_val, max_val = self._parse_processor_throttle(stdout)
            info.processor_throttle_min = min_val
            info.processor_throttle_max = max_val

        # Performance boost mode
        success, stdout, _ = run_powershell(
            f"powercfg /query {self.PERF_GUID} be337238-0d82-4146-a9d8-f431c258242a"
        )
        if success and stdout.strip():
            try:
                for line in stdout.split('\n'):
                    line = line.strip()
                    if '0x' in line.lower() and ('current' in line.lower() or ':' in line):
                        parts = line.split(':')
                        if len(parts) >= 2:
                            hex_val = parts[1].strip()
                            if hex_val.startswith('0x'):
                                info.processor_performance_boost_mode = int(hex_val, 16)
                                break
            except (ValueError, IndexError):
                pass

        logger.info(f"Active power plan: {info.active_plan_name}")
        return info

    def _parse_power_plans(self, output: str) -> list:
        """Parse powercfg /list output."""
        import re
        plans = []
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('Power Scheme GUID'):
                match = re.search(r'([0-9a-fA-F-]{36})\s*\((.+?)\)\s*\*?', line)
                if match:
                    guid = match.group(1)
                    name = match.group(2).strip()
                    is_active = '*' in line
                    plans.append({
                        "guid": guid,
                        "name": name,
                        "active": is_active,
                    })
        return plans

    def _parse_processor_throttle(self, output: str) -> tuple:
        """Parse processor throttle min/max."""
        min_val = 0
        max_val = 100
        try:
            lines = output.split('\n')
            for i, line in enumerate(lines):
                if 'Index' in line and '0x' in line:
                    hex_val = line.split(':')[-1].strip() if ':' in line else ''
                    if not hex_val:
                        for j in range(i + 1, min(i + 4, len(lines))):
                            if '0x' in lines[j]:
                                parts = lines[j].split(':')
                                hex_val = parts[-1].strip() if len(parts) > 1 else ''
                                if hex_val:
                                    break
                    if hex_val.startswith('0x'):
                        val = int(hex_val, 16)
                        if 'Minimum' in ' '.join(lines[max(0, i-2):i]):
                            min_val = val
                        elif 'Maximum' in ' '.join(lines[max(0, i-2):i]):
                            max_val = val
        except (ValueError, IndexError):
            pass
        return min_val, max_val

    def set_high_performance(self) -> bool:
        """Switch to High Performance power plan."""
        return self._set_power_plan(self.PERF_GUID)

    def set_balanced(self) -> bool:
        """Switch to Balanced power plan."""
        return self._set_power_plan(self.BALANCED_GUID)

    def _set_power_plan(self, guid: str) -> bool:
        """Set the active power plan."""
        success, _, stderr = run_powershell(f"powercfg /setactive {guid}")
        if success:
            logger.info(f"Power plan set to {guid}")
        else:
            logger.error(f"Failed to set power plan: {stderr}")
        return success

    def set_processor_max_performance(self) -> bool:
        """Set processor to 100% max performance state."""
        success, _, _ = run_powershell(
            f"powercfg /setacvalueindex {self.PERF_GUID} "
            f"5d76a2ca-e8c0-402f-a133-2158492d58ad 5d76a2ca-e8c0-402f-a133-2158492d58ad 100"
        )
        if success:
            # Apply changes
            run_powershell(f"powercfg /setactive {self.PERF_GUID}")
            logger.info("Processor max performance set to 100%")
        return success

    def set_process_foreground_boost(self, disable: bool = True) -> bool:
        """Disable or enable foreground application CPU priority boost."""
        value = 0 if disable else 1
        success, _, _ = run_powershell(
            f"powercfg /setacvalueindex {self.PERF_GUID} "
            f"75b0ae3f-bce0-45a7-8c89-c9611c25e100 75b0ae3f-bce0-45a7-8c89-c9611c25e100 {value}"
        )
        if success:
            run_powershell(f"powercfg /setactive {self.PERF_GUID}")
            logger.info(f"Foreground CPU boost: {'disabled' if disable else 'enabled'}")
        return success

    def get_current_values(self) -> dict:
        """Get current power-related settings for snapshot."""
        info = self.detect()
        return {
            "active_plan_guid": info.active_plan_guid,
            "active_plan_name": info.active_plan_name,
            "processor_throttle_min": info.processor_throttle_min,
            "processor_throttle_max": info.processor_throttle_max,
            "boost_mode": info.processor_performance_boost_mode,
        }


# Singleton
power_monitor = PowerMonitor()
