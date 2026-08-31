"""
Display detection and configuration module.
Monitors display resolution, refresh rate, and multi-monitor setups.
"""

import os
import time
from dataclasses import dataclass, field
from typing import Optional

from app.utils.commands import run_powershell
from app.utils.logger import get_logger

logger = get_logger("system.display")


@dataclass
class DisplayInfo:
    """Display configuration information."""
    resolution_x: int = 1920
    resolution_y: int = 1080
    refresh_rate_hz: int = 60
    color_depth: int = 32
    display_name: str = "Default Monitor"
    is_primary: bool = True
    adapter_name: str = "Unknown"
    driver_version: str = "Unknown"
    all_displays: list = field(default_factory=list)


class DisplayMonitor:
    """Display detection and configuration."""

    def detect(self) -> DisplayInfo:
        """Detect current display configuration."""
        info = DisplayInfo()
        try:
            displays = self._detect_displays_wmi()
            if displays:
                info.all_displays = displays
                # Find primary display
                for d in displays:
                    if d.get("is_primary", False):
                        info.resolution_x = d.get("width", 1920)
                        info.resolution_y = d.get("height", 1080)
                        info.refresh_rate_hz = d.get("refresh_rate", 60)
                        info.display_name = d.get("name", "Unknown")
                        info.adapter_name = d.get("adapter", "Unknown")
                        info.driver_version = d.get("driver", "Unknown")
                        info.is_primary = True
                        break
                else:
                    # Use first display
                    d = displays[0]
                    info.resolution_x = d.get("width", 1920)
                    info.resolution_y = d.get("height", 1080)
                    info.refresh_rate_hz = d.get("refresh_rate", 60)
                    info.display_name = d.get("name", "Unknown")
            else:
                # Fallback detection
                info = self._detect_via_powershell()

            logger.info(
                f"Display: {info.resolution_x}x{info.resolution_y} @ {info.refresh_rate_hz}Hz"
            )
        except Exception as e:
            logger.error(f"Display detection error: {e}")

        return info

    def _detect_displays_wmi(self) -> list:
        """Detect displays via WMI."""
        displays = []
        try:
            import pythoncom
            pythoncom.CoInitialize()
            # Suppress harmless pywin32 IUnknown::Release() SEH exceptions
            # These are C-level stderr writes during COM object teardown
            _devnull_fd = os.open(os.devnull, os.O_WRONLY)
            _old_stderr_fd = os.dup(2)
            os.dup2(_devnull_fd, 2)
            try:
                import wmi
                w = wmi.WMI(namespace="root\\cimv2")
                desktops = w.Win32_DesktopMonitor()
                for i, monitor in enumerate(desktops):
                    try:
                        width = int(getattr(monitor, 'ScreenWidth', 0) or 0)
                        height = int(getattr(monitor, 'ScreenHeight', 0) or 0)
                        if width > 0 and height > 0:
                            displays.append({
                                "name": getattr(monitor, 'Name', 'Monitor ' + str(i)),
                                "width": width,
                                "height": height,
                                "refresh_rate": 60,
                                "is_primary": getattr(monitor, 'Primary', False),
                                "adapter": "Unknown",
                                "driver": getattr(monitor, 'DriverVersion', 'Unknown'),
                            })
                    except Exception:
                        continue

                # Also try video controller for adapter info
                controllers = w.Win32_VideoController()
                for ctrl in controllers:
                    try:
                        adapter_name = getattr(ctrl, 'Name', 'Unknown')
                        driver_ver = getattr(ctrl, 'DriverVersion', 'Unknown')
                        for d in displays:
                            d["adapter"] = adapter_name
                            d["driver"] = driver_ver
                    except Exception:
                        continue
                del w
            finally:
                pythoncom.CoUninitialize()
                os.dup2(_old_stderr_fd, 2)
                os.close(_old_stderr_fd)
                os.close(_devnull_fd)

        except ImportError:
            logger.debug("WMI or pythoncom not available for display detection")
        except Exception as e:
            logger.error(f"WMI display detection error: {e}")

        return displays

    def _detect_via_powershell(self) -> DisplayInfo:
        """Fallback display detection via PowerShell."""
        info = DisplayInfo()
        try:
            # Get screen resolution
            success, stdout, _ = run_powershell(
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds"
            )
            if success and stdout:
                # Parse the bounds
                import re
                match = re.search(r'Width\s*[=:]\s*(\d+).*Height\s*[=:]\s*(\d+)',
                                  stdout, re.IGNORECASE | re.DOTALL)
                if match:
                    info.resolution_x = int(match.group(1))
                    info.resolution_y = int(match.group(2))

            # Get refresh rate
            success, stdout, _ = run_powershell(
                "Get-CimInstance Win32_VideoController | Select-Object CurrentRefreshRate"
            )
            if success and stdout.strip():
                import re
                match = re.search(r'(\d+)', stdout)
                if match:
                    info.refresh_rate_hz = int(match.group(1))

        except Exception as e:
            logger.error(f"PowerShell display detection error: {e}")

        return info

    def set_refresh_rate(self, rate: int) -> bool:
        """Attempt to set display refresh rate (Windows API required for actual change)."""
        logger.info(f"Refresh rate change requested: {rate}Hz")
        # Actual refresh rate change requires Windows API calls
        # This is a placeholder for the safe implementation path
        success, _, stderr = run_powershell(
            f"Get-CimInstance Win32_VideoController | Select-Object CurrentRefreshRate"
        )
        if success:
            logger.info("Refresh rate inspection successful")
        return success

    def get_all_displays(self) -> list:
        """Get information about all connected displays."""
        info = self.detect()
        return info.all_displays

    def get_current_settings(self) -> dict:
        """Get current display settings for snapshot."""
        info = self.detect()
        return {
            "resolution_x": info.resolution_x,
            "resolution_y": info.resolution_y,
            "refresh_rate_hz": info.refresh_rate_hz,
            "display_name": info.display_name,
            "adapter_name": info.adapter_name,
        }


# Singleton
display_monitor = DisplayMonitor()
