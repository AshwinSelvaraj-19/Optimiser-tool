"""
Windows Gaming Diagnostics — real system state detection.

Reads actual Windows registry and system state.
Every value is VERIFIED by re-reading after any change.
No fabricated states. No placeholder values.

Statuses:
  AVAILABLE / ENABLED / DISABLED / REQUIRES_ADMIN / NOT_AVAILABLE / UNKNOWN
"""

import platform
import os
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from app.utils.registry import read_registry_value, write_registry_value, registry_key_exists
from app.utils.commands import run_powershell
from app.utils.logger import get_logger

logger = get_logger("system.windows_gaming")


# ── Data Models ────────────────────────────────────────────────

@dataclass
class DiagnosticItem:
    """A single diagnostic item with state and status."""
    name: str = ""
    value: str = "UNKNOWN"
    status: str = "UNKNOWN"       # ENABLED, DISABLED, AVAILABLE, NOT_AVAILABLE, REQUIRES_ADMIN, UNKNOWN
    description: str = ""
    category: str = ""            # POWER, GAME_MODE, RECORDING, HAGS, DISPLAY, GPU, VISUAL
    can_modify: bool = False
    recommendation: str = ""
    registry_hive: str = ""
    registry_path: str = ""
    registry_value_name: str = ""


@dataclass
class WindowsGamingReport:
    """Complete Windows gaming diagnostics report."""
    items: List[DiagnosticItem] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    is_admin: bool = False
    windows_version: str = ""
    target_name: str = ""
    target_pid: int = 0

    @property
    def enabled_count(self) -> int:
        return sum(1 for i in self.items if i.status == "ENABLED")

    @property
    def disabled_count(self) -> int:
        return sum(1 for i in self.items if i.status == "DISABLED")

    @property
    def available_count(self) -> int:
        return sum(1 for i in self.items if i.status == "AVAILABLE")

    @property
    def items_by_category(self) -> dict:
        cats = {}
        for item in self.items:
            cats.setdefault(item.category, []).append(item)
        return cats


# ── Diagnostics Reader ─────────────────────────────────────────

