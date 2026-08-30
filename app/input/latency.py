"""
Input latency diagnostics module.
Separates input SETTINGS from ACTUAL MEASURED LATENCY.
"""

from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("input.latency")


@dataclass
class LatencyReport:
    """Input latency diagnostic report."""
    mouse_polling_rate_hz: Optional[int] = None
    display_refresh_hz: int = 60
    vsync_enabled: bool = True
    estimated_display_latency_ms: float = 0.0
    estimated_input_latency_ms: float = 0.0
    total_estimated_latency_ms: float = 0.0
    measurement_available: bool = False
    notes: str = ""


class LatencyDiagnostics:
    """Input latency measurement and diagnostics."""

    def diagnose(self, display_refresh_hz: int = 60,
                 vsync_enabled: bool = True) -> LatencyReport:
        """Generate input latency diagnostics."""
        report = LatencyReport()
        report.display_refresh_hz = display_refresh_hz
        report.vsync_enabled = vsync_enabled

        # Estimate display latency from refresh rate
        if display_refresh_hz > 0:
            report.estimated_display_latency_ms = 1000.0 / display_refresh_hz

        # VSync adds at least one frame of latency
        if vsync_enabled:
            report.estimated_display_latency_ms += 1000.0 / display_refresh_hz

        report.total_estimated_latency_ms = report.estimated_display_latency_ms

        report.notes = (
            "These are ESTIMATES based on display configuration. "
            "They do NOT represent actual measured end-to-end latency. "
            "True latency measurement requires external hardware (LDAT, high-speed camera)."
        )

        logger.info(
            f"Input latency estimate: {report.total_estimated_latency_ms:.1f}ms "
            f"(display: {report.estimated_display_latency_ms:.1f}ms)"
        )
        return report

    def separate_settings_from_reality(self) -> dict:
        """
        Clearly separate input settings from measured latency.
        Never fabricate latency measurements.
        """
        return {
            "input_settings": {
                "description": "Configurable input settings detected by this tool",
                "measurable": True,
                "includes": [
                    "Mouse pointer precision setting",
                    "Display refresh rate",
                    "VSync setting",
                    "Game Mode setting",
                    "Emulator input configuration",
                ],
            },
            "actual_latency": {
                "description": "Actual end-to-end input latency (requires external measurement)",
                "measurable": False,
                "note": "This tool does NOT measure actual input latency. "
                        "Use external tools for real measurements.",
            },
        }


# Singleton
latency_diagnostics = LatencyDiagnostics()
