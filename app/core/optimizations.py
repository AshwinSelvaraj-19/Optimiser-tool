"""
Real optimization implementations.

Every optimization follows: CHECK → SNAPSHOT → APPLY → VERIFY → ROLLBACK
Only optimizations that actually modify and verify system state are included.

Background process optimization is RECOMMENDATION_ONLY — it does NOT terminate processes.
"""

import psutil
from app.core.optimization_base import Optimization, OptimizationResult, OptimizationStatus
from app.system.power import power_monitor
from app.utils.registry import read_registry_value, write_registry_value
from app.utils.commands import run_powershell
from app.utils.logger import get_logger

logger = get_logger("core.optimizations")


class PowerPlanOptimization(Optimization):
    """Switch to High Performance power plan."""
    id = "power_plan"
    name = "Power Plan"
    description = "Switch to High Performance power plan for maximum CPU/GPU throughput"
    category = "SYSTEM"
    risk_level = "LOW"

    def check(self) -> OptimizationResult:
        info = power_monitor.detect()
        plan_lower = info.active_plan_name.lower()
        is_performance = any(p in plan_lower for p in [
            "high performance", "turbo", "ultimate", "performance"
        ])
        if is_performance:
            self._status = OptimizationStatus.ALREADY_OPTIMAL
            return OptimizationResult(
                status=self._status,
                current_value=info.active_plan_name,
                recommended_value="High Performance / Turbo",
                message="Already on a performance power plan",
            )
        self._status = OptimizationStatus.OPTIMIZABLE
        return OptimizationResult(
            status=self._status,
            current_value=info.active_plan_name,
            recommended_value="High Performance",
        )

    def snapshot(self) -> dict:
        info = power_monitor.detect()
        self._snapshot_data = {
            "plan_guid": info.active_plan_guid,
            "plan_name": info.active_plan_name,
        }
        return self._snapshot_data

    def apply(self) -> OptimizationResult:
        if self._status != OptimizationStatus.OPTIMIZABLE:
            return OptimizationResult(status=self._status)
        info = power_monitor.detect()
        hp_guid = None
        for plan in info.available_plans:
            if "high performance" in plan["name"].lower():
                hp_guid = plan["guid"]
                break
        if not hp_guid:
            hp_guid = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
        success, _, _ = run_powershell(f"powercfg /setactive {hp_guid}")
        if success:
            verify = power_monitor.detect()
            if "high performance" in verify.active_plan_name.lower():
                self._status = OptimizationStatus.APPLIED
                return OptimizationResult(
                    status=self._status,
                    message=f"Power plan set to: {verify.active_plan_name}",
                )
        self._status = OptimizationStatus.FAILED
        return OptimizationResult(status=self._status, message="Failed to set power plan")

    def verify(self) -> bool:
        info = power_monitor.detect()
        return "high performance" in info.active_plan_name.lower()

    def rollback(self) -> bool:
        if self._snapshot_data and self._snapshot_data.get("plan_guid"):
            success, _, _ = run_powershell(
                f"powercfg /setactive {self._snapshot_data['plan_guid']}"
            )
            return success
        return False


class GameModeOptimization(Optimization):
    """Enable Windows Game Mode."""
    id = "game_mode"
    name = "Game Mode"
    description = "Enable Windows Game Mode for optimized gaming resource allocation"
    category = "SYSTEM"
    risk_level = "LOW"

    def check(self) -> OptimizationResult:
        val = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled"
        )
        current = "ENABLED" if val == 1 else "DISABLED"
        if val == 1:
            self._status = OptimizationStatus.ALREADY_OPTIMAL
        else:
            self._status = OptimizationStatus.OPTIMIZABLE
        return OptimizationResult(
            status=self._status, current_value=current, recommended_value="ENABLED"
        )

    def snapshot(self) -> dict:
        val = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled"
        )
        self._snapshot_data = {"value": val}
        return self._snapshot_data

    def apply(self) -> OptimizationResult:
        if self._status != OptimizationStatus.OPTIMIZABLE:
            return OptimizationResult(status=self._status)
        success = write_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1
        )
        if success:
            verify = read_registry_value(
                "HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled"
            )
            if verify == 1:
                self._status = OptimizationStatus.APPLIED
                return OptimizationResult(
                    status=self._status, message="Game Mode enabled"
                )
        self._status = OptimizationStatus.FAILED
        return OptimizationResult(status=self._status, message="Failed to enable Game Mode")

    def verify(self) -> bool:
        val = read_registry_value(
            "HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled"
        )
        return val == 1

    def rollback(self) -> bool:
        if self._snapshot_data:
            return write_registry_value(
                "HKCU", r"Software\Microsoft\GameBar",
                "AutoGameModeEnabled", self._snapshot_data["value"]
            )
        return False