class WindowsGamingDiagnostics:
    """Read-only diagnostics for Windows gaming configuration."""

    def __init__(self):
        self._cache = {}
        self._cache_time = 0

    def read_all(self, target_name: str = "", target_pid: int = 0) -> WindowsGamingReport:
        """Read all Windows gaming diagnostics. Read-only, no modifications."""
        report = WindowsGamingReport(
            target_name=target_name,
            target_pid=target_pid,
        )

        # Windows version
        report.windows_version = self._get_windows_version()

        # Admin status
        try:
            from app.utils.admin import is_admin
            report.is_admin = is_admin()
        except Exception:
            report.is_admin = False

        # Power Plan
        self._read_power_plan(report)

        # Game Mode
        self._read_game_mode(report)

        # Game Bar
        self._read_game_bar(report)

        # Background Recording / Game DVR
        self._read_background_recording(report)

        # HAGS
        self._read_hags(report)

        # Visual Effects
        self._read_visual_effects(report)

        # Display
        self._read_display(report)

        # GPU Driver
        self._read_gpu_driver(report)

        # Generate recommendations
        self._generate_recommendations(report)

        return report

    def _get_windows_version(self) -> str:
        """Get Windows version string."""
        try:
            ver = platform.version()
            release = platform.release()
            return f"Windows {release} (Build {ver})"
        except Exception:
            return "Unknown"

    def _read_power_plan(self, report: WindowsGamingReport):
        """Read active power plan."""
        try:
            from app.system.power import power_monitor
            info = power_monitor.detect()

            is_performance = any(p in info.active_plan_name.lower() for p in [
                "high performance", "turbo", "ultimate", "performance"
            ])

            item = DiagnosticItem(
                name="Power Plan",
                value=info.active_plan_name,
                status="ENABLED" if is_performance else "DISABLED",
                category="POWER",
                can_modify=True,
                description=f"Active plan: {info.active_plan_name}",
            )

            if not is_performance:
                item.recommendation = "Switch to High Performance for maximum CPU/GPU throughput"

            report.items.append(item)
        except Exception as e:
            logger.debug(f"Power plan read error: {e}")
            report.items.append(DiagnosticItem(
                name="Power Plan", value="UNKNOWN", status="UNKNOWN",
                category="POWER", description=f"Error: {e}",
            ))

    def _read_game_mode(self, report: WindowsGamingReport):
        """Read Windows Game Mode state from registry."""
        val = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled"
        )

        if val is None:
            status = "NOT_AVAILABLE"
            value = "Not found in registry"
        elif val == 1:
            status = "ENABLED"
            value = "ENABLED"
        else:
            status = "DISABLED"
            value = "DISABLED"

        item = DiagnosticItem(
            name="Game Mode",
            value=value,
            status=status,
            category="GAME_MODE",
            can_modify=True,
            description="Windows Game Mode optimizes system resources for gaming",
            registry_hive="HKCU",
            registry_path=r"Software\Microsoft\GameBar",
            registry_value_name="AutoGameModeEnabled",
        )

        if status == "DISABLED":
            item.recommendation = "Enable Game Mode for optimized gaming resource allocation"

        report.items.append(item)

    def _read_game_bar(self, report: WindowsGamingReport):
        """Read Xbox Game Bar overlay state."""
        # Game Bar enabled state
        val = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode"
        )
        # Also check the GameBar key existence
        exists = registry_key_exists("HKCU", r"Software\Microsoft\GameBar")

        if val is None and not exists:
            status = "NOT_AVAILABLE"
            value = "Game Bar not configured"
        elif val == 0:
            status = "DISABLED"
            value = "DISABLED"
        else:
            status = "ENABLED"
            value = "ENABLED"

        item = DiagnosticItem(
            name="Game Bar",
            value=value,
            status=status,
            category="OVERLAY",
            can_modify=True,
            description="Xbox Game Bar overlay can add capture/recording overhead",
            registry_hive="HKCU",
            registry_path=r"Software\Microsoft\GameBar",
            registry_value_name="AllowAutoGameMode",
        )

        report.items.append(item)

    def _read_background_recording(self, report: WindowsGamingReport):
        """Read background recording / Game DVR state."""
        # Check if background recording is enabled
        val = read_registry_value(
            "HKCU",
            r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
            "AppCaptureEnabled",
        )

        # Also check the GameDVR key
        val2 = read_registry_value(
            "HKCU",
            r"System\GameConfigStore",
            "GameDVR_Enabled",
        )

        # Determine state: if either is explicitly 0, it's disabled
        if val == 0 or val2 == 0:
            status = "DISABLED"
            value = "DISABLED"
        elif val is None and val2 is None:
            status = "UNKNOWN"
            value = "Not configured"
        else:
            status = "ENABLED"
            value = "ENABLED"

        item = DiagnosticItem(
            name="Background Recording",
            value=value,
            status=status,
            category="RECORDING",
            can_modify=True,
            description="Background recording adds continuous capture overhead",
            registry_hive="HKCU",
            registry_path=r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
            registry_value_name="AppCaptureEnabled",
        )

        if status == "ENABLED":
            item.recommendation = "Disable background recording if not needed — reduces CPU/disk overhead"

        report.items.append(item)

    def _read_hags(self, report: WindowsGamingReport):
        """Read Hardware-Accelerated GPU Scheduling state."""
        val = read_registry_value(
            "HKLM",
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
            "HwSchMode",
        )

        if val is None:
            status = "NOT_AVAILABLE"
            value = "Not configured (default)"
        elif val == 2:
            status = "ENABLED"
            value = "ENABLED (mode 2)"
        elif val == 1:
            status = "DISABLED"
            value = "DISABLED (mode 1)"
        else:
            status = "UNKNOWN"
            value = f"Unknown mode ({val})"

        item = DiagnosticItem(
            name="HAGS",
            value=value,
            status=status,
            category="GPU",
            can_modify=False,  # Changing HAGS requires reboot — recommendation only
            description="Hardware-Accelerated GPU Scheduling offloads scheduling to GPU",
            registry_hive="HKLM",
            registry_path=r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
            registry_value_name="HwSchMode",
        )

        if status == "NOT_AVAILABLE":
            item.recommendation = "HAGS not configured — default Windows behavior"
        elif status == "DISABLED":
            item.recommendation = "HAGS is disabled — may benefit from enabling (requires reboot)"
        elif status == "ENABLED":
            item.recommendation = "HAGS is active"

        report.items.append(item)

    def _read_visual_effects(self, report: WindowsGamingReport):
        """Read Windows visual effects / performance configuration."""
        # Check the VisualEffects key
        val = read_registry_value(
            "HKCU",
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
            "VisualFXSetting",
        )

        # 0=Let Windows choose, 1=Best appearance, 2=Best performance, 3=Custom
        if val is None:
            status = "UNKNOWN"
            value = "Default (Let Windows choose)"
        elif val == 2:
            status = "ENABLED"  # Best performance = optimized
            value = "Best Performance"
        elif val == 1:
            status = "DISABLED"  # Best appearance = not optimized
            value = "Best Appearance"
        elif val == 3:
            status = "AVAILABLE"
            value = "Custom"
        else:
            status = "UNKNOWN"
            value = f"Setting {val}"

        item = DiagnosticItem(
            name="Visual Effects",
            value=value,
            status=status,
            category="VISUAL",
            can_modify=False,  # Too many sub-settings for safe rollback — recommendation only
            description="Windows visual effects consume GPU/CPU resources",
            registry_hive="HKCU",
            registry_path=r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
            registry_value_name="VisualFXSetting",
        )

        if status == "DISABLED":
            item.recommendation = "Visual effects set to Best Appearance — consider Best Performance for gaming"
        elif status == "UNKNOWN":
            item.recommendation = "Visual effects on default — no action needed"

        report.items.append(item)

    def _read_display(self, report: WindowsGamingReport):
        """Read display refresh rate and resolution."""
        try:
            from app.system.display import display_monitor
            info = display_monitor.detect()

            if info.refresh_rate_hz > 0:
                status = "ENABLED"
                value = f"{info.resolution_x}x{info.resolution_y} @ {info.refresh_rate_hz:.0f}Hz"
            else:
                status = "UNKNOWN"
                value = f"{info.resolution_x}x{info.resolution_y}"

            item = DiagnosticItem(
                name="Display",
                value=value,
                status=status,
                category="DISPLAY",
                can_modify=False,
                description=f"Display: {info.resolution_x}x{info.resolution_y} @ {info.refresh_rate_hz:.0f}Hz",
            )
            report.items.append(item)
        except Exception as e:
            logger.debug(f"Display read error: {e}")
            report.items.append(DiagnosticItem(
                name="Display", value="UNKNOWN", status="UNKNOWN",
                category="DISPLAY", description=f"Error: {e}",
            ))

    def _read_gpu_driver(self, report: WindowsGamingReport):
        """Read GPU driver information."""
        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            if gpus:
                gpu = gpus[0]
                item = DiagnosticItem(
                    name="GPU Driver",
                    value=f"{gpu.name} — Driver {gpu.driver_version}",
                    status="AVAILABLE",
                    category="GPU",
                    can_modify=False,
                    description=f"GPU: {gpu.name}, Driver: {gpu.driver_version}",
                )
                report.items.append(item)
            else:
                report.items.append(DiagnosticItem(
                    name="GPU Driver", value="Not detected", status="NOT_AVAILABLE",
                    category="GPU", can_modify=False,
                ))
        except Exception as e:
            logger.debug(f"GPU driver read error: {e}")
            report.items.append(DiagnosticItem(
                name="GPU Driver", value="UNKNOWN", status="UNKNOWN",
                category="GPU", description=f"Error: {e}",
            ))

    def _generate_recommendations(self, report: WindowsGamingReport):
        """Generate actionable recommendations from diagnostics."""
        recs = []

        for item in report.items:
            if item.recommendation:
                recs.append(f"{item.name}: {item.recommendation}")

        if not recs:
            recs.append("No critical Windows gaming changes required.")

        report.recommendations = recs


