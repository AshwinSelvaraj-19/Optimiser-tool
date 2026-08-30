"""
Input configuration inspection and optimization.
Mouse polling rate detection, pointer precision, display refresh analysis.
"""

from dataclasses import dataclass
from typing import Optional

from app.utils.commands import run_powershell
from app.utils.registry import read_registry_value
from app.utils.logger import get_logger

logger = get_logger("input.mouse")


@dataclass
class MouseInfo:
    """Mouse/input configuration information."""
    pointer_precision: bool = True
    enhance_pointer_precision: int = 1
    mouse_speed: int = 10
    double_click_speed: int = 500
    pointer_speed: int = 10
    mouse_sensitivity: str = "Unknown"
    raw_input_available: bool = True


@dataclass
class InputConfig:
    """Complete input configuration."""
    mouse: MouseInfo = None
    display_refresh_rate: int = 60
    vsync_enabled: bool = True
    game_mode_enabled: bool = False
    measured_latency_ms: Optional[float] = None
    input_settings_latency_ms: Optional[float] = None

    def __post_init__(self):
        if self.mouse is None:
            self.mouse = MouseInfo()


class InputMonitor:
    """Input configuration detection and diagnostics."""

    def detect(self) -> InputConfig:
        """Detect current input configuration."""
        config = InputConfig()
        config.mouse = self._detect_mouse()

        # Display refresh (influences input latency)
        from app.system.display import display_monitor
        display = display_monitor.detect()
        config.display_refresh_rate = display.refresh_rate_hz

        # Game mode
        game_mode = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled"
        )
        config.game_mode_enabled = game_mode == 1

        logger.info(f"Input config: pointer_precision={config.mouse.pointer_precision}, "
                     f"refresh={config.display_refresh_rate}Hz")
        return config

    def _detect_mouse(self) -> MouseInfo:
        """Detect mouse configuration."""
        mouse = MouseInfo()

        # Pointer precision (Enhance pointer precision)
        try:
            val = read_registry_value(
                "HKCU", r"Control Panel\Mouse", "MouseSpeed"
            )
            if val is not None:
                mouse.enhance_pointer_precision = int(val)
                mouse.pointer_precision = int(val) != 0

            val = read_registry_value(
                "HKCU", r"Control Panel\Mouse", "MouseThreshold1"
            )
            if val is not None:
                mouse.double_click_speed = int(val)

            val = read_registry_value(
                "HKCU", r"Control Panel\Mouse", "MouseSensitivity"
            )
            if val is not None:
                mouse.pointer_speed = int(val)
        except Exception as e:
            logger.debug(f"Mouse detection error: {e}")

        return mouse

    def get_diagnostics(self) -> list:
        """Get input diagnostics and recommendations."""
        config = self.detect()
        diagnostics = []

        if config.mouse.pointer_precision:
            diagnostics.append({
                "setting": "Enhance Pointer Precision",
                "current": "ENABLED (adds mouse acceleration)",
                "recommendation": "DISABLE for consistent muscle memory in gaming",
                "impact": "MEDIUM — Mouse acceleration causes inconsistent aim",
                "how_to": "Mouse Settings > Additional Options > Enhance Pointer Precision: OFF",
            })

        if config.display_refresh_rate <= 60:
            diagnostics.append({
                "setting": "Display Refresh Rate",
                "current": f"{config.display_refresh_rate}Hz",
                "recommendation": "Use highest available refresh rate (120Hz+ if available)",
                "impact": "HIGH — Higher refresh rate reduces perceived input latency",
                "how_to": "Display Settings > Advanced Display > Refresh Rate",
            })

        if not config.game_mode_enabled:
            diagnostics.append({
                "setting": "Windows Game Mode",
                "current": "DISABLED",
                "recommendation": "Enable Game Mode for reduced background interference",
                "impact": "LOW-MEDIUM — Reduces Windows Update and background interrupts",
                "how_to": "Settings > Gaming > Game Mode > ON",
            })

        # Separate input settings from measured latency
        diagnostics.append({
            "setting": "Measured End-to-End Latency",
            "current": "UNAVAILABLE — Not measured",
            "recommendation": "Use external tools (e.g., LDAT, high-speed camera) for true latency measurement",
            "impact": "INFO — Input settings diagnostics are separate from actual measured latency",
            "how_to": "This tool provides configuration diagnostics only, not hardware latency measurement",
        })

        return diagnostics

    def disable_pointer_precision(self) -> bool:
        """Disable Windows mouse acceleration."""
        from app.utils.registry import write_registry_value

        success = write_registry_value(
            "HKCU", r"Control Panel\Mouse", "MouseSpeed", "0"
        )
        if success:
            logger.info("Pointer precision disabled")
        return success

    def enable_pointer_precision(self) -> bool:
        """Re-enable Windows mouse acceleration."""
        from app.utils.registry import write_registry_value

        success = write_registry_value(
            "HKCU", r"Control Panel\Mouse", "MouseSpeed", "1"
        )
        if success:
            logger.info("Pointer precision enabled")
        return success


# Singleton
input_monitor = InputMonitor()