class EmulatorPriorityOptimization(Optimization):
    """Set emulator process to high priority. Requires admin."""
    id = "emulator_priority"
    name = "Emulator Priority"
    description = "Set emulator process priority to HIGH for better frame delivery"
    category = "EMULATOR"
    risk_level = "LOW"

    def __init__(self):
        super().__init__()
        self._target_pid = None
        self._original_priority = None

    def _is_admin(self) -> bool:
        try:
            from app.utils.admin import is_admin
            return is_admin()
        except Exception:
            return False

    def check(self) -> OptimizationResult:
        self._target_pid = self._find_emulator_pid()
        if not self._target_pid:
            self._status = OptimizationStatus.NOT_APPLICABLE
            return OptimizationResult(
                status=self._status,
                current_value="No emulator running",
                message="Emulator not detected",
            )
        # Check admin first — AccessDenied on process access is the indicator
        if not self._is_admin():
            self._status = OptimizationStatus.REQUIRES_ADMIN
            return OptimizationResult(
                status=self._status,
                current_value="Emulator running (PID {})".format(self._target_pid),
                recommended_value="Priority -1 (HIGH)",
                message="Administrator privileges required",
            )
        try:
            proc = psutil.Process(self._target_pid)
            current = proc.nice()
            if current < 0:
                self._status = OptimizationStatus.ALREADY_OPTIMAL
                return OptimizationResult(
                    status=self._status,
                    current_value=f"Priority {current} (HIGH)",
                    recommended_value="Already optimal",
                )
            self._status = OptimizationStatus.OPTIMIZABLE
            return OptimizationResult(
                status=self._status,
                current_value=f"Priority {current} (NORMAL)",
                recommended_value="Priority -1 (HIGH)",
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._status = OptimizationStatus.NOT_APPLICABLE
            return OptimizationResult(
                status=self._status,
                current_value="Cannot access emulator process",
                message="Emulator process not accessible",
            )

    def snapshot(self) -> dict:
        if self._target_pid:
            try:
                proc = psutil.Process(self._target_pid)
                self._original_priority = proc.nice()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._original_priority = None
        self._snapshot_data = {
            "pid": self._target_pid,
            "original_priority": self._original_priority,
        }
        return self._snapshot_data

    def apply(self) -> OptimizationResult:
        if self._status != OptimizationStatus.OPTIMIZABLE:
            return OptimizationResult(status=self._status)
        if not self._target_pid:
            self._status = OptimizationStatus.FAILED
            return OptimizationResult(
                status=self._status, message="No emulator PID"
            )
        try:
            proc = psutil.Process(self._target_pid)
            proc.nice(psutil.HIGH_PRIORITY_CLASS)
            verify = psutil.Process(self._target_pid)
            if verify.nice() < 0:
                self._status = OptimizationStatus.APPLIED
                return OptimizationResult(
                    status=self._status,
                    message=f"Emulator priority set to HIGH (PID {self._target_pid})",
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning(f"Cannot set emulator priority: {e}")
        self._status = OptimizationStatus.FAILED
        return OptimizationResult(status=self._status, message="Failed to set priority")

    def verify(self) -> bool:
        if not self._target_pid:
            return False
        try:
            proc = psutil.Process(self._target_pid)
            return proc.nice() < 0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def rollback(self) -> bool:
        if self._target_pid and self._original_priority is not None:
            try:
                proc = psutil.Process(self._target_pid)
                proc.nice(self._original_priority)
                return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    def _find_emulator_pid(self) -> int:
        """Find emulator rendering process PID."""
        emulator_procs = [
            "HD-Player.exe", "BstHdViewer.exe", "LDPlayer.exe",
            "MuMuPlayer.exe", "MobileGamePC.exe",
        ]
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.info["name"] in emulator_procs:
                    return proc.info["pid"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return 0


class BackgroundProcessOptimization(Optimization):
    """
    RECOMMENDATION ONLY — detect optional background processes and suggest
    closing them. Does NOT terminate any processes.
    """
    id = "background_load"
    name = "Background Load"
    description = "Detect optional background applications consuming resources"
    category = "SYSTEM"
    risk_level = "LOW"

    def __init__(self):
        super().__init__()
        self._candidates = []

    def check(self) -> OptimizationResult:
        from app.system.processes import process_monitor
        processes = process_monitor.list_processes()
        optional = [
            p for p in processes
            if p.category == "OPTIONAL BACKGROUND" and p.cpu_percent > 0.5
        ]
        self._candidates = optional
        if not optional:
            self._status = OptimizationStatus.ALREADY_OPTIMAL
            return OptimizationResult(
                status=self._status,
                current_value="0 active optional processes",
                message="No optional processes consuming resources",
            )
        total_cpu = sum(p.cpu_percent for p in optional)
        total_ram = sum(p.memory_mb for p in optional)
        self._status = OptimizationStatus.RECOMMENDATION_ONLY
        return OptimizationResult(
            status=self._status,
            current_value=f"{len(optional)} processes ({total_cpu:.1f}% CPU, {total_ram:.0f}MB RAM)",
            recommended_value=f"Close {len(optional)} optional processes",
            message="Review and close manually if desired",
        )

    def snapshot(self) -> dict:
        return {"candidates": [], "action": "recommendation_only"}

    def apply(self) -> OptimizationResult:
        """RECOMMENDATION ONLY — does not terminate processes."""
        self._status = OptimizationStatus.RECOMMENDATION_ONLY
        return OptimizationResult(
            status=self._status,
            message="Review and close optional processes manually",
        )

    def verify(self) -> bool:
        return True

    def rollback(self) -> bool:
        return True  # Nothing to roll back


class MemoryAnalysisOptimization(Optimization):
    """Analyze memory pressure and provide recommendations. READ-ONLY diagnostic."""
    id = "memory_analysis"
    name = "Memory Analysis"
    description = "Analyze memory pressure and provide safe recommendations for gaming"
    category = "SYSTEM"
    risk_level = "NONE"

    def check(self) -> OptimizationResult:
        try:
            from app.system.memory_optimizer import memory_optimizer
            report = memory_optimizer.analyze()
            if report.diagnostics:
                level = report.diagnostics.pressure_level
                if level in ("HIGH", "CRITICAL"):
                    self._status = OptimizationStatus.OPTIMIZABLE
                    return OptimizationResult(
                        status=self._status,
                        current_value=f"Pressure: {level}",
                        recommended_value="Reduce memory pressure",
                        message=report.diagnostics.pressure_recommendation,
                    )
                self._status = OptimizationStatus.ALREADY_OPTIMAL
                return OptimizationResult(
                    status=self._status,
                    current_value=f"Pressure: {level}",
                    message="Memory pressure is acceptable",
                )
        except Exception:
            pass
        self._status = OptimizationStatus.NOT_APPLICABLE
        return OptimizationResult(
            status=self._status,
            current_value="Memory diagnostics unavailable",
        )

    def snapshot(self) -> dict:
        self._snapshot_data = {}
        return self._snapshot_data

    def apply(self) -> OptimizationResult:
        # This is a diagnostic — nothing to apply
        return OptimizationResult(
            status=OptimizationStatus.RECOMMENDATION_ONLY,
            message="Memory analysis is diagnostic-only. See recommendations.",
        )

    def verify(self) -> bool:
        return True

    def rollback(self) -> bool:
        return True  # Nothing to roll back


def get_all_optimizations() -> list:
    """Get all available optimization instances."""
    from app.core.windows_optimizations import (
        GameBarAdapter, BackgroundRecordingAdapter, VisualEffectsAdapter,
        StartupOptimization, CleanupOptimization,
    )
    return [
        # Performance
        PowerPlanOptimization(),
        BackgroundProcessOptimization(),
        # Memory
        MemoryAnalysisOptimization(),
        # Gaming
        GameModeOptimization(),
        EmulatorPriorityOptimization(),
        GameBarAdapter(),
        BackgroundRecordingAdapter(),
        # Startup
        StartupOptimization(),
        # Cleanup
        CleanupOptimization(),
        # System
        VisualEffectsAdapter(),
    ]


def get_optimization_by_id(opt_id: str) -> Optimization:
    """Get a specific optimization by ID."""
    for opt in get_all_optimizations():
        if opt.id == opt_id:
            return opt
    # Check emulator-specific optimizations
    try:
        from app.core.emulator_controller import CpuAffinityOptimization
        if opt_id == "cpu_affinity":
            return CpuAffinityOptimization()
    except ImportError:
        pass
    # Check Windows gaming optimizations
    try:
        from app.system.windows_gaming import (
            GameBarOptimization, BackgroundRecordingOptimization,
            VisualEffectsOptimization, FullscreenOptimizationDiagnostic,
        )
        _win_opts = {
            "game_bar": GameBarOptimization,
            "background_recording": BackgroundRecordingOptimization,
            "visual_effects": VisualEffectsOptimization,
            "fullscreen_optimization": FullscreenOptimizationDiagnostic,
        }
        if opt_id in _win_opts:
            return _win_opts[opt_id]()
    except ImportError:
        pass
    return None