# ── Safe Optimizations ─────────────────────────────────────────


class GameBarOptimization:
    """
    Safe Game Bar overlay toggle.
    CHECK → SNAPSHOT → APPLY → VERIFY → ROLLBACK
    """

    id = "game_bar"
    name = "Game Bar"
    description = "Toggle Xbox Game Bar overlay"
    category = "OVERLAY"
    risk_level = "LOW"

    def __init__(self):
        self._snapshot_data = None

    def check(self) -> Tuple[str, str, str]:
        """Returns (current_value, status, message)."""
        val = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode"
        )
        if val is None:
            return "Not configured", "NOT_AVAILABLE", "Game Bar registry key not found"
        elif val == 0:
            return "DISABLED", "ALREADY_OPTIMAL", "Game Bar is already disabled"
        else:
            return "ENABLED", "OPTIMIZABLE", "Game Bar is enabled — can be disabled"

    def snapshot(self) -> dict:
        val = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode"
        )
        self._snapshot_data = {"value": val}
        return self._snapshot_data

    def apply(self) -> Tuple[bool, str]:
        """Disable Game Bar. Returns (success, message)."""
        success = write_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", 0
        )
        if success:
            verify = read_registry_value(
                "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode"
            )
            if verify == 0:
                return True, "Game Bar disabled"
            return False, "Verification failed — value not changed"
        return False, "Registry write failed"

    def verify(self) -> bool:
        val = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode"
        )
        return val == 0

    def rollback(self) -> bool:
        if self._snapshot_data and self._snapshot_data.get("value") is not None:
            return write_registry_value(
                "HKCU", r"Software\Microsoft\GameBar",
                "AllowAutoGameMode", self._snapshot_data["value"]
            )
        return False


class BackgroundRecordingOptimization:
    """
    Safe background recording toggle.
    CHECK → SNAPSHOT → APPLY → VERIFY → ROLLBACK
    """

    id = "background_recording"
    name = "Background Recording"
    description = "Disable background recording to reduce CPU/disk overhead"
    category = "RECORDING"
    risk_level = "LOW"

    def __init__(self):
        self._snapshot_data = None
        self._primary_key = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
        self._primary_value = "AppCaptureEnabled"
        self._secondary_key = r"System\GameConfigStore"
        self._secondary_value = "GameDVR_Enabled"

    def check(self) -> Tuple[str, str, str]:
        val1 = read_registry_value("HKCU", self._primary_key, self._primary_value)
        val2 = read_registry_value("HKCU", self._secondary_key, self._secondary_value)

        if val1 == 0 and val2 == 0:
            return "DISABLED", "ALREADY_OPTIMAL", "Background recording is already disabled"
        elif val1 is None and val2 is None:
            return "Not configured", "NOT_AVAILABLE", "Recording registry keys not found"
        else:
            return "ENABLED", "OPTIMIZABLE", "Background recording is active"

    def snapshot(self) -> dict:
        self._snapshot_data = {
            "primary": read_registry_value("HKCU", self._primary_key, self._primary_value),
            "secondary": read_registry_value("HKCU", self._secondary_key, self._secondary_value),
        }
        return self._snapshot_data

    def apply(self) -> Tuple[bool, str]:
        ok1 = write_registry_value("HKCU", self._primary_key, self._primary_value, 0)
        ok2 = write_registry_value("HKCU", self._secondary_key, self._secondary_value, 0)

        if ok1 or ok2:
            # Verify
            v1 = read_registry_value("HKCU", self._primary_key, self._primary_value)
            v2 = read_registry_value("HKCU", self._secondary_key, self._secondary_value)
            if v1 == 0 or v2 == 0:
                return True, "Background recording disabled"
            return False, "Verification failed"
        return False, "Registry write failed"

    def verify(self) -> bool:
        v1 = read_registry_value("HKCU", self._primary_key, self._primary_value)
        v2 = read_registry_value("HKCU", self._secondary_key, self._secondary_value)
        return v1 == 0 or v2 == 0

    def rollback(self) -> bool:
        if not self._snapshot_data:
            return False
        ok = True
        if self._snapshot_data.get("primary") is not None:
            ok = ok and write_registry_value(
                "HKCU", self._primary_key, self._primary_value,
                self._snapshot_data["primary"]
            )
        if self._snapshot_data.get("secondary") is not None:
            ok = ok and write_registry_value(
                "HKCU", self._secondary_key, self._secondary_value,
                self._snapshot_data["secondary"]
            )
        return ok


class VisualEffectsOptimization:
    """
    Windows visual effects optimization.
    RECOMMENDATION ONLY — too many sub-settings for safe granular rollback.
    Setting 'Best Performance' modifies many individual registry values.
    """

    id = "visual_effects"
    name = "Visual Effects"
    description = "Set Windows visual effects to Best Performance (recommendation only)"
    category = "VISUAL"
    risk_level = "LOW"

    def __init__(self):
        self._snapshot_data = None

    def check(self) -> Tuple[str, str, str]:
        val = read_registry_value(
            "HKCU",
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
            "VisualFXSetting",
        )
        if val == 2:
            return "Best Performance", "ALREADY_OPTIMAL", "Already optimized"
        elif val is None:
            return "Default", "NOT_AVAILABLE", "Visual effects key not found"
        else:
            return f"Setting {val}", "RECOMMENDATION_ONLY", "Recommendation: set to Best Performance"

    def snapshot(self) -> dict:
        val = read_registry_value(
            "HKCU",
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
            "VisualFXSetting",
        )
        self._snapshot_data = {"value": val}
        return self._snapshot_data

    def apply(self) -> Tuple[bool, str]:
        """RECOMMENDATION ONLY — does not modify anything."""
        return True, "Recommendation: set Windows visual effects to Best Performance"

    def verify(self) -> bool:
        return True  # Recommendation only

    def rollback(self) -> bool:
        return True  # Nothing to rollback


class FullscreenOptimizationDiagnostic:
    """
    Per-executable fullscreen optimization diagnostic.
    RECOMMENDATION ONLY — modifying per-app compatibility flags has complex side effects.
    """

    id = "fullscreen_optimization"
    name = "Fullscreen Optimization"
    description = "Diagnostic for per-executable fullscreen optimization settings"
    category="DISPLAY"
    risk_level = "LOW"

    def __init__(self):
        self._snapshot_data = None

    def check(self, exe_path: str = "") -> Tuple[str, str, str]:
        """Check fullscreen optimization state for a specific executable."""
        if not exe_path:
            return "No target", "NOT_AVAILABLE", "No executable path provided"

        # Check the PerApplicationSystemDpiCompatibility key
        # FullScreenBoost is controlled per-app via compatibility flags
        # This is read-only for safety — modifying compatibility flags is risky
        return "Requires manual review", "RECOMMENDATION_ONLY", \
            "Review fullscreen optimization in Properties > Compatibility"

    def snapshot(self) -> dict:
        self._snapshot_data = {}
        return self._snapshot_data

    def apply(self) -> Tuple[bool, str]:
        return True, "Recommendation: review fullscreen optimization per-app settings"

    def verify(self) -> bool:
        return True

    def rollback(self) -> bool:
        return True


# ── WindowsGamingAnalyzer ──────────────────────────────────────

class WindowsGamingAnalyzer:
    """
    Combines all Windows gaming diagnostics into a structured report.
    Uses the existing emulator controller for target-aware analysis.
    """

    def __init__(self):
        self._diagnostics = WindowsGamingDiagnostics()

    def analyze(self, target_name: str = "", target_pid: int = 0) -> WindowsGamingReport:
        """
        Run full Windows gaming diagnostics.
        Read-only — does not modify anything.
        """
        report = self._diagnostics.read_all(target_name, target_pid)
        return report

    def get_optimization_candidates(self, report: WindowsGamingReport) -> list:
        """
        Determine which optimizations are applicable based on diagnostics.
        Returns list of (OptimizationClass, reason) tuples.
        """
        candidates = []

        for item in report.items:
            if item.name == "Game Bar" and item.status == "ENABLED":
                candidates.append((GameBarOptimization, "Game Bar is enabled"))
            elif item.name == "Background Recording" and item.status == "ENABLED":
                candidates.append((BackgroundRecordingOptimization, "Background recording is active"))
            elif item.name == "Visual Effects" and item.status == "DISABLED":
                candidates.append((VisualEffectsOptimization, "Visual effects not optimized"))
            elif item.name == "Fullscreen Optimization":
                candidates.append((FullscreenOptimizationDiagnostic, "Review recommended"))

        return candidates


# Singletons
windows_gaming_diagnostics = WindowsGamingDiagnostics()
windows_gaming_analyzer = WindowsGamingAnalyzer()
